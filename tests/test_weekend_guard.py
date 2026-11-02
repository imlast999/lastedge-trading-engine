"""
Unit Tests for Weekend Exposure Guard
tests/test_weekend_guard.py
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest

from services.weekend_guard import WeekendExposureGuard
from strategies.base import BaseStrategy


class MockOpenPosition:
    def __init__(self, ticket: int, symbol: str, volume: float, pos_type: int, profit: float, price_current: float):
        self.ticket = ticket
        self.symbol = symbol
        self.volume = volume
        self.type = pos_type
        self.profit = profit
        self.price_current = price_current

    def _asdict(self):
        return {
            "ticket": self.ticket,
            "symbol": self.symbol,
            "volume": self.volume,
            "type": self.type,
            "profit": self.profit,
            "price_current": self.price_current,
        }


class CustomCryptoStrategy(BaseStrategy):
    weekend_exposure_guard = False

    def __init__(self):
        super().__init__("CustomCrypto")

    def _get_default_config(self):
        return {}

    def _add_specific_indicators(self, df):
        return df

    def detect_setup(self, df, config=None):
        return None


class CustomSwingForexStrategy(BaseStrategy):
    # Strategy author explicitly disables weekend guard to allow swing trade over weekend
    weekend_exposure_guard = False

    def __init__(self):
        super().__init__("CustomSwingForex")

    def _get_default_config(self):
        return {}

    def _add_specific_indicators(self, df):
        return df

    def detect_setup(self, df, config=None):
        return None


class StandardDayTradingStrategy(BaseStrategy):
    weekend_exposure_guard = True

    def __init__(self):
        super().__init__("StandardDayTrading")

    def _get_default_config(self):
        return {}

    def _add_specific_indicators(self, df):
        return df

    def detect_setup(self, df, config=None):
        return None


@pytest.fixture
def guard():
    # Instantiate guard with defaults
    return WeekendExposureGuard(rules_config_path="non_existent_path.json")


def test_crypto_classification(guard):
    assert guard.is_crypto("BTCEUR") is True
    assert guard.is_crypto("BTCUSD") is True
    assert guard.is_crypto("ETHUSD") is True
    assert guard.is_crypto("SOLUSD") is True
    assert guard.is_crypto("XAUUSD") is False
    assert guard.is_crypto("EURUSD") is False
    assert guard.is_crypto("GBPUSD") is False


def test_is_symbol_guarded_defaults(guard):
    # Non-crypto are guarded by default
    assert guard.is_symbol_guarded("XAUUSD") is True
    assert guard.is_symbol_guarded("EURUSD") is True

    # Crypto is never guarded
    assert guard.is_symbol_guarded("BTCEUR") is False
    assert guard.is_symbol_guarded("BTCUSD") is False


def test_strategy_switch_override(guard):
    swing_strat = CustomSwingForexStrategy()
    day_strat = StandardDayTradingStrategy()

    # Even though EURUSD is traditional forex, swing_strat explicitly opts out:
    assert guard.is_symbol_guarded("EURUSD", strategy=swing_strat) is False

    # Standard day trading strategy keeps guard active:
    assert guard.is_symbol_guarded("EURUSD", strategy=day_strat) is True

    # Crypto strategy remains un-guarded:
    assert guard.is_symbol_guarded("BTCEUR", strategy=day_strat) is False


def test_entry_allowed_boundaries(guard):
    # Wednesday 14:00 UTC -> Everyone allowed
    wed = datetime(2026, 10, 28, 14, 0, 0, tzinfo=timezone.utc)
    ok, _ = guard.is_entry_allowed("XAUUSD", now=wed)
    assert ok is True
    ok, _ = guard.is_entry_allowed("BTCEUR", now=wed)
    assert ok is True

    # Friday 15:30 UTC -> Before 18:00 blackout -> Allowed
    fri_afternoon = datetime(2026, 10, 30, 15, 30, 0, tzinfo=timezone.utc)
    ok, _ = guard.is_entry_allowed("XAUUSD", now=fri_afternoon)
    assert ok is True

    # Friday 18:01 UTC -> Inside blackout -> Gold blocked, BTC allowed
    fri_evening = datetime(2026, 10, 30, 18, 1, 0, tzinfo=timezone.utc)
    ok, reason = guard.is_entry_allowed("XAUUSD", now=fri_evening)
    assert ok is False
    assert "blackout" in reason.lower()
    ok_btc, _ = guard.is_entry_allowed("BTCEUR", now=fri_evening)
    assert ok_btc is True

    # Saturday 12:00 UTC -> Gold blocked, BTC allowed
    sat = datetime(2026, 10, 31, 12, 0, 0, tzinfo=timezone.utc)
    ok, _ = guard.is_entry_allowed("XAUUSD", now=sat)
    assert ok is False
    ok_btc, _ = guard.is_entry_allowed("BTCEUR", now=sat)
    assert ok_btc is True

    # Sunday 20:00 UTC (before 22:00 reopen) -> Gold blocked, BTC allowed
    sun_early = datetime(2026, 11, 1, 20, 0, 0, tzinfo=timezone.utc)
    ok, _ = guard.is_entry_allowed("XAUUSD", now=sun_early)
    assert ok is False
    ok_btc, _ = guard.is_entry_allowed("BTCEUR", now=sun_early)
    assert ok_btc is True

    # Sunday 22:05 UTC (reopened) -> Both allowed
    sun_night = datetime(2026, 11, 1, 22, 5, 0, tzinfo=timezone.utc)
    ok, reason = guard.is_entry_allowed("XAUUSD", now=sun_night)
    assert ok is True
    assert "reopened" in reason.lower()


def test_flattening_time_detection(guard):
    # Friday 20:59 UTC -> Not flattening time
    t1 = datetime(2026, 10, 30, 20, 59, 0, tzinfo=timezone.utc)
    assert guard.is_flattening_time(now=t1) is False

    # Friday 21:30 UTC -> Flattening time starts
    t2 = datetime(2026, 10, 30, 21, 30, 0, tzinfo=timezone.utc)
    assert guard.is_flattening_time(now=t2) is True

    # Friday 22:15 UTC -> Flattening time active
    t3 = datetime(2026, 10, 30, 22, 15, 0, tzinfo=timezone.utc)
    assert guard.is_flattening_time(now=t3) is True

    # Saturday 14:00 UTC -> Flattening time active (safety net)
    t4 = datetime(2026, 10, 31, 14, 0, 0, tzinfo=timezone.utc)
    assert guard.is_flattening_time(now=t4) is True

    # Sunday 21:55 UTC -> Flattening time active
    t5 = datetime(2026, 11, 1, 21, 55, 0, tzinfo=timezone.utc)
    assert guard.is_flattening_time(now=t5) is True

    # Sunday 22:01 UTC -> Trading week resumed, no flattening
    t6 = datetime(2026, 11, 1, 22, 1, 0, tzinfo=timezone.utc)
    assert guard.is_flattening_time(now=t6) is False


def test_check_and_flatten_positions_execution():
    mock_mt5 = MagicMock()
    mock_bot = MagicMock()

    # 1 Gold position (#11777738) and 1 BTC position (#11780584)
    pos_gold = MockOpenPosition(
        ticket=11777738,
        symbol="XAUUSD",
        volume=0.01,
        pos_type=1,  # SELL
        profit=14.50,
        price_current=2735.20
    )
    pos_btc = MockOpenPosition(
        ticket=11780584,
        symbol="BTCEUR",
        volume=0.02,
        pos_type=1,  # SELL
        profit=18.20,
        price_current=69400.0
    )

    mock_mt5.positions_get.return_value = [pos_gold, pos_btc]
    mock_bot.close_position.return_value = {"ok": True, "message": "Closed via BotService"}

    guard = WeekendExposureGuard(
        rules_config_path="non_existent_path.json",
        bot_service=mock_bot,
        mt5_module=mock_mt5
    )

    # 1. During Friday afternoon (16:00 UTC): does not flatten
    fri_afternoon = datetime(2026, 10, 30, 16, 0, 0, tzinfo=timezone.utc)
    closed = guard.check_and_flatten_positions(now=fri_afternoon)
    assert len(closed) == 0
    mock_bot.close_position.assert_not_called()

    # 2. At Friday night (21:35 UTC): flattens Gold, leaves BTC untouched
    fri_night = datetime(2026, 10, 30, 21, 35, 0, tzinfo=timezone.utc)
    closed = guard.check_and_flatten_positions(now=fri_night)

    assert len(closed) == 1
    assert closed[0]["ticket"] == 11777738
    assert closed[0]["symbol"] == "XAUUSD"
    assert closed[0]["profit"] == 14.50
    assert closed[0]["status"] == "CLOSED"

    mock_bot.close_position.assert_called_once_with(11777738)

    # 3. Repeat call during same weekend skips already closed ticket
    closed_repeat = guard.check_and_flatten_positions(now=fri_night)
    assert len(closed_repeat) == 0
import os

def test_real_rules_config_integration():
    real_config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "rules_config.json"
    )
    guard = WeekendExposureGuard(rules_config_path=real_config_path)
    assert guard.enabled is True
    assert guard.close_hour == 21
    assert guard.close_minute == 30
    assert guard.block_entry_hour == 18
    assert guard.is_symbol_guarded("XAUUSD") is True
    assert guard.is_symbol_guarded("EURUSD") is True
    assert guard.is_symbol_guarded("BTCEUR") is False
