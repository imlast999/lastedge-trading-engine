"""
Tests para P5.5 — Stability Verification Engine
===============================================
Verifica la inspección automatizada de los 9 factores de estabilidad de tiempo de ejecución.
"""

from __future__ import annotations

import os
import unittest
import tempfile
from services.database import get_database_manager
from services.stability_verification import (
    StabilityVerificationService,
    get_stability_verification_service,
)
from services.bot_service import BotService


class TestP55StabilityVerification(unittest.TestCase):

    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.db_path = self.tmp_db.name
        self.db_manager = get_database_manager(self.db_path)
        self.stab_svc = StabilityVerificationService(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    def test_run_stability_audit_structure(self):
        report = self.stab_svc.run_stability_audit()

        self.assertIn("timestamp", report)
        self.assertIn("stability_status", report)
        self.assertIn("verdict_message", report)
        self.assertIn("stability_index_score", report)
        self.assertIn("summary", report)
        self.assertIn("checks", report)

        checks = report["checks"]
        self.assertEqual(len(checks), 9)

        expected_ids = [
            "MEMORY_LEAKS", "FILE_HANDLE_LEAKS", "SOCKET_LEAKS",
            "ORPHAN_ASYNCIO_TASKS", "SILENT_EXCEPTIONS", "THREAD_DEADLOCKS",
            "SQLITE_LOCKING", "RACE_CONDITIONS", "INFINITE_RECONNECTION_LOOPS"
        ]

        actual_ids = [c["check_id"] for c in checks]
        for cid in expected_ids:
            self.assertIn(cid, actual_ids)

        for c in checks:
            self.assertIn(c["status"], ["PASS", "WARN", "FAIL"])
            self.assertGreaterEqual(c["latency_ms"], 0.0)

    def test_bot_service_stability_verification_integration(self):
        bot_svc = BotService()
        report = bot_svc.run_stability_verification()
        self.assertIn("stability_status", report)
        self.assertEqual(len(report["checks"]), 9)


if __name__ == "__main__":
    unittest.main()
