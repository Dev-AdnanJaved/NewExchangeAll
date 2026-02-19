"""Free on-chain monitoring (optional)."""

from utils.logger import get_logger

logger = get_logger("onchain")


class OnchainMonitor:
    def __init__(self, etherscan_key=""):
        self.key = etherscan_key

    def check_sync(self, symbol):
        return []