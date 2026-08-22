"""
Tests para P4 Observabilidad (Execution Analytics & Health Monitor)
===================================================================
Verifica las métricas de calidad de ejecución del bróker, desgloses por sesión/símbolo,
score de bróker y telemetría de salud de proceso/BD/MT5.
"""

from __future__ import annotations

import os
import unittest
import tempfile
from datetime import datetime, timezone

from services.database import get_database_manager
from services.execution_analytics import ExecutionAnalyticsService, get_execution_analytics_service
from services.health_monitor import HealthMonitorService, get_health_monitor_service
from services.bot_service import BotService


class TestObservabilityP4(unittest.TestCase):

    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.db_path = self.tmp_db.name
        self.db_manager = get_database_manager(self.db_path)

        # Inicializar esquemas en BD temporal
        with self.db_manager.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    entry_price REAL,
                    sl_price REAL,
                    tp_price REAL,
                    lot_size REAL,
                    latency_ms INTEGER,
                    fill_time_ms INTEGER,
                    slippage_pips REAL,
                    slippage_cost_eur REAL,
                    spread_open_pips REAL,
                    spread_close_pips REAL,
                    execution_session TEXT,
                    execution_status TEXT DEFAULT 'SUCCESS',
                    mt5_retcode INTEGER,
                    entry_time TEXT NOT NULL
                );
            """)
            # Insertar datos de prueba
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                INSERT INTO trade_journal (symbol, strategy, signal_type, entry_price, sl_price, tp_price, lot_size, latency_ms, fill_time_ms, slippage_pips, slippage_cost_eur, spread_open_pips, execution_session, execution_status, mt5_retcode, entry_time)
                VALUES ('EURUSD', 'eurusd_trend', 'BUY', 1.0850, 1.0820, 1.0910, 0.10, 85, 40, 0.2, 2.0, 1.1, 'LONDON', 'SUCCESS', 10009, ?);
            """, (now_iso,))
            conn.execute("""
                INSERT INTO trade_journal (symbol, strategy, signal_type, entry_price, sl_price, tp_price, lot_size, latency_ms, fill_time_ms, slippage_pips, slippage_cost_eur, spread_open_pips, execution_session, execution_status, mt5_retcode, entry_time)
                VALUES ('XAUUSD', 'xauusd_breakout', 'SELL', 2350.0, 2360.0, 2330.0, 0.05, 140, 60, 0.5, 5.0, 2.5, 'NEWYORK', 'SUCCESS', 10009, ?);
            """, (now_iso,))

        self.analytics_svc = ExecutionAnalyticsService(self.db_path)
        self.health_svc = HealthMonitorService(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    def test_execution_analytics_metrics(self):
        metrics = self.analytics_svc.get_execution_metrics(days=30)
        self.assertEqual(metrics['total_orders'], 2)
        self.assertEqual(metrics['successful_orders'], 2)
        self.assertEqual(metrics['fill_rate_pct'], 100.0)
        self.assertGreater(metrics['avg_latency_ms'], 0)
        self.assertGreater(metrics['broker_quality_score'], 80.0)
        self.assertIn('EURUSD', metrics['symbol_breakdown'])
        self.assertIn('LONDON', metrics['session_breakdown'])

    def test_execution_analytics_symbol_filter(self):
        metrics = self.analytics_svc.get_execution_metrics(days=30, symbol='EURUSD')
        self.assertEqual(metrics['total_orders'], 1)
        self.assertEqual(metrics['symbol_filter'], 'EURUSD')

    def test_health_monitor_report(self):
        report = self.health_svc.get_full_health_report()
        self.assertIn('status', report)
        self.assertIn('process', report)
        self.assertIn('database', report)
        self.assertIn('mt5', report)
        self.assertGreaterEqual(report['process']['memory_mb'], 0.0)
        self.assertTrue(report['database']['exists'])

    def test_bot_service_observability_integration(self):
        bot_service = BotService()
        health = bot_service.get_health_status()
        self.assertTrue(health['ok'])
        self.assertIn('broker_quality', health)
        
        analytics = bot_service.get_execution_analytics(days=7)
        self.assertTrue(analytics['ok'])
        self.assertIn('analytics', analytics)


if __name__ == '__main__':
    unittest.main()
