"""
Pruebas Unitarias y de Concurrencia para P1.1 Execution Quality & Broker Monitoring
"""

import os
import pytest
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

from core.journal import TradeJournal, get_journal
from services.execution import ExecutionService, ExecutionResult


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    journal = TradeJournal(db_path=path)
    yield path, journal
    try:
        os.remove(path)
    except OSError:
        pass


def test_trade_journal_p11_schema_migration(temp_db):
    db_path, journal = temp_db
    
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cols = {row['name'] for row in conn.execute("PRAGMA table_info(trade_journal)").fetchall()}
        
        required_p11_cols = {
            'slippage_pips',
            'slippage_cost_eur',
            'spread_open_pips',
            'spread_close_pips',
            'max_allowed_spread_pips',
            'latency_ms',
            'fill_time_ms',
            'execution_session',
            'execution_status',
            'execution_error',
            'mt5_retcode',
            'close_requested_price',
            'close_executed_price',
            'close_slippage_pips',
            'close_latency_ms',
            'commission',
            'swap',
        }
        
        for col in required_p11_cols:
            assert col in cols, f"Falta la columna {col} en trade_journal"


def test_log_entry_success_and_rejected(temp_db):
    db_path, journal = temp_db
    
    signal = {
        'symbol': 'EURUSD',
        'type': 'BUY',
        'entry': 1.0850,
        'sl': 1.0820,
        'tp': 1.0910,
        'strategy': 'eurusd_simple'
    }
    
    # 1. Trade Exitoso
    entry_id = journal.log_entry(
        signal,
        score=0.85,
        confidence='HIGH',
        lot_size=0.10,
        requested_price=1.0850,
        executed_price=1.0852,
        slippage_pips=0.2,
        slippage_cost_eur=2.00,
        spread_open_pips=1.2,
        max_allowed_spread_pips=3.0,
        latency_ms=45,
        fill_time_ms=45,
        execution_session='LONDON',
        execution_status='SUCCESS',
        mt5_retcode=10009
    )
    
    assert entry_id > 0
    
    # 2. Orden Rechazada
    rejected_id = journal.log_entry(
        signal,
        score=0.85,
        confidence='HIGH',
        lot_size=0.10,
        requested_price=1.0850,
        executed_price=None,
        slippage_pips=None,
        spread_open_pips=1.5,
        max_allowed_spread_pips=3.0,
        latency_ms=120,
        execution_session='LONDON',
        execution_status='REJECTED',
        execution_error='MT5 error 10015: Invalid Price',
        mt5_retcode=10015
    )
    
    assert rejected_id > 0
    
    summary = journal.get_execution_quality_summary(days=1)
    assert summary['total_orders'] == 2
    assert summary['successful_orders'] == 1
    assert summary['rejected_orders'] == 1
    assert summary['rejection_rate_pct'] == 50.0
    assert summary['avg_spread_pips'] == 1.35


def test_log_close_telemetry(temp_db):
    db_path, journal = temp_db
    
    signal = {'symbol': 'XAUUSD', 'type': 'SELL', 'entry': 2350.0, 'sl': 2360.0, 'tp': 2330.0}
    entry_id = journal.log_entry(signal, execution_status='SUCCESS')
    
    ok = journal.log_close(
        entry_id,
        result='WIN',
        close_price=2330.0,
        pnl_pips=200.0,
        pnl_eur=100.0,
        spread_close_pips=2.5,
        close_requested_price=2330.0,
        close_executed_price=2329.8,
        close_slippage_pips=-0.2,
        close_latency_ms=50,
        commission=-1.50,
        swap=-0.20
    )
    
    assert ok is True
    
    trades = journal.get_recent_trades(limit=1, symbol='XAUUSD')
    assert len(trades) == 1
    trade = trades[0]
    assert trade['result'] == 'WIN'
    assert trade['spread_close_pips'] == 2.5
    assert trade['close_slippage_pips'] == -0.2
    assert trade['commission'] == -1.50


def test_signed_slippage_calculation():
    service = ExecutionService()
    
    # BUY: req=1.0850, exec=1.0852 -> Slippage adverso (+0.2 pips)
    pip_size = 0.0001
    buy_req = 1.0850
    buy_exec = 1.0852
    buy_slippage = (buy_exec - buy_req) / pip_size
    assert round(buy_slippage, 1) == 2.0
    
    # SELL: req=1.0850, exec=1.0848 -> Slippage adverso (+0.2 pips)
    sell_req = 1.0850
    sell_exec = 1.0848
    sell_slippage = (sell_req - sell_exec) / pip_size
    assert round(sell_slippage, 1) == 2.0

    # SELL: req=1.0850, exec=1.0853 -> Slippage favorable (-0.3 pips)
    sell_fav_exec = 1.0853
    sell_fav_slippage = (sell_req - sell_fav_exec) / pip_size
    assert round(sell_fav_slippage, 1) == -3.0


def test_get_current_price_sell_bid_fix():
    service = ExecutionService()
    
    mock_tick = MagicMock()
    mock_tick.ask = 1.0855
    mock_tick.bid = 1.0853
    
    with patch("MetaTrader5.symbol_info_tick", return_value=mock_tick):
        buy_price = service._get_current_price("EURUSD", "BUY")
        sell_price = service._get_current_price("EURUSD", "SELL")
        
        assert buy_price == 1.0855
        assert sell_price == 1.0853
