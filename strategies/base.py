"""
Base Strategy Class - Clase base para todas las estrategias

Define la interfaz común que deben implementar todas las estrategias específicas.
Cada estrategia se enfoca SOLO en detectar oportunidades de mercado.
"""

from abc import ABC, abstractmethod
from typing import Dict, Optional, Tuple
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)

class StrategyMetadata:
    """
    Metadatos que cada estrategia publica sobre sí misma.

    Todos los runners (Exit Research, Walk-Forward, Backtest, Replay)
    deben consultar estos valores en lugar de usar constantes hardcodeadas.

    Campos
    ------
    required_history : int
        Número mínimo de velas que la estrategia necesita para calcular
        todos sus indicadores correctamente (warmup + lookback combinados).
        Este es el único valor que los runners deben usar como ventana.
    symbol : str
        Par de trading principal de la estrategia.
    timeframe : str
        Timeframe de operación ('H1', 'H4', 'D1', ...).
    strategy_name : str
        Nombre legible de la estrategia.
    version : str
        Versión de la estrategia (para trazabilidad en resultados).
    """

    def __init__(
        self,
        required_history: int,
        symbol: str = "UNKNOWN",
        timeframe: str = "H1",
        strategy_name: str = "unnamed",
        version: str = "1.0",
    ) -> None:
        if required_history < 50:
            raise ValueError(
                f"required_history={required_history} es demasiado bajo. "
                "Mínimo 50 velas para indicadores básicos."
            )
        self.required_history = required_history
        self.symbol           = symbol
        self.timeframe        = timeframe
        self.strategy_name    = strategy_name
        self.version          = version

    def __repr__(self) -> str:
        return (
            f"StrategyMetadata(strategy={self.strategy_name!r}, "
            f"symbol={self.symbol!r}, tf={self.timeframe!r}, "
            f"required_history={self.required_history}, version={self.version!r})"
        )


def resolve_strategy_metadata(strategy: Optional[object] = None, fallback_required_history: int = 200) -> StrategyMetadata:
    """Resolve strategy metadata from a strategy instance or fallback defaults."""
    if strategy is None:
        return StrategyMetadata(required_history=fallback_required_history, strategy_name="unknown")

    metadata = getattr(strategy, "metadata", None)
    if isinstance(metadata, StrategyMetadata):
        return metadata

    required_history = getattr(strategy, "required_history", None)
    if required_history is None:
        required_history = fallback_required_history

    try:
        required_history = int(required_history)
    except (TypeError, ValueError):
        required_history = fallback_required_history

    return StrategyMetadata(
        required_history=max(required_history, fallback_required_history if fallback_required_history is not None else 50),
        symbol=getattr(strategy, "symbol", "UNKNOWN"),
        timeframe=getattr(strategy, "required_timeframe", None) or "H1",
        strategy_name=getattr(strategy, "name", getattr(strategy, "__class__", type(strategy)).__name__),
    )


def resolve_required_history(strategy: Optional[object] = None, fallback_required_history: int = 200) -> int:
    """Convenience helper returning the required history for a strategy or fallback."""
    return resolve_strategy_metadata(strategy, fallback_required_history=fallback_required_history).required_history


class BaseStrategy(ABC):
    """
    Clase base para estrategias de trading.
    
    Responsabilidades:
    - Detectar setups de mercado
    - Calcular niveles (entry, SL, TP)
    - Retornar contexto para scoring
    - Publicar metadatos (required_history, symbol, timeframe)
    
    NO responsabilidades:
    - Gestión de confianza
    - Logging de señales
    - Gestión de riesgo
    - Decisiones de ejecución
    """
    
    # Timeframe requerido por la estrategia. Si es None, usa el timeframe
    # por defecto del replay/backtest (normalmente H1).
    # Estrategias multi-timeframe como btceur_regime_momentum deben
    # declarar 'H4' aquí para que el ReplayEngine descargue los datos correctos.
    required_timeframe: Optional[str] = None
    
    def __init__(self, name: str):
        self.name = name
        self.default_config = self._get_default_config()

    # ── Metadatos públicos ────────────────────────────────────────────────────

    @property
    def metadata(self) -> "StrategyMetadata":
        """
        Metadatos de la estrategia.

        Cada subclase DEBE sobreescribir este método para declarar sus
        requisitos reales. El valor por defecto (200) es un fallback seguro
        para estrategias heredadas que aún no han migrado.

        Los runners deben usar strategy.metadata.required_history en lugar
        de cualquier constante hardcodeada.
        """
        return StrategyMetadata(
            required_history=200,
            symbol="UNKNOWN",
            timeframe=self.required_timeframe or "H1",
            strategy_name=self.name,
        )

    @property
    def required_history(self) -> int:
        """Atajo directo a metadata.required_history para uso en runners."""
        return self.metadata.required_history

    def reset_state(self) -> None:
        """Reinicia estado interno entre replays (opcional en subclases)."""
        pass

    @abstractmethod
    def _get_default_config(self) -> Dict:
        """Retorna configuración por defecto de la estrategia"""
        pass
    
    @abstractmethod
    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[Dict]:
        """
        Detecta setup de trading en los datos.
        
        Args:
            df: DataFrame con datos OHLCV
            config: Configuración específica (opcional)
            
        Returns:
            Dict con señal o None si no hay setup
            
        Formato de retorno:
        {
            'type': 'BUY' | 'SELL',
            'entry': float,
            'sl': float, 
            'tp': float,
            'explanation': str,
            'expires': datetime,
            'setup_strength': float (0-1),
            'context': Dict  # Información adicional para scoring
        }
        """
        pass
    
    def add_indicators(self, df: pd.DataFrame, config: Dict = None) -> pd.DataFrame:
        """
        Añade indicadores técnicos necesarios al DataFrame.
        Por defecto añade indicadores comunes.
        """
        cfg = {**self.default_config, **(config or {})}
        df = df.copy()
        
        # Indicadores básicos comunes
        df['sma20'] = self._sma(df['close'], 20)
        df['sma50'] = self._sma(df['close'], 50)
        df['ema20'] = self._ema(df['close'], 20)
        df['ema50'] = self._ema(df['close'], 50)
        df['rsi'] = self._rsi(df['close'], 14)
        df['atr'] = self._atr(df, 14)
        
        # Indicadores específicos de la estrategia
        df = self._add_specific_indicators(df, cfg)
        
        return df
    
    @abstractmethod
    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        """Añade indicadores específicos de la estrategia"""
        pass
    
    def validate_data(self, df: pd.DataFrame) -> bool:
        """Valida que los datos sean suficientes para la estrategia"""
        if df is None or len(df) < 50:
            return False
        
        required_columns = ['open', 'high', 'low', 'close']
        return all(col in df.columns for col in required_columns)
    
    def calculate_position_size(self, signal: Dict, balance: float, risk_pct: float = 1.0) -> Dict:
        """
        Calcula tamaño de posición basado en riesgo.

        ⚠️  DEPRECADO — Solo para uso en backtesting/simulación sin conexión MT5.
            En producción, el tamaño de posición siempre lo decide el Risk Engine
            (core/risk/engine.py). Las estrategias NO deben llamar a este método
            para órdenes reales.

        Este método usa una fórmula simplificada (pip_value ≈ 10 USD, válida
        aproximadamente solo para EURUSD). Para cálculos precisos multi-activo
        usa: get_risk_engine().evaluate(signal)
        """
        logger.warning(
            "[%s] calculate_position_size() está DEPRECADO. "
            "En producción usa get_risk_engine().evaluate(signal). "
            "Este método es solo para simulación/backtest sin conexión MT5.",
            self.name
        )
        try:
            entry = float(signal['entry'])
            sl = float(signal['sl'])

            # Distancia de SL en puntos
            sl_distance = abs(entry - sl)

            # Cantidad a arriesgar
            risk_amount = balance * (risk_pct / 100.0)

            # Cálculo básico de lote (simplificado, aprox. válido para EURUSD)
            pip_value = 10.0  # Valor aproximado por pip para EURUSD
            sl_pips = sl_distance * 10000  # Convertir a pips

            if sl_pips > 0:
                lot_size = risk_amount / (sl_pips * pip_value)
                lot_size = max(0.01, min(1.0, lot_size))  # Límites básicos
            else:
                lot_size = 0.01

            return {
                'lot_size': lot_size,
                'risk_amount': risk_amount,
                'sl_pips': sl_pips,
                'pip_value': pip_value
            }

        except Exception as e:
            logger.warning(f"Error calculando tamaño de posición: {e}")
            return {'lot_size': 0.01, 'risk_amount': 0, 'sl_pips': 0, 'pip_value': 0}

    
    def evaluate_signal(self, df: pd.DataFrame, config: Dict = None) -> Optional[Dict]:
        """
        Evalúa señal completa con indicadores y setup.
        Método de compatibilidad que combina add_indicators + detect_setup.
        
        Args:
            df: DataFrame con datos OHLCV
            config: Configuración específica (opcional)
            
        Returns:
            Dict con resultado de evaluación o None si no hay señal
            
        Formato de retorno:
        {
            'signal_found': bool,
            'signal': Dict,  # Señal detectada
            'confidence': str,  # Nivel de confianza estimado
            'score': float  # Score numérico (0-1)
        }
        """
        try:
            # Validar datos
            if not self.validate_data(df):
                return None
            
            # Añadir indicadores
            df_with_indicators = self.add_indicators(df, config)
            
            # Detectar setup
            signal = self.detect_setup(df_with_indicators, config)
            
            if not signal:
                return None
            
            # Calcular confianza básica basada en setup_strength
            setup_strength = signal.get('setup_strength', 0.5)
            
            if setup_strength >= 0.8:
                confidence = 'HIGH'
            elif setup_strength >= 0.6:
                confidence = 'MEDIUM-HIGH'
            elif setup_strength >= 0.4:
                confidence = 'MEDIUM'
            else:
                confidence = 'LOW'
            
            return {
                'signal_found': True,
                'signal': signal,
                'confidence': confidence,
                'score': setup_strength
            }
            
        except Exception as e:
            logger.error(f"Error evaluating signal in {self.name}: {e}")
            return None
    
    # ========================================================================
    # INDICADORES TÉCNICOS COMUNES
    # ========================================================================
    
    def _sma(self, series: pd.Series, window: int) -> pd.Series:
        """Simple Moving Average"""
        return series.rolling(window).mean()
    
    def _ema(self, series: pd.Series, span: int) -> pd.Series:
        """Exponential Moving Average"""
        return series.ewm(span=span, adjust=False).mean()
    
    def _rsi(self, series: pd.Series, period: int = 14) -> pd.Series:
        """Relative Strength Index"""
        delta = series.diff()
        up = delta.clip(lower=0).ewm(alpha=1/period, adjust=False).mean()
        down = -delta.clip(upper=0).ewm(alpha=1/period, adjust=False).mean()
        rs = up / down.replace(0, np.nan)
        return 100 - (100 / (1 + rs))
    
    def _atr(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average True Range"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return true_range.rolling(window=period).mean()
    
    def _macd(self, close: pd.Series, fast=12, slow=26, signal=9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """MACD Indicator"""
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        signal_line = macd.ewm(span=signal, adjust=False).mean()
        histogram = macd - signal_line
        return macd, signal_line, histogram
    
    def _bollinger_bands(self, close: pd.Series, window=20, std_dev=2) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """Bollinger Bands"""
        sma = close.rolling(window).mean()
        std = close.rolling(window).std()
        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        return upper, sma, lower
    
    def _stochastic(self, high: pd.Series, low: pd.Series, close: pd.Series, k_period=14, d_period=3) -> Tuple[pd.Series, pd.Series]:
        """Stochastic Oscillator"""
        lowest_low = low.rolling(k_period).min()
        highest_high = high.rolling(k_period).max()
        k_percent = 100 * ((close - lowest_low) / (highest_high - lowest_low))
        d_percent = k_percent.rolling(d_period).mean()
        return k_percent, d_percent
    
    # ========================================================================
    # UTILIDADES DE ANÁLISIS
    # ========================================================================
    
    def _is_bullish_candle(self, candle: pd.Series) -> bool:
        """Verifica si una vela es alcista"""
        return candle['close'] > candle['open']
    
    def _is_bearish_candle(self, candle: pd.Series) -> bool:
        """Verifica si una vela es bajista"""
        return candle['close'] < candle['open']
    
    def _candle_body_size(self, candle: pd.Series) -> float:
        """Tamaño del cuerpo de la vela"""
        return abs(candle['close'] - candle['open'])
    
    def _candle_range(self, candle: pd.Series) -> float:
        """Rango total de la vela"""
        return candle['high'] - candle['low']
    
    def _is_doji(self, candle: pd.Series, threshold: float = 0.1) -> bool:
        """Verifica si una vela es doji"""
        body_size = self._candle_body_size(candle)
        candle_range = self._candle_range(candle)
        return (body_size / candle_range) < threshold if candle_range > 0 else False
    
    def _detect_support_resistance(self, df: pd.DataFrame, window: int = 20) -> Dict:
        """Detecta niveles básicos de soporte y resistencia"""
        try:
            # Máximos y mínimos locales
            highs = df['high'].rolling(window, center=True).max()
            lows = df['low'].rolling(window, center=True).min()
            
            # Niveles de resistencia (máximos locales)
            resistance_levels = df[df['high'] == highs]['high'].dropna().tail(5).tolist()
            
            # Niveles de soporte (mínimos locales)
            support_levels = df[df['low'] == lows]['low'].dropna().tail(5).tolist()
            
            return {
                'resistance': resistance_levels,
                'support': support_levels,
                'current_price': float(df['close'].iloc[-1])
            }
            
        except Exception as e:
            logger.warning(f"Error detectando soporte/resistencia: {e}")
            return {'resistance': [], 'support': [], 'current_price': 0}
    
    def __str__(self) -> str:
        return f"Strategy: {self.name}"
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}')>"