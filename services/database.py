"""
Servicio de Base de Datos y DatabaseManager (P3.1 Technical Consolidation)
==========================================================================
Punto de acceso unificado, thread-safe y optimizado para SQLite (`bot_state.db`).
Implementa modo WAL (Write-Ahead Logging), busy timeout, manejo seguro de contextos
y eliminación total de "database is locked" y fugas de recursos.
"""

from __future__ import annotations

import os
import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional, Generator

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = os.getenv(
    'TRADING_DB_PATH',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bot_state.db')
)


class DatabaseManager:
    """
    Gestor centralizado de conexiones SQLite con soporte para WAL Mode y Context Manager.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self.db_path = db_path
        self._ensure_wal_mode()

    def _ensure_wal_mode(self) -> None:
        """Configura WAL mode y pragmas de optimización al inicializar."""
        try:
            with sqlite3.connect(self.db_path, timeout=30.0) as conn:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA busy_timeout=10000;")
                conn.execute("PRAGMA synchronous=NORMAL;")
        except Exception as e:
            logger.warning(f"[DatabaseManager] No se pudo configurar WAL mode en {self.db_path}: {e}")

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context Manager seguro para obtener conexiones de SQLite.
        Asegura commit automático al salir, rollback en caso de error y cierre estricto de la conexión.
        """
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=10000;")
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"[DatabaseManager] Error en transacción SQLite: {e}")
            raise
        finally:
            conn.close()


class DatabaseService:
    """Servicio para operaciones de base de datos del bot."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH):
        self.db_manager = DatabaseManager(db_path)
        self.db_path = db_path
        self.init_db()

    def init_db(self) -> None:
        """Inicializa las tablas básicas del bot."""
        with self.db_manager.get_connection() as conn:
            c = conn.cursor()
            c.execute('CREATE TABLE IF NOT EXISTS autosignals(state INTEGER)')
            c.execute('CREATE TABLE IF NOT EXISTS last_auto_sent(symbol TEXT PRIMARY KEY, time TEXT, type TEXT, entry REAL, sl REAL, tp REAL)')
            c.execute("CREATE TABLE IF NOT EXISTS trades_counter(date TEXT PRIMARY KEY, count INTEGER)")
            c.execute("""
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

        # Inicialización de tablas de la app móvil
        try:
            from services.mobile_store import get_mobile_store
            get_mobile_store(self.db_path).ensure_tables()
        except Exception as e:
            logger.debug(f"Mobile tables init: {e}")

    def load_state(self, state_obj: Any) -> None:
        """Carga el estado desde la base de datos."""
        with self.db_manager.get_connection() as conn:
            c = conn.cursor()

            # Cargar autosignals state
            c.execute('SELECT state FROM autosignals LIMIT 1')
            r = c.fetchone()
            if r is not None:
                state_obj.autosignals = bool(r[0])

            # Cargar trades_today para hoy (UTC)
            today = datetime.now(timezone.utc).date().isoformat()
            c.execute('SELECT count FROM trades_counter WHERE date=?', (today,))
            tr = c.fetchone()
            if tr is not None:
                state_obj.trades_today = int(tr[0])
            else:
                state_obj.trades_today = 0

            # Cargar last_auto_sent
            c.execute('SELECT symbol,time,type,entry,sl,tp FROM last_auto_sent')
            rows = c.fetchall()
            for row in rows:
                sym, time_s, t, entry, sl, tp = row[0], row[1], row[2], row[3], row[4], row[5]
                try:
                    time_dt = datetime.fromisoformat(time_s)
                except Exception:
                    time_dt = datetime.now(timezone.utc)
                state_obj.last_auto_sent[sym] = {'time': time_dt, 'sig': (t, entry, sl, tp)}

    def save_autosignals_state(self, value: bool) -> None:
        """Guarda el estado de autosignals."""
        with self.db_manager.get_connection() as conn:
            c = conn.cursor()
            c.execute('DELETE FROM autosignals')
            c.execute('INSERT INTO autosignals(state) VALUES(?)', (1 if value else 0,))

    def save_last_auto_sent(self, symbol: str, time_dt: datetime, sig_tuple: Tuple) -> None:
        """Guarda la última señal automática enviada."""
        with self.db_manager.get_connection() as conn:
            c = conn.cursor()
            c.execute(
                'INSERT OR REPLACE INTO last_auto_sent(symbol,time,type,entry,sl,tp) VALUES(?,?,?,?,?,?)',
                (symbol, time_dt.isoformat(), sig_tuple[0], float(sig_tuple[1]), float(sig_tuple[2]), float(sig_tuple[3]))
            )

    def save_trades_today(self, count: int) -> None:
        """Guarda el contador de trades de hoy."""
        with self.db_manager.get_connection() as conn:
            c = conn.cursor()
            today = datetime.now(timezone.utc).date().isoformat()
            c.execute('INSERT OR REPLACE INTO trades_counter(date,count) VALUES(?,?)', (today, count))

    def reset_trades_today(self) -> None:
        """Resetea el contador de trades de hoy."""
        with self.db_manager.get_connection() as conn:
            c = conn.cursor()
            today = datetime.now(timezone.utc).date().isoformat()
            c.execute('INSERT OR REPLACE INTO trades_counter(date,count) VALUES(?,?)', (today, 0))


# Instancia global del DatabaseManager y DatabaseService
_db_manager: Optional[DatabaseManager] = None
_db_service: Optional[DatabaseService] = None


def get_database_manager(db_path: Optional[str] = None) -> DatabaseManager:
    """Obtiene la instancia del DatabaseManager."""
    global _db_manager
    if _db_manager is None or (db_path and _db_manager.db_path != db_path):
        path = db_path or _DEFAULT_DB_PATH
        _db_manager = DatabaseManager(path)
    return _db_manager


def get_database_service(db_path: Optional[str] = None) -> DatabaseService:
    """Obtiene la instancia global del servicio de base de datos."""
    global _db_service
    if _db_service is None or (db_path and _db_service.db_path != db_path):
        path = db_path or _DEFAULT_DB_PATH
        _db_service = DatabaseService(path)
    return _db_service


# Funciones de conveniencia para compatibilidad
def init_db():
    get_database_service().init_db()

def load_db_state(state_obj):
    get_database_service().load_state(state_obj)

def save_autosignals_state(value: bool):
    get_database_service().save_autosignals_state(value)

def save_last_auto_sent(symbol: str, time_dt: datetime, sig_tuple: Tuple):
    get_database_service().save_last_auto_sent(symbol, time_dt, sig_tuple)

def save_trades_today(count: int):
    get_database_service().save_trades_today(count)

def reset_trades_today():
    get_database_service().reset_trades_today()