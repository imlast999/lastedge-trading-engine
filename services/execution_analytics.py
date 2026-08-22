"""
Execution Analytics & Broker Quality Service (P4.1 Observability)
===================================================================
Servicio centralizado para análisis de calidad de ejecución, medición de latencia,
slippage, tasa de llenado (fill rate), desglose por sesión/símbolo y métricas de bróker.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone

from services.database import get_database_manager

logger = logging.getLogger(__name__)


class ExecutionAnalyticsService:
    """
    Servicio de análisis cuantitativo de calidad de ejecución de órdenes.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_manager = get_database_manager(db_path)

    def get_execution_metrics(self, days: int = 30, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Calcula métricas agregadas de ejecución para los últimos N días.
        """
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        
        where_clause = "WHERE entry_time >= ?"
        params: list[Any] = [cutoff_date]

        if symbol:
            where_clause += " AND symbol = ?"
            params.append(symbol.upper().strip())

        query = f"""
            SELECT
                COUNT(*) as total_orders,
                SUM(CASE WHEN execution_status = 'SUCCESS' THEN 1 ELSE 0 END) as successful_orders,
                SUM(CASE WHEN execution_status IN ('REJECTED', 'FAILED') THEN 1 ELSE 0 END) as rejected_orders,
                AVG(latency_ms) as avg_latency_ms,
                MIN(latency_ms) as min_latency_ms,
                MAX(latency_ms) as max_latency_ms,
                AVG(slippage_pips) as avg_slippage_pips,
                SUM(slippage_cost_eur) as total_slippage_cost_eur,
                AVG(spread_open_pips) as avg_spread_pips
            FROM trade_journal
            {where_clause}
        """

        with self.db_manager.get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            
            if not row or row['total_orders'] == 0:
                return {
                    'period_days': days,
                    'symbol_filter': symbol or 'ALL',
                    'total_orders': 0,
                    'fill_rate_pct': 100.0,
                    'rejection_rate_pct': 0.0,
                    'avg_latency_ms': 0.0,
                    'min_latency_ms': 0,
                    'max_latency_ms': 0,
                    'avg_slippage_pips': 0.0,
                    'total_slippage_cost_eur': 0.0,
                    'avg_spread_pips': 0.0,
                    'broker_quality_score': 100.0,
                    'retcodes_breakdown': {},
                    'session_breakdown': {},
                    'symbol_breakdown': {}
                }

            total = row['total_orders']
            success = row['successful_orders'] or 0
            rejected = row['rejected_orders'] or 0

            fill_rate = round((success / total) * 100.0, 2) if total > 0 else 0.0
            rejection_rate = round((rejected / total) * 100.0, 2) if total > 0 else 0.0
            avg_latency = round(float(row['avg_latency_ms'] or 0.0), 2)
            avg_slippage = round(float(row['avg_slippage_pips'] or 0.0), 3)

            # Cálculo de Broker Quality Score (0-100)
            quality_score = self._calculate_quality_score(fill_rate, avg_latency, avg_slippage)

            # Desglose por códigos MT5 (retcodes)
            retcodes_query = f"""
                SELECT mt5_retcode, COUNT(*) as count
                FROM trade_journal
                {where_clause} AND mt5_retcode IS NOT NULL
                GROUP BY mt5_retcode
            """
            retcodes_rows = conn.execute(retcodes_query, params).fetchall()
            retcodes_breakdown = {str(r['mt5_retcode']): r['count'] for r in retcodes_rows}

            # Desglose por sesión de mercado
            session_query = f"""
                SELECT execution_session, COUNT(*) as count, AVG(latency_ms) as avg_lat, AVG(slippage_pips) as avg_slip
                FROM trade_journal
                {where_clause} AND execution_session IS NOT NULL
                GROUP BY execution_session
            """
            session_rows = conn.execute(session_query, params).fetchall()
            session_breakdown = {
                r['execution_session']: {
                    'count': r['count'],
                    'avg_latency_ms': round(float(r['avg_lat'] or 0.0), 1),
                    'avg_slippage_pips': round(float(r['avg_slip'] or 0.0), 3)
                } for r in session_rows
            }

            # Desglose por símbolo (si es filtro global)
            symbol_breakdown = {}
            if not symbol:
                symbol_query = f"""
                    SELECT symbol, COUNT(*) as count, AVG(latency_ms) as avg_lat, AVG(slippage_pips) as avg_slip
                    FROM trade_journal
                    {where_clause}
                    GROUP BY symbol
                """
                symbol_rows = conn.execute(symbol_query, params).fetchall()
                symbol_breakdown = {
                    r['symbol']: {
                        'count': r['count'],
                        'avg_latency_ms': round(float(r['avg_lat'] or 0.0), 1),
                        'avg_slippage_pips': round(float(r['avg_slip'] or 0.0), 3)
                    } for r in symbol_rows
                }

            return {
                'period_days': days,
                'symbol_filter': symbol or 'ALL',
                'total_orders': total,
                'successful_orders': success,
                'rejected_orders': rejected,
                'fill_rate_pct': fill_rate,
                'rejection_rate_pct': rejection_rate,
                'avg_latency_ms': avg_latency,
                'min_latency_ms': row['min_latency_ms'] or 0,
                'max_latency_ms': row['max_latency_ms'] or 0,
                'avg_slippage_pips': avg_slippage,
                'total_slippage_cost_eur': round(float(row['total_slippage_cost_eur'] or 0.0), 2),
                'avg_spread_pips': round(float(row['avg_spread_pips'] or 0.0), 2),
                'broker_quality_score': quality_score,
                'retcodes_breakdown': retcodes_breakdown,
                'session_breakdown': session_breakdown,
                'symbol_breakdown': symbol_breakdown
            }

    def _calculate_quality_score(self, fill_rate: float, avg_latency: float, avg_slippage: float) -> float:
        """
        Calcula una puntuación objetiva de calidad del bróker (0.0 - 100.0).
        - Fill Rate (40% peso): 100% fill = 40 pts.
        - Latencia (40% peso): < 100ms = 40 pts, decrece linealmente hasta 1000ms.
        - Slippage adverso (20% peso): <= 0 pips = 20 pts, decrece si hay slippage adverso.
        """
        fill_score = (fill_rate / 100.0) * 40.0

        if avg_latency <= 100:
            lat_score = 40.0
        elif avg_latency >= 1000:
            lat_score = 0.0
        else:
            lat_score = 40.0 * (1.0 - (avg_latency - 100) / 900.0)

        if avg_slippage <= 0:
            slip_score = 20.0
        elif avg_slippage >= 3.0:
            slip_score = 0.0
        else:
            slip_score = 20.0 * (1.0 - (avg_slippage / 3.0))

        return round(max(0.0, min(100.0, fill_score + lat_score + slip_score)), 1)


# Instancia global del servicio
_execution_analytics_instance: Optional[ExecutionAnalyticsService] = None


def get_execution_analytics_service(db_path: Optional[str] = None) -> ExecutionAnalyticsService:
    global _execution_analytics_instance
    if _execution_analytics_instance is None or (db_path and _execution_analytics_instance.db_manager.db_path != db_path):
        _execution_analytics_instance = ExecutionAnalyticsService(db_path)
    return _execution_analytics_instance
