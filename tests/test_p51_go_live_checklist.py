"""
Tests para P5.1 — Go-Live Pre-Production Checklist
===================================================
Verifica las 17 comprobaciones del servicio GoLiveChecklistService.
"""

from __future__ import annotations

import os
import unittest
import tempfile
from services.database import get_database_manager
from services.go_live_checklist import GoLiveChecklistService, get_go_live_checklist_service
from services.bot_service import BotService


class TestP51GoLiveChecklist(unittest.TestCase):

    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.db_path = self.tmp_db.name
        self.db_manager = get_database_manager(self.db_path)

        # Crear esquema básico de BD
        with self.db_manager.get_connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS session_stats (id INTEGER PRIMARY KEY);")

        self.checklist_svc = GoLiveChecklistService(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    def test_run_checklist_structure(self):
        report = self.checklist_svc.run_checklist()
        self.assertIn("timestamp", report)
        self.assertIn("ready_to_trade", report)
        self.assertIn("summary", report)
        self.assertIn("checks", report)

        summary = report["summary"]
        self.assertEqual(summary["total_checks"], 17)
        self.assertGreaterEqual(summary["passed"] + summary["warnings"] + summary["failed"], 17)

    def test_checks_returned_fields(self):
        report = self.checklist_svc.run_checklist()
        checks = report["checks"]
        check_ids = [c["id"] for c in checks]

        # Verificar presencia de los 17 IDs requeridos
        expected_ids = [
            "mt5_connection", "trading_account", "expected_broker", "market_open",
            "risk_config", "circuit_breaker", "autosignals_config", "database_availability",
            "dashboard_availability", "mobile_api_availability", "discord_connectivity",
            "telegram_connectivity", "research_db_availability", "environment_variables",
            "disk_space", "clock_sync", "runtime_errors"
        ]

        for req_id in expected_ids:
            self.assertIn(req_id, check_ids)

        for c in checks:
            self.assertIn(c["status"], ["PASS", "WARN", "FAIL"])
            self.assertTrue(len(c["message"]) > 0)

    def test_bot_service_integration(self):
        bot_svc = BotService()
        report = bot_svc.run_go_live_checklist()
        self.assertIn("ready_to_trade", report)
        self.assertEqual(len(report["checks"]), 17)

    def test_circuit_breaker_tripped_behavior(self):
        """Verifica que si el Circuit Breaker está DISPARADO, la comprobación devuelve FAIL y ready_to_trade es False."""
        class MockBotServiceTripped:
            def get_system_status(self):
                return {"circuit_breaker": {"state": "TRIPPED", "reason": "Max Daily Drawdown Reached"}}

        mock_bot = MockBotServiceTripped()
        report = self.checklist_svc.run_checklist(bot_service=mock_bot)

        cb_check = next(c for c in report["checks"] if c["id"] == "circuit_breaker")
        self.assertEqual(cb_check["status"], "FAIL")
        self.assertFalse(report["ready_to_trade"])
        self.assertGreaterEqual(report["summary"]["failed"], 1)


if __name__ == "__main__":
    unittest.main()
