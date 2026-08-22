"""
Servicio de Ejecución de Trades Consolidado

Consolida toda la lógica de ejecución que estaba fragmentada en:
- bot.py (funciones de ejecución)
- position_manager.py
- Otros archivos relacionados con MT5
"""

import logging
import os
from datetime import datetime, timezone
import time
from typing import Dict, Optional, Tuple, List, Any
from dataclasses import dataclass
import MetaTrader5 as mt5

# Imports locales
from services.mt5_client import initialize as mt5_initialize, place_order, shutdown as mt5_shutdown
from core.risk import RiskManager, get_risk_manager

logger = logging.getLogger(__name__)

@dataclass
class ExecutionResult:
    """Resultado de ejecución de una orden"""
    success: bool
    order_id: Optional[int]
    message: str
    details: Dict
    execution_time: datetime

@dataclass
class PositionInfo:
    """Información de una posición abierta"""
    ticket: int
    symbol: str
    type: str
    volume: float
    open_price: float
    current_price: float
    sl: float
    tp: float
    profit: float
    swap: float
    comment: str
    open_time: datetime

class ExecutionService:
    """
    Servicio consolidado de ejecución de trades
    
    Responsabilidades:
    - Ejecución de órdenes MT5
    - Gestión de posiciones
    - Cálculo de tamaños de lote
    - Validación pre-ejecución
    - Logging de operaciones
    """
    
    def __init__(self):
        self.risk_manager = get_risk_manager()
        self.auto_execute_enabled = os.getenv('AUTO_EXECUTE_SIGNALS', '0') == '1'
        self.auto_execute_confidence = os.getenv('AUTO_EXECUTE_CONFIDENCE', 'HIGH')
        
        # Configuración de ejecución
        self.execution_config = {
            'max_slippage': int(os.getenv('MAX_SLIPPAGE', '3')),  # pips
            'order_timeout': int(os.getenv('ORDER_TIMEOUT', '30')),  # segundos
            'retry_attempts': int(os.getenv('RETRY_ATTEMPTS', '3')),
            'min_lot_size': float(os.getenv('MIN_LOT_SIZE', '0.01')),
            'max_lot_size': float(os.getenv('MAX_LOT_SIZE', '1.0'))
        }
        
        # Estadísticas de ejecución
        self.execution_stats = {
            'orders_attempted': 0,
            'orders_successful': 0,
            'orders_failed': 0,
            'total_volume': 0.0,
            'symbols_traded': set()
        }
    
    def execute_signal(self, signal: Dict, lot_size: float = None, 
                      force_execute: bool = False) -> ExecutionResult:
        """
        Ejecuta una señal de trading
        
        Args:
            signal: Diccionario con datos de la señal
            lot_size: Tamaño de lote específico (opcional)
            force_execute: Forzar ejecución sin validaciones adicionales
            
        Returns:
            ExecutionResult con resultado de la ejecución
        """
        execution_time = datetime.now(timezone.utc)
        
        try:
            # Validar señal
            validation_result = self._validate_signal(signal)
            if not validation_result['valid'] and not force_execute:
                return ExecutionResult(
                    success=False,
                    order_id=None,
                    message=f"Signal validation failed: {validation_result['reason']}",
                    details=validation_result,
                    execution_time=execution_time
                )
            
            # Conectar a MT5
            if not self._ensure_mt5_connection():
                return ExecutionResult(
                    success=False,
                    order_id=None,
                    message="MT5 connection failed",
                    details={'error': 'connection_failed'},
                    execution_time=execution_time
                )
            
            # Calcular tamaño de lote si no se especifica
            if lot_size is None:
                lot_calculation = self._calculate_lot_size(signal)
                if not lot_calculation['success']:
                    return ExecutionResult(
                        success=False,
                        order_id=None,
                        message=f"Lot calculation failed: {lot_calculation['reason']}",
                        details=lot_calculation,
                        execution_time=execution_time
                    )
                lot_size = lot_calculation['lot_size']
            
            # Validar tamaño de lote
            lot_size = self._validate_lot_size(signal['symbol'], lot_size)
            
            # Preparar orden
            order_request = self._prepare_order_request(signal, lot_size)
            
            # Ejecutar orden con reintentos
            execution_result = self._execute_order_with_retries(order_request)
            
            # Actualizar estadísticas
            self._update_execution_stats(signal, lot_size, execution_result['success'])

            journal_id = None
            try:
                from core.journal import get_journal
                
                # Obtener detalles de ejecución
                req_price = execution_result.get('requested_price', float(signal['entry']))
                exec_price = execution_result.get('executed_price', req_price)
                symbol = signal.get('symbol', 'EURUSD').upper()
                sig_type = signal.get('type', 'BUY').upper()
                
                # Calcular pip_size dinámico
                pip_sizes = {'EURUSD': 0.0001, 'GBPUSD': 0.0001, 'USDJPY': 0.01, 'XAUUSD': 0.1, 'BTCEUR': 1.0, 'BTCUSDT': 1.0}
                pip_size = pip_sizes.get(symbol, 0.0001)
                
                # Slippage con signo (Positivo = Adverso / Desfavorable, Negativo = Favorable)
                if sig_type == 'BUY':
                    slippage_pips = (exec_price - req_price) / pip_size
                else:
                    slippage_pips = (req_price - exec_price) / pip_size
                    
                # Coste aproximado del slippage en EUR
                slippage_cost_eur = slippage_pips * (lot_size * 10.0) if symbol in ('EURUSD', 'GBPUSD') else (slippage_pips * lot_size)
                
                # Captura de spread en apertura y límite de spread
                spread_open_pips = None
                max_allowed_spread = float(signal.get('max_allowed_spread_pips') or signal.get('max_spread') or 3.0)
                try:
                    tick = mt5.symbol_info_tick(symbol)
                    if tick and tick.bid > 0 and tick.ask > 0:
                        spread_open_pips = round((tick.ask - tick.bid) / pip_size, 2)
                except Exception as tick_err:
                    logger.debug(f"Error al obtener tick spread en apertura para {symbol}: {tick_err}")
                
                # Determinar sesión de mercado actual
                utc_hour = datetime.now(timezone.utc).hour
                if 8 <= utc_hour < 12:
                    exec_session = 'LONDON'
                elif 12 <= utc_hour < 16:
                    exec_session = 'OVERLAP'
                elif 16 <= utc_hour < 21:
                    exec_session = 'NEWYORK'
                elif 21 <= utc_hour < 23:
                    exec_session = 'NIGHT'
                else:
                    exec_session = 'ASIAN'

                # Estado de ejecución y códigos de retorno
                exec_status = 'SUCCESS' if execution_result['success'] else 'FAILED'
                exec_error = None if execution_result['success'] else execution_result.get('message')
                mt5_retcode = execution_result.get('retcode')
                mt5_res = execution_result.get('mt5_result')
                if isinstance(mt5_res, dict) and 'retcode' in mt5_res:
                    mt5_retcode = mt5_res['retcode']

                journal_id = get_journal().log_entry(
                    signal,
                    confidence=str(signal.get('confidence', 'MEDIUM')),
                    confidence_score=float(signal.get('confidence_score', 0) or 0),
                    score=float(signal.get('score', 0) or 0),
                    lot_size=lot_size,
                    mt5_ticket=execution_result.get('order_id'),
                    mode='live',
                    notes='Ejecutado vía ExecutionService',
                    requested_price=req_price,
                    executed_price=exec_price,
                    slippage_pips=round(slippage_pips, 2),
                    slippage_cost_eur=round(slippage_cost_eur, 2),
                    spread_open_pips=spread_open_pips,
                    max_allowed_spread_pips=max_allowed_spread,
                    latency_ms=execution_result.get('latency_ms'),
                    fill_time_ms=execution_result.get('latency_ms'),
                    execution_session=exec_session,
                    execution_status=exec_status,
                    execution_error=exec_error,
                    mt5_retcode=mt5_retcode,
                    broker_message=execution_result.get('broker_message')
                )
            except Exception as journal_err:
                logger.warning(f"Trade journal log_entry error: {journal_err}")

            return ExecutionResult(
                success=execution_result['success'],
                order_id=execution_result.get('order_id'),
                message=execution_result['message'],
                details={
                    'signal': signal,
                    'lot_size': lot_size,
                    'order_request': order_request,
                    'mt5_result': execution_result.get('mt5_result'),
                    'validation': validation_result,
                    'journal_id': journal_id,
                },
                execution_time=execution_time
            )
            
        except Exception as e:
            logger.error(f"Error executing signal: {e}")
            return ExecutionResult(
                success=False,
                order_id=None,
                message=f"Execution error: {str(e)}",
                details={'error': str(e), 'signal': signal},
                execution_time=execution_time
            )
    
    def should_auto_execute(self, signal: Dict) -> Tuple[bool, str]:
        """
        Determina si una señal debe ejecutarse automáticamente
        
        Args:
            signal: Diccionario con datos de la señal
            
        Returns:
            (should_execute, reason)
        """
        if not self.auto_execute_enabled:
            return False, "Auto-execution disabled"
        
        # Verificar nivel de confianza
        signal_confidence = signal.get('confidence', 'MEDIUM')
        required_confidence = self.auto_execute_confidence
        
        confidence_levels = ['LOW', 'MEDIUM', 'MEDIUM-HIGH', 'HIGH', 'VERY_HIGH']
        
        try:
            signal_level = confidence_levels.index(signal_confidence)
            required_level = confidence_levels.index(required_confidence)
            
            if signal_level < required_level:
                return False, f"Confidence too low ({signal_confidence} < {required_confidence})"
        except ValueError:
            return False, f"Invalid confidence level: {signal_confidence}"
        
        # Verificar otras condiciones
        if not signal.get('symbol'):
            return False, "No symbol specified"
        
        if not all(key in signal for key in ['entry', 'sl', 'tp']):
            return False, "Missing price levels"
        
        # Verificar evaluación de riesgo
        risk_assessment = self.risk_manager.assess_signal_risk(signal)
        if not risk_assessment.approved:
            return False, f"Risk assessment failed: {risk_assessment.reason}"
        
        return True, "Auto-execution approved"
    
    def get_open_positions(self, symbol: str = None) -> List[PositionInfo]:
        """
        Obtiene posiciones abiertas
        
        Args:
            symbol: Filtrar por símbolo específico (opcional)
            
        Returns:
            Lista de PositionInfo
        """
        try:
            if not self._ensure_mt5_connection():
                return []
            
            # Obtener posiciones de MT5
            if symbol:
                positions = mt5.positions_get(symbol=symbol)
            else:
                positions = mt5.positions_get()
            
            if positions is None:
                return []
            
            # Convertir a PositionInfo
            position_list = []
            for pos in positions:
                position_info = PositionInfo(
                    ticket=pos.ticket,
                    symbol=pos.symbol,
                    type='BUY' if pos.type == mt5.ORDER_TYPE_BUY else 'SELL',
                    volume=pos.volume,
                    open_price=pos.price_open,
                    current_price=pos.price_current,
                    sl=pos.sl,
                    tp=pos.tp,
                    profit=pos.profit,
                    swap=pos.swap,
                    comment=pos.comment,
                    open_time=datetime.fromtimestamp(pos.time, tz=timezone.utc)
                )
                position_list.append(position_info)
            
            return position_list
            
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return []
    
    def close_position(self, ticket: int, reason: str = "Manual close") -> ExecutionResult:
        """
        Cierra una posición específica
        
        Args:
            ticket: Ticket de la posición
            reason: Razón del cierre
            
        Returns:
            ExecutionResult con resultado del cierre
        """
        execution_time = datetime.now(timezone.utc)
        
        try:
            if not self._ensure_mt5_connection():
                return ExecutionResult(
                    success=False,
                    order_id=None,
                    message="MT5 connection failed",
                    details={'error': 'connection_failed'},
                    execution_time=execution_time
                )
            
            # Obtener información de la posición
            position = mt5.positions_get(ticket=ticket)
            if not position:
                return ExecutionResult(
                    success=False,
                    order_id=None,
                    message=f"Position {ticket} not found",
                    details={'ticket': ticket},
                    execution_time=execution_time
                )
            
            pos = position[0]
            
            # Preparar orden de cierre
            close_request = {
                'action': mt5.TRADE_ACTION_DEAL,
                'symbol': pos.symbol,
                'volume': pos.volume,
                'type': mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                'position': ticket,
                'deviation': self.execution_config['max_slippage'],
                'magic': 0,
                'comment': f"Close: {reason}",
                'type_time': mt5.ORDER_TIME_GTC,
                'type_filling': mt5.ORDER_FILLING_IOC,
            }
            
            # Ejecutar cierre
            result = mt5.order_send(close_request)
            
            if result is None:
                return ExecutionResult(
                    success=False,
                    order_id=None,
                    message="Order send failed",
                    details={'close_request': close_request},
                    execution_time=execution_time
                )
            
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                return ExecutionResult(
                    success=False,
                    order_id=result.order,
                    message=f"Close failed: {result.comment}",
                    details={'mt5_result': result._asdict(), 'close_request': close_request},
                    execution_time=execution_time
                )
            
            return ExecutionResult(
                success=True,
                order_id=result.order,
                message=f"Position {ticket} closed successfully",
                details={
                    'ticket': ticket,
                    'symbol': pos.symbol,
                    'volume': pos.volume,
                    'profit': pos.profit,
                    'mt5_result': result._asdict()
                },
                execution_time=execution_time
            )
            
        except Exception as e:
            logger.error(f"Error closing position {ticket}: {e}")
            return ExecutionResult(
                success=False,
                order_id=None,
                message=f"Close error: {str(e)}",
                details={'error': str(e), 'ticket': ticket},
                execution_time=execution_time
            )
    
    def _validate_signal(self, signal: Dict) -> Dict:
        """Valida una señal antes de la ejecución"""
        try:
            # Verificar campos requeridos
            required_fields = ['symbol', 'type', 'entry', 'sl']
            missing_fields = [field for field in required_fields if field not in signal]
            
            if missing_fields:
                return {
                    'valid': False,
                    'reason': f"Missing required fields: {missing_fields}"
                }
            
            # Verificar valores numéricos
            numeric_fields = ['entry', 'sl', 'tp']
            for field in numeric_fields:
                if field in signal:
                    try:
                        float(signal[field])
                    except (ValueError, TypeError):
                        return {
                            'valid': False,
                            'reason': f"Invalid numeric value for {field}: {signal[field]}"
                        }
            
            # Verificar tipo de orden
            if signal['type'] not in ['BUY', 'SELL']:
                return {
                    'valid': False,
                    'reason': f"Invalid order type: {signal['type']}"
                }
            
            # Verificar que SL y entry sean diferentes
            entry = float(signal['entry'])
            sl = float(signal['sl'])
            
            if abs(entry - sl) < 0.00001:  # Prácticamente iguales
                return {
                    'valid': False,
                    'reason': "Entry and SL prices are too close"
                }
            
            # Verificar dirección lógica del SL
            if signal['type'] == 'BUY' and sl >= entry:
                return {
                    'valid': False,
                    'reason': "BUY order SL must be below entry price"
                }
            
            if signal['type'] == 'SELL' and sl <= entry:
                return {
                    'valid': False,
                    'reason': "SELL order SL must be above entry price"
                }
            
            return {'valid': True, 'reason': 'Signal validation passed'}
            
        except Exception as e:
            return {
                'valid': False,
                'reason': f"Validation error: {str(e)}"
            }
    
    def _calculate_lot_size(self, signal: Dict) -> Dict:
        """Calcula el tamaño de lote para una señal"""
        try:
            # Usar el risk manager para calcular
            risk_assessment = self.risk_manager.assess_signal_risk(signal)
            
            if not risk_assessment.approved:
                return {
                    'success': False,
                    'reason': risk_assessment.reason,
                    'lot_size': 0.0
                }
            
            if risk_assessment.parameters is None:
                return {
                    'success': False,
                    'reason': 'No risk parameters calculated',
                    'lot_size': 0.0
                }
            
            return {
                'success': True,
                'reason': 'Lot size calculated successfully',
                'lot_size': risk_assessment.parameters.suggested_lot,
                'risk_amount': risk_assessment.parameters.risk_amount,
                'rr_ratio': risk_assessment.parameters.rr_ratio
            }
            
        except Exception as e:
            logger.error(f"Error calculating lot size: {e}")
            return {
                'success': False,
                'reason': f'Calculation error: {str(e)}',
                'lot_size': 0.01  # Fallback mínimo
            }
    
    def _validate_lot_size(self, symbol: str, lot_size: float) -> float:
        """Valida y ajusta el tamaño de lote según las especificaciones del símbolo"""
        try:
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                logger.warning(f"No symbol info for {symbol}, using default limits")
                return max(self.execution_config['min_lot_size'], 
                          min(self.execution_config['max_lot_size'], lot_size))
            
            vol_min = symbol_info.volume_min
            vol_max = symbol_info.volume_max
            vol_step = symbol_info.volume_step
            
            # Ajustar al step más cercano
            steps = round(lot_size / vol_step)
            adjusted_lot = steps * vol_step
            
            # Aplicar límites
            final_lot = max(vol_min, min(vol_max, adjusted_lot))
            
            if final_lot != lot_size:
                logger.info(f"Lot size adjusted for {symbol}: {lot_size} -> {final_lot}")
            
            return final_lot
            
        except Exception as e:
            logger.error(f"Error validating lot size for {symbol}: {e}")
            return max(self.execution_config['min_lot_size'], 
                      min(self.execution_config['max_lot_size'], lot_size))
    
    def _prepare_order_request(self, signal: Dict, lot_size: float) -> Dict:
        """Prepara la request de orden para MT5"""
        symbol = signal['symbol']
        order_type = mt5.ORDER_TYPE_BUY if signal['type'] == 'BUY' else mt5.ORDER_TYPE_SELL
        
        request = {
            'action': mt5.TRADE_ACTION_DEAL,
            'symbol': symbol,
            'volume': lot_size,
            'type': order_type,
            'price': float(signal['entry']),
            'sl': float(signal['sl']),
            'deviation': self.execution_config['max_slippage'],
            'magic': 0,
            'comment': f"Bot: {signal.get('strategy', 'unknown')}",
            'type_time': mt5.ORDER_TIME_GTC,
            'type_filling': mt5.ORDER_FILLING_IOC,
        }
        
        # Añadir TP si está especificado
        if 'tp' in signal and signal['tp']:
            request['tp'] = float(signal['tp'])
        
        return request
    
    def _execute_order_with_retries(self, order_request: Dict) -> Dict:
        """Ejecuta orden con reintentos en caso de fallo"""
        last_error = None
        
        for attempt in range(self.execution_config['retry_attempts']):
            try:
                start_time = time.time()
                result = mt5.order_send(order_request)
                end_time = time.time()
                latency_ms = int((end_time - start_time) * 1000)
                
                if result is None:
                    last_error = "MT5 order_send returned None"
                    continue
                
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    return {
                        'success': True,
                        'message': 'Order executed successfully',
                        'order_id': result.order,
                        'mt5_result': result._asdict(),
                        'latency_ms': latency_ms,
                        'requested_price': order_request.get('price'),
                        'executed_price': result.price,
                        'broker_message': result.comment
                    }
                else:
                    last_error = f"MT5 error {result.retcode}: {result.comment}"
                    
                    # Si es un error de precio, intentar con precio actual
                    if result.retcode in [mt5.TRADE_RETCODE_PRICE_OFF, mt5.TRADE_RETCODE_INVALID_PRICE]:
                        order_type_str = 'SELL' if order_request.get('type') == mt5.ORDER_TYPE_SELL else 'BUY'
                        current_price = self._get_current_price(order_request['symbol'], order_type_str)
                        if current_price:
                            order_request['price'] = current_price
                            logger.info(f"Retrying with current price ({order_type_str}): {current_price}")
                            continue
                
            except Exception as e:
                last_error = f"Exception during order execution: {str(e)}"
                logger.error(f"Order execution attempt {attempt + 1} failed: {e}")
        
        return {
            'success': False,
            'message': f'Order failed after {self.execution_config["retry_attempts"]} attempts: {last_error}',
            'order_id': None,
            'broker_message': last_error
        }
    
    def _get_current_price(self, symbol: str, order_type: str = 'BUY') -> Optional[float]:
        """Obtiene el precio actual de un símbolo respetando la dirección de la orden"""
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return None
            
            if order_type.upper() == 'SELL':
                return tick.bid
            return tick.ask
            
        except Exception as e:
            logger.error(f"Error getting current price for {symbol}: {e}")
            return None
    
    def _ensure_mt5_connection(self) -> bool:
        """Asegura que la conexión MT5 esté activa"""
        try:
            # Verificar si ya está conectado
            if mt5.terminal_info() is not None:
                return True
            
            # Intentar conectar
            return mt5_initialize()
            
        except Exception as e:
            logger.error(f"MT5 connection error: {e}")
            return False
    
    def _update_execution_stats(self, signal: Dict, lot_size: float, success: bool):
        """Actualiza estadísticas de ejecución"""
        self.execution_stats['orders_attempted'] += 1
        
        if success:
            self.execution_stats['orders_successful'] += 1
            self.execution_stats['total_volume'] += lot_size
            self.execution_stats['symbols_traded'].add(signal['symbol'])
        else:
            self.execution_stats['orders_failed'] += 1
    
    def get_execution_statistics(self) -> Dict:
        """Obtiene estadísticas de ejecución"""
        total_orders = self.execution_stats['orders_attempted']
        success_rate = (self.execution_stats['orders_successful'] / total_orders * 100) if total_orders > 0 else 0
        
        return {
            'orders_attempted': self.execution_stats['orders_attempted'],
            'orders_successful': self.execution_stats['orders_successful'],
            'orders_failed': self.execution_stats['orders_failed'],
            'success_rate': success_rate,
            'total_volume': self.execution_stats['total_volume'],
            'symbols_traded': list(self.execution_stats['symbols_traded']),
            'auto_execute_enabled': self.auto_execute_enabled,
            'auto_execute_confidence': self.auto_execute_confidence,
            'execution_config': self.execution_config
        }

# Instancia global del servicio de ejecución
execution_service = ExecutionService()

def get_execution_service() -> ExecutionService:
    """Obtiene la instancia global del servicio de ejecución"""
    return execution_service