"""
Signal computation engine — 9 signals with realistic normalization.
"""

import json
import time
from typing import Any, Dict, List, Optional

import numpy as np

from core.database import Database
from utils.helpers import clamp, piecewise_lerp, safe_divide
from utils.logger import get_logger

logger = get_logger("signals")


class SignalEngine:
    def __init__(self, db: Database):
        self.db = db

    def compute_all(self, symbol, collected_data):
        signals = {}
        signals["oi_surge"] = self._compute_oi_surge(symbol, collected_data)
        signals["funding_rate"] = self._compute_funding_rate(symbol, collected_data)
        signals["liquidation_leverage"] = self._compute_liquidation_leverage(symbol, collected_data)
        signals["cross_exchange_volume"] = self._compute_cross_exchange_volume(symbol, collected_data)
        signals["depth_imbalance"] = self._compute_depth_imbalance(symbol, collected_data)
        signals["volume_price_decouple"] = self._compute_volume_price_decouple(symbol, collected_data)
        signals["volatility_compression"] = self._compute_volatility_compression(symbol, collected_data)
        signals["long_short_ratio"] = self._compute_long_short_ratio(symbol, collected_data)
        signals["futures_spot_divergence"] = self._compute_futures_spot_divergence(symbol, collected_data)

        ts = time.time()
        rows = [
            (ts, symbol, n, s.get("raw_value", 0),
             s.get("normalized_score", 0), json.dumps(s.get("metadata", {})))
            for n, s in signals.items()
        ]
        if rows:
            self.db.store_signals_batch(rows)
        return signals

    def _compute_oi_surge(self, symbol, data):
        current_oi = {ex: v for ex, v in data.get("open_interest", {}).items() if v and v > 0}
        if not current_oi:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "no OI"}}
        total_current = sum(current_oi.values())

        historical = self.db.get_snapshots(symbol, "open_interest", hours_back=72)
        if not historical:
            return {"raw_value": 0, "normalized_score": 0,
                    "metadata": {"reason": "no hist OI", "current_oi": total_current}}

        earliest = min(h["_timestamp"] for h in historical)
        oldest_oi = {}
        for h in historical:
            if h["_timestamp"] <= earliest + 3600:
                ex = h["_exchange"]
                oi = h.get("open_interest", 0)
                if oi and oi > 0:
                    oldest_oi[ex] = oi

        if not oldest_oi:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "no valid hist OI"}}

        total_old = sum(oldest_oi.values())
        if total_old == 0:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "zero hist OI"}}

        oi_pct = ((total_current - total_old) / total_old) * 100
        price_pct = self._get_price_change(symbol, data, hours=72)
        pf = max(0.2, 1.0 - abs(price_pct) / 20.0)
        effective = oi_pct * pf

        norm = piecewise_lerp(effective, [
            (-10, 0), (0, 10), (5, 25), (10, 45), (15, 58),
            (20, 68), (30, 80), (40, 90), (60, 100),
        ])

        return {
            "raw_value": round(oi_pct, 2),
            "normalized_score": round(clamp(norm, 0, 100), 1),
            "metadata": {
                "oi_change_pct": round(oi_pct, 2),
                "price_change_pct": round(price_pct, 2),
                "current_oi": round(total_current, 2),
                "old_oi": round(total_old, 2),
                "history_hours": round((time.time() - earliest) / 3600, 1),
                "exchanges_with_oi": list(current_oi.keys()),
            },
        }

    def _compute_funding_rate(self, symbol, data):
        fr = data.get("funding_rates", {})
        if not fr:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "no funding"}}

        current = float(np.mean(list(fr.values())))

        hist = self.db.get_snapshots(symbol, "funding_rate", hours_back=72)
        neg, total = 0, 0
        for h in hist:
            r = h.get("funding_rate")
            if r is not None:
                total += 1
                if float(r) < -0.0001:
                    neg += 1
        persist = safe_divide(neg, max(total, 1))

        if current >= 0:
            mag = piecewise_lerp(-current, [(-0.001, 0), (0, 5)])
        else:
            mag = piecewise_lerp(abs(current), [
                (0, 5), (0.0003, 20), (0.0005, 30), (0.001, 45),
                (0.0015, 55), (0.002, 65), (0.003, 78), (0.005, 90), (0.01, 100),
            ])

        per = piecewise_lerp(persist, [
            (0, 0), (0.3, 20), (0.5, 45), (0.7, 70), (0.85, 90), (1.0, 100),
        ])

        norm = mag * 0.55 + per * 0.45

        return {
            "raw_value": round(current, 6),
            "normalized_score": round(clamp(norm, 0, 100), 1),
            "metadata": {
                "current_rate": round(current, 6),
                "current_rate_pct": f"{current * 100:.4f}%",
                "negative_periods": neg,
                "total_periods": total,
                "persistence_ratio": round(persist, 2),
                "exchanges": list(fr.keys()),
            },
        }

    def _compute_liquidation_leverage(self, symbol, data):
        price = self._get_current_price(data)
        if not price or price <= 0:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "no price"}}

        total_oi = sum(v for v in data.get("open_interest", {}).values() if v and v > 0)
        if total_oi == 0:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "no OI"}}

        ls = data.get("long_short_ratios", {})
        sf = safe_divide(1.0, 1.0 + float(np.mean(list(ls.values()))), 0.5) if ls else 0.5
        short_oi = total_oi * sf
        liq15 = short_oi * min(0.15 / (1.0 / 8.0), 0.8)

        ask_res = sum(
            p * a for ex, ob in data.get("orderbooks", {}).items()
            for p, a in ob.get("asks", []) if p <= price * 1.15
        )
        ratio = safe_divide(liq15, ask_res, 3.0) if ask_res > 0 else 3.0

        norm = piecewise_lerp(ratio, [
            (0.5, 0), (1, 10), (2, 35), (3, 55), (5, 75), (8, 90), (12, 100),
        ])

        return {
            "raw_value": round(ratio, 2),
            "normalized_score": round(clamp(norm, 0, 100), 1),
            "metadata": {
                "leverage_ratio": round(ratio, 2),
                "estimated_liq_within_15pct": round(liq15, 2),
                "ask_resistance_15pct": round(ask_res, 2),
                "short_fraction": round(sf, 2),
            },
        }

    def _compute_cross_exchange_volume(self, symbol, data):
        vols = {}
        for ex, t in data.get("tickers", {}).items():
            v = float(t.get("quoteVolume") or t.get("volume", 0) or 0)
            if v > 0:
                vols[ex] = v

        if len(vols) < 2:
            if len(vols) == 1:
                return self._single_exchange_volume(symbol, vols)
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "need 2+ exchanges"}}

        vals = list(vols.values())
        med = float(np.median(vals))
        if med <= 0:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "zero median"}}

        div = max(vals) / med
        norm = piecewise_lerp(div, [
            (1, 0), (1.3, 18), (1.5, 35), (2, 55), (3, 75), (4, 88), (6, 100),
        ])

        return {
            "raw_value": round(div, 2),
            "normalized_score": round(clamp(norm, 0, 100), 1),
            "metadata": {
                "divergence_ratio": round(div, 2),
                "max_volume_exchange": max(vols, key=vols.get),
                "volumes": {k: round(v, 2) for k, v in vols.items()},
            },
        }

    def _single_exchange_volume(self, symbol, volumes):
        ex = list(volumes.keys())[0]
        cur = volumes[ex]
        hist = self.db.get_snapshots(symbol, "ticker", hours_back=72)
        if not hist or len(hist) < 5:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "no hist"}}
        hvols = [float(h.get("quoteVolume") or h.get("volume", 0)) for h in hist if float(h.get("quoteVolume") or h.get("volume", 0) or 0) > 0]
        if not hvols:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "no hist vol"}}
        avg = float(np.mean(hvols))
        if avg == 0:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "zero avg"}}
        ratio = cur / avg
        norm = piecewise_lerp(ratio, [(0.8, 0), (1, 5), (1.5, 30), (2, 50), (3, 70), (5, 90), (8, 100)])
        return {
            "raw_value": round(ratio, 2),
            "normalized_score": round(clamp(norm, 0, 100), 1),
            "metadata": {"volume_vs_avg": round(ratio, 2), "single_exchange": ex},
        }

    def _compute_depth_imbalance(self, symbol, data):
        bid_v = sum(p * a for ex, ob in data.get("orderbooks", {}).items() for p, a in ob.get("bids", []))
        ask_v = sum(p * a for ex, ob in data.get("orderbooks", {}).items() for p, a in ob.get("asks", []))
        if ask_v == 0:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "no asks"}}
        ratio = safe_divide(bid_v, ask_v, 1.0)
        norm = piecewise_lerp(ratio, [
            (1, 0), (1.15, 15), (1.3, 30), (1.5, 50), (1.8, 65),
            (2, 75), (2.5, 88), (3, 95), (4, 100),
        ]) if ratio >= 1.0 else 0

        return {
            "raw_value": round(ratio, 3),
            "normalized_score": round(clamp(norm, 0, 100), 1),
            "metadata": {
                "imbalance_ratio": round(ratio, 3),
                "total_bid_value": round(bid_v, 2),
                "total_ask_value": round(ask_v, 2),
            },
        }

    def _compute_volume_price_decouple(self, symbol, data):
        candles = []
        for ex, c in data.get("ohlcv", {}).items():
            if c and len(c) >= 20:
                candles = c
                break
        if not candles or len(candles) < 20:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "no OHLCV"}}

        if len(candles) >= 48:
            recent, prev = candles[-24:], candles[-48:-24]
        else:
            h = len(candles) // 2
            recent, prev = candles[h:], candles[:h]

        rv = sum(c[5] for c in recent if len(c) > 5 and c[5])
        pv = sum(c[5] for c in prev if len(c) > 5 and c[5])
        if pv == 0:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "zero prev vol"}}

        vc = (rv - pv) / pv * 100
        pc = abs((recent[-1][4] - recent[0][1]) / recent[0][1] * 100) if recent[0][1] else 0
        raw = max(0, vc * max(0.15, 1.0 - pc / 12.0)) if vc > 0 else 0

        norm = piecewise_lerp(raw, [
            (0, 0), (10, 15), (20, 30), (35, 50), (50, 63),
            (75, 78), (100, 88), (150, 95), (200, 100),
        ])

        return {
            "raw_value": round(raw, 2),
            "normalized_score": round(clamp(norm, 0, 100), 1),
            "metadata": {"volume_change_pct": round(vc, 2), "price_change_pct": round(pc, 2)},
        }

    def _compute_volatility_compression(self, symbol, data):
        candles = []
        for ex, c in data.get("ohlcv", {}).items():
            if c and len(c) > len(candles):
                candles = c
        if not candles or len(candles) < 30:
            return {"raw_value": 0, "normalized_score": 0,
                    "metadata": {"reason": "no data", "candles": len(candles) if candles else 0}}

        closes = np.array([c[4] for c in candles], dtype=float)
        highs = np.array([c[2] for c in candles], dtype=float)
        lows = np.array([c[3] for c in candles], dtype=float)

        bbw = []
        for i in range(20, len(closes)):
            w = closes[i - 20:i]
            s, st = np.mean(w), np.std(w)
            if s > 0:
                bbw.append((2 * st) / s)

        if not bbw or len(bbw) < 5:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "no BB data"}}

        cur_bbw = bbw[-1]
        pctl = sum(1 for w in bbw if w > cur_bbw) / len(bbw) * 100

        tr = [
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, len(closes))
        ]
        atr = float(np.mean(tr[-14:])) if len(tr) >= 14 else (float(np.mean(tr)) if tr else 0)
        atr_pct = (atr / closes[-1] * 100) if closes[-1] > 0 else 0

        norm = piecewise_lerp(pctl, [
            (0, 0), (30, 10), (50, 25), (65, 42), (75, 58),
            (85, 75), (92, 88), (97, 95), (100, 100),
        ])

        return {
            "raw_value": round(cur_bbw, 6),
            "normalized_score": round(clamp(norm, 0, 100), 1),
            "metadata": {
                "bb_width": round(cur_bbw, 6),
                "bb_percentile": round(pctl, 1),
                "atr": round(atr, 6),
                "atr_pct": round(atr_pct, 4),
                "candles_used": len(closes),
            },
        }

    def _compute_long_short_ratio(self, symbol, data):
        ls = data.get("long_short_ratios", {})
        if not ls:
            hist = self.db.get_snapshots(symbol, "long_short_ratio", hours_back=24)
            if hist:
                r = hist[-1].get("long_short_ratio")
                if r:
                    ls = {"historical": float(r)}
        if not ls:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "no L/S"}}

        avg = float(np.mean(list(ls.values())))

        if avg >= 1.0:
            norm = piecewise_lerp(avg, [(1.0, 8), (1.1, 3), (1.3, 0)])
        else:
            norm = piecewise_lerp(avg, [
                (0.5, 100), (0.6, 90), (0.7, 75), (0.8, 55),
                (0.85, 42), (0.9, 30), (0.95, 18), (1.0, 8),
            ])

        return {
            "raw_value": round(avg, 4),
            "normalized_score": round(clamp(norm, 0, 100), 1),
            "metadata": {"avg_ls_ratio": round(avg, 4),
                         "per_exchange": {k: round(v, 4) for k, v in ls.items()}},
        }

    def _compute_futures_spot_divergence(self, symbol, data):
        tickers = data.get("tickers", {})
        if not tickers:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "no tickers"}}

        total_vol = sum(float(t.get("quoteVolume", 0) or 0) for t in tickers.values())

        hist = self.db.get_snapshots(symbol, "ticker", hours_back=72)
        if not hist or len(hist) < 5:
            return {"raw_value": 0, "normalized_score": 0,
                    "metadata": {"reason": "no hist", "current_volume": total_vol}}

        hvols = [
            float(h.get("quoteVolume") or h.get("volume", 0))
            for h in hist if float(h.get("quoteVolume") or h.get("volume", 0) or 0) > 0
        ]
        if not hvols:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "no hist vol"}}

        avg = float(np.mean(hvols))
        if avg == 0:
            return {"raw_value": 0, "normalized_score": 0, "metadata": {"reason": "zero avg"}}

        ratio = total_vol / avg
        norm = piecewise_lerp(ratio, [
            (0.5, 0), (1, 5), (1.3, 20), (1.5, 35), (2, 55),
            (2.5, 68), (3, 78), (4, 90), (6, 100),
        ])

        return {
            "raw_value": round(ratio, 2),
            "normalized_score": round(clamp(norm, 0, 100), 1),
            "metadata": {
                "volume_ratio": round(ratio, 2),
                "current_volume": round(total_vol, 2),
                "avg_volume": round(avg, 2),
            },
        }

    # ─── Helpers ─────────────────────────────────────────────────

    def _get_current_price(self, data):
        for ex, t in data.get("tickers", {}).items():
            p = t.get("last", 0)
            if p and float(p) > 0:
                return float(p)
        for ex, c in data.get("ohlcv", {}).items():
            if c:
                return float(c[-1][4])
        return 0

    def _get_price_change(self, symbol, data, hours=72):
        cur = self._get_current_price(data)
        if not cur:
            return 0
        for ex, candles in data.get("ohlcv", {}).items():
            if candles and len(candles) >= hours:
                old = float(candles[-hours][4])
                if old > 0:
                    return ((cur - old) / old) * 100
            elif candles and len(candles) > 1:
                old = float(candles[0][4])
                if old > 0:
                    return ((cur - old) / old) * 100
        hist = self.db.get_snapshots(symbol, "ticker", hours_back=hours)
        if hist:
            for h in hist:
                old = h.get("last", 0)
                if old and float(old) > 0:
                    return ((cur - float(old)) / float(old)) * 100
        return 0