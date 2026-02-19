#!/usr/bin/env python3
"""Guided first-time setup."""

import json
import os
import sys


def main():
    print("=" * 60)
    print("🔍 PUMP DETECTOR SETUP")
    print("=" * 60)

    if os.path.exists("config.example.json"):
        with open("config.example.json") as f:
            config = json.load(f)
    else:
        print("❌ config.example.json not found")
        sys.exit(1)

    print("\n📡 EXCHANGE API KEYS (need at least 1)\n")
    for ex in ["binance", "bybit", "okx", "bitget", "gate", "mexc"]:
        if input(f"Configure {ex}? (y/n): ").strip().lower() == "y":
            config["exchanges"][ex]["enabled"] = True
            config["exchanges"][ex]["api_key"] = input(f"  API Key: ").strip()
            config["exchanges"][ex]["api_secret"] = input(f"  Secret: ").strip()
            if ex in ("okx", "bitget"):
                config["exchanges"][ex]["passphrase"] = input(
                    f"  Passphrase: "
                ).strip()
            print(f"  ✅ {ex}\n")

    if input("\n📱 Telegram? (y/n): ").strip().lower() == "y":
        config["telegram"]["enabled"] = True
        config["telegram"]["bot_token"] = input("  Token: ").strip()
        config["telegram"]["chat_id"] = input("  Chat ID: ").strip()
        print("  ✅ Telegram\n")

    with open("config.json", "w") as f:
        json.dump(config, f, indent=4)

    print(f"\n✅ Saved config.json")
    print("Run: python run.py")


if __name__ == "__main__":
    main()