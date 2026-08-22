"""
Tests para BotService (services/bot_service.py) — tests/test_bot_service.py
"""

import unittest
from services.bot_service import BotService

class TestBotService(unittest.TestCase):

    def setUp(self):
        self.service = BotService()

    def test_get_system_status(self):
        status = self.service.get_system_status()
        self.assertTrue(status["ok"])
        self.assertEqual(status["system_status"], "RUNNING")
        self.assertIn("uptime_formatted", status)
        self.assertIn("circuit_breaker", status)

    def test_toggle_autosignals(self):
        res_off = self.service.toggle_autosignals("off")
        self.assertFalse(res_off["autosignals_enabled"])
        
        res_on = self.service.toggle_autosignals("on")
        self.assertTrue(res_on["autosignals_enabled"])

    def test_get_research_summary(self):
        res = self.service.get_research_summary()
        self.assertTrue(res["ok"])
        self.assertIn("total_experiments", res)

    def test_get_journal_summary(self):
        res = self.service.get_journal_summary(days=7)
        self.assertTrue(res["ok"])
        self.assertIn("stats", res)


if __name__ == '__main__':
    unittest.main()
