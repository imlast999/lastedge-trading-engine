"""
Signals Dispatcher - Versión Refactorizada

Este archivo ahora actúa SOLO como dispatcher de estrategias.
Toda la lógica compleja se ha movido a:
- core/engine.py (orquestación)
- core/scoring.py (scoring)
- core/filters.py (filtros)
- strategies/ (estrategias específicas)
"""

import logging
from typing import Dict, Optional, Tuple
import pandas as pd

# Imports del core refactorizado
from core.engine import get_trading_engine, is_symbol_active, set_btceur_health, record_signal

# Import usando el nuevo sistema de estrategias
from strategies import get_strategy

logger = logging.getLogger(__name__)

# Estrategias con estado interno (1 señal/día, 1/semana, etc.) — una instancia por sesión de replay
STATEFUL_STRATEGIES = frozenset({'eurusd_asian_breakout', 'btceur_weekly_breakout', 'xauusd_gsrs'})
_strategy_instances: Dict[str, object] = {}


def reset_strategy_instances() -> None:
    """Limpia instancias cacheadas; llamar al inicio de cada replay / ventana WF."""
    for inst in _strategy_instances.values():
        if hasattr(inst, 'reset_state'):
            inst.reset_state()
    _strategy_instances.clear()


# Registry de estrategias disponibles
# rules_config.json usa eurusd_simple, xauusd_simple, btceur_simple → deben estar registradas
STRATEGY_REGISTRY = {
    'ema50_200':        lambda: get_strategy('EURUSD'),
    'eurusd':           lambda: get_strategy('EURUSD'),
    'eurusd_partial':   lambda: get_strategy('EURUSD'),          # v1.1 — partial_close (activo)
    'eurusd_simple':    lambda: get_strategy('EURUSD_LEGACY'),   # legacy — referencia histórica
    'eurusd_advanced':  lambda: _get_eurusd_advanced(),
    # eurusd_asian_breakout descartada (retest progresivo junio 2026, PF<1.0 en 10k/15k/20k) — ver strategies/experimental/
    'eurusd_asian_breakout': lambda: _get_eurusd_asian_breakout(),   # mantenida para compatibilidad backtest
    # eurusd_mtf descartada (grid search mayo 2026, PF max 0.42) — ver strategies/experimental/
    'eurusd_mtf':       lambda: _get_eurusd_mtf(),   # mantenida para compatibilidad backtest
    'xauusd':           lambda: get_strategy('XAUUSD'),
    'xauusd_simple':    lambda: get_strategy('XAUUSD'),
    'xauusd_partial':   lambda: get_strategy('XAUUSD'),
    'xauusd_advanced':  lambda: _get_xauusd_advanced(),
    'xauusd_reversal':  lambda: _get_xauusd_reversal(),    # descartada (1 señal/5000v)
    'xauusd_momentum':  lambda: _get_xauusd_momentum(),
    'xauusd_psychological': lambda: _get_xauusd_psychological(),  # descartada (PF max 0.94)
    'xauusd_gsrs':      lambda: _get_xauusd_gsrs(),         # GSRS experimental (oro, M1)

    # BTCEUR: todos los alias apuntan a la misma estrategia específica
    'btceur':                lambda: get_strategy('BTCEUR'),
    'btceur_simple':         lambda: get_strategy('BTCEUR'),
    'btceur_partial':        lambda: get_strategy('BTCEUR'),
    'btceur_advanced':       lambda: get_strategy('BTCEUR'),
    'btc_trend_pullback_v1': lambda: _get_btc_trend_pullback(),
    'btceur_weekly_breakout': lambda: _get_btceur_weekly_breakout(),
    # btceur_regime_momentum — reactivada: ahora el ReplayEngine detecta su required_timeframe='H4'
    'btceur_regime_momentum': lambda: _get_btceur_regime_momentum(),
    'btcusdt':               lambda: get_strategy('BTCEUR'),
    'btc':                   lambda: get_strategy('BTCEUR'),
}

# ── Helpers para instanciar variantes avanzadas ───────────────────────────────

def _get_btc_trend_pullback():
    try:
        from strategies.btc_trend_pullback_v1 import BTCTrendPullbackV1Strategy
        return BTCTrendPullbackV1Strategy()
    except Exception as e:
        logger.warning(f"BTCTrendPullbackV1Strategy no disponible: {e}")
        return get_strategy('BTCEUR')

def _get_eurusd_asian_breakout():
    try:
        from strategies.experimental.eurusd_asian_breakout import EURUSDAsianBreakoutStrategy
        return EURUSDAsianBreakoutStrategy()
    except Exception as e:
        logger.warning(f"EURUSDAsianBreakoutStrategy no disponible: {e}")
        return get_strategy('EURUSD')

def _get_xauusd_psychological():
    try:
        from strategies.experimental.xauusd_psychological import XAUUSDPsychologicalStrategy
        return XAUUSDPsychologicalStrategy()
    except Exception as e:
        logger.warning(f"XAUUSDPsychologicalStrategy no disponible: {e}")
        return get_strategy('XAUUSD')

def _get_xauusd_gsrs():
    try:
        from strategies.experimental.gold_newstrat import XAUUSDGSRSStrategy
        return XAUUSDGSRSStrategy()
    except Exception as e:
        logger.warning(f"XAUUSDGSRSStrategy no disponible: {e}")
        return get_strategy('XAUUSD')

def _get_btceur_weekly_breakout():
    try:
        from strategies.btceur_weekly_breakout import BTCEURWeeklyBreakoutStrategy
        return BTCEURWeeklyBreakoutStrategy()
    except Exception as e:
        logger.warning(f"BTCEURWeeklyBreakoutStrategy no disponible: {e}")
        return get_strategy('BTCEUR')

def _get_btceur_regime_momentum():
    """
    ESTADO: ACTIVADA — requiere H4+Daily (ReplayEngine respeta required_timeframe).

    BTCEURRegimeMomentumStrategy usa datos H4 y Daily para calcular el
    régimen de mercado. El ReplayEngine ahora detecta el atributo
    'required_timeframe' de la estrategia y descarga los datos correctos.
    """
    try:
        from strategies.btceur_regime_momentum import BTCEURRegimeMomentumStrategy
        return BTCEURRegimeMomentumStrategy()
    except Exception as e:
        logger.warning(f"BTCEURRegimeMomentumStrategy no disponible: {e}")
        return get_strategy('BTCEUR')

def _get_eurusd_advanced():
    try:
        from strategies.eurusd import EURUSDAdvancedStrategy
        return EURUSDAdvancedStrategy()
    except Exception as e:
        logger.warning(f"EURUSDAdvancedStrategy no disponible, usando simple: {e}")
        return get_strategy('EURUSD')

def _get_eurusd_mtf():
    try:
        from strategies.experimental.eurusd_mtf import EURUSDMultiTimeframeStrategy
        return EURUSDMultiTimeframeStrategy()
    except Exception as e:
        logger.warning(f"EURUSDMultiTimeframeStrategy no disponible: {e}")
        return get_strategy('EURUSD')


def _get_xauusd_advanced():
    try:
        from strategies.xauusd import XAUUSDStrategy as XAUUSDReversal
        return XAUUSDReversal()
    except Exception as e:
        logger.warning(f"XAUUSDAdvanced no disponible: {e}")
        return get_strategy('XAUUSD')

def _get_xauusd_reversal():
    try:
        from strategies.xauusd import XAUUSDReversalStrategy
        return XAUUSDReversalStrategy()
    except Exception as e:
        logger.warning(f"XAUUSDReversalStrategy no disponible: {e}")
        return get_strategy('XAUUSD')

def _get_xauusd_momentum():
    try:
        from strategies.xauusd import XAUUSDMomentumStrategy
        return XAUUSDMomentumStrategy()
    except Exception as e:
        logger.warning(f"XAUUSDMomentumStrategy no disponible: {e}")
        return get_strategy('XAUUSD')

def detect_signal(
    df: pd.DataFrame,
    strategy: str = 'ema50_200',
    config: dict = None,
    symbol: Optional[str] = None,
) -> Tuple[Optional[Dict], pd.DataFrame]:
    """
    Dispatcher principal de detección de señales
    
    Args:
        df: DataFrame con datos OHLCV
        strategy: Nombre de la estrategia a usar
        config: Configuración específica (opcional)
        
    Returns:
        (signal_dict or None, df_with_indicators)
    """
    try:
        # Validar datos básicos
        if df is None or len(df) < 10:
            logger.debug(f"Datos insuficientes para {strategy}: {len(df) if df is not None else 0} velas")
            return None, df

        # Respetar configuración de símbolos activos si se especifica un símbolo
        if symbol is not None and not is_symbol_active(symbol):
            logger.info(f"Símbolo {symbol} desactivado en active_symbols; omitiendo detección de señal.")
            return None, df
        
        # Obtener estrategia del registry
        strategy_name = (strategy or 'ema50_200').lower()
        strategy_factory = STRATEGY_REGISTRY.get(strategy_name)
        
        # PROTECCIÓN: si no hay factory registrada
        if strategy_factory is None:
            # BTCEUR NUNCA debe hacer fallback silencioso
            if symbol and symbol.upper() == 'BTCEUR':
                err_msg = f"Estrategia '{strategy_name}' no registrada; BTCEUR no puede usar fallback a EURUSD."
                logger.error("[CRITICAL][BTCEUR] %s", err_msg)
                set_btceur_health(status="ERROR", last_error=err_msg)
                return None, df
            # Otros símbolos mantienen el comportamiento previo
            logger.warning(f"Estrategia {strategy_name} no encontrada, usando EURUSD por defecto")
            strategy_factory = STRATEGY_REGISTRY['eurusd']
        
        # Instancia: cachear las que guardan estado entre velas del mismo replay
        if strategy_name in STATEFUL_STRATEGIES:
            if strategy_name not in _strategy_instances:
                _strategy_instances[strategy_name] = strategy_factory()
            strategy_instance = _strategy_instances[strategy_name]
        else:
            strategy_instance = strategy_factory()
        
        # Log del nombre real de la estrategia para BTCEUR
        if symbol and symbol.upper() == 'BTCEUR':
            logger.debug(f"[BTCEUR] Strategy instance: {strategy_instance.__class__.__name__} from {strategy_instance.__class__.__module__}")
        
        # Verificación estricta para BTCEUR: la clase debe ser BTCEURStrategy
        if symbol and symbol.upper() == 'BTCEUR':
            if strategy_instance is None:
                err_msg = "get_strategy('BTCEUR') devolvió None."
                logger.error("[CRITICAL][BTCEUR] %s", err_msg)
                set_btceur_health(status="ERROR", last_error=err_msg)
                return None, df
            cls_name = strategy_instance.__class__.__name__
            # Clases válidas para BTCEUR: BTCEURStrategy (baseline), BTCTrendPullbackV1Strategy,
            # BTCEURWeeklyBreakoutStrategy, BTCEURRegimeMomentumStrategy.
            valid_btceur_classes = ('BTCEURStrategy', 'BTCEURPartialStrategy', 'BTCTrendPullbackV1Strategy', 'BTCEURWeeklyBreakoutStrategy', 'BTCEURRegimeMomentumStrategy')
            if cls_name not in valid_btceur_classes:
                err_msg = f"Estrategia incorrecta: {cls_name} (válidas: {valid_btceur_classes})."
                logger.error("[CRITICAL][BTCEUR] %s Abortando detección.", err_msg)
                set_btceur_health(status="ERROR", last_error=err_msg)
                return None, df
        
        # Detectar señal usando la estrategia
        df_with_indicators = strategy_instance.add_indicators(df, config)
        signal = strategy_instance.detect_setup(df_with_indicators, config)
        
        if signal:
            logger.debug(f"Señal detectada con {strategy_name}: {signal['type']} {signal.get('symbol', 'UNKNOWN')}")
            if symbol:
                record_signal(symbol.upper())
        else:
            logger.debug(f"No hay señal con {strategy_name}")
        
        return signal, df_with_indicators
        
    except Exception as e:
        logger.error(f"Error en detect_signal con estrategia {strategy}: {e}")
        return None, df

def detect_signal_advanced(df: pd.DataFrame, strategy: str = 'ema50_200', 
                          config: dict = None, current_balance: float = 5000.0, 
                          symbol: str = 'EURUSD') -> Tuple[Optional[Dict], pd.DataFrame, Dict]:
    """
    Versión avanzada que usa el trading engine completo
    
    Args:
        df: DataFrame con datos OHLCV
        strategy: Nombre de la estrategia
        config: Configuración específica
        current_balance: Balance actual (para cálculos de riesgo)
        symbol: Símbolo del instrumento
        
    Returns:
        (signal_dict or None, df_with_indicators, evaluation_info)
    """
    try:
        # Usar el trading engine para evaluación completa
        trading_engine = get_trading_engine()
        
        # Evaluar señal con pipeline completo
        result = trading_engine.evaluate_signal(df, symbol, strategy, config)

        # Obtener nombre real de la estrategia instanciada
        actual_strategy_name = strategy
        
        # Para BTCEUR, forzar el nombre correcto
        if symbol and symbol.upper() == 'BTCEUR':
            actual_strategy_name = 'btceur_new'
        
        # Si hay señal, intentar obtener el nombre del contexto
        if result.signal and 'context' in result.signal:
            context_strategy = result.signal['context'].get('strategy')
            if context_strategy:
                actual_strategy_name = context_strategy
        elif result.details and 'strategy_name' in result.details:
            actual_strategy_name = result.details['strategy_name']

        # Extraer información para compatibilidad
        if result.signal:
            evaluation_info = {
                'approved': result.should_show,
                'strategy_used': actual_strategy_name,
                'confidence': result.confidence,
                'score': result.score,
                'should_show': result.should_show,
                'can_auto_execute': result.should_execute,
                'rejection_reason': result.rejection_reason,
                'details': result.details
            }
            
            return result.signal, df, evaluation_info
        else:
            evaluation_info = {
                'approved': False,
                'strategy_used': actual_strategy_name,
                'confidence': 'NONE',
                'score': 0.0,
                'should_show': False,
                'can_auto_execute': False,
                'rejection_reason': result.rejection_reason,
                'details': result.details
            }
            
            return None, df, evaluation_info
            
    except Exception as e:
        logger.error(f"Error en detect_signal_advanced: {e}")
        return None, df, {'error': str(e), 'approved': False}

def get_available_strategies() -> Dict[str, str]:
    """
    Obtiene lista de estrategias disponibles
    
    Returns:
        Dict con nombre -> descripción de estrategias
    """
    return {
        'ema50_200': 'EMA 50/200 Crossover (EURUSD)',
        'eurusd': 'EURUSD Breakout Strategy',
        'eurusd_advanced': 'EURUSD Advanced Multi-Timeframe',
        'eurusd_asian_breakout': 'EURUSD Asian Range Breakout (Experimental)',
        'eurusd_mtf': 'EURUSD Multi-Timeframe (Experimental)',
        'xauusd': 'XAUUSD Reversal Strategy',
        'xauusd_advanced': 'XAUUSD Advanced Ultra-Selective',
        'xauusd_psychological': 'XAUUSD Psychological Levels (Experimental)',
        'btceur': 'BTCEUR Momentum Strategy',
        'btc_trend_pullback_v1': 'BTCEUR Trend Pullback V1',
        'btceur_weekly_breakout': 'BTCEUR Weekly Breakout',
        'btceur_regime_momentum': 'BTCEUR Regime Momentum',
    }

def register_strategy(name: str, strategy_factory):
    """
    Registra una nueva estrategia
    
    Args:
        name: Nombre de la estrategia
        strategy_factory: Factory function que retorna instancia de estrategia
    """
    STRATEGY_REGISTRY[name.lower()] = strategy_factory
    logger.info(f"Estrategia {name} registrada exitosamente")

# Funciones de compatibilidad con el código existente
def _detect_signal_wrapper(df: pd.DataFrame, symbol: str = None):
    """
    Wrapper de compatibilidad para el código existente en bot.py
    
    Esta función mantiene la interfaz original pero usa el nuevo sistema.
    """
    try:
        # Determinar estrategia basada en símbolo
        sym = (symbol or 'EURUSD').upper()
        
        if sym == 'EURUSD':
            strategy = 'eurusd_advanced'
        elif sym == 'XAUUSD':
            strategy = 'xauusd_advanced'
        elif sym in ['BTCEUR', 'BTCUSDT']:
            strategy = 'btceur'
        else:
            strategy = 'ema50_200'  # Fallback
        
        # Usar detect_signal_advanced para evaluación completa
        signal, df_processed, evaluation_info = detect_signal_advanced(
            df, strategy=strategy, symbol=sym
        )
        
        return signal, df_processed, evaluation_info
        
    except Exception as e:
        logger.error(f"Error en _detect_signal_wrapper para {symbol}: {e}")
        return None, df, {'approved': False, 'reason': f'Error: {str(e)}'}

# Mantener compatibilidad con imports existentes
SYMBOL = "EURUSD"  # Para compatibilidad

# Funciones auxiliares que pueden estar siendo usadas
def _rsi(series: pd.Series, period: int = 14):
    """RSI calculation for compatibility"""
    import numpy as np
    delta = series.diff()
    up = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
    down = -delta.clip(upper=0).ewm(alpha=1/period, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _atr(df: pd.DataFrame, period: int = 14):
    """ATR calculation for compatibility"""
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.rolling(window=period).mean()

# Log de inicialización
logger.info(f"Signals dispatcher inicializado con {len(STRATEGY_REGISTRY)} estrategias disponibles")