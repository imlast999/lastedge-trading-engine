"""
Tests para SignalIntent y compatibilidad en BaseStrategy
tests/test_signal_intent.py
"""

from datetime import datetime, timezone, timedelta
import pytest
import pandas as pd
from strategies.base import SignalIntent, BaseStrategy, StrategyMetadata


class DummyIntentStrategy(BaseStrategy):
    """Estrategia de prueba que emite SignalIntent."""
    def _get_default_config(self):
        return {"param": 1}

    def _add_specific_indicators(self, df: pd.DataFrame, config: dict):
        return df

    def detect_setup(self, df: pd.DataFrame, config: dict = None):
        return SignalIntent(
            type="BUY",
            entry=1.1000,
            sl=1.0950,
            tp=1.1100,
            symbol="EURUSD",
            timeframe="H1",
            setup_strength=0.85,
            explanation="Test SignalIntent",
            context={"indicator": 42}
        )


class DummyDictStrategy(BaseStrategy):
    """Estrategia de prueba que emite dict tradicional."""
    def _get_default_config(self):
        return {"param": 1}

    def _add_specific_indicators(self, df: pd.DataFrame, config: dict):
        return df

    def detect_setup(self, df: pd.DataFrame, config: dict = None):
        return {
            "type": "SELL",
            "entry": 2000.0,
            "sl": 2010.0,
            "tp": 1980.0,
            "symbol": "XAUUSD",
            "timeframe": "H1",
            "setup_strength": 0.75,
            "explanation": "Test Dict",
            "context": {"indicator": 99}
        }


def test_signal_intent_creation_valid_buy():
    sig = SignalIntent(
        type="BUY",
        entry=1.0850,
        sl=1.0800,
        tp=1.0950,
        symbol="EURUSD",
        timeframe="H1",
        setup_strength=0.9
    )
    assert sig.type == "BUY"
    assert sig.is_buy is True
    assert sig.is_sell is False
    assert sig.entry == 1.0850
    assert sig.sl == 1.0800
    assert sig.tp == 1.0950

    is_valid, errors = sig.validate()
    assert is_valid is True
    assert len(errors) == 0


def test_signal_intent_creation_valid_sell():
    sig = SignalIntent(
        type="SELL",
        entry=100.0,
        sl=105.0,
        tp=90.0,
        symbol="BTCEUR",
        timeframe="H1"
    )
    assert sig.type == "SELL"
    assert sig.is_buy is False
    assert sig.is_sell is True

    is_valid, errors = sig.validate()
    assert is_valid is True
    assert len(errors) == 0


def test_signal_intent_invalid_type_raises():
    with pytest.raises(ValueError, match="type inválido"):
        SignalIntent(type="HOLD", entry=1.0, sl=0.9, tp=1.2)


def test_signal_intent_negative_prices_raises():
    with pytest.raises(ValueError, match="entry debe ser positivo"):
        SignalIntent(type="BUY", entry=-1.0, sl=0.9, tp=1.2)

    with pytest.raises(ValueError, match="sl debe ser positivo"):
        SignalIntent(type="BUY", entry=1.0, sl=-0.9, tp=1.2)

    with pytest.raises(ValueError, match="tp debe ser positivo"):
        SignalIntent(type="BUY", entry=1.0, sl=0.9, tp=-1.2)


def test_signal_intent_validation_geometry_errors():
    # BUY con SL mayor que entrada
    sig_buy_bad_sl = SignalIntent(type="BUY", entry=1.0800, sl=1.0850, tp=1.0900)
    ok, errors = sig_buy_bad_sl.validate()
    assert ok is False
    assert any("SL" in e and ">=" in e for e in errors)

    # BUY con TP menor que entrada
    sig_buy_bad_tp = SignalIntent(type="BUY", entry=1.0800, sl=1.0750, tp=1.0780)
    ok, errors = sig_buy_bad_tp.validate()
    assert ok is False
    assert any("TP" in e and "<=" in e for e in errors)

    # SELL con SL menor que entrada
    sig_sell_bad_sl = SignalIntent(type="SELL", entry=1.0800, sl=1.0750, tp=1.0700)
    ok, errors = sig_sell_bad_sl.validate()
    assert ok is False
    assert any("SL" in e and "<=" in e for e in errors)

    # SELL con TP mayor que entrada
    sig_sell_bad_tp = SignalIntent(type="SELL", entry=1.0800, sl=1.0850, tp=1.0900)
    ok, errors = sig_sell_bad_tp.validate()
    assert ok is False
    assert any("TP" in e and ">=" in e for e in errors)


def test_signal_intent_to_dict_and_from_dict_roundtrip():
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=2)
    original = SignalIntent(
        type="BUY",
        entry=1.2000,
        sl=1.1900,
        tp=1.2200,
        symbol="GBPUSD",
        timeframe="H4",
        setup_strength=0.8,
        explanation="Trend pullback setup",
        expires=expires,
        context={"ema_fast": 1.2010, "ema_slow": 1.1980},
        created_at=now
    )

    d = original.to_dict()
    assert d["type"] == "BUY"
    assert d["entry"] == 1.2000
    assert d["sl"] == 1.1900
    assert d["tp"] == 1.2200
    assert d["symbol"] == "GBPUSD"
    assert d["expires"] == expires

    reconstructed = SignalIntent.from_dict(d)
    assert reconstructed.type == original.type
    assert reconstructed.entry == original.entry
    assert reconstructed.sl == original.sl
    assert reconstructed.tp == original.tp
    assert reconstructed.symbol == original.symbol
    assert reconstructed.context == original.context


def test_signal_intent_from_dict_with_aliases():
    data = {
        "direction": "sell",
        "price": 1850.50,
        "stop_loss": 1860.00,
        "take_profit": 1830.00,
        "symbol": "XAUUSD"
    }
    sig = SignalIntent.from_dict(data)
    assert sig.type == "SELL"
    assert sig.entry == 1850.50
    assert sig.sl == 1860.00
    assert sig.tp == 1830.00
    assert sig.symbol == "XAUUSD"


def test_signal_intent_mapping_access():
    sig = SignalIntent(
        type="BUY",
        entry=1.0850,
        sl=1.0800,
        tp=1.0950,
        symbol="EURUSD",
        context={"custom_key": "custom_val"}
    )
    assert sig["type"] == "BUY"
    assert sig["entry"] == 1.0850
    assert sig["custom_key"] == "custom_val"
    assert sig.get("type") == "BUY"
    assert sig.get("non_existent", "fallback") == "fallback"
    assert "type" in sig
    assert "custom_key" in sig


def test_base_strategy_evaluate_signal_compatibility():
    # DataFrame ficticio de 60 barras
    df = pd.DataFrame({
        "open": [1.0800] * 60,
        "high": [1.0850] * 60,
        "low": [1.0750] * 60,
        "close": [1.0820] * 60,
    })

    # 1. Estrategia con SignalIntent
    s_intent = DummyIntentStrategy("intent_strat")
    res_intent = s_intent.evaluate_signal(df)
    assert res_intent is not None
    assert res_intent["signal_found"] is True
    assert isinstance(res_intent["signal"], dict)
    assert res_intent["signal"]["type"] == "BUY"
    assert res_intent["confidence"] == "HIGH"
    assert res_intent["score"] == 0.85

    # 2. Estrategia con Dict tradicional
    s_dict = DummyDictStrategy("dict_strat")
    res_dict = s_dict.evaluate_signal(df)
    assert res_dict is not None
    assert res_dict["signal_found"] is True
    assert isinstance(res_dict["signal"], dict)
    assert res_dict["signal"]["type"] == "SELL"
    assert res_dict["confidence"] == "MEDIUM-HIGH"
    assert res_dict["score"] == 0.75


def test_base_strategy_helpers():
    sig = SignalIntent(type="BUY", entry=1.0, sl=0.9, tp=1.2)
    d = {"type": "BUY", "entry": 1.0, "sl": 0.9, "tp": 1.2}

    assert BaseStrategy.ensure_signal_dict(None) is None
    assert BaseStrategy.ensure_signal_intent(None) is None

    assert isinstance(BaseStrategy.ensure_signal_dict(sig), dict)
    assert isinstance(BaseStrategy.ensure_signal_dict(d), dict)

    assert isinstance(BaseStrategy.ensure_signal_intent(sig), SignalIntent)
    assert isinstance(BaseStrategy.ensure_signal_intent(d), SignalIntent)
