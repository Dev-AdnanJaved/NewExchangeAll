"""
Composite scoring + classification + event detection.
"""

import time
from typing import Any, Dict, List

from core.database import Database
from utils.helpers import (
    EXTENDED_PRICE_PENALTY,
    EXTENDED_PRICE_THRESHOLD_PCT,
    INTERACTION_BONUSES,
    SIGNAL_WEIGHTS,
    clamp,
    classify_score,
)
from utils.logger import get_logger

logger = get_logger("scorer")


class Scorer:
    def __init__(self, db: Database):
        self.db = db

    def score(self, symbol, signals, price_change_7d=0.0):
        signal_scores = {}
        weighted = {}
        base = 0

        for name, weight in SIGNAL_WEIGHTS.items():
            ns = signals.get(name, {}).get("normalized_score", 0)
            signal_scores[name] = round(ns, 1)
            c = ns * weight
            weighted[name] = round(c, 2)
            base += c

        bonuses = []
        bonus_mult = 0
        for b in INTERACTION_BONUSES:
            if all(signal_scores.get(s, 0) >= b["min_score"] for s in b["signals"]):
                bonus_mult += b["bonus"]
                bonuses.append(b["name"])

        penalties = []
        penalty_mult = 0
        if price_change_7d > EXTENDED_PRICE_THRESHOLD_PCT:
            penalty_mult += EXTENDED_PRICE_PENALTY
            penalties.append(f"extended_{price_change_7d:.1f}%")

        final = clamp(base * (1 + bonus_mult) * (1 - penalty_mult), 0, 100)
        classification = classify_score(final)

        self.db.store_score(
            symbol, final, classification, signal_scores, bonuses, penalties
        )

        return {
            "composite_score": round(final, 1),
            "classification": classification,
            "base_score": round(base, 1),
            "signal_scores": signal_scores,
            "weighted_contributions": weighted,
            "bonuses_applied": bonuses,
            "penalties_applied": penalties,
            "bonus_total": round(bonus_mult * 100, 1),
            "penalty_total": round(penalty_mult * 100, 1),
        }

    def detect_events(self, symbol, current_score, current_price):
        events = []
        prev = self.db.get_previous_score(symbol)
        if not prev:
            return events

        ps = prev["composite_score"]
        cs = current_score["composite_score"]
        pc = prev["classification"]
        cc = current_score["classification"]

        delta = cs - ps
        if delta >= 15:
            events.append({
                "type": "SCORE_JUMP", "symbol": symbol,
                "previous_score": ps, "current_score": cs,
                "delta": round(delta, 1),
                "message": f"Score jumped +{delta:.0f} points",
            })

        order = ["NONE", "MONITOR", "WATCHLIST", "HIGH_ALERT", "CRITICAL"]
        if cc in order and pc in order and order.index(cc) > order.index(pc):
            events.append({
                "type": "UPGRADE", "symbol": symbol,
                "from_class": pc, "to_class": cc, "score": cs,
                "message": f"Upgraded {pc} → {cc}",
            })

        hist = self.db.get_snapshots(symbol, "ticker", hours_back=6)
        if hist and current_price > 0:
            for h in hist:
                op = h.get("last", 0)
                if op and float(op) > 0:
                    pm = ((current_price - float(op)) / float(op)) * 100
                    if pm >= 5.0 and cs >= 48:
                        events.append({
                            "type": "IGNITION", "symbol": symbol,
                            "price_move_pct": round(pm, 1), "score": cs,
                            "message": f"IGNITION — Price +{pm:.1f}% in 6h with score {cs:.0f}",
                        })
                    break
        return events