#!/usr/bin/env python3
"""Main entry point."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from alerts.console import ConsoleAlert
from alerts.telegram_bot import TelegramAlert
from core.scanner import Scanner
from utils.helpers import load_config
from utils.logger import setup_logger


def main():
    p = argparse.ArgumentParser(description="Pump Detector")
    p.add_argument("--once", action="store_true", help="Single scan")
    p.add_argument("--stats", action="store_true", help="Show stats")
    p.add_argument("--cleanup", action="store_true", help="Clean old data")
    p.add_argument("--config", default="config.json", help="Config path")
    a = p.parse_args()

    try:
        config = load_config(a.config)
    except FileNotFoundError as e:
        print(f"❌ {e}\nRun: python setup.py")
        sys.exit(1)

    lc = config.get("logging", {})
    setup_logger(
        level=lc.get("level", "INFO"),
        log_file=lc.get("file", "logs/pump_detector.log"),
    )

    scanner = Scanner(config)
    scanner.add_alert_handler(ConsoleAlert())

    tg = config.get("telegram", {})
    if tg.get("enabled") and tg.get("bot_token") and tg.get("chat_id"):
        scanner.add_alert_handler(
            TelegramAlert(tg["bot_token"], tg["chat_id"], scanner)
        )

    if a.stats:
        for k, v in scanner.get_stats().items():
            print(f"  {k}: {v}")
        return

    if a.cleanup:
        days = config.get("database", {}).get("cleanup_days", 30)
        print(f"Cleaned {scanner.cleanup(days)} rows")
        return

    if a.once:
        r = scanner.run_once()
        print(f"\n{'📭 No alerts' if not r else f'📊 {len(r)} alerts'}")
        return

    print("🔍 Continuous mode... Ctrl+C to stop\n")
    try:
        scanner.run_continuous()
    except KeyboardInterrupt:
        print("\n👋 Stopped")
    finally:
        scanner.db.close()


if __name__ == "__main__":
    main()