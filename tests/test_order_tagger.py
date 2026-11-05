"""
Tests for services/order_tagger.py
"""

import unittest
from services.order_tagger import OrderTagger


class TestOrderTagger(unittest.TestCase):

    def test_known_strategies_comments(self):
        # 1. BTCEUR Trend Surge
        sig1 = {
            "symbol": "BTCEUR",
            "strategy": "btceur_trend_surge",
            "type": "BUY",
            "entry": 85000.0,
            "sl": 84000.0,
            "tp": 88000.0,
            "setup_type": "PULLBACK_EMA20",
        }
        c1 = OrderTagger.generate_entry_comment(sig1)
        m1 = OrderTagger.generate_magic_number(sig1)
        self.assertEqual(c1, "BTC-TRND·Pullback·RR3.0")
        self.assertEqual(m1, 130101)
        self.assertLessEqual(len(c1), 31)

        # 2. BTCEUR Volatility Breakout
        sig2 = {
            "symbol": "BTCEUR",
            "strategy": "btceur_volatility_breakout",
            "type": "BUY",
            "entry": 85000.0,
            "sl": 84000.0,
            "tp": 87600.0,
            "setup_type": "VOLATILITY_BREAKOUT_LONG",
        }
        c2 = OrderTagger.generate_entry_comment(sig2)
        m2 = OrderTagger.generate_magic_number(sig2)
        self.assertEqual(c2, "BTC-VOLB·Breakout·RR2.6")
        self.assertEqual(m2, 130102)
        self.assertLessEqual(len(c2), 31)

        # 3. XAUUSD Partial Close
        sig3 = {
            "symbol": "XAUUSD",
            "strategy": "xauusd_partial",
            "type": "BUY",
            "entry": 4036.0,
            "sl": 4016.0,
            "tp": 4086.0,
            "setup_type": "WICK_REJECTION",
        }
        c3 = OrderTagger.generate_entry_comment(sig3)
        m3 = OrderTagger.generate_magic_number(sig3)
        self.assertEqual(c3, "XAU-PART·Rejection·RR2.5")
        self.assertEqual(m3, 120101)
        self.assertLessEqual(len(c3), 31)

        # 4. EURUSD Flow
        sig4 = {
            "symbol": "EURUSD",
            "strategy": "eurusd_flow",
            "type": "BUY",
            "entry": 1.1200,
            "sl": 1.1150,
            "tp": 1.1300,
            "setup_type": "ORDER_FLOW_MOMENTUM",
        }
        c4 = OrderTagger.generate_entry_comment(sig4)
        m4 = OrderTagger.generate_magic_number(sig4)
        self.assertEqual(c4, "EUR-FLOW·Momentum·RR2.0")
        self.assertEqual(m4, 110102)
        self.assertLessEqual(len(c4), 31)

    def test_custom_unknown_strategy_and_symbol(self):
        sig = {
            "symbol": "US500",
            "strategy": "custom_bollinger_reversal_v2",
            "type": "SELL",
            "entry": 5800.0,
            "sl": 5850.0,
            "tp": 5710.0,
            "setup_type": "REVERSAL",
        }
        c = OrderTagger.generate_entry_comment(sig)
        m = OrderTagger.generate_magic_number(sig)
        self.assertLessEqual(len(c), 31)
        self.assertTrue(c.startswith("SP500-CUBO·Reversal·RR1.8"))
        self.assertGreater(m, 100000)

    def test_lifecycle_comments(self):
        self.assertEqual(OrderTagger.generate_partial_close_comment(50), "PARTIAL:50%·BE-LOCKED")
        self.assertLessEqual(len(OrderTagger.generate_partial_close_comment()), 31)

        self.assertEqual(OrderTagger.generate_trailing_exit_comment(), "TRAIL:ATR-PROFIT-LOCK")
        self.assertLessEqual(len(OrderTagger.generate_trailing_exit_comment()), 31)

        self.assertEqual(OrderTagger.generate_breakeven_comment(), "EXIT:BE-PROTECTED")
        self.assertLessEqual(len(OrderTagger.generate_breakeven_comment()), 31)

        self.assertEqual(OrderTagger.generate_stoploss_comment(), "EXIT:STOPLOSS-HIT")
        self.assertLessEqual(len(OrderTagger.generate_stoploss_comment()), 31)


if __name__ == "__main__":
    unittest.main()
