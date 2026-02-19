"""
Token universe builder — discovers futures-listed coins across exchanges.
"""

import time
from typing import Any, Dict, Set

import ccxt

from core.database import Database
from utils.helpers import normalize_symbol
from utils.logger import get_logger

logger = get_logger("universe")


class UniverseBuilder:
    EXCHANGE_CLASSES = {
        "binance": ccxt.binance,
        "bybit": ccxt.bybit,
        "okx": ccxt.okx,
        "bitget": ccxt.bitget,
        "gate": ccxt.gateio,
        "mexc": ccxt.mexc,
    }

    def __init__(self, config: Dict[str, Any], db: Database):
        self.config = config
        self.db = db
        self.exchanges: Dict[str, ccxt.Exchange] = {}
        self._init_exchanges()

    def _init_exchanges(self):
        ex_config = self.config.get("exchanges", {})
        for name, cls in self.EXCHANGE_CLASSES.items():
            cfg = ex_config.get(name, {})
            if not cfg.get("enabled", False):
                continue
            try:
                params = {"enableRateLimit": True, "timeout": 30000}
                if cfg.get("api_key"):
                    params["apiKey"] = cfg["api_key"]
                if cfg.get("api_secret"):
                    params["secret"] = cfg["api_secret"]
                if cfg.get("passphrase"):
                    params["password"] = cfg["passphrase"]
                params["options"] = {"defaultType": "swap"}
                exchange = cls(params)
                self.exchanges[name] = exchange
                logger.info(f"Exchange initialized: {name}")
            except Exception as e:
                logger.error(f"Failed to initialize {name}: {e}")

    def build(self, min_futures_exchanges=1):
        logger.info("Building token universe...")
        futures_map: Dict[str, Set[str]] = {}
        spot_map: Dict[str, Set[str]] = {}

        for name, exchange in self.exchanges.items():
            try:
                logger.info(f"Loading markets from {name}...")
                exchange.load_markets()

                for market_id, market in exchange.markets.items():
                    if not market.get("active", True):
                        continue
                    base = market.get("base", "")
                    quote = market.get("quote", "")
                    if quote not in ("USDT", "USD"):
                        continue
                    symbol = normalize_symbol(base)
                    if symbol in ("USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD"):
                        continue
                    if market.get("swap") or market.get("future") or market.get("linear"):
                        futures_map.setdefault(symbol, set()).add(name)
                    if market.get("spot"):
                        spot_map.setdefault(symbol, set()).add(name)

                logger.info(
                    f"{name}: {len([s for s, e in futures_map.items() if name in e])} futures"
                )
                time.sleep(1)
            except Exception as e:
                logger.error(f"Error loading {name}: {e}")

        universe = {}
        for symbol, fut_ex in futures_map.items():
            if len(fut_ex) >= min_futures_exchanges:
                all_ex = fut_ex | spot_map.get(symbol, set())
                universe[symbol] = {
                    "exchanges": sorted(list(all_ex)),
                    "futures_exchanges": sorted(list(fut_ex)),
                }

        self.db.store_universe(universe)
        logger.info(
            f"Universe: {len(universe)} tokens with futures on "
            f"{min_futures_exchanges}+ exchanges"
        )
        return universe

    def get_or_build(self, min_futures_exchanges=1, max_age_hours=24.0):
        cached = self.db.get_universe()
        if cached:
            ages = [v["last_updated"] for v in cached.values()]
            if ages:
                age_h = (time.time() - min(ages)) / 3600
                if age_h < max_age_hours:
                    logger.info(
                        f"Cached universe: {len(cached)} tokens ({age_h:.1f}h old)"
                    )
                    return cached
        return self.build(min_futures_exchanges)

    def get_exchange(self, name):
        return self.exchanges.get(name)

    def get_all_exchanges(self):
        return self.exchanges