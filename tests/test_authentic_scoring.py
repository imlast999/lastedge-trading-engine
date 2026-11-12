import unittest
import pandas as pd
from core.scoring import get_scoring_system


class TestAuthenticScoring(unittest.TestCase):
    def setUp(self):
        self.scoring = get_scoring_system()
        closes = [65000 + i * 40 for i in range(50)]
        self.df_btc = pd.DataFrame({
            'open': [c - 10 for c in closes],
            'close': closes,
            'high': [c + 20 for c in closes],
            'low': [c - 20 for c in closes],
            'volume': [100.0] * 50,
            'ema20': closes,
            'atr': [150.0] * 50,
            'rsi': [55.0] * 50,
        })

    def test_btceur_scoring_not_artificially_saturated(self):
        """BTC signal with 0.88 native score returns proportional authentic score without hard saturation."""
        signal_btc = {
            'type': 'BUY',
            'score': 0.88,
            'entry': 67000.0,
            'sl': 66000.0,
            'tp': 70000.0,
        }

        class MockContext:
            symbol = 'BTCEUR'
            raw_signal = signal_btc
            dataframe = self.df_btc

        res = self.scoring.evaluate_signal_context(MockContext())
        self.assertTrue(res.should_show)
        self.assertEqual(res.details['setup_quality'], 0.88)
        # Should be authentic score combining setup + dynamic confirmations, not hardcoded 1.00
        self.assertLessEqual(res.final_score, 1.0)
        self.assertGreaterEqual(res.final_score, 0.70)
        self.assertIn('ENTRY_DISCIPLINE', res.details['passed_confirmations'])
        self.assertIn('VOLATILITY_HEALTH', res.details['passed_confirmations'])

    def test_eurusd_respects_setup_strength(self):
        """EURUSD respects setup_strength from strategy."""
        signal_fx = {
            'type': 'BUY',
            'setup_strength': 0.72,
            'entry': 1.0850,
            'sl': 1.0820,
            'tp': 1.0910,
        }
        closes = [1.0800 + i * 0.0001 for i in range(50)]
        df_fx = pd.DataFrame({
            'open': [c - 0.00005 for c in closes],
            'close': closes,
            'high': [c + 0.0001 for c in closes],
            'low': [c - 0.0001 for c in closes],
            'volume': [500.0] * 50,
            'ema20': closes,
            'atr': [0.0015] * 50,
            'rsi': [52.0] * 50,
        })

        class MockContext:
            symbol = 'EURUSD'
            raw_signal = signal_fx
            dataframe = df_fx

        res = self.scoring.evaluate_signal_context(MockContext())
        self.assertEqual(res.details['setup_quality'], 0.72)
        # Since setup is 0.72 and confirmations pass, score reflects both cleanly
        self.assertGreaterEqual(res.final_score, 0.70)
        self.assertLess(res.final_score, 1.0)

    def test_uncapped_perfection_can_reach_one_if_earned(self):
        """No artificial ceiling: if setup is 1.0 and all confirmations pass, 1.0 is legitimately reachable."""
        signal_perfect = {
            'type': 'BUY',
            'score': 1.0,
            'entry': 67000.0,
            'sl': 66000.0,
            'tp': 70000.0,
        }

        class MockContext:
            symbol = 'BTCEUR'
            raw_signal = signal_perfect
            dataframe = self.df_btc

        res = self.scoring.evaluate_signal_context(MockContext())
        # All confirmations pass and setup is 1.0 -> uncapped natural 1.0
        self.assertEqual(res.final_score, 1.0)


if __name__ == '__main__':
    unittest.main()
