"""
Unit Tests for Institutional News Filter Enhancements
tests/test_news_guard_enhancements.py
=====================================================
Covers:
1. Live Economic Calendar Sync & Local Cache.
2. Dynamic Spread Guard (price-unit based MT5 spread check).
3. Active Trade Guard (pre-news position break-even locking).
4. Autosignals spread integration & TrailingStopManager news protection.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import json
import pytest

from services.news_filter import NewsFilter, get_news_filter


# ── Fixtures & Mocks ──────────────────────────────────────────────────────────

class MockSymbolInfo:
    def __init__(self, bid: float, ask: float, digits: int = 5):
        self.bid = bid
        self.ask = ask
        self.digits = digits


class MockPosition:
    def __init__(self, ticket: int, symbol: str, entry_price: float, current_price: float, sl: float, tp: float, pos_type: int = 0):
        self.ticket = ticket
        self.symbol = symbol
        self.price_open = entry_price
        self.price_current = current_price
        self.sl = sl
        self.tp = tp
        self.type = pos_type  # 0: BUY, 1: SELL
        self.volume = 0.01


# ── Test Suite 1: Calendar Cache & Fallback ───────────────────────────────────

def test_static_calendar_coverage():
    """Verify that verified 2025 and 2026 NFP, CPI, and FOMC dates are present."""
    nf = NewsFilter(cache_path="nonexistent_cache.json", auto_fetch_live=False)

    # NFP on Nov 6, 2026 at 13:30 UTC
    nfp_time = datetime(2026, 11, 6, 13, 0, tzinfo=timezone.utc)
    is_blackout, reason = nf.is_news_blackout("EURUSD", check_time=nfp_time)
    assert is_blackout is True
    assert "NFP" in reason

    # Outside blackout window (same day at 04:00 UTC)
    early_time = datetime(2026, 11, 6, 4, 0, tzinfo=timezone.utc)
    is_blackout, reason = nf.is_news_blackout("EURUSD", check_time=early_time)
    assert is_blackout is False


def test_calendar_cache_loading(tmp_path):
    """Verify loading from cached economic calendar JSON."""
    cache_file = tmp_path / "economic_calendar.json"
    dummy_events = [
        {
            "name": "US Non-Farm Payrolls",
            "currency": "USD",
            "impact": "High",
            "time": "2026-11-06T13:30:00+00:00"
        },
        {
            "name": "ECB Interest Rate Decision",
            "currency": "EUR",
            "impact": "High",
            "time": "2026-11-06T12:15:00+00:00"
        }
    ]
    cache_file.write_text(json.dumps(dummy_events), encoding="utf-8")

    nf = NewsFilter(cache_path=str(cache_file), auto_fetch_live=False)
    assert len(nf._cached_live_events) == 2

    # Blackout check 10 minutes before ECB Decision
    test_dt = datetime(2026, 11, 6, 12, 5, tzinfo=timezone.utc)
    is_blackout, reason = nf.is_news_blackout("EURUSD", check_time=test_dt)
    assert is_blackout is True
    assert "ECB Interest Rate Decision" in reason


# ── Test Suite 2: Dynamic Spread Guard ────────────────────────────────────────

def test_spread_acceptable_normal():
    """Spread within normal limit returns True."""
    nf = NewsFilter(auto_fetch_live=False)

    with patch('services.news_filter.mt5') as mock_mt5:
        mock_mt5.symbol_info.return_value = MockSymbolInfo(bid=1.12000, ask=1.12015, digits=5)  # Spread: 0.00015
        acceptable, reason, spread, max_allowed = nf.is_spread_acceptable('EURUSD')

        assert acceptable is True
        assert spread == pytest.approx(0.00015, abs=1e-5)
        assert max_allowed == 0.00035
        assert "OK" in reason


def test_spread_acceptable_spiked():
    """Abnormal spread spike (e.g. 5 pips on EURUSD) returns False."""
    nf = NewsFilter(auto_fetch_live=False)

    with patch('services.news_filter.mt5') as mock_mt5:
        mock_mt5.symbol_info.return_value = MockSymbolInfo(bid=1.12000, ask=1.12050, digits=5)  # Spread: 0.00050
        acceptable, reason, spread, max_allowed = nf.is_spread_acceptable('EURUSD')

        assert acceptable is False
        assert spread == pytest.approx(0.00050, abs=1e-5)
        assert "EXCEEDS_MAX" in reason


def test_spread_acceptable_custom_threshold():
    """Custom threshold can be passed explicitly."""
    nf = NewsFilter(auto_fetch_live=False)

    with patch('services.news_filter.mt5') as mock_mt5:
        # XAUUSD: spread = $1.50 USD
        mock_mt5.symbol_info.return_value = MockSymbolInfo(bid=4050.00, ask=4051.50, digits=2)
        
        # Default is $1.00 -> should fail
        acc_default, _, _, _ = nf.is_spread_acceptable('XAUUSD')
        assert acc_default is False

        # Custom threshold of $2.00 -> should pass
        acc_custom, _, _, _ = nf.is_spread_acceptable('XAUUSD', max_spread=2.00)
        assert acc_custom is True


def test_spread_acceptable_graceful_on_missing_tick():
    """When MT5 tick is unavailable, defaults to True to avoid freezing engine."""
    nf = NewsFilter(auto_fetch_live=False)

    with patch('services.news_filter.mt5') as mock_mt5:
        mock_mt5.symbol_info.return_value = None
        mock_mt5.symbol_info_tick.return_value = None
        acceptable, reason, spread, max_allowed = nf.is_spread_acceptable('BTCEUR')

        assert acceptable is True
        assert "NO_TICK" in reason


# ── Test Suite 3: Active Trade Guard (Pre-News Position Shield) ───────────────

def test_active_trade_guard_lock_breakeven_buy():
    """Profitable BUY position approaching high-impact news gets locked to BE."""
    nf = NewsFilter(cache_path="nonexistent_cache.json", auto_fetch_live=False)

    # NFP at 13:30 UTC
    now = datetime(2026, 11, 6, 13, 20, tzinfo=timezone.utc)  # 10 minutes prior

    # BUY opened at 4000.0, now at 4020.0, current SL is at 3980.0
    prot = nf.get_position_news_protection(
        symbol="XAUUSD",
        open_price=4000.0,
        current_price=4020.0,
        current_sl=3980.0,
        pos_type="BUY",
        window_minutes=15,
        check_time=now
    )

    assert prot['action'] == 'LOCK_BREAKEVEN'
    assert prot['recommended_sl'] == 4000.0
    assert "NFP" in prot['event_name']
    assert prot['minutes_until'] == 10


def test_active_trade_guard_lock_breakeven_sell():
    """Profitable SELL position approaching high-impact news gets locked to BE."""
    nf = NewsFilter(cache_path="nonexistent_cache.json", auto_fetch_live=False)

    now = datetime(2026, 11, 6, 13, 20, tzinfo=timezone.utc)  # 10 minutes prior

    # SELL opened at 4020.0, now at 4000.0, current SL is at 4040.0
    prot = nf.get_position_news_protection(
        symbol="XAUUSD",
        open_price=4020.0,
        current_price=4000.0,
        current_sl=4040.0,
        pos_type="SELL",
        window_minutes=15,
        check_time=now
    )

    assert prot['action'] == 'LOCK_BREAKEVEN'
    assert prot['recommended_sl'] == 4020.0
    assert "NFP" in prot['event_name']


def test_active_trade_guard_already_secured():
    """Position already secured at or above Break-Even reports SAFE."""
    nf = NewsFilter(cache_path="nonexistent_cache.json", auto_fetch_live=False)

    now = datetime(2026, 11, 6, 13, 20, tzinfo=timezone.utc)

    # BUY opened at 4000.0, now at 4020.0, current SL is already at 4005.0 (guaranteed profit)
    prot = nf.get_position_news_protection(
        symbol="XAUUSD",
        open_price=4000.0,
        current_price=4020.0,
        current_sl=4005.0,
        pos_type="BUY",
        window_minutes=15,
        check_time=now
    )

    assert prot['action'] == 'SAFE'


def test_active_trade_guard_unprofitable():
    """Position currently in loss reports WARNING."""
    nf = NewsFilter(cache_path="nonexistent_cache.json", auto_fetch_live=False)

    now = datetime(2026, 11, 6, 13, 20, tzinfo=timezone.utc)

    # BUY opened at 4000.0, now at 3990.0 (in loss)
    prot = nf.get_position_news_protection(
        symbol="XAUUSD",
        open_price=4000.0,
        current_price=3990.0,
        current_sl=3980.0,
        pos_type="BUY",
        window_minutes=15,
        check_time=now
    )

    assert prot['action'] == 'WARNING'


def test_active_trade_guard_no_news():
    """When no event is near the window, reports NO_NEWS."""
    nf = NewsFilter(cache_path="nonexistent_cache.json", auto_fetch_live=False)

    now = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)  # Several hours before NFP

    prot = nf.get_position_news_protection(
        symbol="XAUUSD",
        open_price=4000.0,
        current_price=4020.0,
        current_sl=3980.0,
        pos_type="BUY",
        window_minutes=15,
        check_time=now
    )

    assert prot['action'] == 'NO_NEWS'


# ── Test Suite 4: Trailing Stops Pre-News BE Integration ─────────────────────

def test_trailing_stop_executes_breakeven_on_news_shield():
    """TrailingStopManager triggers _execute_breakeven when Active Trade Guard advises LOCK_BREAKEVEN."""
    from services.trailing_stops import TrailingStopManager

    tsm = TrailingStopManager(config={'enabled': True})
    # Position with small profit (+0.2R, where standard BE at 0.8R does NOT trigger yet)
    pos = MockPosition(
        ticket=998877,
        symbol="XAUUSD",
        entry_price=4000.0,
        current_price=4004.0,  # +$4 profit (initial risk is $20: 0.2R)
        sl=3980.0,
        tp=4050.0,
        pos_type=0
    )

    # Register in active trails
    tsm.active_trails[998877] = {
        'ticket': 998877,
        'symbol': "XAUUSD",
        'trade_type': "BUY",
        'entry_price': 4000.0,
        'original_sl': 3980.0,
        'original_tp': 4050.0,
        'current_sl': 3980.0,
        'breakeven_moved': False,
        'trailing_active': False,
        'partial_closed': False,
        'highest_profit': 0.0,
    }

    # Mock NewsFilter to return LOCK_BREAKEVEN
    mock_nf = MagicMock()
    mock_nf.get_position_news_protection.return_value = {
        'action': 'LOCK_BREAKEVEN',
        'recommended_sl': 4000.0,
        'reason': 'Locking BE before NFP'
    }

    with patch('services.news_filter.get_news_filter', return_value=mock_nf):
        with patch.object(tsm, '_execute_breakeven') as mock_exec_be:
            with patch('services.trailing_stops.mt5') as mock_mt5:
                mock_mt5.symbol_info.return_value = MagicMock(point=0.001, spread=150, volume_min=0.01)
                tsm.update_single_trailing_stop(pos)

                # Verify _execute_breakeven was called exactly once due to news shield
                mock_exec_be.assert_called_once()
