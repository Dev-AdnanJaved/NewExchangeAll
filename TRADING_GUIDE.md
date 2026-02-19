# TRADING GUIDE — How to Read and Act on Signals

## Entry Rules

### CRITICAL (Score 78+)

Bot shows urgency: immediate

1. Check chart — not already moved 10%+
2. Check BTC — not dumping >3%
3. Enter at ideal price shown
4. Use stop and TPs exactly as shown
5. Register: /trade TOKEN IDEAL_PRICE SIZE STOP_PCT

### HIGH_ALERT (Score 62-77)

Bot shows urgency: wait_pullback

1. Set limit order at ideal entry (VWAP/bid-side)
2. If fills within 4 hours, register trade
3. If not, setup may be weakening

### WATCHLIST (Score 48-61)

1. Add to personal watchlist
2. Check if score trending UP or DOWN
3. Wait for upgrade to HIGH_ALERT

## Understanding Smart Stop Loss

### ATR Method

ATR = how much the coin moves per candle. 2x ATR stop means
stop is 2 typical moves away. Volatile coin gets wider stop.

### Swing Low Method

Stop below lowest price in last 24 hours. Respects actual
price structure.

### Orderbook Support Method

Stop below largest bid cluster. Real money defending the level.

### Which Gets Used?

Tightest stop that is at least 1x ATR away. Never tighter
than 2.5%, never wider than 15%.

## Understanding Smart Take Profits

### ATR Scaling

TPs are ATR multiples. 3% daily coin gets tighter TPs than
10% daily coin. Adapts automatically.

### Resistance Walls

Bot checks orderbook for large sell clusters. Places TPs
just below walls where price will stall.

### Liquidation Cascade

High liquidation leverage (5x+) extends TPs up to 1.8x.
More liquidation fuel = bigger expected move.

## Understanding Risk/Reward

R:R 2.84:1 means for every $1 risked, expect $2.84 average.

Position sizing:
Position = (Account x Risk%) / Stop%
$10,000 x 0.02 / 0.07 = $2,857

## After You Enter

### Step 1: Register

/trade DOGE 0.165 2857 7

### Step 2: Bot Monitors

Every 5 min: checks price, stop, TPs
Every hour: sends status update

### What You Receive

Hourly status: price, P&L, score
Stop updates: when to move stop higher
TP hits: when to sell 25%
Degradation warnings: when signals weaken

## Stop Trail Schedule

| Price Move | Move Stop To |
| ---------- | ------------ |
| +5%        | Break-even   |
| +10%       | +5%          |
| +15%       | +10%         |
| +25%       | +18%         |
| +40%       | +30%         |
| +60%       | +45%         |

## When NOT to Trade

1. BTC dumping >3%
2. Score declining 2 scans in a row
3. Price already up 10%+
4. 3+ trades already open
5. R:R below 1.5:1
6. Data quality LOW
7. Weekend + low volume

## Example Trade

Day 1 14:30 — Bot: CRITICAL TOKEN_X Score 84
Smart levels: Entry $0.050, Stop $0.0465 (-7%), TP1 $0.055
Send: /trade TOKENX 0.050 2857 7

Day 1 20:00 — Bot: STATUS +2.3%, signals strong
Day 2 08:00 — Bot: Move stop to break-even
Day 2 14:00 — Bot: IGNITION breakout
Day 2 16:00 — Bot: TP1 sell 25% at +10%. Profit $75
Day 2 22:00 — Bot: TP2 sell 25% at +20%. Profit $142
Day 3 10:00 — Bot: TP3 sell 25% at +30%. Profit $214
Day 3 18:00 — Bot: Trail stop hit at +20%. Profit $142

Result: $573 on $2,857 (20.1%). Risked $200 (2% of $10k).

## Key Principle

Bot tells you WHERE to look and gives DATA-DRIVEN levels.
Your judgment, discipline, and risk management determine profit.
Follow the levels. Follow the stops. Do not chase. Do not overtrade.
