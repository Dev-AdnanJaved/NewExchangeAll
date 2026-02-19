"""Console output with smart levels."""

from utils.helpers import format_pct, format_price, format_usd, score_bar, utc_now
from utils.logger import get_logger

logger = get_logger("console")


class ConsoleAlert:
    def send_signal_alert(self, r):
        sym = r["symbol"]
        sc = r["composite_score"]
        cl = r["classification"]
        sigs = r.get("signal_scores", {})
        det = r.get("signal_details", {})
        bon = r.get("bonuses_applied", [])
        pen = r.get("penalties_applied", [])
        price = r.get("current_price", 0)
        levels = r.get("levels")

        em = {
            "CRITICAL": "🔴🔴🔴", "HIGH_ALERT": "🟠🟠",
            "WATCHLIST": "🟡", "MONITOR": "⚪",
        }.get(cl, "")

        print("\n" + "=" * 60)
        print(f"{em} {cl}: {sym} {em}")
        print("=" * 60)
        print(f"📊 Score: {sc:.1f} / 100  |  💰 Price: {format_price(price)}\n")

        print("🎯 Signals:")
        for n, s in sorted(sigs.items(), key=lambda x: x[1], reverse=True):
            print(f"  {n:25s} {score_bar(s)} {s:.0f}")
        print()

        # Key metrics
        oi = det.get("oi_surge", {})
        if oi.get("oi_change_pct"):
            print(f"  OI 72h: {format_pct(oi['oi_change_pct'])}")
        fu = det.get("funding_rate", {})
        if fu.get("current_rate_pct"):
            print(f"  Funding: {fu['current_rate_pct']}")
        lq = det.get("liquidation_leverage", {})
        if lq.get("leverage_ratio"):
            print(f"  Liq: {lq['leverage_ratio']:.1f}x")
        vo = det.get("volatility_compression", {})
        if vo.get("atr_pct"):
            print(f"  ATR: {vo['atr_pct']:.2f}%")
        if vo.get("bb_percentile"):
            print(f"  BB: {vo['bb_percentile']:.0f}th pctl")
        print()

        if bon:
            print("🔗 " + ", ".join(bon))
        if pen:
            print("⚠️ " + ", ".join(pen))
        if bon or pen:
            print()

        # Smart levels for HIGH_ALERT and CRITICAL
        if levels and cl in ("CRITICAL", "HIGH_ALERT"):
            e = levels["entry"]
            s = levels["stop"]
            t = levels["take_profits"]
            tr = levels["trailing"]
            rr = levels["risk_reward"]
            a = levels["atr"]
            q = levels["data_quality"]

            print(f"⚡ SMART LEVELS (quality: {q['label']})")
            print(f"  ATR: {format_price(a['value'])} ({a['pct']:.2f}%)\n")

            print(f"  📥 ENTRY ({e['urgency']}): {format_price(e['low'])} → {format_price(e['high'])}")
            print(f"     Ideal: {format_price(e['ideal'])} [{e['method']}]\n")

            print(f"  🛑 STOP ({s['method']}): {format_price(s['price'])} ({format_pct(-s['pct'])})")
            print(f"     {s.get('atr_distance', 0):.1f}× ATR\n")

            if t:
                print("  🎯 TAKE PROFITS:")
                for tp in t:
                    print(
                        f"     TP{tp['level']} ({tp['sell_pct']}%): "
                        f"{format_price(tp['price'])} ({format_pct(tp['pct'])}) "
                        f"[{tp['atr_multiple']:.1f}× ATR]"
                    )
                if tr:
                    print(
                        f"     TP4 ({tr['sell_pct']}%): Trail {tr['trail_pct']:.1f}% "
                        f"({tr['trail_atr_multiple']}× ATR)"
                    )
                print()

            if rr:
                print(
                    f"  📐 R:R {rr['ratio']:.2f}:1 | Risk: {rr['risk_pct']:.1f}% | "
                    f"$10k 2%: {rr.get('position_2pct_risk_10k', 'N/A')}\n"
                )

        elif cl == "WATCHLIST" and levels:
            e = levels["entry"]
            print(
                f"  👀 Watch: {format_price(e['low'])} → "
                f"{format_price(e['high'])}\n"
            )

        print(f"⏰ {utc_now().strftime('%H:%M:%S UTC')}")
        print("=" * 60)

    def send_event(self, e):
        em = {"IGNITION": "🚀", "SCORE_JUMP": "📈", "UPGRADE": "⬆️"}.get(
            e.get("type", ""), "📢"
        )
        print(f"\n{em} {e.get('type', '')}: {e.get('symbol', '')}  {e.get('message', '')}")

    def send_trade_registered(self, sym, ep, ps, sp):
        print(
            f"\n✅ TRADE: {sym} @ {format_price(ep)} | "
            f"Size: {format_usd(ps)} | Stop: {format_pct(-sp)}"
        )

    def send_stop_update(self, symbol, new_stop_price, new_stop_pct,
                         current_price, entry_price, reason):
        print(
            f"\n📍 STOP {symbol}: {format_price(new_stop_price)} "
            f"({format_pct(new_stop_pct)}) — {reason}"
        )

    def send_tp_hit(self, symbol, tp_level, tp_pct, current_price,
                    entry_price, pnl_chunk, remaining_pct):
        print(
            f"\n🎯 TP{tp_level} {symbol}: {format_price(current_price)} "
            f"(+{tp_pct}%) | PnL: {format_usd(pnl_chunk)} | Rem: {remaining_pct:.0f}%"
        )

    def send_trade_closed(self, r, reason):
        em = "🟢" if r["total_pnl"] >= 0 else "🔴"
        print(
            f"\n{em} CLOSED {r['symbol']}: {format_usd(r['total_pnl'])} "
            f"({format_pct(r['total_pnl_pct'])}) — {reason}"
        )

    def send_trade_status(self, symbol, entry_price, current_price,
                          price_change_pct, unrealized_pnl, realized_pnl,
                          remaining_pct, current_stop, hours_in, score):
        em = "🟢" if price_change_pct >= 0 else "🔴"
        print(
            f"\n{em} {symbol} ({hours_in:.1f}h): "
            f"{format_price(current_price)} ({format_pct(price_change_pct)}) | "
            f"U:{format_usd(unrealized_pnl)} R:{format_usd(realized_pnl)} | "
            f"{remaining_pct:.0f}% | Score:{score:.0f}"
        )

    def send_signal_degradation(self, symbol, old_score, new_score,
                                current_price, entry_price, price_change_pct):
        print(
            f"\n⚠️ DEGRADE {symbol}: {old_score:.0f}→{new_score:.0f} | "
            f"{format_price(current_price)} ({format_pct(price_change_pct)})"
        )