"""
PostgreSQL database layer for persistent storage of trading data.
Dual-write alongside JSON files — if DB fails, JSON still works.
"""

import os
import re
import logging
import threading
from datetime import datetime
from typing import Optional, Dict, List, Any

try:
    import psycopg2
    from psycopg2.extras import execute_values
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False
    psycopg2 = None
    execute_values = None

from .config import IST

log = logging.getLogger("db_layer")


class DatabaseLayer:
    """Handles PostgreSQL connection and operations. Safe to call even if DB is unavailable."""

    def __init__(self):
        self._conn: Optional[Any] = None
        self._lock = threading.Lock()
        self._db_available = False
        self._last_health_check = 0.0
        self._health_interval = 900  # 15 minutes in seconds
        self._rows_written_today = 0
        self._write_errors = 0

        if not HAS_PSYCOPG2:
            log.warning("psycopg2 not installed — DB layer disabled, JSON-only mode")
            return

        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            log.warning("DATABASE_URL not set — DB layer disabled, JSON-only mode")
            return

        try:
            self._conn = psycopg2.connect(database_url, connect_timeout=10)
            self._conn.autocommit = True
            self._db_available = True
            self._create_tables()
            log.info("Database connected successfully")
        except Exception as e:
            log.error(f"Database connection failed: {e} — running in JSON-only mode")
            self._db_available = False

    def _create_tables(self):
        """Create tables if they don't exist. Called once on startup."""
        if not self._db_available:
            return

        create_statements = [
            """
            CREATE TABLE IF NOT EXISTS active_opportunities (
                id TEXT PRIMARY KEY,
                date DATE NOT NULL,
                sym TEXT NOT NULL,
                sector TEXT,
                lot INTEGER,
                initial_spread FLOAT,
                current_spread FLOAT,
                discount FLOAT,
                lots_available INTEGER,
                age_sec INTEGER,
                expiry_days INTEGER,
                last_updated TIMESTAMP,
                status TEXT,
                spread_at_signal FLOAT,
                executed BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS expired_opportunities (
                id TEXT PRIMARY KEY,
                date DATE NOT NULL,
                sym TEXT NOT NULL,
                sector TEXT,
                lot INTEGER,
                initial_spread FLOAT,
                current_spread FLOAT,
                final_spread FLOAT,
                discount FLOAT,
                lots_available INTEGER,
                age_sec INTEGER,
                expiry_days INTEGER,
                last_updated TIMESTAMP,
                expired_at TIMESTAMP,
                status TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS daily_instruction_log (
                id TEXT PRIMARY KEY,
                date DATE NOT NULL,
                alert_id TEXT,
                sym TEXT NOT NULL,
                sector TEXT,
                lot_size INTEGER,
                price FLOAT,
                expiry TEXT,
                lots_held INTEGER,
                lots_instructed INTEGER,
                lots_filled INTEGER,
                lots_partial INTEGER,
                lots_not_filled INTEGER,
                pending_lots INTEGER,
                avg_fill_price FLOAT,
                final_spread FLOAT,
                dealer_remarks TEXT,
                confirm_status TEXT,
                estimated_spread FLOAT,
                estimated_saving FLOAT,
                confirmed_saving FLOAT,
                missed_saving FLOAT,
                last_updated TIMESTAMP,
                instruction_timestamp TIMESTAMP,
                finalised BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS execution_details (
                id TEXT PRIMARY KEY,
                date DATE NOT NULL,
                alert_id TEXT,
                sym TEXT NOT NULL,
                sector TEXT,
                lot_size INTEGER,
                price FLOAT,
                expiry TEXT,
                lots_held INTEGER,
                lots_instructed INTEGER,
                lots_filled INTEGER,
                lots_partial INTEGER,
                lots_not_filled INTEGER,
                pending_lots INTEGER,
                avg_fill_price FLOAT,
                final_spread FLOAT,
                dealer_remarks TEXT,
                confirm_status TEXT,
                estimated_spread FLOAT,
                estimated_saving FLOAT,
                confirmed_saving FLOAT,
                missed_saving FLOAT,
                last_updated TIMESTAMP,
                instruction_timestamp TIMESTAMP,
                finalised BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS correction_history (
                id TEXT PRIMARY KEY,
                date DATE NOT NULL,
                entry_id TEXT,
                stock TEXT NOT NULL,
                field_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                reason TEXT,
                timestamp TIMESTAMP DEFAULT NOW(),
                created_at TIMESTAMP DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS session_log (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                login_at TIMESTAMP NOT NULL,
                logout_at TIMESTAMP,
                duration_sec INTEGER,
                created_at TIMESTAMP DEFAULT NOW()
            )
            """,
        ]

        try:
            with self._conn.cursor() as cur:
                for stmt in create_statements:
                    cur.execute(stmt)
            log.info("Database tables created/verified")
        except Exception as e:
            log.error(f"Failed to create tables: {e}")
            self._db_available = False

    @property
    def is_available(self) -> bool:
        return self._db_available

    def _reconnect_if_needed(self):
        """Reconnect if connection is lost."""
        if not self._db_available:
            return

        try:
            if self._conn is None or self._conn.closed:
                database_url = os.environ.get("DATABASE_URL")
                if database_url:
                    self._conn = psycopg2.connect(database_url, connect_timeout=10)
                    self._conn.autocommit = True
                    log.info("Database reconnected")
        except Exception as e:
            log.error(f"Database reconnect failed: {e}")
            self._db_available = False

    def save_table_data(self, table: str, content: Any):
        """Save data to both JSON (existing) and DB (new). Safe — if DB fails, JSON still works."""
        if not self._db_available:
            return

        self._reconnect_if_needed()
        if not self._db_available:
            return

        try:
            with self._lock:
                if self._save_to_db(table, content):
                    self._rows_written_today += 1
        except Exception as e:
            self._write_errors += 1
            log.error(f"DB write failed for {table}: {e}")

    def _save_to_db(self, table: str, content: Any) -> bool:
        """Internal: write to PostgreSQL. Frontend sends date-suffixed names (e.g. active_opportunities_20261026)."""
        if not isinstance(content, list) or not content:
            return False

        base_table = table
        today = datetime.now(IST).date()
        m = re.fullmatch(r"(.+)_(\d{8})", table)
        if m:
            base_table = m.group(1)
            try:
                today = datetime.strptime(m.group(2), "%Y%m%d").date()
            except ValueError:
                pass

        known_tables = {
            "active_opportunities", "expired_opportunities",
            "daily_instruction_log", "execution_details", "correction_history",
        }
        if base_table not in known_tables:
            log.debug(f"DB save skipped: unknown table {table}")
            return False

        with self._conn.cursor() as cur:
            if base_table == "active_opportunities":
                execute_values(
                    cur,
                    """
                    INSERT INTO active_opportunities
                    (id, date, sym, sector, lot, initial_spread, current_spread, discount,
                     lots_available, age_sec, expiry_days, last_updated, status, spread_at_signal, executed)
                    VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                        current_spread = EXCLUDED.current_spread,
                        discount = EXCLUDED.discount,
                        lots_available = EXCLUDED.lots_available,
                        age_sec = EXCLUDED.age_sec,
                        last_updated = EXCLUDED.last_updated,
                        status = EXCLUDED.status
                    """,
                    [
                        (
                            row.get("id"), today, row.get("sym"), row.get("sector"),
                            row.get("lot"), row.get("initial"), row.get("current"),
                            row.get("discount"), row.get("lotsAvailable"),
                            row.get("ageSec"), row.get("expiryDays"),
                            row.get("lastUpdated"), row.get("status"),
                            row.get("spreadAtSignal"), row.get("executed", False)
                        )
                        for row in content
                    ],
                )
            elif base_table == "expired_opportunities":
                execute_values(
                    cur,
                    """
                    INSERT INTO expired_opportunities
                    (id, date, sym, sector, lot, initial_spread, current_spread, final_spread,
                     discount, lots_available, age_sec, expiry_days, last_updated, expired_at, status)
                    VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                        final_spread = EXCLUDED.final_spread,
                        expired_at = EXCLUDED.expired_at,
                        status = EXCLUDED.status
                    """,
                    [
                        (
                            row.get("id"), today, row.get("sym"), row.get("sector"),
                            row.get("lot"), row.get("initial"), row.get("current"),
                            row.get("current"), row.get("discount"),
                            row.get("lotsAvailable"), row.get("ageSec"),
                            row.get("expiryDays"), row.get("lastUpdated"),
                            row.get("lastUpdated"), row.get("status", "Expired")
                        )
                        for row in content
                    ],
                )
            elif base_table == "daily_instruction_log":
                execute_values(
                    cur,
                    """
                    INSERT INTO daily_instruction_log
                    (id, date, alert_id, sym, sector, lot_size, price, expiry,
                     lots_held, lots_instructed, lots_filled, lots_partial, lots_not_filled,
                     pending_lots, avg_fill_price, final_spread, dealer_remarks, confirm_status,
                     estimated_spread, estimated_saving, confirmed_saving, missed_saving,
                     last_updated, instruction_timestamp, finalised)
                    VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                        lots_filled = EXCLUDED.lots_filled,
                        lots_partial = EXCLUDED.lots_partial,
                        lots_not_filled = EXCLUDED.lots_not_filled,
                        pending_lots = EXCLUDED.pending_lots,
                        avg_fill_price = EXCLUDED.avg_fill_price,
                        final_spread = EXCLUDED.final_spread,
                        dealer_remarks = EXCLUDED.dealer_remarks,
                        confirm_status = EXCLUDED.confirm_status,
                        confirmed_saving = EXCLUDED.confirmed_saving,
                        missed_saving = EXCLUDED.missed_saving,
                        last_updated = EXCLUDED.last_updated,
                        finalised = EXCLUDED.finalised
                    """,
                    [
                        (
                            row.get("id"), today, row.get("alertId"), row.get("sym"),
                            row.get("sector"), row.get("lotSize"), row.get("price"),
                            row.get("expiry"), row.get("lotsHeld"), row.get("lotsInstructed"),
                            row.get("lotsFilled"), row.get("lotsPartiallyFilled"),
                            row.get("lotsNotFilled"), row.get("pendingLots"),
                            row.get("avgFillPrice"), row.get("finalSpread"),
                            row.get("dealerRemarks"), row.get("confirmStatus"),
                            row.get("estimatedSpread"), row.get("estimatedSaving"),
                            row.get("confirmedSaving"), row.get("missedSaving"),
                            row.get("lastUpdated"), row.get("instructionTimestamp"),
                            row.get("finalised", False)
                        )
                        for row in content
                    ],
                )
            elif base_table == "execution_details":
                execute_values(
                    cur,
                    """
                    INSERT INTO execution_details
                    (id, date, alert_id, sym, sector, lot_size, price, expiry,
                     lots_held, lots_instructed, lots_filled, lots_partial, lots_not_filled,
                     pending_lots, avg_fill_price, final_spread, dealer_remarks, confirm_status,
                     estimated_spread, estimated_saving, confirmed_saving, missed_saving,
                     last_updated, instruction_timestamp, finalised)
                    VALUES %s
                    ON CONFLICT (id) DO UPDATE SET
                        lots_filled = EXCLUDED.lots_filled,
                        lots_partial = EXCLUDED.lots_partial,
                        lots_not_filled = EXCLUDED.lots_not_filled,
                        pending_lots = EXCLUDED.pending_lots,
                        avg_fill_price = EXCLUDED.avg_fill_price,
                        final_spread = EXCLUDED.final_spread,
                        dealer_remarks = EXCLUDED.dealer_remarks,
                        confirm_status = EXCLUDED.confirm_status,
                        confirmed_saving = EXCLUDED.confirmed_saving,
                        missed_saving = EXCLUDED.missed_saving,
                        last_updated = EXCLUDED.last_updated,
                        finalised = EXCLUDED.finalised
                    """,
                    [
                        (
                            row.get("id"), today, row.get("alertId"), row.get("sym"),
                            row.get("sector"), row.get("lotSize"), row.get("price"),
                            row.get("expiry"), row.get("lotsHeld"), row.get("lotsInstructed"),
                            row.get("lotsFilled"), row.get("lotsPartiallyFilled"),
                            row.get("lotsNotFilled"), row.get("pendingLots"),
                            row.get("avgFillPrice"), row.get("finalSpread"),
                            row.get("dealerRemarks"), row.get("confirmStatus"),
                            row.get("estimatedSpread"), row.get("estimatedSaving"),
                            row.get("confirmedSaving"), row.get("missedSaving"),
                            row.get("lastUpdated"), row.get("instructionTimestamp"),
                            True
                        )
                        for row in content
                    ],
                )
            elif base_table == "correction_history":
                execute_values(
                    cur,
                    """
                    INSERT INTO correction_history
                    (id, date, entry_id, stock, field_name, old_value, new_value, reason, timestamp)
                    VALUES %s
                    ON CONFLICT (id) DO NOTHING
                    """,
                    [
                        (
                            row.get("id"), today, row.get("entryId"), row.get("stock"),
                            row.get("field"), str(row.get("oldValue")),
                            str(row.get("newValue")), row.get("reason"),
                            row.get("timestamp")
                        )
                        for row in content
                    ],
                )
        return True

    def log_session_event(self, user_id: str, event: str, now_str: str, duration_sec=None):
        """Mirror a session event into DB. login=INSERT, logout=closes the open row (no duplicates)."""
        if not self._db_available:
            return
        self._reconnect_if_needed()
        if not self._db_available:
            return
        try:
            with self._lock:
                with self._conn.cursor() as cur:
                    if event == "login":
                        cur.execute(
                            "INSERT INTO session_log (user_id, login_at) VALUES (%s, %s)",
                            (user_id, now_str),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE session_log
                            SET logout_at = %s, duration_sec = %s
                            WHERE id = (
                                SELECT id FROM session_log
                                WHERE user_id = %s AND logout_at IS NULL
                                ORDER BY login_at DESC
                                LIMIT 1
                            )
                            """,
                            (now_str, duration_sec, user_id),
                        )
            self._rows_written_today += 1
        except Exception as e:
            self._write_errors += 1
            log.error(f"DB session log failed for {user_id}: {e}")

    def log_db_health(self):
        """Log DB health status every 15 minutes. Call from main loop."""
        import time
        now = time.monotonic()
        if now - self._last_health_check < self._health_interval:
            return

        self._last_health_check = now

        if not self._db_available:
            log.warning("DB HEALTH: DISABLED — running in JSON-only mode")
            return

        try:
            self._reconnect_if_needed()
            if self._db_available:
                log.info(
                    f"DB HEALTH: OK — {self._rows_written_today} rows written today, "
                    f"{self._write_errors} errors"
                )
            else:
                log.warning("DB HEALTH: CONNECTION LOST — falling back to JSON-only")
        except Exception as e:
            log.error(f"DB HEALTH CHECK FAILED: {e}")

    def close(self):
        """Close database connection on shutdown."""
        if self._conn:
            try:
                self._conn.close()
                log.info("Database connection closed")
            except Exception:
                pass
