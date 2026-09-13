"""
Unit tests for Registry Unification in LastEdge Trading Engine.
Verifies bidirectional discovery and resolution between:
- services.signals.STRATEGY_REGISTRY
- strategies.STRATEGY_REGISTRY
- Dynamic lookup in detect_signal()
"""

import unittest
import pandas as pd
from datetime import datetime
from pathlib import Path
import tempfile
import json
import hashlib
from typing import Dict, Optional, Union

from strategies.base import BaseStrategy, SignalIntent
import strategies
import services.signals as signals_svc
from services.strategy_loader import StrategyPackageVerifier, StrategyLoader, register_promoted_strategies


class DummyAlphaStrategy(BaseStrategy):
    """Estrategia dummy conforme al contrato BaseStrategy para pruebas de registro unificado."""
    def __init__(self, name: str = "DummyAlpha"):
        super().__init__(name)

    def _get_default_config(self) -> Dict:
        return {"param": 1}

    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        return df

    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[SignalIntent]:
        return SignalIntent(
            type="BUY",
            entry=1.0550,
            sl=1.0500,
            tp=1.0600,
            symbol="EURUSD",
            timeframe="M5",
            explanation="Dummy alpha signal"
        )


class TestRegistryUnification(unittest.TestCase):

    def setUp(self):
        # Guardar snapshots de los registries para aislamiento total
        self._orig_signals_reg = dict(signals_svc.STRATEGY_REGISTRY)
        self._orig_strategies_reg = dict(strategies.STRATEGY_REGISTRY)

        # Datos OHLCV suficientes para pasar validación mínima de detect_signal (>= 50 velas)
        n = 60
        self.df = pd.DataFrame({
            'open': [1.0500 + i * 0.0001 for i in range(n)],
            'high': [1.0510 + i * 0.0001 for i in range(n)],
            'low': [1.0490 + i * 0.0001 for i in range(n)],
            'close': [1.0505 + i * 0.0001 for i in range(n)],
            'volume': [100 + i for i in range(n)]
        })

    def tearDown(self):
        # Restaurar registries
        signals_svc.STRATEGY_REGISTRY.clear()
        signals_svc.STRATEGY_REGISTRY.update(self._orig_signals_reg)

        strategies.STRATEGY_REGISTRY.clear()
        strategies.STRATEGY_REGISTRY.update(self._orig_strategies_reg)

    def test_signals_register_strategy_syncs_both_registries(self):
        """register_strategy in signals must populate strategies.STRATEGY_REGISTRY too."""
        strat_key = "test_dummy_alpha_v1"
        signals_svc.register_strategy(strat_key, DummyAlphaStrategy)

        # 1. Accessible in signals registry as factory
        self.assertIn(strat_key, signals_svc.STRATEGY_REGISTRY)
        inst1 = signals_svc.STRATEGY_REGISTRY[strat_key]()
        self.assertIsInstance(inst1, DummyAlphaStrategy)

        # 2. Accessible via strategies.get_strategy
        inst2 = strategies.get_strategy(strat_key)
        self.assertIsNotNone(inst2)
        self.assertIsInstance(inst2, DummyAlphaStrategy)

        # 3. Accessible case-insensitively
        inst3 = strategies.get_strategy(strat_key.upper())
        self.assertIsNotNone(inst3)
        self.assertIsInstance(inst3, DummyAlphaStrategy)

    def test_detect_signal_dynamic_resolution_from_strategies_registry(self):
        """detect_signal should dynamically discover a strategy registered only in strategies."""
        custom_key = "test_isolated_strategy"
        strategies.register_strategy(custom_key, DummyAlphaStrategy)

        # Ensure not pre-cached in signals_svc
        if custom_key in signals_svc.STRATEGY_REGISTRY:
            del signals_svc.STRATEGY_REGISTRY[custom_key]

        # Call detect_signal using the strategy key
        signal, out_df = signals_svc.detect_signal(
            self.df,
            symbol="EURUSD",
            strategy=custom_key
        )

        # Must have resolved DummyAlphaStrategy without falling back to default EURUSD
        self.assertIn(custom_key, signals_svc.STRATEGY_REGISTRY)
        sig_type = signal.type if hasattr(signal, 'type') else signal
        self.assertEqual(sig_type, 'BUY')

    def test_btceur_never_falls_back_to_generic_strategy(self):
        """BTCEUR protection must prevent any unmapped fallback."""
        signal, _ = signals_svc.detect_signal(
            self.df,
            symbol="BTCEUR",
            strategy="non_existent_btc_strat_xyz"
        )
        self.assertIsNone(signal, "BTCEUR must return None when strategy is unknown, never fall back")

    def test_register_promoted_strategies_populates_both_registries(self):
        """register_promoted_strategies should register compliant packages in both registries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            code_file = tmp_path / "custom_strat_v1.py"
            manifest_file = tmp_path / "custom_strat_v1.json"

            code_content = (
                "from strategies.base import BaseStrategy, SignalIntent\n"
                "class CustomPromotedStrat(BaseStrategy):\n"
                "    def __init__(self):\n"
                "        super().__init__('CustomPromotedStrat')\n"
                "    def _get_default_config(self):\n"
                "        return {}\n"
                "    def _add_specific_indicators(self, df, config):\n"
                "        return df\n"
                "    def detect_setup(self, df, config=None):\n"
                "        return SignalIntent('BUY', 1.055, 1.050, 1.060, 'EURUSD', 'M5')\n"
            )
            code_file.write_text(code_content, encoding="utf-8")
            raw_bytes = code_file.read_bytes()
            code_sha256 = hashlib.sha256(raw_bytes).hexdigest()

            manifest = {
                "manifest_version": "1.0.0",
                "strategy_name": "CustomPromotedStrat",
                "symbol": "EURUSD",
                "timeframe": "M5",
                "version": "1.0.0",
                "code_file": "custom_strat_v1.py",
                "code_sha256": code_sha256,
                "config_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000"
            }
            manifest_file.write_text(json.dumps(manifest), encoding="utf-8")

            count = register_promoted_strategies(
                target_registry=strategies.STRATEGY_REGISTRY,
                strategies_dir=tmp_path
            )
            self.assertGreaterEqual(count, 1)

            # Check accessible in both registries
            self.assertIn("custom_strat_v1", strategies.STRATEGY_REGISTRY)
            self.assertIn("custom_strat_v1", signals_svc.STRATEGY_REGISTRY)

            inst_from_strat = strategies.get_strategy("custom_strat_v1")
            self.assertIsNotNone(inst_from_strat)
            self.assertEqual(inst_from_strat.__class__.__name__, "CustomPromotedStrat")


if __name__ == '__main__':
    unittest.main()
