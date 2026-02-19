# PUMP DETECTOR — Free Edition

Detects crypto pumps BEFORE they happen. $0 cost. All free APIs.
Smart entry/stop/TP based on real market data, not fixed percentages.

## Quick Start (5 min)

    git clone <repo-url> pump_detector && cd pump_detector
    pip install -r requirements.txt
    cp config.example.json config.json
    # Edit config.json — add at least 1 exchange API key
    python run.py

## What It Does

Scans 150-400+ futures-listed coins across 6 exchanges every 15 min.
Detects stealth accumulation, short squeeze setups, and pre-pump
patterns using 9 signal categories. Sends Telegram alerts with:

- Signal breakdown — which signals fire and why
- Smart entry zone — based on VWAP, orderbook, score urgency
- Smart stop loss — based on ATR, swing lows, orderbook support
- Smart take profits — based on ATR, resistance walls, liquidation cascade
- Risk/reward ratio — with position sizing for your account
- Trade monitoring — auto stop trail, TP notifications, degradation warnings

## Signal Categories

| Signal                  | Weight | What It Detects                          |
| ----------------------- | ------ | ---------------------------------------- |
| OI Surge                | 18%    | Position building without price movement |
| Funding Rate            | 17%    | Crowded shorts = squeeze fuel            |
| Liquidation Leverage    | 15%    | Cascade potential vs resistance          |
| Cross-Exchange Volume   | 12%    | Accumulation on one venue                |
| Depth Imbalance         | 11%    | Order book manipulation                  |
| Volume-Price Decouple   | 8%     | Hidden buying                            |
| Volatility Compression  | 8%     | Coiled spring                            |
| Long/Short Ratio        | 6%     | Short dominance                          |
| Futures/Spot Divergence | 5%     | Leveraged speculation                    |

Weights sum to 100%. Interaction bonuses up to +30%.

## Telegram Commands

| Command    | Example                  | Description     |
| ---------- | ------------------------ | --------------- |
| /trade     | /trade DOGE 0.165 5000 7 | Register trade  |
| /close     | /close DOGE              | Close trade     |
| /status    | /status                  | Show all trades |
| /adjust    | /adjust DOGE stop 0.175  | Move stop       |
| /scan      | /scan                    | Force scan      |
| /watchlist | /watchlist               | Show watchlist  |

## Smart Levels

Stop Loss: ATR-based (1.5-2.5x), swing low, orderbook support.
Take Profits: ATR multiples (3x, 5.5x, 9x) adjusted by liquidation
cascade strength and resistance walls.
Entry: Market for CRITICAL, VWAP pullback for HIGH_ALERT.

## Commands

    python run.py              # Continuous scanning
    python run.py --once       # Single scan
    python run.py --stats      # Database stats
    python run.py --cleanup    # Delete old data
    python setup.py            # First-time setup

## API Keys (FREE)

| Exchange | Steps                               |
| -------- | ----------------------------------- |
| Binance  | API Management → Create (Read Only) |
| Bybit    | API → Create (Read Only)            |
| OKX      | API → Create (Read Only)            |
| Bitget   | API → Create (Read Only)            |
| Gate.io  | API → Create (Read Only)            |
| MEXC     | API → Create (Read Only)            |

No deposit needed. Read-only keys cannot trade.

## Disclaimer

Detection tool, not financial advice. Never risk more than 2%
per trade. Always use stop losses. Paper trade first.

## License

MIT
