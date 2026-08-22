"""
Sistema de Trailing Stops automático para el bot de trading MT5
Protege ganancias y optimiza salidas
"""

import MetaTrader5 as mt5
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

class TrailingStopManager:
    """Gestor de trailing stops automático"""
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.active_trails = {}  # {ticket: trail_info}
        
    def add_position_to_trail(self, ticket: int, symbol: str, entry_price: float, 
                             original_sl: float, original_tp: float, trade_type: str):
        """Añade una posición al sistema de trailing stops"""
        try:
            self.active_trails[ticket] = {
                'symbol': symbol,
                'entry_price': entry_price,
                'original_sl': original_sl,
                'original_tp': original_tp,
                'trade_type': trade_type,  # 'BUY' or 'SELL'
                'current_sl': original_sl,
                'highest_profit': 0.0,
                'breakeven_moved': False,
                'trailing_active': False,
                'partial_closed': False,
                'created_at': datetime.now(timezone.utc)
            }
            logger.info(f"Posición {ticket} añadida al trailing stop system")
            
        except Exception as e:
            logger.exception(f"Error añadiendo posición {ticket} al trailing: {e}")
    
    def update_all_trailing_stops(self):
        """Actualiza todos los trailing stops activos"""
        try:
            # Obtener posiciones abiertas
            positions = mt5.positions_get()
            if not positions:
                # Limpiar trails de posiciones cerradas
                self.active_trails.clear()
                return
            
            open_tickets = {pos.ticket for pos in positions}
            
            # Limpiar trails de posiciones cerradas
            closed_tickets = set(self.active_trails.keys()) - open_tickets
            for ticket in closed_tickets:
                del self.active_trails[ticket]
                logger.info(f"Trailing stop removido para posición cerrada {ticket}")
            
            # Actualizar trails activos
            for pos in positions:
                if pos.ticket in self.active_trails:
                    self.update_single_trailing_stop(pos)
                    
        except Exception as e:
            logger.exception(f"Error actualizando trailing stops: {e}")
    
    def update_single_trailing_stop(self, position):
        """Actualiza el trailing stop de una posición específica"""
        try:
            ticket = position.ticket
            trail_info = self.active_trails[ticket]
            
            current_price = position.price_current
            entry_price = trail_info['entry_price']
            original_tp = trail_info['original_tp']
            trade_type = trail_info['trade_type']
            
            # Calcular profit actual
            if trade_type == 'BUY':
                profit_points = current_price - entry_price
                tp_distance = original_tp - entry_price
            else:  # SELL
                profit_points = entry_price - current_price
                tp_distance = entry_price - original_tp
            
            profit_percentage = (profit_points / tp_distance) if tp_distance != 0 else 0
            
            # Actualizar máximo profit
            trail_info['highest_profit'] = max(trail_info['highest_profit'], profit_percentage)
            
            # 1. Mover SL a breakeven cuando profit >= 50% del TP
            if not trail_info['breakeven_moved'] and profit_percentage >= 0.5:
                new_sl = entry_price
                if self.modify_stop_loss(ticket, new_sl):
                    trail_info['breakeven_moved'] = True
                    trail_info['current_sl'] = new_sl
                    logger.info(f"SL movido a breakeven para {ticket} (profit: {profit_percentage:.1%})")
            
            # 2. Activar trailing cuando profit >= 75% del TP
            if not trail_info['trailing_active'] and profit_percentage >= 0.75:
                trail_info['trailing_active'] = True
                logger.info(f"Trailing stop activado para {ticket} (profit: {profit_percentage:.1%})")
            
            # 3. Cierre parcial cuando profit >= 100% del TP
            if not trail_info['partial_closed'] and profit_percentage >= 1.0:
                if self.partial_close_position(ticket, 0.5):  # Cerrar 50%
                    trail_info['partial_closed'] = True
                    logger.info(f"Cierre parcial 50% ejecutado para {ticket}")
            
            # 4. Aplicar trailing stop si está activo
            if trail_info['trailing_active']:
                self.apply_trailing_logic(position, trail_info)
                
        except Exception as e:
            logger.exception(f"Error actualizando trailing stop para {position.ticket}: {e}")
    
    def apply_trailing_logic(self, position, trail_info):
        """Aplica la lógica de trailing stop"""
        try:
            ticket = position.ticket
            current_price = position.price_current
            current_sl = trail_info['current_sl']
            trade_type = trail_info['trade_type']
            symbol = trail_info['symbol']
            
            # Obtener información del símbolo para calcular trailing distance
            symbol_info = mt5.symbol_info(symbol)
            if not symbol_info:
                return
            
            point = symbol_info.point
            
            # Distancia de trailing en puntos (configurable por símbolo)
            trailing_distances = {
                'EURUSD': 150,   # 15 pips
                'XAUUSD': 500,   # 50 cents
                'BTCEUR': 5000   # 500 puntos
            }
            
            trailing_distance = trailing_distances.get(symbol, 200) * point
            
            # Calcular nuevo SL
            if trade_type == 'BUY':
                new_sl = current_price - trailing_distance
                # Solo mover SL si es mejor que el actual
                if new_sl > current_sl:
                    if self.modify_stop_loss(ticket, new_sl):
                        trail_info['current_sl'] = new_sl
                        logger.info(f"Trailing SL actualizado para {ticket}: {new_sl:.5f}")
            
            else:  # SELL
                new_sl = current_price + trailing_distance
                # Solo mover SL si es mejor que el actual
                if new_sl < current_sl:
                    if self.modify_stop_loss(ticket, new_sl):
                        trail_info['current_sl'] = new_sl
                        logger.info(f"Trailing SL actualizado para {ticket}: {new_sl:.5f}")
                        
        except Exception as e:
            logger.exception(f"Error aplicando trailing logic para {position.ticket}: {e}")
    
    def modify_stop_loss(self, ticket: int, new_sl: float) -> bool:
        """Modifica el stop loss de una posición"""
        try:
            # Obtener la posición actual
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                return False
            
            position = positions[0]
            
            # Crear request de modificación
            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "sl": new_sl,
                "tp": position.tp,
            }
            
            # Enviar request
            result = mt5.order_send(request)
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                return True
            else:
                logger.warning(f"Error modificando SL para {ticket}: {result.comment}")
                return False
                
        except Exception as e:
            logger.exception(f"Error modificando SL para {ticket}: {e}")
            return False
    
    def partial_close_position(self, ticket: int, close_percentage: float) -> bool:
        """Cierra parcialmente una posición"""
        try:
            # Obtener la posición actual
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                return False
            
            position = positions[0]
            
            # Calcular volumen a cerrar
            close_volume = position.volume * close_percentage
            
            # Redondear al step del símbolo
            symbol_info = mt5.symbol_info(position.symbol)
            if symbol_info:
                volume_step = symbol_info.volume_step
                close_volume = round(close_volume / volume_step) * volume_step
                close_volume = max(close_volume, symbol_info.volume_min)
            
            # Determinar tipo de orden de cierre
            if position.type == 0:  # BUY position
                order_type = mt5.ORDER_TYPE_SELL
            else:  # SELL position
                order_type = mt5.ORDER_TYPE_BUY
            
            # Crear request de cierre parcial
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": position.symbol,
                "volume": close_volume,
                "type": order_type,
                "deviation": 20,
                "magic": 0,
                "comment": "Partial close - trailing stop",
            }
            
            # Enviar request
            result = mt5.order_send(request)
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"Cierre parcial exitoso para {ticket}: {close_volume} lots")
                return True
            else:
                logger.warning(f"Error en cierre parcial para {ticket}: {result.comment}")
                return False
                
        except Exception as e:
            logger.exception(f"Error en cierre parcial para {ticket}: {e}")
            return False
    
    def get_trailing_status(self) -> Dict:
        """Obtiene el estado de todos los trailing stops"""
        try:
            status = {
                'active_trails': len(self.active_trails),
                'positions': []
            }
            
            for ticket, trail_info in self.active_trails.items():
                status['positions'].append({
                    'ticket': ticket,
                    'symbol': trail_info['symbol'],
                    'breakeven_moved': trail_info['breakeven_moved'],
                    'trailing_active': trail_info['trailing_active'],
                    'partial_closed': trail_info['partial_closed'],
                    'highest_profit': trail_info['highest_profit']
                })
            
            return status
            
        except Exception as e:
            logger.exception(f"Error obteniendo trailing status: {e}")
            return {'active_trails': 0, 'positions': []}
    
    def remove_position(self, ticket: int):
        """Remueve una posición del sistema de trailing"""
        if ticket in self.active_trails:
            del self.active_trails[ticket]
            logger.info(f"Posición {ticket} removida del trailing system")


# Instancia global del trailing stop manager
trailing_manager = TrailingStopManager()

def get_trailing_manager() -> TrailingStopManager:
    """Obtiene la instancia del trailing manager"""
    return trailing_manager