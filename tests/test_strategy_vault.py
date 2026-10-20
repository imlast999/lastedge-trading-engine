"""
Unit Tests for Strategy Vault Private Architecture
tests/test_strategy_vault.py
"""

import unittest
import tempfile
import shutil
from pathlib import Path

from services.strategy_loader import (
    discover_vault_strategies,
    register_vault_strategies,
    StrategyPackageVerifier,
)
from strategies.base import BaseStrategy, StrategyMetadata, SignalIntent


class DummyVaultStrategy(BaseStrategy):
    symbol = "EURUSD"
    strategy_name = "DummyVaultAlpha"
    version = "2.0.0"

    def __init__(self, config=None):
        super().__init__(symbol=self.symbol, timeframe="H1", config=config or {})
        self.metadata = StrategyMetadata(
            required_history=100,
            symbol=self.symbol,
            timeframe="H1",
            strategy_name=self.strategy_name,
            version=self.version
        )

    def calculate_indicators(self, df):
        return df

    def generate_signal(self, df):
        return None


class TestStrategyVault(unittest.TestCase):

    def setUp(self):
        self.temp_vault = tempfile.mkdtemp(prefix="test_vault_")

    def tearDown(self):
        shutil.rmtree(self.temp_vault, ignore_errors=True)

    def test_discover_empty_vault(self):
        discovered = discover_vault_strategies(self.temp_vault)
        self.assertEqual(discovered, {})

    def test_discover_and_register_python_strategy(self):
        vault_path = Path(self.temp_vault)
        strat_code = '''
from strategies.base import BaseStrategy, StrategyMetadata

class ProprietaryGoldStrategy(BaseStrategy):
    symbol = "XAUUSD"
    strategy_name = "ProprietaryGoldAlpha"
    version = "1.5.0"

    def __init__(self, config=None):
        super().__init__(symbol="XAUUSD", timeframe="M15", config=config or {})
        self.metadata = StrategyMetadata(
            required_history=60,
            symbol="XAUUSD",
            timeframe="M15",
            strategy_name=self.strategy_name,
            version=self.version
        )

    def calculate_indicators(self, df):
        return df

    def generate_signal(self, df):
        return None
'''
        (vault_path / "xauusd_alpha.py").write_text(strat_code, encoding="utf-8")

        discovered = discover_vault_strategies(vault_path)
        self.assertIn("xauusd_alpha", discovered)
        self.assertEqual(discovered["xauusd_alpha"]["symbol"], "XAUUSD")
        self.assertEqual(discovered["xauusd_alpha"]["strategy_name"], "ProprietaryGoldAlpha")

        # Test registration
        test_registry = {}
        count = register_vault_strategies(test_registry, vault_dir=vault_path)
        self.assertEqual(count, 1)
        self.assertIn("XAUUSD", test_registry)
        self.assertEqual(test_registry["XAUUSD"].__name__, "ProprietaryGoldStrategy")
        self.assertEqual(test_registry["xauusd_alpha"].__name__, "ProprietaryGoldStrategy")


if __name__ == "__main__":
    unittest.main()
