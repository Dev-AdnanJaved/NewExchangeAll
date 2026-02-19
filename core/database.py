"""
SQLite storage layer — all data persistence.
"""

import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("database")


class Database:
    def __init__(self, db_path: str = "data/pump_detector.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._create_tables()

    def _create_tables(self):
        c = self.conn.cursor()

        c.execute("""CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            symbol TEXT NOT NULL,
            exchange TEXT NOT NULL,
            data_type TEXT NOT NULL,
            data TEXT NOT NULL
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            symbol TEXT NOT NULL,
            signal_name TEXT NOT NULL,
            raw_value REAL,
            normalized_score REAL,
            metadata TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS score_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL NOT NULL,
            symbol TEXT NOT NULL,
            composite_score REAL NOT NULL,
            classification TEXT NOT NULL,
            signal_scores TEXT NOT NULL,
            bonuses_applied TEXT,
            penalties_applied TEXT
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS active_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL UNIQUE,
            entry_price REAL NOT NULL,
            position_size_usd REAL NOT NULL,
            stop_loss_pct REAL NOT NULL,
            current_stop_price REAL NOT NULL,
            entry_timestamp REAL NOT NULL,
            tp1_hit INTEGER DEFAULT 0,
            tp2_hit INTEGER DEFAULT 0,
            tp3_hit INTEGER DEFAULT 0,
            tp4_hit INTEGER DEFAULT 0,
            remaining_fraction REAL DEFAULT 1.0,
            realized_pnl REAL DEFAULT 0.0,
            last_notified_stop_pct REAL DEFAULT 0.0,
            last_score REAL DEFAULT 0.0,
            metadata TEXT DEFAULT '{}'
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS trade_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            entry_price REAL NOT NULL,
            exit_price REAL,
            position_size_usd REAL NOT NULL,
            realized_pnl REAL DEFAULT 0.0,
            entry_timestamp REAL NOT NULL,
            exit_timestamp REAL,
            duration_hours REAL,
            max_gain_pct REAL DEFAULT 0.0,
            exit_reason TEXT,
            metadata TEXT DEFAULT '{}'
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS universe (
            symbol TEXT PRIMARY KEY,
            exchanges TEXT NOT NULL,
            futures_exchanges TEXT NOT NULL,
            last_updated REAL NOT NULL
        )""")

        c.execute("CREATE INDEX IF NOT EXISTS idx_snap_sym_ts ON snapshots(symbol, timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_snap_type ON snapshots(data_type, timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sig_sym_ts ON signal_history(symbol, timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_score_sym_ts ON score_history(symbol, timestamp)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_score_class ON score_history(classification, timestamp)")

        self.conn.commit()
        logger.info(f"Database initialized: {self.db_path}")

    # ─── Snapshots ──────────────────────────────────────────────

    def store_snapshot(self, symbol, exchange, data_type, data, timestamp=None):
        ts = timestamp or time.time()
        self.conn.execute(
            "INSERT INTO snapshots (timestamp, symbol, exchange, data_type, data) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts, symbol, exchange, data_type, json.dumps(data)),
        )
        self.conn.commit()

    def store_snapshots_batch(self, rows: List[Tuple]):
        self.conn.executemany(
            "INSERT INTO snapshots (timestamp, symbol, exchange, data_type, data) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()

    def get_snapshots(self, symbol, data_type, hours_back=72, exchange=None):
        cutoff = time.time() - (hours_back * 3600)
        if exchange:
            rows = self.conn.execute(
                "SELECT timestamp, exchange, data FROM snapshots "
                "WHERE symbol=? AND data_type=? AND exchange=? AND timestamp>? "
                "ORDER BY timestamp ASC",
                (symbol, data_type, exchange, cutoff),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT timestamp, exchange, data FROM snapshots "
                "WHERE symbol=? AND data_type=? AND timestamp>? "
                "ORDER BY timestamp ASC",
                (symbol, data_type, cutoff),
            ).fetchall()

        results = []
        for row in rows:
            d = json.loads(row["data"])
            d["_timestamp"] = row["timestamp"]
            d["_exchange"] = row["exchange"]
            results.append(d)
        return results

    def get_latest_snapshot(self, symbol, data_type, exchange=None):
        if exchange:
            row = self.conn.execute(
                "SELECT timestamp, exchange, data FROM snapshots "
                "WHERE symbol=? AND data_type=? AND exchange=? "
                "ORDER BY timestamp DESC LIMIT 1",
                (symbol, data_type, exchange),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT timestamp, exchange, data FROM snapshots "
                "WHERE symbol=? AND data_type=? "
                "ORDER BY timestamp DESC LIMIT 1",
                (symbol, data_type),
            ).fetchone()

        if row:
            d = json.loads(row["data"])
            d["_timestamp"] = row["timestamp"]
            d["_exchange"] = row["exchange"]
            return d
        return None

    # ─── Signals ────────────────────────────────────────────────

    def store_signals_batch(self, rows: List[Tuple]):
        self.conn.executemany(
            "INSERT INTO signal_history "
            "(timestamp, symbol, signal_name, raw_value, normalized_score, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()

    def get_signal_history(self, symbol, signal_name, hours_back=72):
        cutoff = time.time() - (hours_back * 3600)
        rows = self.conn.execute(
            "SELECT timestamp, raw_value, normalized_score, metadata "
            "FROM signal_history "
            "WHERE symbol=? AND signal_name=? AND timestamp>? "
            "ORDER BY timestamp ASC",
            (symbol, signal_name, cutoff),
        ).fetchall()

        return [
            {
                "timestamp": r["timestamp"],
                "raw_value": r["raw_value"],
                "normalized_score": r["normalized_score"],
                "metadata": json.loads(r["metadata"]) if r["metadata"] else {},
            }
            for r in rows
        ]

    # ─── Scores ─────────────────────────────────────────────────

    def store_score(self, symbol, composite_score, classification,
                    signal_scores, bonuses, penalties, timestamp=None):
        ts = timestamp or time.time()
        self.conn.execute(
            "INSERT INTO score_history "
            "(timestamp, symbol, composite_score, classification, "
            "signal_scores, bonuses_applied, penalties_applied) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, symbol, composite_score, classification,
             json.dumps(signal_scores), json.dumps(bonuses), json.dumps(penalties)),
        )
        self.conn.commit()

    def get_latest_score(self, symbol):
        row = self.conn.execute(
            "SELECT * FROM score_history WHERE symbol=? "
            "ORDER BY timestamp DESC LIMIT 1",
            (symbol,),
        ).fetchone()

        if row:
            return {
                "timestamp": row["timestamp"],
                "symbol": row["symbol"],
                "composite_score": row["composite_score"],
                "classification": row["classification"],
                "signal_scores": json.loads(row["signal_scores"]),
                "bonuses_applied": json.loads(row["bonuses_applied"])
                if row["bonuses_applied"] else [],
                "penalties_applied": json.loads(row["penalties_applied"])
                if row["penalties_applied"] else [],
            }
        return None

    def get_previous_score(self, symbol):
        rows = self.conn.execute(
            "SELECT * FROM score_history WHERE symbol=? "
            "ORDER BY timestamp DESC LIMIT 2",
            (symbol,),
        ).fetchall()

        if len(rows) >= 2:
            row = rows[1]
            return {
                "timestamp": row["timestamp"],
                "symbol": row["symbol"],
                "composite_score": row["composite_score"],
                "classification": row["classification"],
                "signal_scores": json.loads(row["signal_scores"]),
            }
        return None

    def get_top_scores(self, min_score=48, limit=50):
        rows = self.conn.execute(
            """
            SELECT s1.* FROM score_history s1
            INNER JOIN (
                SELECT symbol, MAX(timestamp) as max_ts
                FROM score_history GROUP BY symbol
            ) s2 ON s1.symbol = s2.symbol AND s1.timestamp = s2.max_ts
            WHERE s1.composite_score >= ?
            ORDER BY s1.composite_score DESC LIMIT ?
            """,
            (min_score, limit),
        ).fetchall()

        return [
            {
                "timestamp": r["timestamp"],
                "symbol": r["symbol"],
                "composite_score": r["composite_score"],
                "classification": r["classification"],
                "signal_scores": json.loads(r["signal_scores"]),
                "bonuses_applied": json.loads(r["bonuses_applied"])
                if r["bonuses_applied"] else [],
                "penalties_applied": json.loads(r["penalties_applied"])
                if r["penalties_applied"] else [],
            }
            for r in rows
        ]

    # ─── Trades ─────────────────────────────────────────────────

    def add_trade(self, symbol, entry_price, position_size_usd, stop_loss_pct):
        stop_price = entry_price * (1 - stop_loss_pct / 100)
        try:
            self.conn.execute(
                "INSERT OR REPLACE INTO active_trades "
                "(symbol, entry_price, position_size_usd, stop_loss_pct, "
                "current_stop_price, entry_timestamp, remaining_fraction, "
                "realized_pnl, last_notified_stop_pct, tp1_hit, tp2_hit, "
                "tp3_hit, tp4_hit, last_score, metadata) "
                "VALUES (?, ?, ?, ?, ?, ?, 1.0, 0.0, 0.0, 0, 0, 0, 0, 0.0, '{}')",
                (symbol, entry_price, position_size_usd, stop_loss_pct,
                 stop_price, time.time()),
            )
            self.conn.commit()
            logger.info(
                f"Trade added: {symbol} @ {entry_price}, "
                f"size=${position_size_usd}, stop={stop_loss_pct}%"
            )
            return True
        except Exception as e:
            logger.error(f"Error adding trade {symbol}: {e}")
            return False

    def get_active_trades(self):
        rows = self.conn.execute(
            "SELECT * FROM active_trades ORDER BY entry_timestamp DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_active_trade(self, symbol):
        row = self.conn.execute(
            "SELECT * FROM active_trades WHERE symbol=?", (symbol,)
        ).fetchone()
        return dict(row) if row else None

    def update_trade(self, symbol, updates):
        if not updates:
            return
        set_clause = ", ".join(f"{k}=?" for k in updates.keys())
        values = list(updates.values()) + [symbol]
        self.conn.execute(
            f"UPDATE active_trades SET {set_clause} WHERE symbol=?", values
        )
        self.conn.commit()

    def close_trade(self, symbol, exit_price, exit_reason="manual"):
        trade = self.get_active_trade(symbol)
        if not trade:
            return None

        now = time.time()
        duration_hours = (now - trade["entry_timestamp"]) / 3600
        pnl_remaining = (
            trade["remaining_fraction"]
            * trade["position_size_usd"]
            * (exit_price - trade["entry_price"])
            / trade["entry_price"]
        )
        total_pnl = trade["realized_pnl"] + pnl_remaining
        max_gain = (exit_price - trade["entry_price"]) / trade["entry_price"] * 100

        self.conn.execute(
            "INSERT INTO trade_history "
            "(symbol, entry_price, exit_price, position_size_usd, "
            "realized_pnl, entry_timestamp, exit_timestamp, "
            "duration_hours, max_gain_pct, exit_reason, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (symbol, trade["entry_price"], exit_price,
             trade["position_size_usd"], total_pnl,
             trade["entry_timestamp"], now, duration_hours,
             max_gain, exit_reason, trade.get("metadata", "{}")),
        )
        self.conn.execute("DELETE FROM active_trades WHERE symbol=?", (symbol,))
        self.conn.commit()

        result = {
            "symbol": symbol,
            "entry_price": trade["entry_price"],
            "exit_price": exit_price,
            "position_size_usd": trade["position_size_usd"],
            "total_pnl": total_pnl,
            "total_pnl_pct": (total_pnl / trade["position_size_usd"]) * 100,
            "duration_hours": duration_hours,
            "exit_reason": exit_reason,
        }
        logger.info(
            f"Trade closed: {symbol} PnL=${total_pnl:.2f} "
            f"({result['total_pnl_pct']:.1f}%)"
        )
        return result

    # ─── Universe ───────────────────────────────────────────────

    def store_universe(self, universe):
        now = time.time()
        rows = [
            (s, json.dumps(i.get("exchanges", [])),
             json.dumps(i.get("futures_exchanges", [])), now)
            for s, i in universe.items()
        ]
        self.conn.execute("DELETE FROM universe")
        self.conn.executemany(
            "INSERT INTO universe (symbol, exchanges, futures_exchanges, last_updated) "
            "VALUES (?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()

    def get_universe(self):
        rows = self.conn.execute("SELECT * FROM universe").fetchall()
        return {
            r["symbol"]: {
                "exchanges": json.loads(r["exchanges"]),
                "futures_exchanges": json.loads(r["futures_exchanges"]),
                "last_updated": r["last_updated"],
            }
            for r in rows
        }

    # ─── Maintenance ────────────────────────────────────────────

    def cleanup(self, days=30):
        cutoff = time.time() - (days * 86400)
        total = 0
        for table in ["snapshots", "signal_history", "score_history"]:
            c = self.conn.execute(
                f"DELETE FROM {table} WHERE timestamp < ?", (cutoff,)
            )
            total += c.rowcount
        self.conn.execute("VACUUM")
        self.conn.commit()
        logger.info(f"Cleanup: removed {total} rows older than {days} days")
        return total

    def get_stats(self):
        stats = {}
        for table in ["snapshots", "signal_history", "score_history",
                       "active_trades", "trade_history", "universe"]:
            row = self.conn.execute(
                f"SELECT COUNT(*) as cnt FROM {table}"
            ).fetchone()
            stats[table] = row["cnt"]

        if os.path.exists(self.db_path):
            stats["file_size_mb"] = os.path.getsize(self.db_path) / (1024 * 1024)
        else:
            stats["file_size_mb"] = 0
        return stats

    def close(self):
        self.conn.close()