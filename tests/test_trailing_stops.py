"""
Tests exhaustivos para TrailingStopManager
==========================================
Valida las 5 correcciones críticas identificadas en producción:
1. Tolerancia a micro-cortes (no borrado de memoria si positions_get() es None).
2. Auto-adopción de posiciones huérfanas al reiniciar el motor.
3. Cierre parcial seguro (price, filling mode, y protección contra cierre del 100% en lote mínimo).
4. Distancias de trailing en unidades reales de precio (independiente de dígitos/puntos).
5. Activación ágil de Breakeven y Trailing por R-múltiplos y porcentajes realistas.
6. Persistencia bidireccional en SQLite.
"""

import os
import tempfile
import pytest
from unittest.mock import MagicMock, patch

import MetaTrader5 as mt5

from services.database import DatabaseService
from services.trailing_stops import TrailingStopManager


@pytest.fixture
def temp_db():
    """Crea una base de datos temporal SQLite para los tests."""
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    
    db_service = DatabaseService(db_path)
    yield db_service
    
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass


@pytest.fixture
def trailing_mgr(temp_db):
    """Instancia de TrailingStopManager con base de datos aislada."""
    config = {
        'enabled': True,
        'breakeven_r_multiple': 0.8,
        'breakeven_at_profit_pct': 30,
        'trailing_start_r_multiple': 1.2,
        'trailing_start_pct': 50,
        'partial_close_r_multiple': 1.5,
        'partial_close_pct': 70,
        'partial_close_amount': 50,
        'price_distances': {
            'EURUSD': 0.0015,
            'XAUUSD': 5.0,
            'BTCEUR': 500.0
        }
    }
    return TrailingStopManager(config=config, db_service=temp_db)


def test_microcut_does_not_clear_active_trails(trailing_mgr):
    """TEST 1: Si mt5.positions_get() devuelve None por micro-corte, los trails NO se borran."""
    trailing_mgr.add_position_to_trail(
        ticket=12345,
        symbol="XAUUSD",
        entry_price=4036.79,
        original_sl=4050.00,
        original_tp=3950.00,
        trade_type="SELL"
    )
    assert 12345 in trailing_mgr.active_trails

    with patch('MetaTrader5.positions_get', return_value=None):
        with patch('MetaTrader5.last_error', return_value=(1, "Connection failed")):
            trailing_mgr.update_all_trailing_stops()

    # Debe seguir existiendo en memoria intacto
    assert 12345 in trailing_mgr.active_trails


def test_auto_adopt_orphan_position_on_restart(trailing_mgr):
    """TEST 2: Al reiniciar, si hay posiciones abiertas en MT5 no registradas en RAM, se auto-adoptan."""
    assert len(trailing_mgr.active_trails) == 0

    mock_pos = MagicMock()
    mock_pos.ticket = 999888
    mock_pos.symbol = "XAUUSD"
    mock_pos.price_open = 4036.79
    mock_pos.sl = 4036.79  # Ya estaba en breakeven
    mock_pos.tp = 3949.38
    mock_pos.type = 1  # mt5.ORDER_TYPE_SELL
    mock_pos.price_current = 4020.00
    mock_pos.volume = 0.02

    with patch('MetaTrader5.positions_get', return_value=[mock_pos]):
        trailing_mgr.update_all_trailing_stops()

    assert 999888 in trailing_mgr.active_trails
    adopted = trailing_mgr.active_trails[999888]
    assert adopted['symbol'] == 'XAUUSD'
    assert adopted['trade_type'] == 'SELL'
    assert adopted['breakeven_moved'] is True


def test_partial_close_prevents_closing_min_lot(trailing_mgr):
    """TEST 3A: No debe cerrar el 100% de una posición cuando el volumen es 0.01 (lote mínimo)."""
    mock_pos = MagicMock()
    mock_pos.ticket = 555
    mock_pos.symbol = "EURUSD"
    mock_pos.volume = 0.01
    mock_pos.type = 0  # BUY

    mock_sym = MagicMock()
    mock_sym.volume_min = 0.01
    mock_sym.volume_step = 0.01

    with patch('MetaTrader5.positions_get', return_value=[mock_pos]):
        with patch('MetaTrader5.symbol_info', return_value=mock_sym):
            with patch('MetaTrader5.order_send') as mock_send:
                result = trailing_mgr.partial_close_position(555, 0.5)
                assert result is False
                mock_send.assert_not_called()


def test_partial_close_sends_price_and_filling_mode(trailing_mgr):
    """TEST 3B: Cierre parcial para volumen divisible incluye 'price' y 'type_filling' válidos."""
    mock_pos = MagicMock()
    mock_pos.ticket = 777
    mock_pos.symbol = "XAUUSD"
    mock_pos.volume = 0.04
    mock_pos.type = 1  # SELL

    mock_sym = MagicMock()
    mock_sym.volume_min = 0.01
    mock_sym.volume_step = 0.01
    mock_sym.filling_mode = 2  # SYMBOL_FILLING_IOC

    mock_tick = MagicMock()
    mock_tick.ask = 4010.50
    mock_tick.bid = 4010.00

    mock_ret = MagicMock()
    mock_ret.retcode = 10009  # TRADE_RETCODE_DONE

    with patch('MetaTrader5.positions_get', return_value=[mock_pos]):
        with patch('MetaTrader5.symbol_info', return_value=mock_sym):
            with patch('MetaTrader5.symbol_info_tick', return_value=mock_tick):
                with patch('MetaTrader5.order_send', return_value=mock_ret) as mock_send:
                    result = trailing_mgr.partial_close_position(777, 0.5)
                    assert result is True
                    mock_send.assert_called_once()
                    req = mock_send.call_args[0][0]
                    assert req['price'] == 4010.50  # Ask para cerrar un SELL
                    assert req['volume'] == 0.02
                    assert req['type_filling'] == mt5.ORDER_FILLING_IOC


def test_gold_trailing_distance_in_dollars_not_cents(trailing_mgr):
    """TEST 4: Para XAUUSD, la distancia de trailing es en dólares ($5.00), no 50 centavos."""
    mock_pos = MagicMock()
    mock_pos.ticket = 111
    mock_pos.symbol = "XAUUSD"
    mock_pos.price_current = 4000.00
    mock_pos.sl = 4020.00
    mock_pos.type = 1  # SELL

    mock_sym = MagicMock()
    mock_sym.point = 0.001  # Bróker con 3 decimales
    mock_sym.digits = 3
    mock_sym.stops_level = 10

    trail_info = {
        'symbol': 'XAUUSD',
        'entry_price': 4030.00,
        'original_sl': 4050.00,  # Risk $20
        'trade_type': 'SELL',
        'current_sl': 4020.00,
        'trailing_active': True
    }

    with patch('MetaTrader5.symbol_info', return_value=mock_sym):
        with patch.object(trailing_mgr, 'modify_stop_loss', return_value=True) as mock_modify:
            trailing_mgr.apply_trailing_logic(mock_pos, trail_info)
            mock_modify.assert_called_once()
            new_sl = mock_modify.call_args[0][1]
            # Con $20 de riesgo original, dist_by_risk = 20 * 0.6 = $12.00
            # Current price 4000.00 + 12.00 = 4012.00 (mejora 4020.00)
            assert new_sl == pytest.approx(4012.00, 0.01)


def test_early_breakeven_and_trailing_activation(trailing_mgr):
    """TEST 5: Breakeven se activa ágilmente al alcanzar 0.8R y trailing al alcanzar 1.2R."""
    # SELL: Entry=4036.79, SL=4050.00 (R = $13.21), TP=3950.00 (TP dist = $86.79)
    trailing_mgr.add_position_to_trail(
        ticket=333,
        symbol="XAUUSD",
        entry_price=4036.79,
        original_sl=4050.00,
        original_tp=3950.00,
        trade_type="SELL"
    )

    mock_pos = MagicMock()
    mock_pos.ticket = 333
    mock_pos.symbol = "XAUUSD"
    mock_pos.sl = 4050.00
    mock_pos.price_open = 4036.79
    mock_pos.tp = 3950.00
    mock_pos.type = 1  # SELL
    mock_pos.volume = 0.02

    mock_sym = MagicMock()
    mock_sym.point = 0.001
    mock_sym.digits = 3
    mock_sym.spread = 20
    mock_sym.stops_level = 10

    # Escenario A: Precio cae a 4025.00 (Ganancia $11.79 -> 0.89R)
    # Debe activar Breakeven sin esperar al 50% del TP (que exigiría caer $43.40)
    mock_pos.price_current = 4025.00

    with patch('MetaTrader5.symbol_info', return_value=mock_sym):
        with patch.object(trailing_mgr, 'modify_stop_loss', return_value=True):
            trailing_mgr.update_single_trailing_stop(mock_pos)

    assert trailing_mgr.active_trails[333]['breakeven_moved'] is True
    assert trailing_mgr.active_trails[333]['trailing_active'] is False

    # Escenario B: Precio cae a 4018.00 (Ganancia $18.79 -> 1.42R)
    # Debe activar Trailing (> 1.2R) sin esperar al 75% del TP (que exigiría caer $65.10)
    mock_pos.price_current = 4018.00
    with patch('MetaTrader5.symbol_info', return_value=mock_sym):
        with patch.object(trailing_mgr, 'modify_stop_loss', return_value=True):
            trailing_mgr.update_single_trailing_stop(mock_pos)

    assert trailing_mgr.active_trails[333]['trailing_active'] is True


def test_sqlite_persistence_across_instances(temp_db):
    """TEST 6: Los trails guardados se recuperan correctamente en una nueva instancia del manager."""
    mgr1 = TrailingStopManager(db_service=temp_db)
    mgr1.add_position_to_trail(
        ticket=888,
        symbol="BTCEUR",
        entry_price=60000.0,
        original_sl=59000.0,
        original_tp=63000.0,
        trade_type="BUY"
    )
    mgr1.active_trails[888]['breakeven_moved'] = True
    mgr1.active_trails[888]['highest_profit'] = 1.15
    mgr1._persist_trail(888)

    # Crear una nueva instancia independiente conectada a la misma BD
    mgr2 = TrailingStopManager(db_service=temp_db)
    assert 888 in mgr2.active_trails
    loaded = mgr2.active_trails[888]
    assert loaded['symbol'] == 'BTCEUR'
    assert loaded['breakeven_moved'] is True
    assert loaded['highest_profit'] == 1.15
