"""
Tests para P5.6 — Operational Readiness & Production Operations
================================================================
Verifica:
  1. Auditoría de preparación operativa de producción.
  2. Generación y restauración de backups SQLite con PRAGMA integrity_check.
  3. Listado de copias de seguridad.
  4. Rotación de archivos de log.
  5. Integración con BotService.
"""

from __future__ import annotations

import os
import unittest
import tempfile
from services.database import get_database_manager
from services.operational_readiness import (
    OperationalReadinessService,
    get_operational_readiness_service,
)
from services.bot_service import BotService


class TestP56OperationalReadiness(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_bot.db")
        self.backup_dir = os.path.join(self.tmp_dir.name, "backups")
        self.logs_dir = os.path.join(self.tmp_dir.name, "logs")

        os.makedirs(self.backup_dir, exist_ok=True)
        os.makedirs(self.logs_dir, exist_ok=True)

        self.db_manager = get_database_manager(self.db_path)
        with self.db_manager.get_connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS test_table (id INTEGER PRIMARY KEY, val TEXT);")
            conn.execute("INSERT INTO test_table (val) VALUES ('operational_test');")

        self.op_svc = OperationalReadinessService(
            db_path=self.db_path, backup_dir=self.backup_dir, logs_dir=self.logs_dir
        )

    def tearDown(self):
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def test_run_operational_readiness_audit(self):
        report = self.op_svc.run_operational_readiness_audit()

        self.assertIn("timestamp", report)
        self.assertEqual(report["readiness_status"], "OPERATIONAL_READY")
        self.assertEqual(report["readiness_score"], 100.0)
        self.assertIn("procedures", report)
        self.assertEqual(len(report["procedures"]), 8)

    def test_backup_and_restore_cycle(self):
        # 1. Crear backup
        res_bak = self.op_svc.create_backup("test_backup.db")
        self.assertTrue(res_bak["ok"])
        self.assertTrue(os.path.exists(res_bak["backup_path"]))

        # 2. Listar backups
        backups = self.op_svc.list_backups()
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0]["filename"], "test_backup.db")

        # 3. Restaurar backup
        res_res = self.op_svc.restore_backup("test_backup.db")
        self.assertTrue(res_res["ok"])

    def test_log_rotation(self):
        # Crear log simulado grande
        big_log = os.path.join(self.logs_dir, "test_big.log")
        with open(big_log, "w") as f:
            f.write("X" * (100 * 1024))  # 100 KB

        # Rotar logs con max_bytes de 50 KB
        res_rot = self.op_svc.rotate_logs(max_bytes=50 * 1024)
        self.assertTrue(res_rot["ok"])
        self.assertEqual(len(res_rot["rotated_files"]), 1)

    def test_bot_service_operational_readiness_integration(self):
        bot_svc = BotService()
        report = bot_svc.run_operational_readiness_audit()
        self.assertIn("readiness_status", report)
        self.assertIn("procedures", report)

        backups = bot_svc.list_backups()
        self.assertIsInstance(backups, list)


if __name__ == "__main__":
    unittest.main()
