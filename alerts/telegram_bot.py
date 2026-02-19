"""Telegram bot with smart levels + commands."""

import asyncio
import json
import threading
import traceback
from typing import Any, Dict

from utils.helpers import format_pct, format_price, format_usd, score_bar, utc_now
from utils.logger import get_logger

logger = get_logger("telegram")

try:
    from telegram import Update
    from telegram.ext import Application, CommandHandler, ContextTypes
    TG = True
except ImportError:
    TG = False
    logger.warning("python-telegram-bot not installed")


class TelegramAlert:
    def __init__(self, bot_token, chat_id, scanner=None):
        self.token = bot_token
        self.chat = str(chat_id)
        self.scanner = scanner
        self._app = None
        self._loop = None
        self._thread = None

        if TG and bot_token and chat_id:
            self._start()

    def _start(self):
        def run():
            try:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
                self._app = Application.builder().token(self.token).build()

                cmds = [
                    ("start", self._start_cmd), ("help", self._help),
                    ("trade", self._trade), ("close", self._close),
                    ("status", self._status), ("adjust", self._adjust),
                    ("scan", self._scan), ("watchlist", self._wl),
                ]
                for cmd, fn in cmds:
                    self._app.add_handler(CommandHandler(cmd, fn))

                logger.info("Telegram bot started")
                self._loop.run_until_complete(
                    self._app.run_polling(drop_pending_updates=True)
                )
            except Exception as e:
                logger.error(f"TG error: {e}")
                logger.debug(traceback.format_exc())

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def _send(self, text):
        if not TG or not self._app:
            return

        async def s():
            try:
                msg = text
                while msg:
                    chunk = msg[:4000]
                    msg = msg[4000:]
                    await self._app.bot.send_message(
                        chat_id=self.chat, text=chunk, parse_mode="HTML"
                    )
            except Exception as e:
                logger.error(f"TG send: {e}")

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(s(), self._loop)
        else:
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(s())
                loop.close()
            except Exception:
                pass

    # ─── Commands ─────────────────────────────────────────────

    async def _start_cmd(self, u: Update, c):
        await u.message.reply_text(
            "🔍 <b>Pump Detector Active</b>\nSend /help for commands.",
            parse_mode="HTML",
        )

    async def _help(self, u: Update, c):
        await u.message.reply_text(
            "🔍 <b>Commands</b>\n\n"
            "<b>/trade</b> TOKEN PRICE SIZE STOP%\n"
            "  Example: /trade DOGE 0.165 5000 7\n\n"
            "<b>/close</b> TOKEN [PRICE]\n"
            "<b>/status</b> — Active trades\n"
            "<b>/adjust</b> TOKEN stop PRICE\n"
            "<b>/scan</b> — Force scan\n"
            "<b>/watchlist</b> — Current watchlist\n"
            "<b>/help</b> — This message",
            parse_mode="HTML",
        )

    async def _trade(self, u: Update, c):
        if not self.scanner:
            await u.message.reply_text("❌ Scanner not connected")
            return
        a = c.args
        if not a or len(a) < 4:
            await u.message.reply_text(
                "Usage: /trade TOKEN PRICE SIZE STOP%\nExample: /trade DOGE 0.165 5000 7"
            )
            return
        try:
            sym = a[0].upper()
            ep, sz, sp = float(a[1]), float(a[2]), float(a[3])
            if self.scanner.add_trade(sym, ep, sz, sp):
                stop_p = ep * (1 - sp / 100)
                await u.message.reply_text(
                    f"✅ <b>{sym}</b> @ {format_price(ep)} | {format_usd(sz)}\n"
                    f"Stop: {format_price(stop_p)} (-{sp}%) | "
                    f"Risk: {format_usd(sz * sp / 100)}\n📡 Monitoring...",
                    parse_mode="HTML",
                )
            else:
                await u.message.reply_text(f"❌ Failed for {sym}")
        except Exception as e:
            await u.message.reply_text(f"❌ {e}")

    async def _close(self, u: Update, c):
        if not self.scanner:
            return
        a = c.args
        if not a:
            await u.message.reply_text("Usage: /close TOKEN [PRICE]")
            return
        sym = a[0].upper()
        exit_p = float(a[1]) if len(a) > 1 else None
        r = self.scanner.close_trade(sym, exit_p)
        if r:
            em = "🟢" if r["total_pnl"] >= 0 else "🔴"
            await u.message.reply_text(
                f"{em} <b>{r['symbol']}</b> PnL: {format_usd(r['total_pnl'])} "
                f"({format_pct(r['total_pnl_pct'])})",
                parse_mode="HTML",
            )
        else:
            await u.message.reply_text(f"❌ No trade for {sym}")

    async def _status(self, u: Update, c):
        if not self.scanner:
            return
        trades = self.scanner.get_trade_status()
        if not trades:
            await u.message.reply_text("📭 No active trades")
            return
        msg = "📊 <b>Active Trades</b>\n\n"
        for t in trades:
            tps = sum(t.get(f"tp{i}_hit", 0) for i in range(1, 5))
            msg += (
                f"<b>{t['symbol']}</b> @ {format_price(t['entry_price'])}\n"
                f"  Stop: {format_price(t['current_stop_price'])} | "
                f"{t['remaining_fraction'] * 100:.0f}% | TP:{tps}/4\n"
                f"  Realized: {format_usd(t['realized_pnl'])}\n\n"
            )
        await u.message.reply_text(msg, parse_mode="HTML")

    async def _adjust(self, u: Update, c):
        if not self.scanner or not c.args or len(c.args) < 3:
            await u.message.reply_text("Usage: /adjust TOKEN stop PRICE")
            return
        if c.args[1].lower() != "stop":
            await u.message.reply_text("Usage: /adjust TOKEN stop PRICE")
            return
        self.scanner.adjust_stop(c.args[0].upper(), float(c.args[2]))
        await u.message.reply_text(f"✅ Stop adjusted for {c.args[0].upper()}")

    async def _scan(self, u: Update, c):
        if not self.scanner:
            return
        await u.message.reply_text("🔄 Scanning...")

        def do():
            try:
                results = self.scanner.run_once()
                asyncio.run_coroutine_threadsafe(
                    u.message.reply_text(f"✅ {len(results)} alerts"),
                    self._loop,
                )
            except Exception as e:
                logger.error(f"Forced scan: {e}")

        threading.Thread(target=do, daemon=True).start()

    async def _wl(self, u: Update, c):
        if not self.scanner:
            return
        top = self.scanner.db.get_top_scores(40, 20)
        if not top:
            await u.message.reply_text("📭 Empty. Run /scan first.")
            return
        em_map = {
            "CRITICAL": "🔴", "HIGH_ALERT": "🟠",
            "WATCHLIST": "🟡", "MONITOR": "⚪",
        }
        msg = "📋 <b>Watchlist</b>\n\n"
        for i in top:
            em = em_map.get(i["classification"], "")
            msg += f"{em} <b>{i['symbol']}</b>: {i['composite_score']:.0f}\n"
        await u.message.reply_text(msg, parse_mode="HTML")

    # ─── Notifications ────────────────────────────────────────

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

        em = {"CRITICAL": "🔴🔴🔴", "HIGH_ALERT": "🟠🟠", "WATCHLIST": "🟡"}.get(cl, "📊")

        m = f"{em} <b>{cl}: {sym}</b> {em}\n\n"
        m += f"📊 Score: <b>{sc:.1f}</b>/100\n"
        if price > 0:
            m += f"💰 {format_price(price)}\n"
        m += "\n🎯 <b>Signals:</b>\n"
        for n, s in sorted(sigs.items(), key=lambda x: x[1], reverse=True):
            m += f"  {n}: {score_bar(s)} {s:.0f}\n"

        m += "\n📈 <b>Metrics:</b>\n"
        oi = det.get("oi_surge", {})
        if oi.get("oi_change_pct"):
            m += f"  OI: {format_pct(oi['oi_change_pct'])}\n"
        fu = det.get("funding_rate", {})
        if fu.get("current_rate_pct"):
            m += f"  Fund: {fu['current_rate_pct']}\n"
        lq = det.get("liquidation_leverage", {})
        if lq.get("leverage_ratio"):
            m += f"  Liq: {lq['leverage_ratio']:.1f}x\n"
        vo = det.get("volatility_compression", {})
        if vo.get("atr_pct"):
            m += f"  ATR: {vo['atr_pct']:.2f}%\n"
        m += "\n"

        if bon:
            m += "🔗 " + ", ".join(bon) + "\n"
        if pen:
            m += "⚠️ " + ", ".join(pen) + "\n"
        if bon or pen:
            m += "\n"

        # Smart levels for HIGH_ALERT and CRITICAL
        if levels and cl in ("CRITICAL", "HIGH_ALERT"):
            e = levels["entry"]
            s = levels["stop"]
            t = levels["take_profits"]
            tr = levels["trailing"]
            rr = levels["risk_reward"]
            a = levels["atr"]
            q = levels["data_quality"]

            m += f"⚡ <b>SMART LEVELS</b> ({q['label']})\n"
            m += f"📏 ATR: {format_price(a['value'])} ({a['pct']:.2f}%)\n\n"

            m += f"📥 <b>ENTRY ({e['urgency']}):</b>\n"
            m += f"  {format_price(e['low'])} → {format_price(e['high'])}\n"
            m += f"  Ideal: {format_price(e['ideal'])}\n\n"

            m += f"🛑 <b>STOP ({s['method']}):</b>\n"
            m += f"  {format_price(s['price'])} ({format_pct(-s['pct'])})"
            m += f" | {s.get('atr_distance', 0):.1f}× ATR\n\n"

            if t:
                m += "🎯 <b>TAKE PROFITS:</b>\n"
                for tp in t:
                    m += (
                        f"  TP{tp['level']}({tp['sell_pct']}%): "
                        f"{format_price(tp['price'])} ({format_pct(tp['pct'])}) "
                        f"[{tp['atr_multiple']:.1f}×ATR]\n"
                    )
                if tr:
                    m += (
                        f"  TP4({tr['sell_pct']}%): Trail "
                        f"{tr['trail_pct']:.1f}%\n"
                    )
                m += "\n"

            if rr:
                m += (
                    f"📐 <b>R:R {rr['ratio']:.2f}:1</b> | "
                    f"Risk: {rr['risk_pct']:.1f}%\n"
                )
                m += f"  $10k 2%→{rr.get('position_2pct_risk_10k', 'N/A')}\n\n"

            m += (
                f"<code>/trade {sym} {e.get('ideal', 0):.8g} "
                f"SIZE {s.get('pct', 7):.1f}</code>\n\n"
            )

        elif cl == "WATCHLIST" and levels:
            e = levels["entry"]
            m += (
                f"👀 Watch: {format_price(e['low'])} → "
                f"{format_price(e['high'])}\n\n"
            )

        m += f"🕐 {utc_now().strftime('%H:%M:%S UTC')}"
        self._send(m)

    def send_event(self, e):
        em = {
            "IGNITION": "🚀🚀🚀", "SCORE_JUMP": "📈📈", "UPGRADE": "⬆️",
        }.get(e.get("type", ""), "📢")
        m = f"{em} <b>{e['type']}: {e['symbol']}</b>\n\n{e['message']}"
        if e["type"] == "IGNITION":
            m += "\n\n⚡ Check if entry still viable"
        self._send(m)

    def send_trade_registered(self, sym, ep, ps, sp):
        stop_p = ep * (1 - sp / 100)
        self._send(
            f"✅ <b>Trade: {sym}</b>\n\n"
            f"Entry: {format_price(ep)}\n"
            f"Size: {format_usd(ps)}\n"
            f"Stop: {format_price(stop_p)} (-{sp}%)\n"
            f"Risk: {format_usd(ps * sp / 100)}\n\n"
            f"📡 Monitoring..."
        )

    def send_stop_update(self, symbol, new_stop_price, new_stop_pct,
                         current_price, entry_price, reason):
        self._send(
            f"📍 <b>STOP {symbol}</b>\n\n"
            f"Move to: {format_price(new_stop_price)} "
            f"({format_pct(new_stop_pct)})\n{reason}"
        )

    def send_tp_hit(self, symbol, tp_level, tp_pct, current_price,
                    entry_price, pnl_chunk, remaining_pct):
        self._send(
            f"🎯 <b>TP{tp_level} {symbol}</b>\n\n"
            f"{format_price(current_price)} (+{tp_pct:.0f}%)\n"
            f"Profit: {format_usd(pnl_chunk)}\n"
            f"Remaining: {remaining_pct:.0f}%"
        )

    def send_trade_closed(self, r, reason):
        em = "🟢" if r["total_pnl"] >= 0 else "🔴"
        self._send(
            f"{em} <b>CLOSED {r['symbol']}</b> — {reason}\n\n"
            f"PnL: {format_usd(r['total_pnl'])} "
            f"({format_pct(r['total_pnl_pct'])})\n"
            f"{r['duration_hours']:.1f}h"
        )

    def send_trade_status(self, symbol, entry_price, current_price,
                          price_change_pct, unrealized_pnl, realized_pnl,
                          remaining_pct, current_stop, hours_in, score):
        em = "🟢" if price_change_pct >= 0 else "🔴"
        self._send(
            f"{em} <b>{symbol}</b> ({hours_in:.1f}h)\n\n"
            f"{format_price(current_price)} ({format_pct(price_change_pct)})\n"
            f"U:{format_usd(unrealized_pnl)} R:{format_usd(realized_pnl)}\n"
            f"{remaining_pct:.0f}% | Stop:{format_price(current_stop)} | "
            f"Score:{score:.0f}"
        )

    def send_signal_degradation(self, symbol, old_score, new_score,
                                current_price, entry_price, price_change_pct):
        self._send(
            f"⚠️ <b>DEGRADE {symbol}</b>\n\n"
            f"{old_score:.0f}→{new_score:.0f}\n"
            f"{format_price(current_price)} ({format_pct(price_change_pct)})\n\n"
            f"<b>Tighten stop or exit 50%</b>"
        )