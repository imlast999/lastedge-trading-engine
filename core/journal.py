"""
Trade Journal — core/journal.py

Registra el historial completo de operaciones con todos los metadatos relevantes:
  - Estrategia usada
  - Score de confianza en el momento de la señal
  - Condiciones de mercado al entrar
  - Duración del trade
  - Resultado y P&L

Usa la misma BD (bot_state.db) que el resto del bot para no fragmentar datos.
La tabla se crea automáticamente si no existe (migración idempotente).

Uso:
    from core.journal import get_journal
    journal = get_journal()
    trade_id = journal.log_entry(signal, score=0.78, market_conditions={...})
    journal.log_close(trade_id, result='WIN', pnl=23.5, close_price=1.0920)
    report = journal.get_report(days=30, symbol='EURUSD')
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Ruta a la BD principal del bot
_DEFAULT_DB = os.getenv(
    'TRADING_DB_PATH',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'bot_state.db')
)

# DDL de la tabla — idempotente
_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS trade_journal (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Identificación
    symbol          TEXT    NOT NULL,
    strategy        TEXT    NOT NULL,
    signal_type     TEXT    NOT NULL,   -- BUY | SELL
    mode            TEXT    NOT NULL DEFAULT 'live',  -- live (MT5 demo/real)

    -- Precios
    entry_price     REAL    NOT NULL,
    sl_price        REAL    NOT NULL,
    tp_price        REAL    NOT NULL,
    lot_size        REAL,

    -- Scoring en el momento de la señal
    confidence      TEXT,               -- HIGH | MEDIUM-HIGH | MEDIUM | LOW
    confidence_score REAL,              -- 0.0 – 1.0
    signal_score    REAL,               -- score del FlexibleScoring

    -- Condiciones de mercado al entrar (JSON)
    market_conditions TEXT,             -- {"atr": ..., "trend": ..., "volatility_ratio": ...}

    -- Sesión de mercado
    market_session  TEXT,               -- london | newyork | overlap | asian | night | always

    -- MT5 ticket (si se ejecutó en live/paper con MT5)
    mt5_ticket      INTEGER,

    -- Timestamps
    entry_time      TEXT    NOT NULL,
    close_time      TEXT,

    -- Resultado
    result          TEXT,               -- WIN | LOSS | BREAKEVEN | PENDING | REJECTED | FAILED
    close_price     REAL,
    pnl_pips        REAL,               -- pips netos (incluye costes)
    pnl_eur         REAL,               -- P&L en EUR/USD según balance

    -- Notas libres
    notes           TEXT,

    -- Execution Quality & Telemetry (P1.1)
    requested_price REAL,
    executed_price  REAL,
    slippage_pips   REAL,               -- Slippage con signo (positivo = adverso, negativo = favorable)
    slippage_cost_eur REAL,             -- Impacto financiero en EUR
    spread_open_pips REAL,              -- Spread al abrir
    spread_close_pips REAL,             -- Spread al cerrar
    max_allowed_spread_pips REAL,       -- Límite de spread de la estrategia
    latency_ms      INTEGER,            -- Latencia total ida y vuelta
    fill_time_ms    INTEGER,            -- Tiempo de llenado por el bróker
    execution_session TEXT,             -- LONDON | NEWYORK | OVERLAP | ASIAN | NIGHT
    execution_status TEXT DEFAULT 'SUCCESS', -- SUCCESS | REJECTED | FAILED | RETRIED
    execution_error TEXT,               -- Mensaje de error si falla
    mt5_retcode     INTEGER,            -- Código retcode de MT5 (10009, 10015, etc.)
    broker_message  TEXT,

    -- Telemetría de Cierre
    close_requested_price REAL,
    close_executed_price  REAL,
    close_slippage_pips   REAL,
    close_latency_ms      INTEGER,
    commission            REAL,
    swap                  REAL,

    created_at      TEXT DEFAULT (datetime('now'))
);
"""

_CREATE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_journal_symbol_time
    ON trade_journal (symbol, entry_time);
"""


# ── Clase principal ───────────────────────────────────────────────────────────

class TradeJournal:
    """
    Journal de operaciones con backend SQLite.

    Thread-safe: cada operación abre y cierra su propia conexión.
    """

    def __init__(self, db_path: str = _DEFAULT_DB):
        self.db_path = db_path
        self._ensure_table()

    @contextmanager
    def _conn(self):
        from services.database import get_database_manager
        with get_database_manager(self.db_path).get_connection() as conn:
            yield conn

    def _ensure_table(self):
        """Crea la tabla si no existe (migración idempotente sin romper esquemas)."""
        try:
            with self._conn() as conn:
                conn.execute(_CREATE_TABLE)
                conn.execute(_CREATE_INDEX)
                
                # Migración segura utilizando PRAGMA table_info
                existing_cols = {row['name'] for row in conn.execute("PRAGMA table_info(trade_journal)").fetchall()}
                new_columns = [
                    ("requested_price", "REAL"),
                    ("executed_price", "REAL"),
                    ("slippage_pips", "REAL"),
                    ("slippage_cost_eur", "REAL"),
                    ("spread_open_pips", "REAL"),
                    ("spread_close_pips", "REAL"),
                    ("max_allowed_spread_pips", "REAL"),
                    ("latency_ms", "INTEGER"),
                    ("fill_time_ms", "INTEGER"),
                    ("execution_session", "TEXT"),
                    ("execution_status", "TEXT"),
                    ("execution_error", "TEXT"),
                    ("mt5_retcode", "INTEGER"),
                    ("broker_message", "TEXT"),
                    ("close_requested_price", "REAL"),
                    ("close_executed_price", "REAL"),
                    ("close_slippage_pips", "REAL"),
                    ("close_latency_ms", "INTEGER"),
                    ("commission", "REAL"),
                    ("swap", "REAL"),
                ]
                for col_name, col_type in new_columns:
                    if col_name not in existing_cols:
                        try:
                            conn.execute(f"ALTER TABLE trade_journal ADD COLUMN {col_name} {col_type};")
                        except sqlite3.OperationalError as err:
                            logger.debug(f"[Journal] Nota de migración de columna {col_name}: {err}")
                    
        except Exception as e:
            logger.error(f"[Journal] Error creando tabla o migrando: {e}")

    # ── Escritura ─────────────────────────────────────────────────────────────

    def log_entry(
        self,
        signal: Dict,
        *,
        score: float = 0.0,
        confidence: str = 'MEDIUM',
        confidence_score: float = 0.0,
        market_conditions: Optional[Dict] = None,
        market_session: str = '',
        lot_size: float = 0.0,
        mt5_ticket: Optional[int] = None,
        mode: str = 'live',
        notes: str = '',
        requested_price: Optional[float] = None,
        executed_price: Optional[float] = None,
        slippage_pips: Optional[float] = None,
        slippage_cost_eur: Optional[float] = None,
        spread_open_pips: Optional[float] = None,
        max_allowed_spread_pips: Optional[float] = None,
        latency_ms: Optional[int] = None,
        fill_time_ms: Optional[int] = None,
        execution_session: Optional[str] = None,
        execution_status: str = 'SUCCESS',
        execution_error: Optional[str] = None,
        mt5_retcode: Optional[int] = None,
        broker_message: Optional[str] = None,
    ) -> int:
        """
        Registra la apertura de un trade (o un intento de orden fallida/rechazada).
        """
        symbol   = str(signal.get('symbol', 'UNKNOWN')).upper()
        sig_type = str(signal.get('type', 'BUY')).upper()
        strategy = str(signal.get('strategy_used') or signal.get('strategy') or 'unknown')
        entry    = float(signal.get('entry', 0.0))
        sl       = float(signal.get('sl', 0.0))
        tp       = float(signal.get('tp', 0.0))

        mc_json = json.dumps(market_conditions or {}, ensure_ascii=False)
        now_iso = datetime.now(timezone.utc).isoformat()
        initial_result = 'PENDING' if execution_status == 'SUCCESS' else execution_status

        try:
            with self._conn() as conn:
                cur = conn.execute(
                    """
                    INSERT INTO trade_journal
                        (symbol, strategy, signal_type, mode,
                         entry_price, sl_price, tp_price, lot_size,
                         confidence, confidence_score, signal_score,
                         market_conditions, market_session,
                         mt5_ticket, entry_time, result, notes,
                         requested_price, executed_price, slippage_pips, slippage_cost_eur,
                         spread_open_pips, max_allowed_spread_pips, latency_ms, fill_time_ms,
                         execution_session, execution_status, execution_error, mt5_retcode, broker_message)
                    VALUES
                        (?, ?, ?, ?,
                         ?, ?, ?, ?,
                         ?, ?, ?,
                         ?, ?,
                         ?, ?, ?, ?,
                         ?, ?, ?, ?,
                         ?, ?, ?, ?,
                         ?, ?, ?, ?, ?)
                    """,
                    (symbol, strategy, sig_type, mode,
                     entry, sl, tp, lot_size if lot_size else None,
                     confidence, confidence_score, score,
                     mc_json, market_session or execution_session or '',
                     mt5_ticket, now_iso, initial_result, notes,
                     requested_price, executed_price, slippage_pips, slippage_cost_eur,
                     spread_open_pips, max_allowed_spread_pips, latency_ms, fill_time_ms,
                     execution_session or market_session or '', execution_status, execution_error, mt5_retcode, broker_message),
                )
                trade_id = cur.lastrowid
                logger.debug(f"[Journal] Entry logged: id={trade_id} {symbol} {sig_type} status={execution_status}")
                return trade_id
        except Exception as e:
            logger.error(f"[Journal] Error en log_entry: {e}")
            return -1

    def log_close(
        self,
        trade_id: int,
        *,
        result: str,
        close_price: float = 0.0,
        pnl_pips: float = 0.0,
        pnl_eur: float = 0.0,
        notes: str = '',
        spread_close_pips: Optional[float] = None,
        close_requested_price: Optional[float] = None,
        close_executed_price: Optional[float] = None,
        close_slippage_pips: Optional[float] = None,
        close_latency_ms: Optional[int] = None,
        commission: Optional[float] = None,
        swap: Optional[float] = None,
    ) -> bool:
        """
        Actualiza el cierre de un trade con telemetría de salida.
        """
        close_iso = datetime.now(timezone.utc).isoformat()
        try:
            with self._conn() as conn:
                conn.execute(
                    """
                    UPDATE trade_journal
                    SET result=?, close_price=?, pnl_pips=?, pnl_eur=?,
                        spread_close_pips=?, close_requested_price=?, close_executed_price=?,
                        close_slippage_pips=?, close_latency_ms=?, commission=?, swap=?,
                        close_time=?, notes = CASE WHEN notes='' THEN ? ELSE notes||' | '||? END
                    WHERE id=?
                    """,
                    (result.upper(), close_price, pnl_pips, pnl_eur,
                     spread_close_pips, close_requested_price, close_executed_price,
                     close_slippage_pips, close_latency_ms, commission, swap,
                     close_iso, notes, notes, trade_id),
                )
                logger.debug(f"[Journal] Close logged: id={trade_id} result={result} pnl={pnl_pips:.1f}p")
                return True
        except Exception as e:
            logger.error(f"[Journal] Error en log_close: {e}")
            return False

    def close_matching_pending(
        self,
        symbol: str,
        *,
        entry_price: float,
        close_price: float,
        result: str,
        pnl_pips: float = 0.0,
        pnl_eur: float = 0.0,
        mt5_ticket: Optional[int] = None,
        notes: str = '',
        spread_close_pips: Optional[float] = None,
        close_slippage_pips: Optional[float] = None,
        close_latency_ms: Optional[int] = None,
    ) -> bool:
        """Cierra el trade PENDING que coincida por ticket MT5 o por entrada."""
        try:
            with self._conn() as conn:
                if mt5_ticket:
                    row = conn.execute(
                        """SELECT id FROM trade_journal
                           WHERE mt5_ticket=? AND result='PENDING'
                           ORDER BY id DESC LIMIT 1""",
                        (mt5_ticket,),
                    ).fetchone()
                else:
                    row = conn.execute(
                        """SELECT id FROM trade_journal
                           WHERE symbol=? AND result='PENDING'
                             AND ABS(entry_price - ?) < 0.00001
                           ORDER BY id DESC LIMIT 1""",
                        (symbol.upper(), entry_price),
                    ).fetchone()
                if not row:
                    return False
                trade_id = row[0]
            return self.log_close(
                trade_id,
                result=result,
                close_price=close_price,
                pnl_pips=pnl_pips,
                pnl_eur=pnl_eur,
                notes=notes,
                spread_close_pips=spread_close_pips,
                close_slippage_pips=close_slippage_pips,
                close_latency_ms=close_latency_ms,
            )
        except Exception as e:
            logger.error(f"[Journal] close_matching_pending: {e}")
            return False

    # ── Lectura y estadísticas ────────────────────────────────────────────────

    def get_summary(
        self,
        days: int = 30,
        symbol: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> Dict:
        """Alias para get_report para compatibilidad con verificadores de producción."""
        return self.get_report(days=days, symbol=symbol, mode=mode)

    def get_report(
        self,
        days: int = 30,
        symbol: Optional[str] = None,
        mode: Optional[str] = None,
    ) -> Dict:
        """
        Genera un reporte de rendimiento del journal.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() if days > 0 else '2000-01-01'

        conditions = ["entry_time >= ?"]
        params: list = [cutoff]
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper())
        if mode:
            conditions.append("mode = ?")
            params.append(mode)

        where = " AND ".join(conditions)

        try:
            with self._conn() as conn:
                rows = conn.execute(
                    f"SELECT * FROM trade_journal WHERE {where} ORDER BY entry_time DESC",
                    params,
                ).fetchall()
        except Exception as e:
            logger.error(f"[Journal] Error en get_report: {e}")
            return {'error': str(e)}

        if not rows:
            return {
                'period_days': days,
                'symbol': symbol or 'ALL',
                'total_trades': 0,
                'message': 'No hay trades en el período especificado.',
            }

        closed  = [r for r in rows if r['result'] in ('WIN', 'LOSS', 'BREAKEVEN')]
        wins    = [r for r in closed if r['result'] == 'WIN']
        losses  = [r for r in closed if r['result'] == 'LOSS']

        # Winrate
        wr = (len(wins) / len(closed) * 100) if closed else 0.0

        # P&L
        total_pnl_pips = sum(r['pnl_pips'] or 0.0 for r in closed)
        total_pnl_eur  = sum(r['pnl_eur']  or 0.0 for r in closed)

        # Profit factor
        gross_wins  = sum(r['pnl_pips'] or 0 for r in wins)
        gross_loss  = abs(sum(r['pnl_pips'] or 0 for r in losses))
        pf = round(gross_wins / gross_loss, 2) if gross_loss > 0 else (
            float('inf') if gross_wins > 0 else 0.0
        )

        # Duración media
        durations = []
        for r in closed:
            if r['entry_time'] and r['close_time']:
                try:
                    t0 = datetime.fromisoformat(r['entry_time'].replace('Z', '+00:00'))
                    t1 = datetime.fromisoformat(r['close_time'].replace('Z', '+00:00'))
                    durations.append((t1 - t0).total_seconds() / 60)
                except Exception:
                    pass
        avg_duration_min = sum(durations) / len(durations) if durations else 0.0

        # Confianza media
        scores = [r['confidence_score'] for r in rows if r['confidence_score'] is not None]
        avg_score = sum(scores) / len(scores) if scores else 0.0

        # Por símbolo
        symbols: Dict[str, Dict] = {}
        for r in closed:
            sym = r['symbol']
            if sym not in symbols:
                symbols[sym] = {'total': 0, 'wins': 0, 'pnl_pips': 0.0}
            symbols[sym]['total'] += 1
            if r['result'] == 'WIN':
                symbols[sym]['wins'] += 1
            symbols[sym]['pnl_pips'] += r['pnl_pips'] or 0.0
        for sym in symbols:
            t = symbols[sym]['total']
            symbols[sym]['winrate'] = round(symbols[sym]['wins'] / t * 100, 1) if t else 0.0

        # Por estrategia
        strategies: Dict[str, Dict] = {}
        for r in closed:
            strat = r['strategy'] or 'unknown'
            if strat not in strategies:
                strategies[strat] = {'total': 0, 'wins': 0, 'pnl_pips': 0.0}
            strategies[strat]['total'] += 1
            if r['result'] == 'WIN':
                strategies[strat]['wins'] += 1
            strategies[strat]['pnl_pips'] += r['pnl_pips'] or 0.0
        for strat in strategies:
            t = strategies[strat]['total']
            strategies[strat]['winrate'] = round(strategies[strat]['wins'] / t * 100, 1) if t else 0.0

        return {
            'period_days':       days,
            'symbol':            symbol or 'ALL',
            'total_trades':      len(rows),
            'closed_trades':     len(closed),
            'pending_trades':    len(rows) - len(closed),
            'wins':              len(wins),
            'losses':            len(losses),
            'winrate':           round(wr, 1),
            'profit_factor':     pf,
            'total_pnl_pips':    round(total_pnl_pips, 1),
            'total_pnl_eur':     round(total_pnl_eur, 2),
            'avg_duration_min':  round(avg_duration_min, 0),
            'avg_confidence_score': round(avg_score, 3),
            'by_symbol':         symbols,
            'by_strategy':       strategies,
        }

    def get_execution_quality_summary(self, days: int = 30) -> Dict:
        """
        Calcula estadísticas completas de Calidad de Ejecución (P1.1).
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() if days > 0 else '2000-01-01'
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM trade_journal WHERE entry_time >= ? ORDER BY entry_time DESC",
                    (cutoff,),
                ).fetchall()
        except Exception as e:
            logger.error(f"[Journal] Error en get_execution_quality_summary: {e}")
            return {}

        if not rows:
            return {
                'total_orders': 0,
                'avg_latency_ms': 0.0,
                'avg_slippage_pips': 0.0,
                'avg_spread_pips': 0.0,
                'favorable_slippage_pct': 0.0,
                'rejection_rate_pct': 0.0,
            }

        latencies = [r['latency_ms'] for r in rows if r['latency_ms'] is not None]
        slippages = [r['slippage_pips'] for r in rows if r['slippage_pips'] is not None]
        spreads   = [r['spread_open_pips'] for r in rows if r['spread_open_pips'] is not None]
        statuses  = [r['execution_status'] for r in rows if r['execution_status']]

        total_orders = len(rows)
        rejected = sum(1 for s in statuses if s in ('REJECTED', 'FAILED'))
        favorable_slips = sum(1 for s in slippages if s < 0)

        return {
            'period_days': days,
            'total_orders': total_orders,
            'successful_orders': total_orders - rejected,
            'rejected_orders': rejected,
            'rejection_rate_pct': round((rejected / total_orders * 100), 1) if total_orders else 0.0,
            'avg_latency_ms': round(sum(latencies) / len(latencies), 1) if latencies else 0.0,
            'max_latency_ms': max(latencies) if latencies else 0,
            'avg_slippage_pips': round(sum(slippages) / len(slippages), 2) if slippages else 0.0,
            'avg_spread_pips': round(sum(spreads) / len(spreads), 2) if spreads else 0.0,
            'favorable_slippage_pct': round((favorable_slips / len(slippages) * 100), 1) if slippages else 0.0,
            'total_slippage_cost_eur': round(sum(r['slippage_cost_eur'] or 0.0 for r in rows), 2),
        }

    def get_recent_trades(self, limit: int = 10, symbol: Optional[str] = None) -> List[Dict]:
        """Devuelve los N trades más recientes como lista de dicts."""
        conditions = []
        params: list = []
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper())
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)
        try:
            with self._conn() as conn:
                rows = conn.execute(
                    f"SELECT * FROM trade_journal {where} ORDER BY entry_time DESC LIMIT ?",
                    params,
                ).fetchall()
            return [dict(r) for r in rows]
        except Exception as e:
            logger.error(f"[Journal] Error en get_recent_trades: {e}")
            return []

    def count_closed_trades(self, symbol: Optional[str] = None, mode: str = 'live') -> int:
        """Cuenta trades cerrados (WIN+LOSS) para verificar criterio de go-live (≥ 50)."""
        conditions = ["result IN ('WIN','LOSS')", "mode = ?"]
        params: list = [mode]
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol.upper())
        where = " AND ".join(conditions)
        try:
            with self._conn() as conn:
                row = conn.execute(
                    f"SELECT COUNT(*) FROM trade_journal WHERE {where}", params
                ).fetchone()
            return row[0] if row else 0
        except Exception as e:
            logger.error(f"[Journal] Error en count_closed_trades: {e}")
            return 0


# ── Instancia global ──────────────────────────────────────────────────────────

_journal: Optional[TradeJournal] = None


def get_journal(db_path: str = _DEFAULT_DB) -> TradeJournal:
    """Obtiene la instancia global del journal (singleton)."""
    global _journal
    if _journal is None:
        _journal = TradeJournal(db_path)
    return _journal

