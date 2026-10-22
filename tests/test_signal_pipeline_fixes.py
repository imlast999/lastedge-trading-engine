import os
import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from core.engine import get_trading_engine, BotState
from services.mobile_store import get_mobile_store
from services.autosignals import create_autosignals_service, AutoSignalsService
from services.mt5_client import ensure_symbols_selected


class TestSignalPipelineFixes(unittest.TestCase):
    def setUp(self):
        # Create a synthetic dataframe with enough bars for indicators
        np.random.seed(42)
        n = 250
        dates = pd.date_range("2026-01-01", periods=n, freq="h")
        price = 1.1000 + np.cumsum(np.random.randn(n) * 0.0005)
        self.df = pd.DataFrame({
            "open": price,
            "high": price + 0.0003,
            "low": price - 0.0003,
            "close": price + 0.0001,
            "tick_volume": [1000] * n,
        }, index=dates)

    def test_engine_evaluate_signal_no_import_error(self):
        """Verify engine.evaluate_signal does NOT fail with 'No module named signals'"""
        engine = get_trading_engine()
        result = engine.evaluate_signal(
            df=self.df,
            symbol="EURUSD",
            strategy="eurusd_simple",
            config={"ema_fast": 20, "ema_slow": 50, "ema_trend": 200, "rsi_period": 14, "atr_period": 14},
            skip_duplicate_filter=True,
        )
        self.assertIsNotNone(result)
        # Rejection reason should never be "No module named 'signals'"
        if result.rejection_reason:
            self.assertNotIn("No module named 'signals'", result.rejection_reason)
            self.assertNotIn("ModuleNotFoundError", result.rejection_reason)

    def test_mobile_store_insert_signal_auto_session(self):
        """Verify MobileStore.insert_signal auto-starts session and inserts into enhanced_signals"""
        store = get_mobile_store()
        store._session_id = None  # Force uninitialized session

        sig_id = store.insert_signal(
            symbol="EURUSD",
            direction="BUY",
            price=1.08500,
            tp_price=1.09500,
            sl_price=1.08000,
            lot_size=0.1,
            confidence_score=0.85,
            confidence="HIGH",
            strategy="eurusd_simple",
            status="PROPOSED",
        )
        self.assertIsNotNone(sig_id)
        self.assertGreater(sig_id, 0)
        self.assertIsNotNone(store._session_id)

    def test_autosignals_headless_creation(self):
        """Verify AutoSignalsService can be instantiated and initialized without Discord bot"""
        service = create_autosignals_service(bot=None)
        self.assertIsInstance(service, AutoSignalsService)
        self.assertIsNone(service.bot)
        self.assertTrue(service.state.autosignals)
        self.assertIn("EURUSD", service.config["AUTOSIGNAL_SYMBOLS"])

    def test_ensure_symbols_selected_safe(self):
        """Verify ensure_symbols_selected does not crash even without MT5 terminal active"""
        res = ensure_symbols_selected(["EURUSD", "XAUUSD", "BTCEUR"])
        self.assertIsInstance(res, dict)


if __name__ == "__main__":
    unittest.main()
