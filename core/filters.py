"""
Sistema de Filtros Consolidado

Consolida todos los filtros que estaban fragmentados en múltiples archivos:
- Filtros de duplicados
- Filtros de riesgo
- Filtros de mercado
- Filtros de tiempo
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from collections import defaultdict
import pandas as pd

logger = logging.getLogger(__name__)

@dataclass
class FilterResult:
    """Resultado de aplicación de filtros"""
    passed: bool
    reason: str
    details: Dict
    filter_name: str

class ConsolidatedFilters:
    """
    Sistema consolidado de filtros que reemplaza la fragmentación anterior
    
    Integra:
    - Filtro de duplicados (de duplicate_filter.py)
    - Filtros de trading (de trading_filters.py)
    - Filtros de riesgo
    - Filtros temporales

    Los contadores de trades (diario y por período) son la ÚNICA fuente de verdad
    del BotState inyectado. Si no se inyecta estado, se usan contadores locales
    como fallback (útil en tests y backtest).
    """
    
    def __init__(self, bot_state=None):
        # Referencia opcional a BotState — fuente de verdad de contadores
        # Se puede inyectar después de la construcción vía set_bot_state()
        self._bot_state = bot_state

        # Configuración de filtros
        self.duplicate_config = {
            'time_window_minutes': 30,
            'max_history': 10,
            'price_tolerance_pct': 0.0005  # 0.05%
        }
        
        self.risk_config = {
            'max_trades_per_day': 3,
            'max_trades_per_period': 5,
            'min_rr_ratio': 1.5,
            'max_risk_per_trade_pct': 2.0
        }
        
        self.market_config = {
            'min_volatility_ratio': 0.8,
            'max_spread_pips': 3.0,
            'session_filters': {
                'EURUSD': ['london', 'newyork'],
                'XAUUSD': ['london_ny_overlap'],  # Solo overlap
                'BTCEUR': ['always']  # 24/7
            }
        }
        
        # Estado interno
        self.recent_signals = {}  # symbol -> list of recent signals

        # Contadores locales: solo se usan cuando no hay BotState inyectado
        # (tests, backtest, ejecución standalone).  NO leer directamente en
        # producción — usar _get_daily_count() / _get_period_count() en su lugar.
        self.daily_trades = defaultdict(int)
        self.period_trades = defaultdict(int)

        # Contadores de señales rechazadas para get_stats()
        self._rejected_signals: int = 0
        self._total_evaluated: int = 0

    def set_bot_state(self, bot_state) -> None:
        """
        Inyecta la referencia al BotState global.
        Llamar desde bot.py después de que ambos objetos estén creados:
            advanced_filter.set_bot_state(state)
        """
        self._bot_state = bot_state
        logger.info("ConsolidatedFilters: BotState inyectado — contadores unificados")
        
    def apply_all_filters(self, df: pd.DataFrame, signal: Dict, 
                         current_balance: float = 10000.0) -> Tuple[bool, str, Dict]:
        """
        Aplica todos los filtros en secuencia.

        Registra contadores globales de señales evaluadas y rechazadas para
        que get_stats() pueda devolver datos reales en lugar de ceros.
        
        Returns:
            (passed, reason, details)
        """
        symbol = signal.get('symbol', 'UNKNOWN')
        self._total_evaluated += 1
        
        # 1. Filtro de duplicados
        duplicate_result = self._filter_duplicates(signal, symbol)
        if not duplicate_result.passed:
            self._rejected_signals += 1
            return False, duplicate_result.reason, duplicate_result.details
        
        # 2. Filtro de límites de trading
        limits_result = self._filter_trading_limits(symbol)
        if not limits_result.passed:
            self._rejected_signals += 1
            return False, limits_result.reason, limits_result.details
        
        # 3. Filtro de riesgo
        risk_result = self._filter_risk(signal, current_balance)
        if not risk_result.passed:
            self._rejected_signals += 1
            return False, risk_result.reason, risk_result.details
        
        # 4. Filtro de condiciones de mercado
        market_result = self._filter_market_conditions(df, signal, symbol)
        if not market_result.passed:
            self._rejected_signals += 1
            return False, market_result.reason, market_result.details
        
        # 5. Filtro de sesión de trading
        session_result = self._filter_trading_session(symbol)
        if not session_result.passed:
            self._rejected_signals += 1
            return False, session_result.reason, session_result.details
        
        # Todos los filtros pasaron
        return True, "All filters passed", {
            'filters_applied': ['duplicates', 'limits', 'risk', 'market', 'session'],
            'symbol': symbol,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    def _filter_duplicates(self, signal: Dict, symbol: str) -> FilterResult:
        """Filtro de señales duplicadas consolidado"""
        try:
            current_time = datetime.now(timezone.utc)
            
            # Limpiar señales antiguas
            self._cleanup_old_signals(symbol, current_time)
            
            # Obtener señales recientes
            recent = self.recent_signals.get(symbol, [])
            
            # Verificar duplicados
            for recent_signal in recent:
                if self._signals_are_similar(signal, recent_signal['signal']):
                    time_diff = (current_time - recent_signal['timestamp']).total_seconds() / 60
                    return FilterResult(
                        passed=False,
                        reason=f"Duplicate signal ({time_diff:.1f}min ago)",
                        details={'time_diff_minutes': time_diff, 'similar_signal': recent_signal['signal']},
                        filter_name="duplicates"
                    )
            
            # Agregar señal actual al historial
            if symbol not in self.recent_signals:
                self.recent_signals[symbol] = []
            
            self.recent_signals[symbol].append({
                'signal': signal.copy(),
                'timestamp': current_time
            })
            
            # Mantener solo las más recientes
            max_history = self.duplicate_config['max_history']
            if len(self.recent_signals[symbol]) > max_history:
                self.recent_signals[symbol] = self.recent_signals[symbol][-max_history:]
            
            return FilterResult(
                passed=True,
                reason="Not duplicate",
                details={'recent_signals_count': len(recent)},
                filter_name="duplicates"
            )
            
        except Exception as e:
            logger.warning(f"Error en filtro de duplicados: {e}")
            return FilterResult(
                passed=True,  # En caso de error, permitir la señal
                reason=f"Duplicate filter error: {str(e)}",
                details={'error': str(e)},
                filter_name="duplicates"
            )
    
    def _filter_trading_limits(self, symbol: str) -> FilterResult:
        """
        Filtro de límites de trading diarios y por período.

        Lee los contadores desde BotState (fuente de verdad unificada) cuando
        está disponible. En modo standalone/test usa los contadores locales.
        """
        try:
            daily_count = self._get_daily_count()
            period_count = self._get_period_count()

            max_daily = self.risk_config['max_trades_per_day']
            max_period = self.risk_config['max_trades_per_period']
            
            # Verificar límite diario
            if daily_count >= max_daily:
                return FilterResult(
                    passed=False,
                    reason=f"Daily limit reached ({daily_count}/{max_daily})",
                    details={'daily_count': daily_count, 'max_daily': max_daily},
                    filter_name="limits"
                )
            
            # Verificar límite por período
            if period_count >= max_period:
                current_period = self._get_current_period()
                return FilterResult(
                    passed=False,
                    reason=f"Period limit reached ({period_count}/{max_period})",
                    details={'period_count': period_count, 'max_period': max_period, 'current_period': current_period},
                    filter_name="limits"
                )
            
            return FilterResult(
                passed=True,
                reason="Within trading limits",
                details={'daily_count': daily_count, 'period_count': period_count},
                filter_name="limits"
            )
            
        except Exception as e:
            logger.warning(f"Error en filtro de límites: {e}")
            return FilterResult(
                passed=True,
                reason=f"Limits filter error: {str(e)}",
                details={'error': str(e)},
                filter_name="limits"
            )

    # ------------------------------------------------------------------
    # Helpers de lectura de contadores — única lógica de acceso al estado
    # ------------------------------------------------------------------

    def _get_daily_count(self) -> int:
        """Devuelve el contador de trades hoy desde BotState o local."""
        if self._bot_state is not None:
            return int(getattr(self._bot_state, 'trades_today', 0))
        today = datetime.now(timezone.utc).date().isoformat()
        return self.daily_trades.get(today, 0)

    def _get_period_count(self) -> int:
        """Devuelve el contador de trades del período actual desde BotState o local."""
        if self._bot_state is not None:
            return int(getattr(self._bot_state, 'trades_current_period', 0))
        current_period = self._get_current_period()
        return self.period_trades.get(current_period, 0)
    
    def _filter_risk(self, signal: Dict, current_balance: float) -> FilterResult:
        """Filtro de gestión de riesgo"""
        try:
            entry = float(signal.get('entry', 0))
            sl = float(signal.get('sl', 0))
            tp = float(signal.get('tp', 0))
            
            if entry == 0 or sl == 0:
                return FilterResult(
                    passed=False,
                    reason="Invalid entry or SL price",
                    details={'entry': entry, 'sl': sl},
                    filter_name="risk"
                )
            
            # Verificar R:R ratio
            risk = abs(entry - sl)
            reward = abs(tp - entry) if tp != 0 else 0
            rr_ratio = reward / risk if risk > 0 else 0
            min_rr = self.risk_config['min_rr_ratio']
            
            if rr_ratio < min_rr:
                return FilterResult(
                    passed=False,
                    reason=f"Poor R:R ratio ({rr_ratio:.2f} < {min_rr})",
                    details={'rr_ratio': rr_ratio, 'min_rr': min_rr, 'risk': risk, 'reward': reward},
                    filter_name="risk"
                )
            
            # Verificar riesgo por trade
            max_risk_pct = self.risk_config['max_risk_per_trade_pct']
            risk_amount = current_balance * (max_risk_pct / 100)
            
            return FilterResult(
                passed=True,
                reason="Risk parameters acceptable",
                details={
                    'rr_ratio': rr_ratio,
                    'risk_amount': risk_amount,
                    'risk_pct': max_risk_pct
                },
                filter_name="risk"
            )
            
        except Exception as e:
            logger.warning(f"Error en filtro de riesgo: {e}")
            return FilterResult(
                passed=True,
                reason=f"Risk filter error: {str(e)}",
                details={'error': str(e)},
                filter_name="risk"
            )
    
    def _filter_market_conditions(self, df: pd.DataFrame, signal: Dict, symbol: str) -> FilterResult:
        """Filtro de condiciones de mercado"""
        try:
            if df is None or len(df) == 0:
                return FilterResult(
                    passed=False,
                    reason="No market data available",
                    details={},
                    filter_name="market"
                )
            
            last = df.iloc[-1]
            
            # Verificar volatilidad mínima
            if 'atr' in df.columns:
                atr_current = last['atr']
                atr_mean = df['atr'].tail(20).mean()
                volatility_ratio = atr_current / atr_mean if atr_mean > 0 else 1.0
                min_volatility = self.market_config['min_volatility_ratio']
                
                if volatility_ratio < min_volatility:
                    return FilterResult(
                        passed=False,
                        reason=f"Low volatility ({volatility_ratio:.2f} < {min_volatility})",
                        details={'volatility_ratio': volatility_ratio, 'min_volatility': min_volatility},
                        filter_name="market"
                    )
            
            # Verificar spread (si está disponible)
            if 'spread' in df.columns:
                current_spread = last['spread']
                max_spread = self.market_config['max_spread_pips']
                
                if current_spread > max_spread:
                    return FilterResult(
                        passed=False,
                        reason=f"High spread ({current_spread:.1f} > {max_spread})",
                        details={'current_spread': current_spread, 'max_spread': max_spread},
                        filter_name="market"
                    )
            
            return FilterResult(
                passed=True,
                reason="Market conditions acceptable",
                details={'symbol': symbol, 'data_points': len(df)},
                filter_name="market"
            )
            
        except Exception as e:
            logger.warning(f"Error en filtro de mercado: {e}")
            return FilterResult(
                passed=True,
                reason=f"Market filter error: {str(e)}",
                details={'error': str(e)},
                filter_name="market"
            )
    
    def _filter_trading_session(self, symbol: str) -> FilterResult:
        """Filtro de sesión de trading"""
        try:
            current_hour = datetime.now(timezone.utc).hour
            allowed_sessions = self.market_config['session_filters'].get(symbol, ['always'])
            
            if 'always' in allowed_sessions:
                return FilterResult(
                    passed=True,
                    reason="24/7 trading allowed",
                    details={'symbol': symbol, 'current_hour': current_hour},
                    filter_name="session"
                )
            
            # Definir sesiones
            sessions = {
                'london': range(8, 17),      # 8-17 GMT
                'newyork': range(13, 22),    # 13-22 GMT
                'london_ny_overlap': range(13, 17)  # 13-17 GMT (overlap)
            }
            
            # Verificar si estamos en alguna sesión permitida
            in_session = False
            active_session = None
            
            for session_name in allowed_sessions:
                if session_name in sessions:
                    if current_hour in sessions[session_name]:
                        in_session = True
                        active_session = session_name
                        break
            
            if not in_session:
                return FilterResult(
                    passed=False,
                    reason=f"Outside trading session (hour: {current_hour}, allowed: {allowed_sessions})",
                    details={
                        'current_hour': current_hour,
                        'allowed_sessions': allowed_sessions,
                        'symbol': symbol
                    },
                    filter_name="session"
                )
            
            return FilterResult(
                passed=True,
                reason=f"In trading session: {active_session}",
                details={
                    'active_session': active_session,
                    'current_hour': current_hour,
                    'symbol': symbol
                },
                filter_name="session"
            )
            
        except Exception as e:
            logger.warning(f"Error en filtro de sesión: {e}")
            return FilterResult(
                passed=True,
                reason=f"Session filter error: {str(e)}",
                details={'error': str(e)},
                filter_name="session"
            )
    
    def _cleanup_old_signals(self, symbol: str, current_time: datetime):
        """Limpia señales antiguas fuera de la ventana de tiempo"""
        if symbol not in self.recent_signals:
            return
        
        window_minutes = self.duplicate_config['time_window_minutes']
        cutoff_time = current_time - timedelta(minutes=window_minutes)
        
        self.recent_signals[symbol] = [
            s for s in self.recent_signals[symbol] 
            if s['timestamp'] > cutoff_time
        ]
    
    def _signals_are_similar(self, signal1: Dict, signal2: Dict) -> bool:
        """Compara si dos señales son similares"""
        try:
            # Mismo tipo de operación
            if signal1.get('type') != signal2.get('type'):
                return False
            
            # Precios similares
            entry1 = float(signal1.get('entry', 0))
            entry2 = float(signal2.get('entry', 0))
            
            tolerance_pct = self.duplicate_config['price_tolerance_pct']
            tolerance = entry1 * tolerance_pct
            
            return abs(entry1 - entry2) <= tolerance
            
        except Exception as e:
            logger.warning(f"Error comparando señales: {e}")
            return False
    
    def _get_current_period(self) -> str:
        """Obtiene el período actual (para límites de 12h)"""
        now = datetime.now(timezone.utc)
        date_str = now.date().isoformat()
        
        if now.hour < 12:
            return f"{date_str}_morning"
        else:
            return f"{date_str}_afternoon"
    
    def increment_trade_counters(self, symbol: str):
        """
        Incrementa contadores de trades después de ejecutar una señal.

        Cuando BotState está inyectado, delega completamente en él
        (bot.py sigue siendo la única fuente de verdad).
        En modo standalone/test, incrementa los contadores locales.
        """
        if self._bot_state is not None:
            # BotState es la fuente de verdad; bot.py ya incrementa sus contadores
            # en el momento de ejecución, así que solo registramos en el log.
            daily = getattr(self._bot_state, 'trades_today', '?')
            period = getattr(self._bot_state, 'trades_current_period', '?')
            logger.info(
                f"Trade counters (BotState): Daily {daily}, Period {period} | symbol={symbol}"
            )
        else:
            # Modo standalone — mantener contadores locales como fallback
            today = datetime.now(timezone.utc).date().isoformat()
            current_period = self._get_current_period()
            self.daily_trades[today] += 1
            self.period_trades[current_period] += 1
            logger.info(
                f"Trade counters (local): Daily {self.daily_trades[today]}, "
                f"Period {self.period_trades[current_period]} | symbol={symbol}"
            )
    
    def get_statistics(self) -> Dict:
        """Obtiene estadísticas de los filtros"""
        return {
            'daily_trades': dict(self.daily_trades),
            'period_trades': dict(self.period_trades),
            'current_daily_count': self._get_daily_count(),
            'current_period_count': self._get_period_count(),
            'recent_signals_count': {symbol: len(signals) for symbol, signals in self.recent_signals.items()},
            'using_bot_state': self._bot_state is not None,
            'config': {
                'duplicate_config': self.duplicate_config,
                'risk_config': self.risk_config,
                'market_config': self.market_config
            }
        }
    
    def get_stats(self) -> Dict:
        """
        Método de compatibilidad para obtener estadísticas.
        Alias para get_statistics() con formato extendido.
        """
        stats = self.get_statistics()
        daily_count = stats['current_daily_count']
        period_count = stats['current_period_count']
        shown = self._total_evaluated - self._rejected_signals

        return {
            'total_signals': self._total_evaluated,
            'shown_signals': shown,
            'rejected_signals': self._rejected_signals,
            'daily_count': daily_count,
            'period_count': period_count,
            'recent_signals': stats['recent_signals_count'],
            'filters_config': stats['config'],
            'using_bot_state': stats['using_bot_state'],
        }

# Instancia global del sistema de filtros
consolidated_filters = ConsolidatedFilters()

def get_filters_system() -> ConsolidatedFilters:
    """Obtiene la instancia global del sistema de filtros"""
    return consolidated_filters