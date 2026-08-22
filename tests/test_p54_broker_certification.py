"""
Tests para P5.4 — Broker Certification Engine
=============================================
Verifica la ejecución de las 14 comprobaciones de certificación operativa
y la generación del dictamen global.
"""

from __future__ import annotations

import os
import unittest
import tempfile
from services.database import get_database_manager
from services.broker_certification import (
    BrokerCertificationService,
    get_broker_certification_service,
)
from services.bot_service import BotService


class TestP54BrokerCertification(unittest.TestCase):

    def setUp(self):
        self.tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp_db.close()
        self.db_path = self.tmp_db.name
        self.db_manager = get_database_manager(self.db_path)
        self.cert_svc = BrokerCertificationService(self.db_path)

    def tearDown(self):
        try:
            os.remove(self.db_path)
        except Exception:
            pass

    def test_run_certification_structure(self):
        report = self.cert_svc.run_certification()
        
        self.assertIn("timestamp", report)
        self.assertIn("certification_status", report)
        self.assertIn("verdict_message", report)
        self.assertIn("certification_score", report)
        self.assertIn("summary", report)
        self.assertIn("checks", report)

        checks = report["checks"]
        self.assertEqual(len(checks), 14)

        expected_ids = [
            "MT5_TERMINAL_STABILITY", "BROKER_CONNECTIVITY", "ACCOUNT_CONSISTENCY",
            "EXECUTION_PERMISSIONS", "MARKET_DATA_INTEGRITY", "SPREAD_SANITY_CHECKS",
            "EXECUTION_LATENCY", "SLIPPAGE_MONITORING", "ORDER_SUCCESS_RATE",
            "ORDER_REJECTION_ANALYSIS", "RECONNECTION_RESILIENCE", "RISK_ENGINE_VALIDATION",
            "EXECUTION_SAFEGUARDS", "CIRCUIT_BREAKER_RECOVERY"
        ]

        actual_ids = [c["check_id"] for c in checks]
        for cid in expected_ids:
            self.assertIn(cid, actual_ids)

        for c in checks:
            self.assertIn(c["status"], ["PASS", "WARN", "FAIL"])
            self.assertGreaterEqual(c["latency_ms"], 0.0)

    def test_bot_service_broker_certification_integration(self):
        bot_svc = BotService()
        report = bot_svc.run_broker_certification()
        self.assertIn("certification_status", report)
        self.assertEqual(len(report["checks"]), 14)


if __name__ == "__main__":
    unittest.main()
