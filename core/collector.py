"""
Exchange data collection + bootstrap historical data.
Uses CCXT unified methods for maximum compatibility across versions.
"""

import json
import time
from typing import Any, Dict, List, Optional

import ccxt

from core.database import Database
from utils.helpers import (
    BOOTSTRAP_FUNDING_PERIODS,
    BOOTSTRAP_LS_PERIODS,
    BOOTSTRAP_OI_PERIODS,
    BOOTSTRAP_OHLCV_CANDLES,
    REGULAR_OHLCV_CANDLES,
    normalize_symbol,
    safe_divide,
)
from utils.logger import get_logger

logger = get_logger("collector")


class DataCollector:
    def __init__(self, exchanges, db, config):
        self.exchanges = exchanges
        self.db = db
        self.config = config
        self.candle_limit = config.get("scanning", {}).get(
            "ohlcv_candle_limit", REGULAR_OHLCV_CANDLES
        )
        self.orderbook_depth = config.get("scanning", {}).get("orderbook_depth", 50)

    # ═══════════════════════════════════════════════════════════
    #  HELPERS
    # ═══════════════════════════════════════════════════════════

    def _make_pair(self, symbol, exchange_name):
        exchange = self.exchanges.get(exchange_name)
        if not exchange:
            return None
        candidates = [f"{symbol}/USDT:USDT", f"{symbol}/USDT"]
        if hasattr(exchange, "markets") and exchange.markets:
            for c in candidates:
                if c in exchange.markets:
                    return c
        return candidates[0]

    def _quick_price(self, exchange, pair):
        try:
            t = exchange.fetch_ticker(pair)
            if t and t.get("last"):
                return float(t["last"])
        except Exception:
            pass
        return 0

    def _call_api(self, exchange, method_names, params):
        """
        Try multiple implicit-API method names so the same code
        works on ccxt v3 (camelCase) and v4 (underscore) naming.
        Returns the response from the first method that exists and succeeds.
        """
        last_err = None
        for name in method_names:
            fn = getattr(exchange, name, None)
            if fn is not None:
                try:
                    return fn(params)
                except Exception as e:
                    last_err = e
        if last_err:
            raise last_err
        raise AttributeError(
            f"Exchange has none of these methods: {method_names}"
        )

    # ═══════════════════════════════════════════════════════════
    #  BOOTSTRAP
    # ═══════════════════════════════════════════════════════════

    def needs_bootstrap(self, symbol):
        snaps = self.db.get_snapshots(symbol, "open_interest", hours_back=200)
        if not snaps:
            return True
        oldest = min(s["_timestamp"] for s in snaps)
        return (time.time() - oldest) / 3600 < 48

    def bootstrap_token(self, symbol, futures_exchanges):
        logger.info(f"  ⏳ Bootstrapping {symbol}...")

        for ex_name in futures_exchanges:
            exchange = self.exchanges.get(ex_name)
            if not exchange:
                continue
            pair = self._make_pair(symbol, ex_name)
            if not pair:
                continue
            current_price = self._quick_price(exchange, pair)

            # ── Historical OI (unified) ──────────────────────
            oi_hist = self._fetch_oi_history(
                exchange, ex_name, symbol, pair, current_price
            )
            if oi_hist:
                rows = [
                    (
                        p["timestamp"], symbol, ex_name, "open_interest",
                        json.dumps({"open_interest": p["open_interest"]}),
                    )
                    for p in oi_hist
                ]
                self.db.store_snapshots_batch(rows)
                logger.info(f"    {ex_name}: {len(rows)} OI points")

            # ── Historical Funding (unified) ─────────────────
            fund_hist = self._fetch_funding_history(
                exchange, ex_name, symbol, pair
            )
            if fund_hist:
                rows = [
                    (
                        p["timestamp"], symbol, ex_name, "funding_rate",
                        json.dumps({"funding_rate": p["funding_rate"]}),
                    )
                    for p in fund_hist
                ]
                self.db.store_snapshots_batch(rows)
                logger.info(f"    {ex_name}: {len(rows)} funding points")

            # ── Historical L/S Ratio (exchange-specific) ─────
            ls_hist = self._fetch_ls_history(exchange, ex_name, symbol)
            if ls_hist:
                rows = [
                    (
                        p["timestamp"], symbol, ex_name, "long_short_ratio",
                        json.dumps({"long_short_ratio": p["long_short_ratio"]}),
                    )
                    for p in ls_hist
                ]
                self.db.store_snapshots_batch(rows)
                logger.info(f"    {ex_name}: {len(rows)} L/S points")

            # ── OHLCV + synthetic tickers ────────────────────
            try:
                ohlcv = exchange.fetch_ohlcv(
                    pair, timeframe="1h", limit=BOOTSTRAP_OHLCV_CANDLES
                )
                if ohlcv and len(ohlcv) > 10:
                    ticker_rows = []
                    for c in ohlcv:
                        ts = c[0] / 1000
                        td = {
                            "last": c[4],
                            "high": c[2],
                            "low": c[3],
                            "volume": c[5],
                            "quoteVolume": (
                                c[5] * c[4] if c[5] and c[4] else 0
                            ),
                        }
                        ticker_rows.append(
                            (ts, symbol, ex_name, "ticker", json.dumps(td))
                        )
                    self.db.store_snapshots_batch(ticker_rows)
                    logger.info(
                        f"    {ex_name}: {len(ticker_rows)} ticker snapshots"
                    )
            except Exception as e:
                logger.warning(f"    {ex_name}: OHLCV bootstrap fail: {e}")

            time.sleep(0.3)

        logger.info(f"  ✅ Bootstrap done: {symbol}")

    # ─── Bootstrap: OI history ────────────────────────────────

 

    def _fetch_oi_history(self, exchange, ex_name, symbol, pair, price):
        """
        Unified first, then exchange-specific fallbacks for
        exchanges where the unified method is not yet supported.
        """
        results = []

        # ── Try unified method first ─────────────────────────
        try:
            data = exchange.fetch_open_interest_history(
                pair, timeframe="1h", limit=BOOTSTRAP_OI_PERIODS
            )
            for item in data:
                ts = item.get("timestamp", 0)
                if ts > 1e12:
                    ts /= 1000
                oi = item.get("openInterestValue") or 0
                if not oi:
                    amt = item.get("openInterestAmount", 0)
                    oi = float(amt) * price if amt and price else 0
                if float(oi) > 0 and ts > 0:
                    results.append({
                        "timestamp": ts,
                        "open_interest": float(oi),
                    })
            if results:
                return results
        except Exception as e:
            logger.debug(f"    OI unified {symbol}/{ex_name}: {e}")

        # ── Bitget fallback (v2 REST API) ────────────────────
        if ex_name == "bitget":
            try:
                resp = self._call_api(
                    exchange,
                    [
                        # v2 API — try both ccxt v3 and v4 naming
                        "publicMixGetV2MixMarketOpenInterestHistory",
                        "public_mix_get_v2_mix_market_open_interest_history",
                        # v1 API fallback
                        "publicMixGetMixV1MarketOpenInterestHistory",
                        "public_mix_get_mix_v1_market_open_interest_history",
                    ],
                    {
                        "symbol": f"{symbol}USDT",
                        "productType": "USDT-FUTURES",
                        "period": "1h",
                        "limit": str(BOOTSTRAP_OI_PERIODS),
                    },
                )
                data_list = []
                if isinstance(resp, dict):
                    data_list = resp.get("data", {})
                    if isinstance(data_list, dict):
                        data_list = data_list.get("list", [])
                elif isinstance(resp, list):
                    data_list = resp

                for item in data_list:
                    ts = int(item.get("ts", item.get("timestamp", 0)))
                    if ts > 1e12:
                        ts /= 1000
                    # bitget may return base-unit OI → multiply by price
                    oi = float(item.get("openInterestValue",
                               item.get("openInterest", 0)))
                    if oi > 0 and oi < 1e6 and price:
                        # heuristic: if value looks like base units, convert
                        oi = oi * price
                    if oi > 0 and ts > 0:
                        results.append({
                            "timestamp": ts,
                            "open_interest": oi,
                        })
                if results:
                    return results
            except Exception as e:
                logger.debug(f"    OI bitget-api {symbol}: {e}")

            # ── Last resort: build from current snapshots ────
            try:
                oi_data = exchange.fetch_open_interest(pair)
                if oi_data:
                    v = oi_data.get("openInterestValue") or 0
                    if not v:
                        amt = oi_data.get("openInterestAmount", 0)
                        v = float(amt) * price if amt and price else 0
                    if float(v) > 0:
                        results.append({
                            "timestamp": time.time(),
                            "open_interest": float(v),
                        })
            except Exception as e:
                logger.debug(f"    OI bitget-single {symbol}: {e}")

        # ── Bybit fallback ───────────────────────────────────
        elif ex_name == "bybit":
            try:
                resp = self._call_api(
                    exchange,
                    [
                        "publicGetV5MarketOpenInterest",
                        "public_get_v5_market_open_interest",
                    ],
                    {
                        "category": "linear",
                        "symbol": f"{symbol}USDT",
                        "intervalTime": "1h",
                        "limit": BOOTSTRAP_OI_PERIODS,
                    },
                )
                if resp and resp.get("result", {}).get("list"):
                    for item in resp["result"]["list"]:
                        ts = int(item.get("timestamp", 0)) / 1000
                        oi_base = float(item.get("openInterest", 0))
                        oi = oi_base * price if price else oi_base
                        if oi > 0 and ts > 0:
                            results.append({
                                "timestamp": ts,
                                "open_interest": oi,
                            })
            except Exception as e:
                logger.debug(f"    OI bybit-api {symbol}: {e}")

        if not results:
            logger.info(f"    OI history {symbol}/{ex_name}: no data")
        return results

    # ─── Bootstrap: Funding history ──────────────────────────

    def _fetch_funding_history(self, exchange, ex_name, symbol, pair):
        """Use the CCXT *unified* fetch_funding_rate_history()."""
        results = []
        try:
            data = exchange.fetch_funding_rate_history(
                pair, limit=BOOTSTRAP_FUNDING_PERIODS
            )
            for item in data:
                ts = item.get("timestamp", 0)
                if ts > 1e12:
                    ts /= 1000
                rate = item.get("fundingRate")
                if ts > 0 and rate is not None:
                    results.append({
                        "timestamp": ts,
                        "funding_rate": float(rate),
                    })
        except Exception as e:
            logger.info(f"    Funding history {symbol}/{ex_name}: {e}")
        return results

    # ─── Bootstrap: L/S ratio history (no unified method) ────

    def _fetch_ls_history(self, exchange, ex_name, symbol):
        results = []
        try:
            if ex_name == "binance":
                resp = self._call_api(
                    exchange,
                    [
                        "fapiDataGetGlobalLongShortAccountRatio",
                        "fapiData_get_globalLongShortAccountRatio",
                    ],
                    {
                        "symbol": f"{symbol}USDT",
                        "period": "1h",
                        "limit": BOOTSTRAP_LS_PERIODS,
                    },
                )
                if resp:
                    for item in resp:
                        ts = int(item.get("timestamp", 0)) / 1000
                        ratio = float(item.get("longShortRatio", 1.0))
                        if ts > 0:
                            results.append({
                                "timestamp": ts,
                                "long_short_ratio": ratio,
                            })

            elif ex_name == "bybit":
                resp = self._call_api(
                    exchange,
                    [
                        "publicGetV5MarketAccountRatio",
                        "public_get_v5_market_account_ratio",
                    ],
                    {
                        "category": "linear",
                        "symbol": f"{symbol}USDT",
                        "period": "1h",
                        "limit": BOOTSTRAP_LS_PERIODS,
                    },
                )
                if resp and resp.get("result", {}).get("list"):
                    for item in resp["result"]["list"]:
                        ts = int(item.get("timestamp", 0)) / 1000
                        buy = float(item.get("buyRatio", 0.5))
                        sell = float(item.get("sellRatio", 0.5))
                        if ts > 0:
                            results.append({
                                "timestamp": ts,
                                "long_short_ratio": safe_divide(
                                    buy, sell, 1.0
                                ),
                            })

        except Exception as e:
            logger.info(f"    L/S history {symbol}/{ex_name}: {e}")
        return results

    # ═══════════════════════════════════════════════════════════
    #  REGULAR COLLECTION
    # ═══════════════════════════════════════════════════════════

    def collect_all(self, symbol, futures_exchanges):
        ts = time.time()
        result = {
            "symbol": symbol,
            "timestamp": ts,
            "ohlcv": {},
            "tickers": {},
            "open_interest": {},
            "funding_rates": {},
            "orderbooks": {},
            "long_short_ratios": {},
        }
        snapshot_rows = []

        for ex_name in futures_exchanges:
            exchange = self.exchanges.get(ex_name)
            if not exchange:
                continue
            pair = self._make_pair(symbol, ex_name)
            if not pair:
                continue

            # OHLCV
            try:
                ohlcv = exchange.fetch_ohlcv(
                    pair, timeframe="1h", limit=self.candle_limit
                )
                if ohlcv and len(ohlcv) > 0:
                    result["ohlcv"][ex_name] = ohlcv
                    snapshot_rows.append(
                        (
                            ts, symbol, ex_name, "ohlcv",
                            json.dumps({"candles": ohlcv[-72:]}),
                        )
                    )
            except Exception as e:
                logger.info(f"OHLCV fail {symbol}/{ex_name}: {e}")

            # Ticker
            try:
                ticker = exchange.fetch_ticker(pair)
                if ticker:
                    td = {
                        "last": ticker.get("last"),
                        "bid": ticker.get("bid"),
                        "ask": ticker.get("ask"),
                        "high": ticker.get("high"),
                        "low": ticker.get("low"),
                        "volume": ticker.get("baseVolume"),
                        "quoteVolume": ticker.get("quoteVolume"),
                        "change_pct": ticker.get("percentage"),
                    }
                    result["tickers"][ex_name] = td
                    snapshot_rows.append(
                        (ts, symbol, ex_name, "ticker", json.dumps(td))
                    )
            except Exception as e:
                logger.info(f"Ticker fail {symbol}/{ex_name}: {e}")

            # Open Interest (unified)
            try:
                oi = self._fetch_open_interest(exchange, ex_name, pair, symbol)
                if oi and oi > 0:
                    result["open_interest"][ex_name] = oi
                    snapshot_rows.append(
                        (
                            ts, symbol, ex_name, "open_interest",
                            json.dumps({"open_interest": oi}),
                        )
                    )
            except Exception as e:
                logger.info(f"OI fail {symbol}/{ex_name}: {e}")

            # Funding Rate (unified)
            try:
                funding = self._fetch_funding_rate(
                    exchange, ex_name, pair, symbol
                )
                if funding is not None:
                    result["funding_rates"][ex_name] = funding
                    snapshot_rows.append(
                        (
                            ts, symbol, ex_name, "funding_rate",
                            json.dumps({"funding_rate": funding}),
                        )
                    )
            except Exception as e:
                logger.info(f"Funding fail {symbol}/{ex_name}: {e}")

            # Order Book
            try:
                ob = exchange.fetch_order_book(
                    pair, limit=self.orderbook_depth
                )
                if ob and ob.get("bids") and ob.get("asks"):
                    obd = {
                        "bids": ob["bids"][: self.orderbook_depth],
                        "asks": ob["asks"][: self.orderbook_depth],
                    }
                    result["orderbooks"][ex_name] = obd
                    snapshot_rows.append(
                        (ts, symbol, ex_name, "orderbook", json.dumps(obd))
                    )
            except Exception as e:
                logger.info(f"OB fail {symbol}/{ex_name}: {e}")

            # Long/Short Ratio
            try:
                ls = self._fetch_long_short_ratio(
                    exchange, ex_name, pair, symbol
                )
                if ls is not None:
                    result["long_short_ratios"][ex_name] = ls
                    snapshot_rows.append(
                        (
                            ts, symbol, ex_name, "long_short_ratio",
                            json.dumps({"long_short_ratio": ls}),
                        )
                    )
            except Exception as e:
                logger.info(f"L/S fail {symbol}/{ex_name}: {e}")

        if snapshot_rows:
            self.db.store_snapshots_batch(snapshot_rows)

        return result

    # ─── Regular: Current OI ─────────────────────────────────

    def _fetch_open_interest(self, exchange, ex_name, pair, symbol):
        """Unified first, then exchange-specific fallback."""
        # --- unified (works for binance / bybit / bitget / okx) ---
        try:
            oi = exchange.fetch_open_interest(pair)
            if oi:
                v = oi.get("openInterestValue") or oi.get(
                    "openInterestAmount", 0
                )
                if v and float(v) > 0:
                    return float(v)
        except Exception as e:
            logger.debug(f"OI unified {symbol}/{ex_name}: {e}")

        # --- fallback ---
        try:
            if ex_name == "binance":
                r = self._call_api(
                    exchange,
                    [
                        "fapiPublicGetOpenInterest",
                        "fapiPublic_get_openInterest",
                    ],
                    {"symbol": f"{symbol}USDT"},
                )
                if r and "openInterest" in r:
                    t = exchange.fetch_ticker(pair)
                    p = t["last"] if t else 1
                    return float(r["openInterest"]) * p

            elif ex_name == "bybit":
                r = self._call_api(
                    exchange,
                    [
                        "publicGetV5MarketOpenInterest",
                        "public_get_v5_market_open_interest",
                    ],
                    {
                        "category": "linear",
                        "symbol": f"{symbol}USDT",
                        "intervalTime": "5min",
                        "limit": 1,
                    },
                )
                if r and r.get("result", {}).get("list"):
                    oi_val = float(
                        r["result"]["list"][0].get("openInterest", 0)
                    )
                    t = exchange.fetch_ticker(pair)
                    p = t["last"] if t else 1
                    return oi_val * p

        except Exception as e:
            logger.info(f"OI fallback {symbol}/{ex_name}: {e}")
        return None

    # ─── Regular: Current Funding ────────────────────────────

    def _fetch_funding_rate(self, exchange, ex_name, pair, symbol):
        """Unified first, then exchange-specific fallback."""
        try:
            fr = exchange.fetch_funding_rate(pair)
            if fr and "fundingRate" in fr:
                return float(fr["fundingRate"])
        except Exception as e:
            logger.debug(f"Funding unified {symbol}/{ex_name}: {e}")

        try:
            if ex_name == "binance":
                r = self._call_api(
                    exchange,
                    [
                        "fapiPublicGetPremiumIndex",
                        "fapiPublic_get_premiumIndex",
                    ],
                    {"symbol": f"{symbol}USDT"},
                )
                if r and "lastFundingRate" in r:
                    return float(r["lastFundingRate"])

            elif ex_name == "bybit":
                r = self._call_api(
                    exchange,
                    [
                        "publicGetV5MarketTickers",
                        "public_get_v5_market_tickers",
                    ],
                    {"category": "linear", "symbol": f"{symbol}USDT"},
                )
                if r and r.get("result", {}).get("list"):
                    return float(
                        r["result"]["list"][0].get("fundingRate", 0)
                    )

        except Exception as e:
            logger.info(f"Funding fallback {symbol}/{ex_name}: {e}")
        return None

    # ─── Regular: Current L/S ratio ──────────────────────────

    def _fetch_long_short_ratio(self, exchange, ex_name, pair, symbol):
        try:
            if ex_name == "binance":
                r = self._call_api(
                    exchange,
                    [
                        "fapiDataGetGlobalLongShortAccountRatio",
                        "fapiData_get_globalLongShortAccountRatio",
                    ],
                    {
                        "symbol": f"{symbol}USDT",
                        "period": "1h",
                        "limit": 1,
                    },
                )
                if r and len(r) > 0:
                    return float(r[0].get("longShortRatio", 1.0))

            elif ex_name == "bybit":
                r = self._call_api(
                    exchange,
                    [
                        "publicGetV5MarketAccountRatio",
                        "public_get_v5_market_account_ratio",
                    ],
                    {
                        "category": "linear",
                        "symbol": f"{symbol}USDT",
                        "period": "1h",
                        "limit": 1,
                    },
                )
                if r and r.get("result", {}).get("list"):
                    buy = float(
                        r["result"]["list"][0].get("buyRatio", 0.5)
                    )
                    sell = float(
                        r["result"]["list"][0].get("sellRatio", 0.5)
                    )
                    return safe_divide(buy, sell, 1.0)

        except Exception as e:
            logger.info(f"L/S fail {symbol}/{ex_name}: {e}")
        return None