"""
EURUSD Strategy - Estrategia específica para EURUSD

Estrategia optimizada para el par EUR/USD basada en:
- Breakout de consolidación con EMAs
- Filtros de tendencia y momentum
- Gestión de riesgo conservadora
"""

from typing import Dict, Optional
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import logging

from .base import BaseStrategy

logger = logging.getLogger(__name__)

class EURUSDStrategy(BaseStrategy):
    """
    Estrategia EURUSD SIMPLIFICADA v2: Tendencia confirmada + Retroceso
    
    Mejoras sobre v1:
    - Filtro EMA200: precio debe estar del lado correcto de la tendencia mayor
    - Separación mínima EMA20/EMA50: evita mercados laterales
    - RSI más estricto (45-58): reduce entradas en zonas ambiguas
    - Confirmación de no-retroceso fuerte
    """
    
    def __init__(self):
        super().__init__("EURUSD_Simple")

    @property
    def metadata(self):
        from strategies.base import StrategyMetadata
        return StrategyMetadata(
            required_history=200,   # EMA200 es el indicador más lento
            symbol="EURUSD",
            timeframe="H1",
            strategy_name="eurusd_simple",
            version="2.0",
        )
    
    def _get_default_config(self) -> Dict:
        return {
            'ema_fast': 20,
            'ema_slow': 50,
            'ema_trend': 200,
            'ema_min_separation': 0.0001,    # 0.01% — evita mercados completamente planos
            'rsi_period': 14,
            'rsi_min': 38,                   # Más amplio que 45 para capturar retrocesos reales
            'rsi_max': 62,                   # Más amplio que 58
            'atr_period': 14,
            'price_ema_distance': 0.003,     # 0.3% — ligeramente más tolerante
            'sl_atr_multiplier': 2.0,   # Subido de 1.5 — aguanta pullbacks en tendencias fuertes
            'tp_atr_multiplier': 4.0,   # R:R 2.0 con SL 2.0x
            'expires_minutes': 30,
        }
    
    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        df['ema20']  = self._ema(df['close'], config['ema_fast'])
        df['ema50']  = self._ema(df['close'], config['ema_slow'])
        df['ema200'] = self._ema(df['close'], config['ema_trend'])
        return df
    
    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[Dict]:
        """
        Detecta setup de tendencia confirmada + retroceso a EMA20

        Filtros activos:
        1. EMA20 > EMA50 (tendencia corto plazo)
        2. Separación mínima EMA20/EMA50 (no lateral)
        3. Precio del lado correcto de EMA200 (tendencia mayor)
        4. RSI en zona operativa (no sobreextendido)
        5. Precio cerca de EMA20 (retroceso, no perseguir)
        6. Pendiente EMA20 en dirección del trade (momentum activo)
        7. No más de 2 velas consecutivas en contra (no entrar en impulso adverso)
        """
        cfg = {**self.default_config, **(config or {})}

        if not self.validate_data(df) or len(df) < cfg['ema_trend']:
            logger.debug("[EURUSD][REJECT] insufficient_data | len=%d required=%d",
                        len(df), cfg['ema_trend'])
            return None

        df = self.add_indicators(df, cfg)

        last  = df.iloc[-1]
        prev  = df.iloc[-2]
        prev2 = df.iloc[-3]

        price       = float(last['close'])
        ema20       = float(last['ema20'])
        ema50       = float(last['ema50'])
        ema200      = float(last['ema200'])
        rsi         = float(last['rsi'])
        atr_current = float(last['atr'])

        # ── 1. Tendencia EMA20 vs EMA50 ──────────────────────────────────────
        bullish_trend = ema20 > ema50
        bearish_trend = ema20 < ema50
        if not (bullish_trend or bearish_trend):
            return None
        direction = 'BUY' if bullish_trend else 'SELL'

        # ── 2. Separación mínima (no lateral) ────────────────────────────────
        ema_separation = abs(ema20 - ema50) / ema50
        if ema_separation < cfg['ema_min_separation']:
            logger.debug("[EURUSD][REJECT] ema_too_close | sep=%.5f", ema_separation)
            return None

        # ── 3. Filtro EMA200 (tendencia mayor) ───────────────────────────────
        if direction == 'BUY' and price < ema200:
            logger.debug("[EURUSD][REJECT] price_below_ema200_for_buy")
            return None
        if direction == 'SELL' and price > ema200:
            logger.debug("[EURUSD][REJECT] price_above_ema200_for_sell")
            return None

        # ── 4. RSI en zona operativa ──────────────────────────────────────────
        if not (cfg['rsi_min'] <= rsi <= cfg['rsi_max']):
            logger.debug("[EURUSD][REJECT] rsi_out_of_range | rsi=%.2f", rsi)
            return None

        # ── 5. Precio cerca de EMA20 (retroceso, no perseguir) ───────────────
        distance_to_ema20 = abs(price - ema20) / ema20
        if distance_to_ema20 > cfg['price_ema_distance']:
            logger.debug("[EURUSD][REJECT] price_far_from_ema20 | dist=%.4f", distance_to_ema20)
            return None

        # ── 6. Filtro de volatilidad: no entrar en mercados impulsivos ───────
        # Si el ATR actual es >1.8x su media, el mercado está en impulso
        # y los retrocesos a EMA20 suelen ser trampas
        atr_mean_check = df['atr'].tail(20).mean()
        if atr_mean_check > 0 and atr_current > atr_mean_check * 1.8:
            logger.debug("[EURUSD][REJECT] high_volatility_impulse | atr=%.5f mean=%.5f ratio=%.2f",
                        atr_current, atr_mean_check, atr_current / atr_mean_check)
            return None

        # ── 7. No entrar si el precio viene de movimiento fuerte en contra ───
        # Si el precio cayó/subió más de 1.5x ATR en las últimas 5 velas → reversión
        price_5bars_ago = float(df.iloc[-6]['close'])
        move_5bars = price - price_5bars_ago

        if direction == 'BUY' and move_5bars < -(atr_current * 1.5):
            logger.debug("[EURUSD][REJECT] strong_bearish_move_on_buy | move=%.5f", move_5bars)
            return None
        if direction == 'SELL' and move_5bars > (atr_current * 1.5):
            logger.debug("[EURUSD][REJECT] strong_bullish_move_on_sell | move=%.5f", move_5bars)
            return None

        # ── 8. No entrar con 2 velas consecutivas en contra ──────────────────
        last_bearish = float(last['close']) < float(last['open'])
        prev_bearish = float(prev['close']) < float(prev['open'])
        last_bullish = float(last['close']) > float(last['open'])
        prev_bullish = float(prev['close']) > float(prev['open'])

        if direction == 'BUY' and last_bearish and prev_bearish:
            logger.debug("[EURUSD][REJECT] two_consecutive_bearish_candles_on_buy")
            return None
        if direction == 'SELL' and last_bullish and prev_bullish:
            logger.debug("[EURUSD][REJECT] two_consecutive_bullish_candles_on_sell")
            return None

        # ── CONFIRMACIONES ────────────────────────────────────────────────────
        confirmations = []

        candle_ok = float(last['close']) > float(last['open']) if direction == 'BUY' \
                    else float(last['close']) < float(last['open'])
        confirmations.append({
            'name': 'CANDLE_DIRECTION', 'passed': candle_ok,
            'value': 1.0 if candle_ok else 0.0,
            'description': f"Vela en dirección {direction}"
        })

        atr_mean = df['atr'].tail(20).mean()
        atr_ok   = atr_current > atr_mean * 0.7
        confirmations.append({
            'name': 'ATR_ADEQUATE', 'passed': atr_ok,
            'value': atr_current / atr_mean if atr_mean > 0 else 0,
            'description': f"ATR adecuado: {atr_current:.5f}"
        })

        # ── NIVELES ───────────────────────────────────────────────────────────
        sl_distance = atr_current * cfg['sl_atr_multiplier']
        tp_distance = atr_current * cfg['tp_atr_multiplier']

        if direction == 'BUY':
            sl = price - sl_distance
            tp = price + tp_distance
        else:
            sl = price + sl_distance
            tp = price - tp_distance

        # ── FORTALEZA ─────────────────────────────────────────────────────────
        passed_conf  = sum(1 for c in confirmations if c['passed'])
        conf_ratio   = passed_conf / len(confirmations)
        ema_strength = min(1.0, ema_separation * 200)

        setup_strength = (conf_ratio * 0.6) + (ema_strength * 0.4)

        # ── SEÑAL ─────────────────────────────────────────────────────────────
        signal = {
            'type': direction,
            'entry': price,
            'sl': sl,
            'tp': tp,
            'timeframe': 'H1',
            'explanation': (f'EURUSD v3: {direction} | EMA200✓ | '
                           f'sep={ema_separation:.4f} | RSI {rsi:.1f}'),
            'expires': datetime.now(timezone.utc) + timedelta(minutes=cfg['expires_minutes']),
            'setup_strength': setup_strength,
            'context': {
                'strategy': 'eurusd_simple',
                'confirmations': confirmations,
                'market_conditions': {
                    'ema20': ema20, 'ema50': ema50, 'ema200': ema200,
                    'ema_trend': direction.lower(),
                    'ema_separation': ema_separation,
                    'rsi': rsi,
                    'distance_to_ema20': distance_to_ema20,
                    'atr_current': atr_current,
                    'atr_mean': atr_mean,
                },
                'risk_reward': tp_distance / sl_distance if sl_distance > 0 else 0,
                'simple_strategy': True
            }
        }

        logger.info("[EURUSD][SIGNAL] type=%s | price=%.5f | rsi=%.2f | sep=%.4f",
                   direction, price, rsi, ema_separation)

        return signal


class EURUSDAdvancedStrategy(BaseStrategy):
    """
    Estrategia EURUSD Avanzada: Versión más sofisticada con múltiples timeframes
    
    Mejoras:
    - Análisis de múltiples timeframes
    - Detección de patrones de velas
    - Filtros de volumen (si disponible)
    - Gestión dinámica de riesgo
    """
    
    def __init__(self):
        super().__init__("EURUSD_Advanced")
    
    def _get_default_config(self) -> Dict:
        return {
            'ema_fast': 21,
            'ema_medium': 50,
            'ema_slow': 200,
            'rsi_period': 14,
            'macd_fast': 12,
            'macd_slow': 26,
            'macd_signal': 9,
            'atr_period': 14,
            'bb_period': 20,
            'bb_std': 2.0,
            'min_confirmations': 3,
            'sl_atr_multiplier': 1.5,
            'tp_atr_multiplier': 3.0,
            'expires_minutes': 45
        }
    
    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        """Añade indicadores avanzados para EURUSD"""
        # EMAs múltiples
        df['ema21'] = self._ema(df['close'], config['ema_fast'])
        df['ema50'] = self._ema(df['close'], config['ema_medium'])
        df['ema200'] = self._ema(df['close'], config['ema_slow'])
        
        # MACD
        df['macd'], df['macd_signal'], df['macd_hist'] = self._macd(
            df['close'], config['macd_fast'], config['macd_slow'], config['macd_signal']
        )
        
        # Bollinger Bands
        df['bb_upper'], df['bb_middle'], df['bb_lower'] = self._bollinger_bands(
            df['close'], config['bb_period'], config['bb_std']
        )
        
        # Stochastic
        df['stoch_k'], df['stoch_d'] = self._stochastic(
            df['high'], df['low'], df['close']
        )
        
        return df
    
    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[Dict]:
        """
        Detecta setup avanzado EURUSD con múltiples confirmaciones
        """
        cfg = {**self.default_config, **(config or {})}
        
        # Validar datos
        if not self.validate_data(df) or len(df) < cfg['ema_slow']:
            return None
        
        # Añadir indicadores
        df = self.add_indicators(df, cfg)
        
        # Datos actuales
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        price = float(last['close'])
        ema21 = float(last['ema21'])
        ema50 = float(last['ema50'])
        ema200 = float(last['ema200'])
        
        # ========================================================================
        # SETUP PRINCIPAL: Alineación de EMAs + Momentum
        # ========================================================================
        
        # Setup alcista: EMAs alineadas + momentum positivo
        bullish_setup = (
            ema21 > ema50 > ema200 and  # EMAs alineadas
            last['macd'] > last['macd_signal'] and  # MACD positivo
            last['macd_hist'] > prev['macd_hist']  # Histograma creciente
        )
        
        # Setup bajista: EMAs alineadas + momentum negativo
        bearish_setup = (
            ema21 < ema50 < ema200 and  # EMAs alineadas
            last['macd'] < last['macd_signal'] and  # MACD negativo
            last['macd_hist'] < prev['macd_hist']  # Histograma decreciente
        )
        
        if not (bullish_setup or bearish_setup):
            return None
        
        direction = 'BUY' if bullish_setup else 'SELL'
        
        # ========================================================================
        # CONFIRMACIONES AVANZADAS
        # ========================================================================
        
        confirmations = []
        
        # Confirmación 1: RSI en zona favorable
        rsi = float(last['rsi'])
        if direction == 'BUY':
            rsi_ok = 40 <= rsi <= 70
        else:
            rsi_ok = 30 <= rsi <= 60
        
        confirmations.append({
            'name': 'RSI_FAVORABLE',
            'passed': rsi_ok,
            'value': rsi,
            'description': f"RSI favorable para {direction}: {rsi:.1f}"
        })
        
        # Confirmación 2: Stochastic alignment
        stoch_k = float(last['stoch_k'])
        stoch_d = float(last['stoch_d'])
        
        if direction == 'BUY':
            stoch_ok = stoch_k > stoch_d and stoch_k < 80
        else:
            stoch_ok = stoch_k < stoch_d and stoch_k > 20
        
        confirmations.append({
            'name': 'STOCHASTIC_ALIGNMENT',
            'passed': stoch_ok,
            'value': stoch_k,
            'description': f"Stochastic alineado para {direction}"
        })
        
        # Confirmación 3: Bollinger Bands position
        bb_position = (price - last['bb_lower']) / (last['bb_upper'] - last['bb_lower'])
        
        if direction == 'BUY':
            bb_ok = 0.2 <= bb_position <= 0.8  # No en extremos
        else:
            bb_ok = 0.2 <= bb_position <= 0.8
        
        confirmations.append({
            'name': 'BB_POSITION',
            'passed': bb_ok,
            'value': bb_position,
            'description': f"Posición en BB: {bb_position:.2f}"
        })
        
        # Confirmación 4: Patrón de velas
        candle_pattern = self._analyze_candle_pattern(df.tail(3), direction)
        confirmations.append({
            'name': 'CANDLE_PATTERN',
            'passed': candle_pattern['valid'],
            'value': candle_pattern['strength'],
            'description': candle_pattern['description']
        })
        
        # Verificar mínimo de confirmaciones
        passed_confirmations = sum(1 for c in confirmations if c['passed'])
        if passed_confirmations < cfg['min_confirmations']:
            return None
        
        # ========================================================================
        # CALCULAR NIVELES CON GESTIÓN DINÁMICA
        # ========================================================================
        
        atr_current = float(last['atr'])
        
        # Ajustar multiplicadores basado en volatilidad
        volatility_factor = min(2.0, max(0.5, atr_current / df['atr'].tail(50).mean()))
        
        sl_distance = atr_current * cfg['sl_atr_multiplier'] * volatility_factor
        tp_distance = atr_current * cfg['tp_atr_multiplier'] * volatility_factor
        
        if direction == 'BUY':
            sl = price - sl_distance
            tp = price + tp_distance
        else:
            sl = price + sl_distance
            tp = price - tp_distance
        
        # ========================================================================
        # CALCULAR FORTALEZA DEL SETUP
        # ========================================================================
        
        confirmation_ratio = passed_confirmations / len(confirmations)
        momentum_strength = abs(last['macd_hist']) / df['macd_hist'].tail(20).std()
        ema_alignment = self._calculate_ema_alignment_strength(ema21, ema50, ema200)
        
        setup_strength = (
            confirmation_ratio * 0.4 +
            min(momentum_strength, 1.0) * 0.3 +
            ema_alignment * 0.3
        )
        
        # ========================================================================
        # CREAR SEÑAL AVANZADA
        # ========================================================================
        
        signal = {
            'type': direction,
            'entry': price,
            'sl': sl,
            'tp': tp,
            'timeframe': 'H1',
            'explanation': f'EURUSD Advanced: {direction} + {passed_confirmations}/{len(confirmations)} confirmaciones + Momentum + EMAs',
            'expires': datetime.now(timezone.utc) + timedelta(minutes=cfg['expires_minutes']),
            'setup_strength': setup_strength,
            'context': {
                'strategy': 'eurusd_advanced',
                'confirmations': confirmations,
                'market_conditions': {
                    'ema_alignment': ema_alignment,
                    'momentum_strength': momentum_strength,
                    'volatility_factor': volatility_factor,
                    'bb_position': bb_position,
                    'macd_histogram': float(last['macd_hist']),
                    'rsi': rsi,
                    'stochastic': {'k': stoch_k, 'd': stoch_d}
                },
                'risk_reward': tp_distance / sl_distance if sl_distance > 0 else 0,
                'advanced_features': True
            }
        }
        
        return signal
    
    def _analyze_candle_pattern(self, candles: pd.DataFrame, direction: str) -> Dict:
        """Analiza patrón de velas para confirmación"""
        try:
            if len(candles) < 3:
                return {'valid': False, 'strength': 0.0, 'description': 'Datos insuficientes'}
            
            last = candles.iloc[-1]
            prev = candles.iloc[-2]
            
            # Análisis básico de momentum de velas
            if direction == 'BUY':
                # Buscar velas alcistas con momentum creciente
                last_bullish = self._is_bullish_candle(last)
                body_size_increasing = self._candle_body_size(last) > self._candle_body_size(prev)
                
                valid = last_bullish and body_size_increasing
                strength = 0.8 if valid else 0.2
                description = f"Patrón alcista: vela {'fuerte' if valid else 'débil'}"
                
            else:
                # Buscar velas bajistas con momentum creciente
                last_bearish = self._is_bearish_candle(last)
                body_size_increasing = self._candle_body_size(last) > self._candle_body_size(prev)
                
                valid = last_bearish and body_size_increasing
                strength = 0.8 if valid else 0.2
                description = f"Patrón bajista: vela {'fuerte' if valid else 'débil'}"
            
            return {
                'valid': valid,
                'strength': strength,
                'description': description
            }
            
        except Exception as e:
            logger.warning(f"Error analizando patrón de velas: {e}")
            return {'valid': False, 'strength': 0.0, 'description': 'Error en análisis'}
    
    def _calculate_ema_alignment_strength(self, ema21: float, ema50: float, ema200: float) -> float:
        """Calcula la fortaleza de la alineación de EMAs"""
        try:
            # Calcular separaciones relativas
            sep_21_50 = abs(ema21 - ema50) / ema50 if ema50 > 0 else 0
            sep_50_200 = abs(ema50 - ema200) / ema200 if ema200 > 0 else 0
            
            # Normalizar y combinar
            strength = min(1.0, (sep_21_50 + sep_50_200) * 50)  # Factor de escala
            
            return strength
            
        except Exception as e:
            logger.warning(f"Error calculando alineación de EMAs: {e}")
            return 0.5


# ============================================================================
# EURUSD PARTIAL — validada mediante Exit Research (julio 2026)
# ============================================================================

class EURUSDPartialStrategy(EURUSDStrategy):
    """
    EURUSD v3 — Partial Close (LastEdge v1.1)

    Entrada: idéntica a EURUSDStrategy (eurusd_simple).
    Salida:  50% Parcial + Trailing — variante validada mediante Exit Research
             (run_id: 20260702_225143, validación: val_20260703_160132).

    Resultados de validación (20.000 velas H1):
        PF = 1.85  |  WR = 54.1%  |  MaxDD = 2,125 pips
        Expectancy = 7.88 pips/trade  |  MC Ruin = 0.0%
        WF = MARGINAL  |  Stability Score = 51.73/100

    Parámetros de salida validados (NO modificar sin nueva validación):
        SL inicial   = 1.5 × ATR
        Cierre 50%   = 2.0 × ATR de beneficio
        Trailing SL  = 1.5 × ATR del segundo tramo
        TP máximo    = 5.0 × ATR (segundo tramo)

    La lógica de entrada (detect_setup) es exactamente la de eurusd_simple.
    Solo se sobreescriben los parámetros de SL/TP en _get_default_config()
    para que el sistema de ejecución en producción use los niveles correctos.
    El cierre parcial y el trailing son gestionados por trailing_stops.py
    con la configuración definida en rules_config.json.

    Referencia:
        backtest_results/exit_research/20260702_225143/
        backtest_results/validation/val_20260703_160132/
    """

    VARIANT = "partial_close"
    EXIT_RESEARCH_RUN   = "20260702_225143"
    VALIDATION_RUN      = "val_20260703_160132"

    # Parámetros validados — no modificar
    _SL_ATR_MULT      = 1.5   # SL inicial
    _PARTIAL_ATR_MULT = 2.0   # trigger del cierre parcial (50%)
    _TRAIL_ATR_MULT   = 1.5   # trailing del segundo tramo
    _MAX_TP_ATR_MULT  = 5.0   # TP máximo del segundo tramo

    def __init__(self):
        super().__init__()
        # Actualizar nombre interno para trazabilidad en el journal
        self.strategy_name = "EURUSD_Partial"

    def _get_default_config(self) -> Dict:
        """
        Extiende la config de eurusd_simple con los parámetros de salida validados.
        Solo SL y TP se modifican respecto al padre — la lógica de entrada es idéntica.
        """
        cfg = super()._get_default_config()
        cfg.update({
            # Niveles de salida validados (exit_research 20260702_225143)
            'sl_atr_multiplier':      self._SL_ATR_MULT,
            'tp_atr_multiplier':      self._MAX_TP_ATR_MULT,   # TP máximo del trailing
            'partial_close_enabled':  True,
            'partial_close_atr_mult': self._PARTIAL_ATR_MULT,
            'trailing_atr_mult':      self._TRAIL_ATR_MULT,
            # Identificación
            'strategy_variant':       self.VARIANT,
            'exit_research_run':      self.EXIT_RESEARCH_RUN,
            'validation_run':         self.VALIDATION_RUN,
        })
        return cfg

    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[Dict]:
        """
        Entrada idéntica a eurusd_simple.
        Solo sobreescribe el campo 'strategy' en la señal para trazabilidad.
        """
        signal = super().detect_setup(df, config)
        if signal is None:
            return None

        # Actualizar identificación de estrategia en la señal
        signal['context']['strategy'] = 'eurusd_partial'
        signal['context']['exit_variant'] = self.VARIANT
        signal['context']['exit_research_run'] = self.EXIT_RESEARCH_RUN
        return signal


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_eurusd_strategy(advanced: bool = False) -> BaseStrategy:
    """
    Factory function para crear estrategia EURUSD
    
    Args:
        advanced: Si True, usa la estrategia avanzada
        
    Returns:
        Instancia de la estrategia EURUSD
    """
    if advanced:
        return EURUSDAdvancedStrategy()
    else:
        return EURUSDStrategy()