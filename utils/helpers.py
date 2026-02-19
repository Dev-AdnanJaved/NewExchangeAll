"""
Utility functions, constants, and formatters.
"""

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

CRITICAL_THRESHOLD = 78
HIGH_ALERT_THRESHOLD = 62
WATCHLIST_THRESHOLD = 48
MONITOR_THRESHOLD = 33

# Weights sum to exactly 1.00
SIGNAL_WEIGHTS = {
    "oi_surge": 0.18,
    "funding_rate": 0.17,
    "liquidation_leverage": 0.15,
    "cross_exchange_volume": 0.12,
    "depth_imbalance": 0.11,
    "volume_price_decouple": 0.08,
    "volatility_compression": 0.08,
    "long_short_ratio": 0.06,
    "futures_spot_divergence": 0.05,
}

INTERACTION_BONUSES = [
    {
        "name": "squeeze_setup",
        "signals": ["oi_surge", "funding_rate", "volatility_compression"],
        "min_score": 45,
        "bonus": 0.25,
        "description": "OI rising + Funding negative + Volatility compressed",
    },
    {
        "name": "cascade_setup",
        "signals": ["liquidation_leverage", "funding_rate", "long_short_ratio"],
        "min_score": 40,
        "bonus": 0.30,
        "description": "High liq leverage + Negative funding + Shorts dominant",
    },
    {
        "name": "accumulation_setup",
        "signals": ["oi_surge", "volume_price_decouple", "cross_exchange_volume"],
        "min_score": 40,
        "bonus": 0.20,
        "description": "OI ratchet + Volume rising + Price flat",
    },
]

EXTENDED_PRICE_PENALTY = 0.40
EXTENDED_PRICE_THRESHOLD_PCT = 15.0
EXTENDED_PRICE_LOOKBACK_DAYS = 7

BOOTSTRAP_OI_PERIODS = 200
BOOTSTRAP_FUNDING_PERIODS = 100
BOOTSTRAP_LS_PERIODS = 100
BOOTSTRAP_OHLCV_CANDLES = 500
REGULAR_OHLCV_CANDLES = 500

STOP_LOSS_TRAIL = [
    {"price_move_pct": 5.0, "stop_at_pct": 0.0, "label": "break-even"},
    {"price_move_pct": 10.0, "stop_at_pct": 5.0, "label": "+5%"},
    {"price_move_pct": 15.0, "stop_at_pct": 10.0, "label": "+10%"},
    {"price_move_pct": 25.0, "stop_at_pct": 18.0, "label": "+18%"},
    {"price_move_pct": 40.0, "stop_at_pct": 30.0, "label": "+30%"},
    {"price_move_pct": 60.0, "stop_at_pct": 45.0, "label": "+45%"},
]

TAKE_PROFIT_LEVELS = [
    {"level": 1, "pct": 15.0, "sell_fraction": 0.25},
    {"level": 2, "pct": 30.0, "sell_fraction": 0.25},
    {"level": 3, "pct": 50.0, "sell_fraction": 0.25},
    {"level": 4, "pct": None, "sell_fraction": 0.25},
]


def load_config(path: str = "config.json") -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Config file not found: {path}\nRun: cp config.example.json config.json"
        )
    with open(path, "r") as f:
        return json.load(f)


def save_config(config: Dict[str, Any], path: str = "config.json"):
    with open(path, "w") as f:
        json.dump(config, f, indent=4)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_timestamp() -> float:
    return time.time()


def ts_to_str(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def classify_score(score: float) -> str:
    if score >= CRITICAL_THRESHOLD:
        return "CRITICAL"
    elif score >= HIGH_ALERT_THRESHOLD:
        return "HIGH_ALERT"
    elif score >= WATCHLIST_THRESHOLD:
        return "WATCHLIST"
    elif score >= MONITOR_THRESHOLD:
        return "MONITOR"
    return "NONE"


def score_bar(value: float, max_val: float = 100, width: int = 10) -> str:
    filled = int((value / max_val) * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def format_pct(value: Optional[float], decimals: int = 2) -> str:
    if value is None:
        return "N/A"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.{decimals}f}%"


def format_usd(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    if abs(value) >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if abs(value) >= 1_000:
        return f"${value / 1_000:.1f}K"
    return f"${value:.2f}"


def format_price(value: Optional[float]) -> str:
    if value is None:
        return "N/A"
    if value >= 1000:
        return f"${value:,.2f}"
    if value >= 1:
        return f"${value:.4f}"
    if value >= 0.01:
        return f"${value:.6f}"
    return f"${value:.8f}"


def normalize_symbol(symbol: str) -> str:
    symbol = symbol.upper().strip()
    for suffix in [
        "/USDT:USDT", "/USDT", "USDT", "/USD:USD", "/USD",
        "-USDT", "_USDT", "PERP", "-PERP", "_PERP",
    ]:
        if symbol.endswith(suffix):
            symbol = symbol[: -len(suffix)]
    return symbol


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0 or denominator is None:
        return default
    return numerator / denominator


def clamp(value: float, min_val: float = 0.0, max_val: float = 100.0) -> float:
    return max(min_val, min(max_val, value))


def piecewise_lerp(value: float, breakpoints: list) -> float:
    if not breakpoints:
        return 0.0
    if value <= breakpoints[0][0]:
        return float(breakpoints[0][1])
    if value >= breakpoints[-1][0]:
        return float(breakpoints[-1][1])
    for i in range(len(breakpoints) - 1):
        x0, y0 = breakpoints[i]
        x1, y1 = breakpoints[i + 1]
        if x0 <= value <= x1:
            if x1 == x0:
                return float(y0)
            t = (value - x0) / (x1 - x0)
            return float(y0 + t * (y1 - y0))
    return 0.0