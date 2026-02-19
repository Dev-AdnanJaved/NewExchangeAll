"""
Smart entry/stop/TP calculator using ATR, orderbook, swing lows,
liquidation data, and signal strength.
"""

import math
from typing import Any, Dict, List, Optional

import numpy as np

from utils.helpers import clamp, safe_divide
from utils.logger import get_logger

logger = get_logger("levels")


class LevelsCalculator:
    MIN_STOP_PCT = 2.5
    MAX_STOP_PCT = 15.0
    MIN_TP1_PCT = 5.0
    MIN_RR_RATIO = 1.5

    def compute(self, symbol, price, collected_data, signals, score_result):
        if not price or price <= 0:
            return self._empty("no price")

        score = score_result.get("composite_score", 0)
        classification = score_result.get("classification", "NONE")
        atr = self._get_atr(signals, price)
        atr_pct = (atr / price * 100) if price > 0 else 5.0
        candles = self._get_candles(collected_data)
        ob = self._merge_ob(collected_data)
        liq = self._get_liq(signals)

        stop = self._calc_stop(price, atr, atr_pct, candles, ob, score, classification)
        entry = self._calc_entry(price, atr, atr_pct, candles, ob, score, classification)
        tps = self._calc_tps(price, atr, atr_pct, candles, ob, liq, score, stop)
        trailing = self._calc_trailing(price, atr, atr_pct, score)
        rr = self._calc_rr(entry, stop, tps)

        return {
            "symbol": symbol,
            "price": price,
            "entry": entry,
            "stop": stop,
            "take_profits": tps,
            "trailing": trailing,
            "risk_reward": rr,
            "atr": {"value": round(atr, 8), "pct": round(atr_pct, 2)},
            "data_quality": self._quality(candles, ob, signals),
        }

    # ═══════════════════════════════════════════════════════════
    # STOP LOSS
    # ═══════════════════════════════════════════════════════════

    def _calc_stop(self, price, atr, atr_pct, candles, ob, score, cl):
        methods = []
        candidates = []

        # Method 1: ATR
        mult = 1.5 if score >= 78 else (2.0 if score >= 62 else 2.5)
        atr_stop = price - (atr * mult)
        atr_pct_val = ((price - atr_stop) / price) * 100
        candidates.append(("atr", atr_stop, atr_pct_val))
        methods.append(f"ATR*{mult}")

        # Method 2: Swing low
        swing_stop = swing_pct = None
        if candles and len(candles) >= 12:
            lookback = min(24, len(candles))
            lows = [c[3] for c in candles[-lookback:] if c[3] > 0]
            if lows:
                sl = min(lows)
                swing_stop = sl * 0.995
                swing_pct = ((price - swing_stop) / price) * 100
                if self.MIN_STOP_PCT <= swing_pct <= self.MAX_STOP_PCT:
                    candidates.append(("swing_low", swing_stop, swing_pct))
                    methods.append(f"Swing ${sl:.6g}")

        # Method 3: Orderbook support
        ob_stop = ob_pct = None
        if ob and ob.get("bids"):
            sup = self._bid_cluster(ob["bids"], price, 10.0)
            if sup:
                ob_stop = sup["price"] * 0.997
                ob_pct = ((price - ob_stop) / price) * 100
                if self.MIN_STOP_PCT <= ob_pct <= self.MAX_STOP_PCT:
                    candidates.append(("support", ob_stop, ob_pct))
                    methods.append(f"OB ${sup['price']:.6g}")

        # Pick best: tightest that is at least 1x ATR away
        min_dist = atr * 1.0
        valid = [
            (m, s, p) for m, s, p in candidates
            if price - s >= min_dist and p >= self.MIN_STOP_PCT
        ]

        if valid:
            best = max(valid, key=lambda x: x[1])
        else:
            best = ("atr", atr_stop, atr_pct_val)

        # Clamp
        fp = max(
            price * (1 - self.MAX_STOP_PCT / 100),
            min(price * (1 - self.MIN_STOP_PCT / 100), best[1]),
        )
        fpct = ((price - fp) / price) * 100

        return {
            "price": round(fp, 8),
            "pct": round(fpct, 2),
            "method": best[0],
            "methods_considered": methods,
            "atr_distance": round((price - fp) / atr, 1) if atr > 0 else 0,
            "swing_low_stop": round(swing_stop, 8) if swing_stop else None,
            "ob_support_stop": round(ob_stop, 8) if ob_stop else None,
            "atr_stop": round(atr_stop, 8),
        }

    # ═══════════════════════════════════════════════════════════
    # ENTRY ZONE
    # ═══════════════════════════════════════════════════════════

    def _calc_entry(self, price, atr, atr_pct, candles, ob, score, cl):
        if cl == "CRITICAL":
            return {
                "low": round(price * 0.998, 8),
                "high": round(price * 1.003, 8),
                "ideal": round(price, 8),
                "method": "market_entry",
                "urgency": "immediate",
            }
        elif cl == "HIGH_ALERT":
            vwap = self._vwap(candles, 12) if candles else None
            if vwap and vwap < price:
                return {
                    "low": round(vwap * 0.998, 8),
                    "high": round(price * 1.002, 8),
                    "ideal": round(vwap, 8),
                    "method": "vwap_pullback",
                    "urgency": "wait_pullback",
                }
            return {
                "low": round(price * (1 - atr_pct / 200), 8),
                "high": round(price * 1.002, 8),
                "ideal": round(price * (1 - atr_pct / 400), 8),
                "method": "bid_side",
                "urgency": "wait_pullback",
            }
        else:
            return {
                "low": round(price * (1 - atr_pct / 100), 8),
                "high": round(price * 0.998, 8),
                "ideal": round(price * (1 - atr_pct / 150), 8),
                "method": "support_entry",
                "urgency": "limit_order",
            }

    # ═══════════════════════════════════════════════════════════
    # TAKE PROFITS
    # ═══════════════════════════════════════════════════════════

    def _calc_tps(self, price, atr, atr_pct, candles, ob, liq, score, stop):
        lr = liq.get("leverage_ratio", 1.0)

        # Cascade multiplier
        if lr >= 5:
            cm = 1.8
        elif lr >= 3:
            cm = 1.4
        elif lr >= 2:
            cm = 1.2
        else:
            cm = 1.0

        # Score multiplier
        if score >= 85:
            sm = 1.3
        elif score >= 75:
            sm = 1.15
        else:
            sm = 1.0

        m = cm * sm

        # ATR-based targets
        tp1a = price + atr * 3.0 * m
        tp2a = price + atr * 5.5 * m
        tp3a = price + atr * 9.0 * m

        # Resistance walls
        walls = self._ask_walls(ob.get("asks", []), price, 60.0) if ob else []

        # Blend ATR + resistance
        tp1, tp1m = tp1a, "atr"
        if walls and walls[0]["price"] < tp1a and walls[0]["price"] > price * 1.03:
            tp1, tp1m = walls[0]["price"] * 0.997, "resistance"

        tp2, tp2m = tp2a, "atr"
        if len(walls) >= 2 and walls[1]["price"] < tp2a * 1.1 and walls[1]["price"] > tp1 * 1.05:
            tp2, tp2m = walls[1]["price"] * 0.997, "resistance"

        tp3, tp3m = tp3a, "atr"
        if len(walls) >= 3 and walls[2]["price"] < tp3a * 1.15 and walls[2]["price"] > tp2 * 1.05:
            tp3, tp3m = walls[2]["price"] * 0.997, "resistance"

        # Minimum distances
        tp1 = max(tp1, price * (1 + self.MIN_TP1_PCT / 100))
        tp2 = max(tp2, tp1 * 1.05)
        tp3 = max(tp3, tp2 * 1.05)

        # Minimum R:R
        risk = price * stop.get("pct", 7) / 100
        tp1 = max(tp1, price + risk * self.MIN_RR_RATIO)

        return [
            {
                "level": i + 1,
                "price": round(p, 8),
                "pct": round(((p - price) / price) * 100, 1),
                "sell_pct": 25,
                "method": mt,
                "atr_multiple": round((p - price) / atr, 1) if atr > 0 else 0,
            }
            for i, (p, mt) in enumerate([(tp1, tp1m), (tp2, tp2m), (tp3, tp3m)])
        ]

    # ═══════════════════════════════════════════════════════════
    # TRAILING STOP
    # ═══════════════════════════════════════════════════════════

    def _calc_trailing(self, price, atr, atr_pct, score):
        mult = 2.0 if score >= 78 else 2.5
        dist = atr * mult
        return {
            "sell_pct": 25,
            "trail_distance": round(dist, 8),
            "trail_pct": round((dist / price) * 100, 2),
            "trail_atr_multiple": mult,
            "activation": "after_tp3",
            "method": f"trail_{mult}x_atr",
        }

    # ═══════════════════════════════════════════════════════════
    # RISK / REWARD
    # ═══════════════════════════════════════════════════════════

    def _calc_rr(self, entry, stop, tps):
        ep = entry.get("ideal", 0)
        sp = stop.get("price", 0)
        sp_pct = stop.get("pct", 7.0)

        if ep <= 0 or sp <= 0:
            return {"ratio": 0, "risk_pct": sp_pct}

        risk = ep - sp
        if risk <= 0:
            return {"ratio": 0, "risk_pct": sp_pct}

        reward = sum((tp["price"] - ep) * (tp["sell_pct"] / 100) for tp in tps)
        if tps:
            reward += (tps[-1]["price"] - ep) * 0.6 * 0.25

        ratio = reward / risk if risk > 0 else 0

        return {
            "ratio": round(ratio, 2),
            "risk_pct": round(sp_pct, 2),
            "position_1pct_risk_10k": f"${10000 * 0.01 / (sp_pct / 100):,.0f}" if sp_pct > 0 else "N/A",
            "position_2pct_risk_10k": f"${10000 * 0.02 / (sp_pct / 100):,.0f}" if sp_pct > 0 else "N/A",
            "position_1pct_risk_25k": f"${25000 * 0.01 / (sp_pct / 100):,.0f}" if sp_pct > 0 else "N/A",
            "position_2pct_risk_25k": f"${25000 * 0.02 / (sp_pct / 100):,.0f}" if sp_pct > 0 else "N/A",
        }

    # ═══════════════════════════════════════════════════════════
    # ORDERBOOK HELPERS
    # ═══════════════════════════════════════════════════════════

    def _bid_cluster(self, bids, price, depth_pct):
        floor = price * (1 - depth_pct / 100)
        bs = price * 0.005
        buckets = {}

        for bp, ba in bids:
            if bp < floor or bp >= price:
                continue
            k = int(bp / bs)
            v = bp * ba
            if k not in buckets:
                buckets[k] = {"ps": 0, "v": 0, "c": 0}
            buckets[k]["ps"] += bp * v
            buckets[k]["v"] += v
            buckets[k]["c"] += 1

        if not buckets:
            return None

        bk = max(buckets, key=lambda k: buckets[k]["v"])
        b = buckets[bk]
        return {"price": b["ps"] / b["v"] if b["v"] > 0 else 0, "value": b["v"]}

    def _ask_walls(self, asks, price, depth_pct):
        ceil = price * (1 + depth_pct / 100)
        bs = price * 0.01
        buckets = {}

        for ap, aa in asks:
            if ap <= price or ap > ceil:
                continue
            k = int(ap / bs)
            v = ap * aa
            if k not in buckets:
                buckets[k] = {"ps": 0, "v": 0, "c": 0}
            buckets[k]["ps"] += ap * v
            buckets[k]["v"] += v
            buckets[k]["c"] += 1

        if not buckets:
            return []

        vals = [b["v"] for b in buckets.values()]
        thresh = np.mean(vals) * 1.5 if vals else 0

        walls = []
        for k, b in buckets.items():
            if b["v"] >= thresh:
                walls.append({
                    "price": b["ps"] / b["v"] if b["v"] > 0 else 0,
                    "value": b["v"],
                })

        walls.sort(key=lambda w: w["price"])
        return walls[:5]

    # ═══════════════════════════════════════════════════════════
    # DATA HELPERS
    # ═══════════════════════════════════════════════════════════

    def _get_atr(self, signals, price):
        m = signals.get("volatility_compression", {}).get("metadata", {})
        atr = m.get("atr", 0)
        if atr and float(atr) > 0:
            return float(atr)
        ap = m.get("atr_pct", 3.0)
        if ap and float(ap) > 0:
            return price * float(ap) / 100
        return price * 0.03

    def _get_candles(self, data):
        best = []
        for ex, c in data.get("ohlcv", {}).items():
            if c and len(c) > len(best):
                best = c
        return best

    def _merge_ob(self, data):
        bids, asks = [], []
        for ex, ob in data.get("orderbooks", {}).items():
            bids.extend(ob.get("bids", []))
            asks.extend(ob.get("asks", []))
        bids.sort(key=lambda x: x[0], reverse=True)
        asks.sort(key=lambda x: x[0])
        return {"bids": bids, "asks": asks}

    def _get_liq(self, signals):
        m = signals.get("liquidation_leverage", {}).get("metadata", {})
        return {
            "leverage_ratio": m.get("leverage_ratio", 1.0),
            "estimated_liq": m.get("estimated_liq_within_15pct", 0),
        }

    def _vwap(self, candles, periods=12):
        if not candles or len(candles) < 2:
            return None
        r = candles[-periods:] if len(candles) >= periods else candles
        tpv = sum(
            ((c[2] + c[3] + c[4]) / 3) * c[5]
            for c in r if len(c) > 5 and c[5] and c[5] > 0
        )
        tv = sum(c[5] for c in r if len(c) > 5 and c[5] and c[5] > 0)
        return tpv / tv if tv > 0 else None

    def _quality(self, candles, ob, signals):
        cc = len(candles) if candles else 0
        bd = len(ob.get("bids", [])) if ob else 0
        ad = len(ob.get("asks", [])) if ob else 0
        ha = bool(signals.get("volatility_compression", {}).get("metadata", {}).get("atr", 0))
        hl = bool(signals.get("liquidation_leverage", {}).get("metadata", {}).get("leverage_ratio", 0))

        s = 0
        s += 30 if cc >= 100 else (15 if cc >= 30 else 0)
        s += 20 if bd >= 20 else (10 if bd >= 5 else 0)
        s += 20 if ad >= 20 else (10 if ad >= 5 else 0)
        s += 15 if ha else 0
        s += 15 if hl else 0

        label = "HIGH" if s >= 80 else ("MEDIUM" if s >= 50 else "LOW")

        return {
            "score": s,
            "label": label,
            "candles": cc,
            "orderbook_depth": bd + ad,
            "has_atr": ha,
            "has_liq_data": hl,
        }

    def _empty(self, reason):
        return {
            "symbol": "", "price": 0,
            "entry": {"low": 0, "high": 0, "ideal": 0, "method": "none", "urgency": "none"},
            "stop": {"price": 0, "pct": 0, "method": "none"},
            "take_profits": [], "trailing": {},
            "risk_reward": {"ratio": 0, "risk_pct": 0},
            "atr": {"value": 0, "pct": 0},
            "data_quality": {"score": 0, "label": "NONE"},
            "error": reason,
        }