"""
Tests para P5.2 — Automated Production Verification Engine
===========================================================
Verifica la ejecución automatizada de pruebas sobre los 11 subsistemas críticos.
"""

from __future__ import annotations

import os
import unittest
import tempfile
from services.database import get_database_manager
from services.production_verifier import ProductionVerifierService, get_production_verifier_service
from services.bot_service import BotService


class TestP52ProductionVerifier(unittest.TestCase):

    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.db_path = self.tmp_db.name
        self.db_manager = get_database_manager(self.db_path)

        with self.db_manager.get_connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS session_stats (id INTEGER PRIMARY KEY);")

        self.verifier_svc = ProductionVerifierService(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    def test_verify_all_subsystems_structure(self):
        report = self.verifier_svc.verify_all_subsystems()
        self.assertIn("timestamp", report)
        self.assertIn("verification_passed", report)
        self.assertIn("summary", report)
        self.assertIn("subsystems", report)

        subsystems = report["subsystems"]
        self.assertEqual(len(subsystems), 11)

        expected_names = [
            "Database", "MT5", "Risk Engine", "Trade Journal",
            "Notification Dispatcher", "Dashboard", "Mobile API",
            "Discord", "Telegram", "Execution Analytics", "Research Database"
        ]

        actual_names = [s["subsystem"] for s in subsystems]
        for name in expected_names:
            self.assertIn(name, actual_names)

        for s in subsystems:
            self.assertIn(s["status"], ["VERIFIED", "DEGRADED", "FAILED"])
            self.assertGreaterEqual(s["latency_ms"], 0.0)

    def test_bot_service_verification_integration(self):
        bot_svc = BotService()
        report = bot_svc.run_production_verification()
        self.assertIn("verification_passed", report)
        self.assertEqual(len(report["subsystems"]), 11)


if __name__ == "__main__":
    unittest.main()
