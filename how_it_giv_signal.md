## What The Bot Actually Checks — Complete Breakdown

---

### STEP 1: What coins does it scan?

```
Every 15 minutes, the bot:

1. Connects to your enabled exchanges (Binance, Bybit, OKX, etc.)
2. Pulls ALL futures-listed coins from each exchange
3. Finds coins that have futures on at least 1 exchange
4. This gives you 150-400+ coins to monitor

Example universe:
  BTC, ETH, SOL, DOGE, XRP, ADA, AVAX, LINK, DOT, MATIC,
  UNI, ATOM, FIL, APT, ARB, OP, SUI, SEI, INJ, TIA,
  NEAR, FTM, AAVE, MKR, LDO, CRV, PEPE, SHIB, BONK, WIF,
  ... 350+ more altcoins
```

---

### STEP 2: What data does it collect for EACH coin?

For every coin, the bot pulls 6 types of data from every exchange:

```
PER COIN, PER EXCHANGE:
─────────────────────────────────────────────────
1. OHLCV Candles      → 500 hourly candles (20 days of price/volume)
2. Ticker             → Current price, 24h volume, bid/ask
3. Open Interest      → Total value of open futures positions
4. Funding Rate       → What shorts/longs are paying each other
5. Order Book         → Top 50 bids and asks with sizes
6. Long/Short Ratio   → How many accounts are long vs short
```

On first run (bootstrap), it also fetches:

```
HISTORICAL DATA (one-time):
─────────────────────────────────────────────────
→ 200 hourly OI snapshots (~8 days back)
→ 100 funding rate records (~months back)
→ 100 L/S ratio records (~4 days back)
→ 500 hourly candles converted to ticker snapshots
```

---

### STEP 3: What 9 signals does it compute?

Each signal answers a specific question about the coin:

---

#### SIGNAL 1: OI Surge (18% weight)

```
QUESTION: Is someone secretly building futures positions?

WHAT IT CHECKS:
  - Current total OI across all exchanges
  - OI from 72 hours ago (from bootstrap/stored data)
  - Price change over same 72 hours

HOW IT SCORES:
  OI up 10% + price flat = score 45
  OI up 20% + price flat = score 68
  OI up 30% + price flat = score 80
  OI up 40% + price flat = score 90

  BUT if price also moved 10%+ = score drops significantly
  (because price moving means it's NOT stealth)

WHY IT MATTERS:
  If OI rises 25% but price barely moves, someone is quietly
  building a massive position without anyone noticing.
  They're preparing for something.
```

---

#### SIGNAL 2: Funding Rate (17% weight)

```
QUESTION: Are shorts crowded and paying longs?

WHAT IT CHECKS:
  - Current average funding rate across exchanges
  - How many of the last 72h funding periods were negative
  - Persistence: what % of time was funding negative

HOW IT SCORES:
  Two components (55% magnitude + 45% persistence):

  Magnitude:
    -0.001%  = score 45
    -0.002%  = score 65
    -0.003%  = score 78
    -0.005%  = score 90

  Persistence (% of periods negative):
    30% negative = score 20
    50% negative = score 45
    70% negative = score 70
    85% negative = score 90

WHY IT MATTERS:
  Negative funding means shorts are PAYING longs to hold.
  This means:
  - Market consensus is bearish (everyone is short)
  - Every short is a potential FORCED BUYER if price goes up
  - More negative + longer = more squeeze fuel stored up
```

---

#### SIGNAL 3: Liquidation Leverage (15% weight)

```
QUESTION: If price goes up 15%, will the short liquidations
          overwhelm the sell orders blocking the way?

WHAT IT CHECKS:
  - Total OI across exchanges
  - L/S ratio to estimate short fraction
  - Estimated short liquidation volume within 15% above price
  - Total ask-side resistance (sell orders) within 15% above price

  Formula: Leverage Ratio = Liq Volume / Ask Resistance

HOW IT SCORES:
  Ratio 2x = score 35
  Ratio 3x = score 55
  Ratio 5x = score 75
  Ratio 8x = score 90

  Example: $10M of shorts liquidate within 15%
           Only $2M of asks blocking the move
           Ratio = 5x → score 75

WHY IT MATTERS:
  If liquidation fuel is 5x the resistance, then when price
  starts moving up:
  - Shorts get liquidated (forced buying)
  - Their forced buying pushes price through the asks
  - Which liquidates more shorts
  - Which pushes price higher
  - Self-sustaining cascade = violent pump
```

---

#### SIGNAL 4: Cross-Exchange Volume (12% weight)

```
QUESTION: Is one exchange seeing abnormally high volume
          compared to others?

WHAT IT CHECKS:
  Multi-exchange: max volume / median volume across exchanges
  Single-exchange: current volume / historical average volume

HOW IT SCORES:
  1.5x divergence = score 35
  2.0x divergence = score 55
  3.0x divergence = score 75
  4.0x divergence = score 88

WHY IT MATTERS:
  An operator accumulates on ONE exchange (cheapest/least watched).
  If Binance volume is 3x normal but Bybit is flat, someone
  is specifically buying on Binance. This is the accumulation
  footprint.
```

---

#### SIGNAL 5: Depth Imbalance (11% weight)

```
QUESTION: Are bids (buy orders) much larger than asks (sell orders)?

WHAT IT CHECKS:
  - Total bid value (price × amount) across all exchanges
  - Total ask value across all exchanges
  - Ratio: bids / asks

HOW IT SCORES:
  1.3x ratio = score 30
  1.5x ratio = score 50
  2.0x ratio = score 75
  2.5x ratio = score 88
  3.0x ratio = score 95

WHY IT MATTERS:
  The operator is ENGINEERING a pump runway:
  - Placing large bids (support) below price
  - Removing asks (resistance) above price
  - Result: path of least resistance is UP
  - When they ignite, price flies with nothing blocking it
```

---

#### SIGNAL 6: Volume-Price Decouple (8% weight)

```
QUESTION: Is volume increasing while price stays flat?

WHAT IT CHECKS:
  - Last 24h volume vs previous 24h volume
  - Price change over last 24h
  - Decouple = volume change × price dampener

HOW IT SCORES:
  Volume +35% with price flat = score 50
  Volume +75% with price flat = score 78
  Volume +100% with price flat = score 88

  BUT if price also moved 8%+ = score drops sharply

WHY IT MATTERS:
  Normally, rising volume moves price. If volume is up 50%
  but price didn't move, someone is:
  - Buying AND selling to themselves (wash)
  - OR systematically buying while algo controls price
  - This is textbook accumulation behavior
```

---

#### SIGNAL 7: Volatility Compression (8% weight)

```
QUESTION: Is the coin's price range at historical lows?
          (coiled spring ready to snap)

WHAT IT CHECKS:
  - Bollinger Band Width (20-period) for all available candles
  - Where current BBW sits vs all historical BBW values
  - ATR (Average True Range) for context

HOW IT SCORES:
  Current BBW narrower than 65% of history = score 42
  Current BBW narrower than 75% of history = score 58
  Current BBW narrower than 85% of history = score 75
  Current BBW narrower than 95% of history = score 95

WHY IT MATTERS:
  Compressed volatility = energy stored up. Like a spring
  being pressed down. When an external force hits (operator
  buying), the breakout is VIOLENT because equilibrium
  was already at breaking point.

  Operators specifically TIME their ignition to coincide
  with maximum compression.
```

---

#### SIGNAL 8: Long/Short Ratio (6% weight)

```
QUESTION: Are there significantly more short accounts than long?

WHAT IT CHECKS:
  - L/S account ratio from Binance/Bybit
  - Falls back to historical if current unavailable

HOW IT SCORES:
  Ratio 0.90 = score 30  (slightly short-heavy)
  Ratio 0.80 = score 55  (moderately short-heavy)
  Ratio 0.70 = score 75  (heavily short-heavy)
  Ratio 0.60 = score 90  (extremely short-heavy)

  Ratio 1.0+  = score 0-8 (longs dominate = no squeeze)

WHY IT MATTERS:
  More shorts = more forced buyers when price goes up.
  Every short position is a future BUY order waiting to
  be triggered by liquidation. More shorts = bigger cascade.
```

---

#### SIGNAL 9: Futures/Spot Volume Divergence (5% weight)

```
QUESTION: Is futures trading volume abnormally high vs recent history?

WHAT IT CHECKS:
  - Current total volume across exchanges
  - Average historical volume over last 72h
  - Ratio: current / average

HOW IT SCORES:
  1.5x above average = score 35
  2.0x above average = score 55
  3.0x above average = score 78
  4.0x above average = score 90

WHY IT MATTERS:
  Leveraged speculation is building. Combined with negative
  funding, this means short-heavy leveraged bets are piling up.
  All of this becomes FUEL for the squeeze.
```

---

### STEP 4: How does scoring work?

```
BASE SCORE = Sum of (each signal's score × its weight)

Example real scenario:
  oi_surge:               62 × 0.18 = 11.16
  funding_rate:           55 × 0.17 =  9.35
  liquidation_leverage:   48 × 0.15 =  7.20
  cross_exchange_volume:  40 × 0.12 =  4.80
  depth_imbalance:        52 × 0.11 =  5.72
  volume_price_decouple:  35 × 0.08 =  2.80
  volatility_compression: 58 × 0.08 =  4.64
  long_short_ratio:       42 × 0.06 =  2.52
  futures_spot_divergence: 30 × 0.05 = 1.50
  ────────────────────────────────────────────
  BASE SCORE:                          49.69
```

---

### STEP 5: Interaction bonuses

```
The bot checks if COMBINATIONS of signals are firing together.
Certain combos are far more predictive than individual signals:

BONUS 1: "squeeze_setup" (+25%)
  IF oi_surge >= 45 AND funding_rate >= 45 AND volatility_compression >= 45
  THEN score × 1.25
  WHY: All three conditions for a short squeeze are present

BONUS 2: "cascade_setup" (+30%)
  IF liquidation_leverage >= 40 AND funding_rate >= 40 AND long_short_ratio >= 40
  THEN score × 1.30
  WHY: Maximum cascade potential — fuel + fire + dry powder

BONUS 3: "accumulation_setup" (+20%)
  IF oi_surge >= 40 AND volume_price_decouple >= 40 AND cross_exchange_volume >= 40
  THEN score × 1.20
  WHY: Classic stealth accumulation fingerprint

Example with bonus:
  Base score: 49.69
  squeeze_setup applies (OI=62, Funding=55, Vol_Compress=58, all >= 45)
  49.69 × 1.25 = 62.11

  Without bonus: WATCHLIST (49)
  With bonus: HIGH_ALERT (62) ← This is how combos elevate signals
```

---

### STEP 6: Penalties

```
PENALTY: "price_extended" (-40%)
  IF price already up >15% in last 7 days
  THEN score × 0.60
  WHY: The pump may have ALREADY STARTED. You're late.

Example:
  Score after bonuses: 75
  Price already up 18% this week
  75 × 0.60 = 45 ← Dropped from HIGH_ALERT to below threshold

  Bot says: "Don't chase this. You missed it."
```

---

### STEP 7: Classification + alert decision

```
FINAL SCORE → CLASSIFICATION → ACTION

78-100  →  CRITICAL    →  Alert sent with FULL smart levels
                           Entry zone, stop, 4 TPs, R:R, position size
                           Urgency: IMMEDIATE

62-77   →  HIGH_ALERT  →  Alert sent with FULL smart levels
                           Entry zone, stop, 4 TPs, R:R, position size
                           Urgency: WAIT FOR PULLBACK

48-61   →  WATCHLIST   →  Alert sent with entry zone only
                           No stop/TP (not ready to trade yet)
                           Urgency: MONITOR

33-47   →  MONITOR     →  No alert sent
                           Stored in database for tracking

0-32    →  NONE        →  No alert, no storage
                           Normal market activity
```

---

### STEP 8: Special events that trigger extra alerts

```
EVENT 1: SCORE_JUMP
  Score jumped +15 points in one scan cycle
  Something significant just changed
  → Alert: "Score jumped +18 points. Investigate now."

EVENT 2: UPGRADE
  Classification upgraded (e.g., WATCHLIST → HIGH_ALERT)
  Setup is developing rapidly
  → Alert: "Upgraded WATCHLIST → HIGH_ALERT"

EVENT 3: IGNITION
  Price up 5%+ in last 6 hours AND score >= 48
  The pump may be starting RIGHT NOW
  → Alert: "IGNITION — Price +7.2% in 6h with score 72"
```

---

### STEP 9: What makes the bot say "THIS WILL PUMP"

```
The bot NEVER says "this will pump." It says:

"Multiple conditions that historically precede pumps
 are present simultaneously."

Specifically, a CRITICAL alert fires when:

✅ OI rising 15%+ while price flat (stealth accumulation)
✅ Funding negative for 24h+ (shorts crowded)
✅ Liquidation leverage 3x+ (cascade will overwhelm resistance)
✅ At least 1-2 supporting signals also active
✅ Interaction bonus applied (signals confirming each other)
✅ Price NOT already extended (you're early, not late)
✅ Combined weighted score reaches 78+

All of this together means:
  Someone is building a position → CHECK
  The market is positioned against them (shorts) → CHECK
  If price moves up, it will cascade violently → CHECK
  The path of least resistance is up → CHECK
  The volatility spring is compressed → CHECK
  You're early (price hasn't moved yet) → CHECK
```

---

### Visual: The Complete Flow

```
EXCHANGE DATA (free APIs)
    │
    ▼
┌─────────────────────────────────────┐
│ COLLECT per coin:                    │
│   500 candles                        │
│   Current OI + 200 historical        │
│   Current funding + 100 historical   │
│   Order book (50 levels each side)   │
│   L/S ratio + 100 historical         │
│   Ticker (price, volume)             │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│ COMPUTE 9 SIGNALS:                   │
│   Each signal → raw value            │
│   Raw → piecewise normalization      │
│   Each signal → 0-100 score          │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│ SCORE:                               │
│   Weighted sum (weights = 1.00)      │
│   + Interaction bonuses (up to +30%) │
│   - Price extended penalty (-40%)    │
│   = Final score 0-100                │
│   → Classification                   │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│ SMART LEVELS (if score >= 48):       │
│   ATR from candles                   │
│   Stop: ATR / swing low / OB support │
│   Entry: market / VWAP / support     │
│   TPs: ATR × cascade × resistance   │
│   R:R ratio + position sizing        │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│ ALERT (if score >= 48):              │
│   Console: full breakdown            │
│   Telegram: full breakdown + levels  │
│   Events: IGNITION / SCORE_JUMP      │
└──────────┬──────────────────────────┘
           │
           ▼
┌─────────────────────────────────────┐
│ TRADE MONITOR (if you register):     │
│   Every 5 min: price check           │
│   Stop trail: auto move higher       │
│   TP hits: notify to sell 25%        │
│   Degradation: warn if score drops   │
│   Hourly: full status update         │
└─────────────────────────────────────┘
```

---

### What a Real Alert Looks Like When Everything Aligns

```
🔴🔴🔴 CRITICAL: TOKENX 🔴🔴🔴

📊 Score: 84.2 / 100
💰 Price: $0.0500

🎯 Signals:
  oi_surge              ████████░░ 78   ← OI up 28% in 72h
  funding_rate          ███████░░░ 72   ← -0.025% for 36h straight
  liquidation_leverage  ██████░░░░ 65   ← 4.8x cascade ratio
  depth_imbalance       ██████░░░░ 58   ← Bids 1.7x asks
  volatility_compress   █████░░░░░ 55   ← BB at 80th percentile low
  cross_exchange_vol    █████░░░░░ 48   ← Binance 2x normal
  volume_price_decouple ████░░░░░░ 42   ← Vol up 35%, price flat
  long_short_ratio      ████░░░░░░ 38   ← Ratio 0.87
  futures_spot_div      ███░░░░░░░ 32   ← 1.4x above average

🔗 squeeze_setup (+25%)

⚡ SMART LEVELS (HIGH quality)
  ATR: $0.0018 (3.60%)

  📥 ENTRY (immediate):
     $0.0499 → $0.0502
     Ideal: $0.0500

  🛑 STOP (swing_low):
     $0.0465 (-7.0%) | 1.9× ATR

  🎯 TAKE PROFITS:
     TP1 (25%): $0.0577 (+15.4%) [4.3× ATR]
     TP2 (25%): $0.0649 (+29.8%) [8.3× ATR]
     TP3 (25%): $0.0751 (+50.2%) [13.9× ATR]
     TP4 (25%): Trail 7.2% (2.0× ATR)

  📐 R:R 3.12:1 | Risk: 7.0%
     $10k 2% → $2,857

/trade TOKENX 0.05 2857 7.0
```

**This alert fires because:** stealth OI buildup + crowded shorts + cascade fuel + compressed volatility + support engineered — all at once. Not one signal, but the COMBINATION that the code detected as historically preceding violent upward moves.
