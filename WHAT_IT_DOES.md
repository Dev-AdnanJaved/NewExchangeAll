# WHAT THIS SYSTEM DOES

## The Problem

Certain futures-listed coins suddenly pump 60-120% within 24-72h.
These pumps follow detectable patterns in OI, funding, orderbooks,
and volume. This system detects those patterns BEFORE the move.

## The Pump Mechanism

Phase 1: Target Selection
Operator finds coins where OI is flat, funding negative, books thin,
volatility compressed.

Phase 2: Accumulation (1-3 weeks)
Silent buying + long position building. OI rises, price stays flat,
funding stays negative, ask-side thins. This is what we detect.

Phase 3: Ignition
Aggressive spot buying on thinnest exchange. Arbitrage cascade.
Short liquidations. 60-120% pump in 24-72h.

Phase 4: Distribution
Operator sells into FOMO. Retail provides exit liquidity.

## 9 Signals

1. OI Surge (18%): OI up 8-40% over 72h, price flat.
2. Funding Rate (17%): Negative -0.01% to -0.05% sustained 24h+.
3. Liquidation Leverage (15%): Short liq / ask resistance ratio 3x+.
4. Cross-Exchange Volume (12%): One exchange 2-4x normal volume.
5. Depth Imbalance (11%): Bid > ask depth ratio 1.3-2.5x.
6. Volume-Price Decouple (8%): Volume up 25-100%, price flat.
7. Volatility Compression (8%): BB width at 30-90 day lows.
8. Long/Short Ratio (6%): Ratio below 0.85 = shorts dominating.
9. Futures/Spot Divergence (5%): Futures volume 1.5-3x above average.

## Scoring

Weights sum to 100%. Realistic piecewise normalization.
Interaction bonuses: squeeze (+25%), cascade (+30%), accumulation (+20%).
Penalty: price extended >15% in 7 days = -40%.

| Score  | Level      | Action                                |
| ------ | ---------- | ------------------------------------- |
| 78-100 | CRITICAL   | Enter now, smart levels shown         |
| 62-77  | HIGH_ALERT | Enter on pullback, smart levels shown |
| 48-61  | WATCHLIST  | Monitor, entry zone shown             |
| 33-47  | MONITOR    | Background awareness                  |

## Smart Trade Levels

Stop Loss: Not fixed %. Uses ATR (1.5-2.5x), swing lows, orderbook
support. Clamped 2.5-15%.

Take Profits: ATR multiples (3x, 5.5x, 9x) adjusted by liquidation
cascade multiplier (1.0-1.8x) and resistance walls.

Entry: CRITICAL = market. HIGH_ALERT = VWAP pullback.
WATCHLIST = limit at support.

## Bootstrap

First scan fetches: 200 OI points, 100 funding records, 100 L/S
ratios, 500 candles. All signals work from scan 1.

## Parallel Scanning

6 tokens simultaneously. 200 tokens in ~2 minutes.

## Trade Monitoring

Every 5 min: price, stop, TPs. Every hour: status update.
Auto stop trail. Signal degradation warnings.

## Cost: $0

Direct exchange APIs, SQLite, Telegram, Python. No paid services.
