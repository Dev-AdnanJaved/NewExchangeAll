"""
Main orchestrator — parallel scanning + bootstrap + trade monitoring.
"""

import json
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from core.collector import DataCollector
from core.database import Database
from core.levels import LevelsCalculator
from core.scorer import Scorer
from core.signals import SignalEngine
from core.universe import UniverseBuilder
from utils.helpers import (
    STOP_LOSS_TRAIL,
    TAKE_PROFIT_LEVELS,
    format_pct,
    format_price,
    safe_divide,
    utc_now,
)
from utils.logger import get_logger

logger = get_logger("scanner")
MAX_SCAN_WORKERS = 6


class Scanner:
    def __init__(self, config):
        self.config = config
        self.db = Database(
            config.get("database", {}).get("path", "data/pump_detector.db")
        )
        self.universe_builder = UniverseBuilder(config, self.db)
        self.collector = DataCollector(
            self.universe_builder.get_all_exchanges(), self.db, config
        )
        self.signal_engine = SignalEngine(self.db)
        self.scorer = Scorer(self.db)
        self.levels = LevelsCalculator()
        self.alert_handlers = []

        sc = config.get("scanning", {})
        self.scan_interval = sc.get("scan_interval_minutes", 15) * 60
        self.trade_monitor_interval = sc.get("trade_monitor_interval_minutes", 5) * 60
        self.min_futures_exchanges = sc.get("min_futures_exchanges", 1)
        self.alert_threshold = sc.get("alert_score_threshold", 48)
        self.max_tokens = sc.get("max_tokens_per_scan", 400)

        self._bootstrapped = set()
        self._bs_lock = threading.Lock()

    def add_alert_handler(self, h):
        self.alert_handlers.append(h)

    # ═══════════════════════════════════════════════════════════
    # MAIN SCAN
    # ═══════════════════════════════════════════════════════════

    def run_once(self):
        logger.info("=" * 60)
        logger.info("STARTING SCAN")
        logger.info("=" * 60)
        t0 = time.time()

        universe = self.universe_builder.get_or_build(
            min_futures_exchanges=self.min_futures_exchanges
        )
        tokens = list(universe.items())[: self.max_tokens]
        total = len(tokens)
        logger.info(f"Universe: {total} tokens")

        bc = self._bootstrap_batch(tokens)
        if bc > 0:
            logger.info(f"Bootstrapped {bc} tokens")

        results = []
        done = errors = 0

        with ThreadPoolExecutor(max_workers=MAX_SCAN_WORKERS) as pool:
            futs = {pool.submit(self._scan_token, s, i): s for s, i in tokens}
            for f in as_completed(futs):
                done += 1
                try:
                    r = f.result()
                    if r and r["composite_score"] >= self.alert_threshold:
                        results.append(r)
                    if done % 25 == 0 or done == total:
                        logger.info(f"Progress: {done}/{total}, {len(results)} alerts")
                except Exception as e:
                    errors += 1
                    logger.error(f"Scan fail {futs[f]}: {e}")

        results.sort(key=lambda x: x["composite_score"], reverse=True)
        self._send_alerts(results)
        self._monitor_trades()

        logger.info("=" * 60)
        logger.info(
            f"DONE {time.time()-t0:.1f}s | {done} scanned | "
            f"{len(results)} alerts | {errors} errors"
        )
        for r in results[:5]:
            logger.info(
                f"  {r['symbol']:12s} {r['composite_score']:.1f} ({r['classification']})"
            )
        logger.info("=" * 60)
        return results

    def _scan_token(self, symbol, info):
        try:
            collected = self.collector.collect_all(symbol, info["futures_exchanges"])
            if not (
                collected.get("tickers")
                or collected.get("open_interest")
                or collected.get("ohlcv")
            ):
                return None

            signals = self.signal_engine.compute_all(symbol, collected)
            p7d = self._price_7d(symbol, collected)
            sr = self.scorer.score(symbol, signals, p7d)
            sr["symbol"] = symbol
            sr["exchanges"] = info["futures_exchanges"]

            cp = self._cur_price(collected)
            sr["current_price"] = cp
            sr["signal_details"] = {
                n: s.get("metadata", {}) for n, s in signals.items()
            }

            if sr["composite_score"] >= self.alert_threshold and cp > 0:
                sr["levels"] = self.levels.compute(
                    symbol, cp, collected, signals, sr
                )
            else:
                sr["levels"] = None

            sr["events"] = self.scorer.detect_events(symbol, sr, cp)
            return sr
        except Exception as e:
            logger.warning(f"Error {symbol}: {e}")
            return None

    # ═══════════════════════════════════════════════════════════
    # BOOTSTRAP
    # ═══════════════════════════════════════════════════════════

    def _bootstrap_batch(self, tokens):
        need = []
        for s, i in tokens:
            with self._bs_lock:
                if s in self._bootstrapped:
                    continue
            if self.collector.needs_bootstrap(s):
                need.append((s, i))

        if not need:
            return 0

        logger.info(f"Bootstrapping {len(need)} tokens...")
        c = 0
        for s, i in need:
            try:
                self.collector.bootstrap_token(s, i["futures_exchanges"])
                with self._bs_lock:
                    self._bootstrapped.add(s)
                c += 1
                if c % 10 == 0:
                    logger.info(f"  Bootstrap: {c}/{len(need)}")
                time.sleep(0.2)
            except Exception as e:
                logger.warning(f"  Bootstrap fail {s}: {e}")
        return c

    # ═══════════════════════════════════════════════════════════
    # CONTINUOUS
    # ═══════════════════════════════════════════════════════════

    def run_continuous(self):
        logger.info("Continuous mode started")
        ls = lt = 0
        while True:
            try:
                now = time.time()
                if now - ls >= self.scan_interval:
                    self.run_once()
                    ls = time.time()
                if now - lt >= self.trade_monitor_interval:
                    self._monitor_trades()
                    lt = time.time()
                time.sleep(10)
            except KeyboardInterrupt:
                logger.info("Stopped")
                break
            except Exception as e:
                logger.error(f"Loop error: {e}")
                logger.debug(traceback.format_exc())
                time.sleep(60)

    # ═══════════════════════════════════════════════════════════
    # TRADE MONITORING
    # ═══════════════════════════════════════════════════════════

    def _monitor_trades(self):
        trades = self.db.get_active_trades()
        if not trades:
            return
        logger.info(f"Monitoring {len(trades)} trade(s)")
        for t in trades:
            try:
                self._check_trade(t)
            except Exception as e:
                logger.error(f"Trade monitor error {t['symbol']}: {e}")

    def _check_trade(self, trade):
        sym = trade["symbol"]
        ep = trade["entry_price"]
        ps = trade["position_size_usd"]
        rem = trade["remaining_fraction"]
        cs = trade["current_stop_price"]

        if rem <= 0:
            self.db.close_trade(sym, ep, "fully_exited")
            return

        cp = self._live_price(sym)
        if not cp:
            return

        pcp = ((cp - ep) / ep) * 100
        upnl = rem * ps * (pcp / 100)

        # Stop hit
        if cp <= cs:
            r = self.db.close_trade(sym, cp, "stop_loss")
            if r:
                for h in self.alert_handlers:
                    h.send_trade_closed(r, "STOP LOSS HIT")
            return

        # Take profits
        for tp in TAKE_PROFIT_LEVELS:
            tl = tp["level"]
            tpct = tp["pct"]
            tk = f"tp{tl}_hit"

            if trade.get(tk) or tpct is None:
                continue

            if pcp >= tpct:
                sf = tp["sell_fraction"]
                chunk = sf * ps * (pcp / 100)
                nr = rem - sf
                nrp = trade["realized_pnl"] + chunk

                self.db.update_trade(sym, {
                    tk: 1,
                    "remaining_fraction": max(0, nr),
                    "realized_pnl": nrp,
                })

                for h in self.alert_handlers:
                    h.send_tp_hit(
                        symbol=sym, tp_level=tl, tp_pct=tpct,
                        current_price=cp, entry_price=ep,
                        pnl_chunk=chunk, remaining_pct=nr * 100,
                    )

                trade[tk] = 1
                trade["remaining_fraction"] = nr
                trade["realized_pnl"] = nrp

        # Stop trail
        nsp = trade.get("last_notified_stop_pct", 0)
        ssp = cs
        for tr in STOP_LOSS_TRAIL:
            if pcp >= tr["price_move_pct"] and tr["stop_at_pct"] > nsp:
                nsp = tr["stop_at_pct"]
                ssp = ep * (1 + nsp / 100)

        if nsp > trade.get("last_notified_stop_pct", 0):
            self.db.update_trade(sym, {
                "current_stop_price": ssp,
                "last_notified_stop_pct": nsp,
            })
            for h in self.alert_handlers:
                h.send_stop_update(
                    symbol=sym, new_stop_price=ssp, new_stop_pct=nsp,
                    current_price=cp, entry_price=ep,
                    reason=f"Price +{pcp:.1f}%",
                )

        # Signal degradation
        latest_score = self.db.get_latest_score(sym)
        if latest_score:
            csc = latest_score["composite_score"]
            psc = trade.get("last_score", 0)
            if psc > 0 and csc < psc - 20:
                for h in self.alert_handlers:
                    h.send_signal_degradation(
                        symbol=sym, old_score=psc, new_score=csc,
                        current_price=cp, entry_price=ep,
                        price_change_pct=pcp,
                    )
            self.db.update_trade(sym, {"last_score": csc})

        # Hourly status
        hrs = (time.time() - trade["entry_timestamp"]) / 3600
        ch = int(hrs)
        try:
            meta = (
                json.loads(trade.get("metadata", "{}"))
                if isinstance(trade.get("metadata"), str)
                else trade.get("metadata", {})
            )
        except Exception:
            meta = {}

        if ch > meta.get("last_status_hour", -1) and ch > 0:
            for h in self.alert_handlers:
                h.send_trade_status(
                    symbol=sym, entry_price=ep, current_price=cp,
                    price_change_pct=pcp, unrealized_pnl=upnl,
                    realized_pnl=trade["realized_pnl"],
                    remaining_pct=trade["remaining_fraction"] * 100,
                    current_stop=cs, hours_in=hrs,
                    score=latest_score["composite_score"] if latest_score else 0,
                )
            meta["last_status_hour"] = ch
            self.db.update_trade(sym, {"metadata": json.dumps(meta)})

    # ═══════════════════════════════════════════════════════════
    # ALERTS
    # ═══════════════════════════════════════════════════════════

    def _send_alerts(self, results):
        for r in results:
            if r["classification"] in ("CRITICAL", "HIGH_ALERT", "WATCHLIST"):
                for h in self.alert_handlers:
                    h.send_signal_alert(r)
            for e in r.get("events", []):
                for h in self.alert_handlers:
                    h.send_event(e)

    # ═══════════════════════════════════════════════════════════
    # TRADE MANAGEMENT
    # ═══════════════════════════════════════════════════════════

    def add_trade(self, sym, ep, ps, sl):
        sym = sym.upper().strip()
        ok = self.db.add_trade(sym, ep, ps, sl)
        if ok:
            for h in self.alert_handlers:
                h.send_trade_registered(sym, ep, ps, sl)
        return ok

    def close_trade(self, sym, exit_p=None):
        sym = sym.upper().strip()
        if exit_p is None:
            exit_p = self._live_price(sym)
        if exit_p is None:
            return None
        r = self.db.close_trade(sym, exit_p, "manual_close")
        if r:
            for h in self.alert_handlers:
                h.send_trade_closed(r, "MANUAL CLOSE")
        return r

    def get_trade_status(self):
        return self.db.get_active_trades()

    def adjust_stop(self, sym, price):
        sym = sym.upper().strip()
        t = self.db.get_active_trade(sym)
        if t:
            self.db.update_trade(sym, {"current_stop_price": price})
            sp = ((price - t["entry_price"]) / t["entry_price"]) * 100
            for h in self.alert_handlers:
                h.send_stop_update(
                    symbol=sym, new_stop_price=price, new_stop_pct=sp,
                    current_price=0, entry_price=t["entry_price"],
                    reason="Manual",
                )

    # ═══════════════════════════════════════════════════════════
    # HELPERS
    # ═══════════════════════════════════════════════════════════

    def _live_price(self, sym):
        u = self.db.get_universe()
        info = u.get(sym, {})
        for ex in info.get("futures_exchanges", []):
            exchange = self.universe_builder.get_exchange(ex)
            if not exchange:
                continue
            for fmt in [f"{sym}/USDT:USDT", f"{sym}/USDT"]:
                try:
                    t = exchange.fetch_ticker(fmt)
                    if t and t.get("last"):
                        return float(t["last"])
                except Exception:
                    continue
        return None

    def _cur_price(self, c):
        for ex, t in c.get("tickers", {}).items():
            p = t.get("last", 0)
            if p and float(p) > 0:
                return float(p)
        for ex, k in c.get("ohlcv", {}).items():
            if k:
                return float(k[-1][4])
        return 0

    def _price_7d(self, sym, c):
        cur = self._cur_price(c)
        if not cur:
            return 0
        for ex, k in c.get("ohlcv", {}).items():
            if k and len(k) >= 168:
                old = float(k[-168][4])
                if old > 0:
                    return ((cur - old) / old) * 100
            elif k and len(k) > 24:
                old = float(k[0][4])
                if old > 0:
                    return ((cur - old) / old) * 100
        h = self.db.get_snapshots(sym, "ticker", hours_back=168)
        if h:
            for x in h:
                p = x.get("last", 0)
                if p and float(p) > 0:
                    return ((cur - float(p)) / float(p)) * 100
        return 0

    def get_stats(self):
        s = self.db.get_stats()
        s["active_trades"] = len(self.db.get_active_trades())
        s["bootstrapped"] = len(self._bootstrapped)
        return s

    def cleanup(self, days=30):
        return self.db.cleanup(days)