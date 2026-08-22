"""
Tests para P5.7 — Production Monitoring Engine
===============================================
Verifica la auditoría de los 6 canales de observabilidad y la detección de puntos ciegos.
"""

from __future__ import annotations

import os
import unittest
import tempfile
from services.database import get_database_manager
from services.production_monitoring import (
    ProductionMonitoringService,
    get_production_monitoring_service,
)
from services.bot_service import BotService


class TestP57ProductionMonitoring(unittest.TestCase):

    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.db_path = self.tmp_db.name
        self.db_manager = get_database_manager(self.db_path)
        self.mon_svc = ProductionMonitoringService(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    def test_run_monitoring_audit_structure(self):
        report = self.mon_svc.run_monitoring_audit()

        self.assertIn("timestamp", report)
        self.assertIn("monitoring_status", report)
        self.assertIn("verdict_message", report)
        self.assertIn("observability_coverage_score", report)
        self.assertIn("summary", report)
        self.assertIn("channels", report)

        channels = report["channels"]
        self.assertEqual(len(channels), 6)

        expected_ids = [
            "DASHBOARD", "MOBILE_APP", "DISCORD",
            "TELEGRAM", "HEALTH_MONITOR", "EXECUTION_ANALYTICS"
        ]

        actual_ids = [c["channel_id"] for c in channels]
        for cid in expected_ids:
            self.assertIn(cid, actual_ids)

        for c in channels:
            self.assertIn(c["status"], ["PASS", "WARN", "FAIL"])
            self.assertGreaterEqual(c["coverage_pct"], 0.0)
            self.assertLessEqual(c["coverage_pct"], 100.0)

    def test_bot_service_production_monitoring_integration(self):
        bot_svc = BotService()
        report = bot_svc.run_production_monitoring_audit()
        self.assertIn("monitoring_status", report)
        self.assertEqual(len(report["channels"]), 6)


if __name__ == "__main__":
    unittest.main()
