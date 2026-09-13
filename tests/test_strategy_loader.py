"""
Tests para StrategyPackageVerifier y StrategyLoader en Trading Engine
tests/test_strategy_loader.py
"""

import json
import hashlib
import tempfile
from pathlib import Path
import pytest
import pandas as pd

from services.strategy_loader import (
    StrategyPackageVerifier,
    StrategyLoader,
    discover_promoted_strategies,
    register_promoted_strategies,
)
from strategies.base import BaseStrategy, SignalIntent


# Plantilla de código de estrategia válida para los tests
VALID_STRATEGY_CODE = '''
from strategies.base import BaseStrategy, SignalIntent

class PromotedAlphaStrategy(BaseStrategy):
    def _get_default_config(self):
        return {"fast_ma": 10, "slow_ma": 30}

    def _add_specific_indicators(self, df, config):
        return df

    def detect_setup(self, df, config=None):
        return SignalIntent(
            type="BUY",
            entry=1.2345,
            sl=1.2300,
            tp=1.2400,
            symbol="EURUSD",
            explanation="Promoted test setup"
        )
'''

NON_COMPLIANT_CODE = '''
class NonCompliantClass:
    def execute(self):
        return "I do not inherit from BaseStrategy"
'''


@pytest.fixture
def temp_strategy_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def create_sample_package(
    directory: Path,
    base_name: str = "eurusd_v1_0_0",
    code_content: str = VALID_STRATEGY_CODE,
    config: dict = None,
    tamper_code: bool = False,
    tamper_config: bool = False,
    omit_code_file: bool = False
):
    if config is None:
        config = {"fast_ma": 10, "slow_ma": 30}

    code_path = directory / f"{base_name}.py"
    manifest_path = directory / f"{base_name}.json"

    if not omit_code_file:
        code_path.write_bytes(code_content.encode("utf-8"))
        code_sha = hashlib.sha256(code_path.read_bytes()).hexdigest()
    else:
        code_sha = hashlib.sha256(code_content.encode("utf-8")).hexdigest()

    config_str = json.dumps(config, sort_keys=True)
    cfg_hash = hashlib.sha256(config_str.encode("utf-8")).hexdigest()[:16]

    manifest = {
        "strategy_name": "PromotedAlphaStrategy",
        "symbol": "EURUSD",
        "timeframe": "H1",
        "version": "1.0.0",
        "config": config,
        "config_hash": cfg_hash,
        "code_sha256": code_sha,
        "dataset_sha256": "abcdef0123456789",
        "promoted_at": "2026-09-13T20:00:00+00:00",
        "approved_by": "Architect"
    }

    if tamper_code and not omit_code_file:
        # Manipulamos el código en disco tras haber registrado el hash
        code_path.write_text(code_content + "\n# Alteración maliciosa o no autorizada\n", encoding="utf-8")

    if tamper_config:
        # Alteramos la config dentro del manifiesto sin recalcular su hash
        manifest["config"]["fast_ma"] = 999

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest_path, code_path


def test_strategy_loader_valid_package(temp_strategy_dir):
    m_path, c_path = create_sample_package(temp_strategy_dir)

    loader = StrategyLoader()
    strat_cls, msg, manifest = loader.load_strategy_class(m_path)

    assert strat_cls is not None
    assert msg == "OK"
    assert issubclass(strat_cls, BaseStrategy)
    assert strat_cls.__name__ == "PromotedAlphaStrategy"

    # Instanciación y prueba funcional
    instance = strat_cls("test_promoted")
    setup = instance.detect_setup(pd.DataFrame())
    assert isinstance(setup, SignalIntent)
    assert setup.type == "BUY"
    assert setup.entry == 1.2345


def test_strategy_loader_code_tampered_rejected(temp_strategy_dir):
    m_path, c_path = create_sample_package(temp_strategy_dir, tamper_code=True)

    loader = StrategyLoader()
    strat_cls, msg, manifest = loader.load_strategy_class(m_path)

    assert strat_cls is None
    assert "Code SHA-256 mismatch" in msg


def test_strategy_loader_config_tampered_rejected(temp_strategy_dir):
    m_path, c_path = create_sample_package(temp_strategy_dir, tamper_config=True)

    loader = StrategyLoader()
    strat_cls, msg, manifest = loader.load_strategy_class(m_path)

    assert strat_cls is None
    assert "Config hash mismatch" in msg


def test_strategy_loader_missing_code_file_rejected(temp_strategy_dir):
    m_path, c_path = create_sample_package(temp_strategy_dir, omit_code_file=True)

    loader = StrategyLoader()
    strat_cls, msg, manifest = loader.load_strategy_class(m_path)

    assert strat_cls is None
    assert "not found" in msg.lower()


def test_strategy_loader_non_compliant_class_rejected(temp_strategy_dir):
    m_path, c_path = create_sample_package(
        temp_strategy_dir,
        code_content=NON_COMPLIANT_CODE
    )

    loader = StrategyLoader()
    strat_cls, msg, manifest = loader.load_strategy_class(m_path)

    assert strat_cls is None
    assert "No compliant BaseStrategy subclass found" in msg


def test_discover_and_register_promoted_strategies(temp_strategy_dir):
    # Crear dos paquetes válidos: EURUSD y XAUUSD
    create_sample_package(temp_strategy_dir, base_name="eurusd_v1_0_0")
    create_sample_package(temp_strategy_dir, base_name="xauusd_v2_1_0")

    # Crear uno corrupto que debe ser descartado
    create_sample_package(temp_strategy_dir, base_name="corrupt_v1_0_0", tamper_code=True)

    discovered = discover_promoted_strategies(temp_strategy_dir)
    assert len(discovered) == 2
    assert "eurusd_v1_0_0" in discovered
    assert "xauusd_v2_1_0" in discovered
    assert "corrupt_v1_0_0" not in discovered

    # Registro en diccionario mock
    mock_registry = {}
    count = register_promoted_strategies(mock_registry, temp_strategy_dir)
    assert count == 2
    assert "eurusd_v1_0_0" in mock_registry
    assert "xauusd_v2_1_0" in mock_registry
    assert "promotedalphastrategy" in mock_registry
