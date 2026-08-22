"""
Persistencia SQLite para la app móvil (api-server Express).

Usa el esquema existente de bot_state.db (session_id, pair, etc.).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "bot_state.db")


def _db_ts() -> str:
    """Timestamp local compatible con datetime('now') de SQLite."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class MobileStore:
    def __init__(self, db_path: str = _DEFAULT_DB):
        self.db_path = db_path
        self._session_id: Optional[str] = None
        self._closed_logged: set[int] = set()

    @contextmanager
    def _conn(self):
        from services.database import get_database_manager
        with get_database_manager(self.db_path).get_connection() as conn:
            yield conn

    def ensure_tables(self) -> None:
        """Migraciones ligeras sobre el esquema existente del bot."""
        try:
            with self._conn() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS session_stats (
                        session_id      TEXT PRIMARY KEY,
                        start_time      TEXT NOT NULL,
                        initial_balance REAL NOT NULL,
                        current_balance REAL NOT NULL,
                        peak_balance    REAL NOT NULL,
                        total_pnl       REAL DEFAULT 0,
                        last_update     TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS balance_snapshots (
                        id             INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id     TEXT,
                        timestamp      TEXT NOT NULL,
                        balance        REAL NOT NULL,
                        equity         REAL NOT NULL,
                        margin         REAL DEFAULT 0,
                        free_margin    REAL DEFAULT 0,
                        profit         REAL DEFAULT 0,
                        open_positions INTEGER DEFAULT 0
                    )
                """)
                bs_cols = {r[1] for r in conn.execute("PRAGMA table_info(balance_snapshots)")}
                for col_name, col_def in [
                    ("session_id", "TEXT"),
                    ("margin", "REAL DEFAULT 0"),
                    ("free_margin", "REAL DEFAULT 0"),
                    ("profit", "REAL DEFAULT 0"),
                    ("open_positions", "INTEGER DEFAULT 0"),
                ]:
                    if col_name not in bs_cols:
                        try:
                            conn.execute(f"ALTER TABLE balance_snapshots ADD COLUMN {col_name} {col_def}")
                        except Exception:
                            pass
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS enhanced_signals (
                        id               INTEGER PRIMARY KEY AUTOINCREMENT,
                        session_id       TEXT,
                        timestamp        TEXT NOT NULL,
                        symbol           TEXT NOT NULL,
                        direction        TEXT NOT NULL DEFAULT 'BUY',
                        signal_type      TEXT DEFAULT 'BUY',
                        strategy         TEXT NOT NULL,
                        price            REAL DEFAULT 0,
                        entry_price      REAL DEFAULT 0,
                        sl_price         REAL DEFAULT 0,
                        tp_price         REAL DEFAULT 0,
                        score            REAL DEFAULT 0,
                        confidence       TEXT,
                        confidence_level TEXT,
                        confidence_score INTEGER DEFAULT 0,
                        status           TEXT DEFAULT 'PROPOSED',
                        executed         INTEGER DEFAULT 0,
                        rejected         INTEGER DEFAULT 0,
                        lot_size         REAL DEFAULT 0.01,
                        created_at       TEXT,
                        mobile_processed INTEGER DEFAULT 0
                    )
                """)
                cols = {r[1] for r in conn.execute("PRAGMA table_info(enhanced_signals)")}
                for col_name, col_def in [
                    ("session_id", "TEXT"),
                    ("direction", "TEXT DEFAULT 'BUY'"),
                    ("price", "REAL DEFAULT 0"),
                    ("sl_price", "REAL DEFAULT 0"),
                    ("tp_price", "REAL DEFAULT 0"),
                    ("lot_size", "REAL DEFAULT 0.01"),
                    ("confidence_score", "INTEGER DEFAULT 0"),
                    ("confidence_level", "TEXT"),
                    ("status", "TEXT DEFAULT 'PROPOSED'"),
                    ("executed", "INTEGER DEFAULT 0"),
                    ("rejected", "INTEGER DEFAULT 0"),
                    ("created_at", "TEXT"),
                    ("mobile_processed", "INTEGER DEFAULT 0"),
                ]:
                    if col_name not in cols:
                        try:
                            conn.execute(f"ALTER TABLE enhanced_signals ADD COLUMN {col_name} {col_def}")
                        except Exception:
                            pass
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS backtest_tasks (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        symbol          TEXT    NOT NULL,
                        strategy        TEXT    NOT NULL,
                        bars            INTEGER NOT NULL,
                        cb_losses       INTEGER DEFAULT 4,
                        cb_pause        INTEGER DEFAULT 168,
                        status          TEXT    NOT NULL DEFAULT 'PENDING',
                        results_json    TEXT,
                        error_message   TEXT,
                        created_at      TEXT    DEFAULT (datetime('now')),
                        updated_at      TEXT    DEFAULT (datetime('now'))
                    )
                """)
            # Garantizar trade_journal
            try:
                from core.journal import get_journal
                get_journal(self.db_path)
            except Exception as journal_err:
                logger.error(f"[MobileStore] Error inicializando trade_journal: {journal_err}")
        except Exception as e:
            logger.error(f"[MobileStore] Error en migración: {e}")

    def start_session(self, balance: float = 0.0) -> None:
        now = _db_ts()
        self._session_id = f"session_{now.replace(' ', '_').replace(':', '')}_{uuid.uuid4().hex[:8]}"
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO session_stats
                       (session_id, start_time, initial_balance, current_balance,
                        peak_balance, total_pnl, last_update)
                       VALUES (?, ?, ?, ?, ?, 0, ?)""",
                    (self._session_id, now, balance, balance, balance, now),
                )
            logger.info(f"[MobileStore] Sesión iniciada: {self._session_id}")
        except Exception as e:
            logger.error(f"[MobileStore] Error iniciando sesión: {e}")
            self._session_id = None

    def update_session(self, balance: float, total_pnl: float) -> None:
        if not self._session_id:
            return
        now = _db_ts()
        try:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE session_stats
                       SET current_balance=?, total_pnl=?, last_update=?,
                           peak_balance=MAX(COALESCE(peak_balance, 0), ?)
                       WHERE session_id=?""",
                    (balance, total_pnl, now, balance, self._session_id),
                )
        except Exception as e:
            logger.warning(f"[MobileStore] update_session: {e}")

    def save_balance_snapshot(
        self,
        balance: float,
        equity: float,
        margin: float = 0.0,
        free_margin: Optional[float] = None,
        open_positions: int = 0,
    ) -> None:
        if not self._session_id:
            return
        if free_margin is None:
            free_margin = max(0.0, equity - margin)
        profit = equity - balance
        now = _db_ts()
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO balance_snapshots
                       (session_id, timestamp, balance, equity, margin,
                        free_margin, profit, open_positions)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        self._session_id,
                        now,
                        balance,
                        equity,
                        margin,
                        free_margin,
                        profit,
                        open_positions,
                    ),
                )
                conn.execute(
                    """DELETE FROM balance_snapshots
                       WHERE id NOT IN (
                         SELECT id FROM balance_snapshots
                         ORDER BY id DESC LIMIT 200
                       )"""
                )
        except Exception as e:
            logger.warning(f"[MobileStore] save_balance_snapshot: {e}")

    def insert_signal(
        self,
        *,
        symbol: str,
        direction: str,
        price: float,
        tp_price: float,
        sl_price: float,
        lot_size: float = 0.01,
        confidence_score: float = 0.0,
        confidence: str = "MEDIUM",
        strategy: str = "",
        status: str = "PROPOSED",
    ) -> Optional[int]:
        if not self._session_id:
            logger.warning("[MobileStore] insert_signal sin session_id activo")
            return None
        now = _db_ts()
        score_int = int(confidence_score * 100) if confidence_score <= 1 else int(confidence_score)
        executed = 1 if status.upper() in ("OPEN", "EXECUTED", "ACCEPTED") else 0
        rejected = 1 if status.upper() == "REJECTED" else 0
        try:
            with self._conn() as conn:
                cur = conn.execute(
                    """INSERT INTO enhanced_signals
                       (session_id, timestamp, symbol, strategy, direction,
                        price, sl_price, tp_price, confidence_level, confidence_score,
                        status, executed, rejected, lot_size, created_at, mobile_processed)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                    (
                        self._session_id,
                        now,
                        symbol.upper(),
                        strategy or "unknown",
                        direction.upper(),
                        price,
                        sl_price,
                        tp_price,
                        confidence,
                        score_int,
                        status.upper(),
                        executed,
                        rejected,
                        lot_size,
                        now,
                    ),
                )
                return cur.lastrowid
        except Exception as e:
            logger.error(f"[MobileStore] insert_signal: {e}")
            return None

    def update_signal_status(self, signal_id: int, status: str) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    "UPDATE enhanced_signals SET status=? WHERE id=?",
                    (status.upper(), signal_id),
                )
        except Exception as e:
            logger.debug(f"[MobileStore] update_signal_status: {e}")

    def log_closed_trade(
        self,
        *,
        signal_id: int,
        symbol: str,
        trade_type: str,
        entry_price: float,
        close_price: float,
        sl_price: float,
        tp_price: float,
        pnl: float,
        lot_size: float,
        close_reason: str,
        strategy: str = "",
    ) -> None:
        if signal_id in self._closed_logged or not self._session_id:
            return
        now = _db_ts()
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO session_trades
                       (session_id, timestamp, pair, strategy, type,
                        entry_price, sl_price, tp_price, lot_size, pnl,
                        status, created_at, closed_at, close_price)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        self._session_id,
                        now,
                        symbol.upper(),
                        strategy or "unknown",
                        trade_type.upper(),
                        entry_price,
                        sl_price,
                        tp_price,
                        lot_size,
                        pnl,
                        close_reason.upper(),
                        now,
                        now,
                        close_price,
                    ),
                )
                conn.execute(
                    "UPDATE enhanced_signals SET status=?, pnl=?, closed_at=?, close_price=? WHERE id=?",
                    (close_reason.upper(), pnl, now, close_price, signal_id),
                )

                # Calcular P&L en pips para el diario cuantitativo (trade_journal)
                pip_sizes = {'EURUSD': 0.0001, 'XAUUSD': 0.1, 'BTCEUR': 1.0, 'BTCUSDT': 1.0}
                pip_size = pip_sizes.get(symbol.upper(), 0.0001)
                pips = 0.0
                if entry_price and close_price:
                    if trade_type.upper() == 'BUY':
                        pips = (close_price - entry_price) / pip_size
                    else:
                        pips = (entry_price - close_price) / pip_size

                result = 'WIN' if pnl > 0 else ('LOSS' if pnl < 0 else 'BREAKEVEN')

                try:
                    from core.journal import get_journal
                    closed = get_journal(self.db_path).close_matching_pending(
                        symbol,
                        entry_price=entry_price,
                        close_price=close_price,
                        result=result,
                        pnl_pips=pips,
                        pnl_eur=pnl,
                        notes=f"Cierre MobileStore · signal_id={signal_id}",
                    )
                    if not closed:
                        get_journal(self.db_path).log_entry(
                            {
                                'symbol': symbol,
                                'type': trade_type,
                                'entry': entry_price,
                                'sl': sl_price,
                                'tp': tp_price,
                                'strategy_used': strategy or 'unknown',
                            },
                            lot_size=lot_size,
                            mode='live',
                            notes=f"Apertura+cierre en un paso · signal_id={signal_id}",
                        )
                        get_journal(self.db_path).close_matching_pending(
                            symbol,
                            entry_price=entry_price,
                            close_price=close_price,
                            result=result,
                            pnl_pips=pips,
                            pnl_eur=pnl,
                        )
                except Exception as journal_err:
                    logger.warning(f"[MobileStore] trade_journal: {journal_err}")

            self._closed_logged.add(signal_id)
        except Exception as e:
            logger.warning(f"[MobileStore] log_closed_trade: {e}")

    def get_unprocessed_mobile_actions(self) -> List[Dict[str, Any]]:
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT id, symbol, direction, price, tp_price, sl_price,
                              lot_size, status, confidence_score, strategy
                       FROM enhanced_signals
                       WHERE COALESCE(mobile_processed, 0) = 0
                         AND status IN ('ACCEPTED', 'REJECTED')
                       ORDER BY id ASC"""
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.debug(f"[MobileStore] get_unprocessed_mobile_actions: {e}")
            return []

    def mark_mobile_processed(self, signal_id: int, *, executed: bool = False) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE enhanced_signals
                       SET mobile_processed=1, executed=?
                       WHERE id=?""",
                    (1 if executed else 0, signal_id),
                )
        except Exception as e:
            logger.debug(f"[MobileStore] mark_mobile_processed: {e}")

    def process_mobile_actions(self) -> None:
        """Ejecuta señales ACCEPTED desde la app en MT5 demo."""
        for row in self.get_unprocessed_mobile_actions():
            sid = row["id"]
            status = (row["status"] or "").upper()

            if status == "REJECTED":
                self.mark_mobile_processed(sid, executed=False)
                logger.info(f"[MobileStore] Señal {sid} rechazada desde app móvil")
                continue

            if status != "ACCEPTED":
                continue

            signal = {
                "symbol": row["symbol"],
                "type": row["direction"],
                "entry": row["price"],
                "sl": row["sl_price"],
                "tp": row["tp_price"],
                "strategy_used": row["strategy"] or "mobile_accept",
            }
            try:
                from services.execution import get_execution_service

                result = get_execution_service().execute_signal(signal)
                if result.success:
                    self.mark_mobile_processed(sid, executed=True)
                    self.update_signal_status(sid, "OPEN")
                    logger.info(
                        f"[MobileStore] Señal {sid} ejecutada en MT5 "
                        f"(ticket {result.order_id})"
                    )
                else:
                    logger.warning(
                        f"[MobileStore] Fallo ejecutando señal {sid}: {result.message}"
                    )
            except Exception as e:
                logger.error(f"[MobileStore] Error ejecutando señal {sid}: {e}")

    def _mt5_open_positions(self) -> int:
        try:
            import MetaTrader5 as mt5

            positions = mt5.positions_get()
            return len(positions) if positions else 0
        except Exception:
            return 0

    def sync_dashboard(self, dashboard) -> None:
        """Sincroniza equity MT5, acciones móviles y trades cerrados."""
        self.process_mobile_actions()

        try:
            snap = dashboard.get_equity_snapshot()
            balance = float(snap.get("balance") or 0)
            equity = float(snap.get("total_equity") or balance)
            change = float(snap.get("change") or 0)
            margin = float(snap.get("margin") or 0)
            free_margin = float(snap.get("free_margin") or max(0.0, equity - margin))
            open_positions = self._mt5_open_positions()

            self.save_balance_snapshot(
                balance, equity, margin, free_margin, open_positions
            )
            self.update_session(equity, change)
        except Exception as e:
            logger.warning(f"[MobileStore] sync equity: {e}")

        # Trades cerrados: solo señales ejecutadas en MT5 (no simulación paper)
        try:
            with dashboard.lock:
                for ev in dashboard.signal_history:
                    if not getattr(ev, "mobile_signal_id", None):
                        continue
                    if not ev.executed:
                        continue
                    if ev.final_status not in ("win", "loss"):
                        continue
                    sid = ev.mobile_signal_id
                    if sid in self._closed_logged:
                        continue

                    pnl = self._estimate_pnl(ev)
                    reason = "TAKE_PROFIT" if ev.final_status == "win" else "STOP_LOSS"
                    close_price = float(ev.tp if ev.final_status == "win" else ev.sl or 0)

                    self.log_closed_trade(
                        signal_id=sid,
                        symbol=ev.symbol,
                        trade_type=ev.signal_type,
                        entry_price=float(ev.entry or 0),
                        close_price=close_price,
                        sl_price=float(ev.sl or 0),
                        tp_price=float(ev.tp or 0),
                        pnl=pnl,
                        lot_size=0.01,
                        close_reason=reason,
                        strategy=ev.strategy,
                    )
        except Exception as e:
            logger.debug(f"[MobileStore] sync closed trades: {e}")

    @staticmethod
    def _estimate_pnl(ev) -> float:
        """Estima P&L en EUR usando MT5 si hay posición; si no, por movimiento de precio."""
        try:
            import MetaTrader5 as mt5

            positions = mt5.positions_get(symbol=ev.symbol)
            if positions:
                return float(sum(p.profit for p in positions))
        except Exception:
            pass
        # Fallback: % del riesgo configurado sobre balance MT5
        try:
            import MetaTrader5 as mt5

            info = mt5.account_info()
            balance = float(info.balance) if info else 5000.0
        except Exception:
            balance = 5000.0
        risk_pct = float(os.getenv("MT5_RISK_PCT", "0.5")) / 100.0
        risk_eur = balance * risk_pct
        if ev.final_status == "win" and ev.entry and ev.sl and ev.tp:
            risk = abs(ev.entry - ev.sl)
            rr = abs(ev.tp - ev.entry) / risk if risk > 0 else 1.0
            return risk_eur * rr
        return -risk_eur


_store: Optional[MobileStore] = None


def get_mobile_store(db_path: str = _DEFAULT_DB) -> MobileStore:
    global _store
    if _store is None:
        _store = MobileStore(db_path)
    return _store
