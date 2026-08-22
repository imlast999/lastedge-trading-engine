"""
XAUUSD Strategy - Estrategia específica para Gold (XAU/USD)

Estrategia ultra-selectiva para oro basada en:
- Reversión en niveles clave con confirmaciones múltiples
- Filtros estrictos de calidad
- Gestión de riesgo adaptada a la volatilidad del oro
"""

from typing import Dict, Optional
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import logging

from .base import BaseStrategy

logger = logging.getLogger(__name__)

class XAUUSDStrategy(BaseStrategy):
    """
    Estrategia XAUUSD: Momentum en tendencia con filtro EMA200

    Condiciones:
    - EMA20 > EMA50 (tendencia corto plazo)
    - Precio por encima de EMA200 (tendencia mayor)
    - RSI > 55 para BUY / RSI < 45 para SELL (momentum)
    - ATR > media (volatilidad presente)
    - Separación mínima EMA20/EMA50 (no lateral)
    """

    def __init__(self):
        super().__init__("XAUUSD_Simple")

    @property
    def metadata(self):
        from strategies.base import StrategyMetadata
        return StrategyMetadata(
            required_history=200,   # EMA200 es el indicador más lento
            symbol="XAUUSD",
            timeframe="H1",
            strategy_name="xauusd_simple",
            version="1.0",
        )

    def _get_default_config(self) -> Dict:
        return {
            'ema_fast':   20,
            'ema_slow':   50,
            'ema_trend':  200,
            'ema_min_separation': 0.001,   # 0.1% mínimo (oro tiene más separación que forex)
            'rsi_period': 14,
            'rsi_buy_threshold':  55,
            'rsi_sell_threshold': 45,
            'atr_period':     14,
            'atr_multiplier': 1.0,
            'sl_atr_multiplier': 2.0,
            'tp_atr_multiplier': 5.0,   # R:R 2.5 — oro necesita más recorrido
            'expires_minutes': 60,
        }

    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        df['ema20']  = self._ema(df['close'], config['ema_fast'])
        df['ema50']  = self._ema(df['close'], config['ema_slow'])
        df['ema200'] = self._ema(df['close'], config['ema_trend'])
        return df

    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[Dict]:
        cfg = {**self.default_config, **(config or {})}

        # ── 0. Session filter: no trading 22:00-06:00 UTC ────────────────────
        if 'time' in df.columns:
            last_hour = int(pd.to_datetime(df.iloc[-1]['time']).hour)
            if last_hour >= 22 or last_hour < 6:
                logger.debug("[XAUUSD][REJECT] outside_active_session | hour=%d", last_hour)
                return None

        if not self.validate_data(df) or len(df) < cfg['ema_trend']:
            logger.debug("[XAUUSD][REJECT] insufficient_data | len=%d", len(df))
            return None

        df = self.add_indicators(df, cfg)

        last = df.iloc[-1]
        price       = float(last['close'])
        ema20       = float(last['ema20'])
        ema50       = float(last['ema50'])
        ema200      = float(last['ema200'])
        rsi         = float(last['rsi'])
        atr_current = float(last['atr'])

        # ── 1. Tendencia EMA20 vs EMA50 ──────────────────────────────────────
        bullish = ema20 > ema50
        bearish = ema20 < ema50
        if not (bullish or bearish):
            return None
        direction = 'BUY' if bullish else 'SELL'

        # ── 2. Separación mínima (no lateral) ────────────────────────────────
        ema_sep = abs(ema20 - ema50) / ema50
        if ema_sep < cfg['ema_min_separation']:
            logger.debug("[XAUUSD][REJECT] ema_too_close | sep=%.4f", ema_sep)
            return None

        # ── 3. Filtro EMA200 (tendencia mayor) ───────────────────────────────
        if direction == 'BUY' and price < ema200:
            logger.debug("[XAUUSD][REJECT] price_below_ema200_buy")
            return None
        if direction == 'SELL' and price > ema200:
            logger.debug("[XAUUSD][REJECT] price_above_ema200_sell")
            return None

        # ── 4. RSI con momentum ───────────────────────────────────────────────
        rsi_ok = rsi > cfg['rsi_buy_threshold'] if direction == 'BUY' \
                 else rsi < cfg['rsi_sell_threshold']
        if not rsi_ok:
            logger.debug("[XAUUSD][REJECT] rsi_no_momentum | rsi=%.1f", rsi)
            return None

        # ── 5. ATR > media (volatilidad presente) ─────────────────────────────
        atr_mean = df['atr'].tail(20).mean()
        if atr_current <= atr_mean * cfg['atr_multiplier']:
            logger.debug("[XAUUSD][REJECT] low_volatility | atr=%.2f mean=%.2f", atr_current, atr_mean)
            return None

        # ── 6. No entrar en impulso adverso (2 velas en contra) ──────────────
        prev = df.iloc[-2]
        last_bearish = float(last['close']) < float(last['open'])
        prev_bearish = float(prev['close']) < float(prev['open'])
        last_bullish = float(last['close']) > float(last['open'])
        prev_bullish = float(prev['close']) > float(prev['open'])

        if direction == 'BUY' and last_bearish and prev_bearish:
            logger.debug("[XAUUSD][REJECT] two_bearish_candles_on_buy")
            return None
        if direction == 'SELL' and last_bullish and prev_bullish:
            logger.debug("[XAUUSD][REJECT] two_bullish_candles_on_sell")
            return None

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
        rsi_strength = abs(rsi - 50) / 50
        ema_strength = min(1.0, ema_sep * 50)
        setup_strength = (rsi_strength * 0.5) + (ema_strength * 0.5)

        signal = {
            'type': direction,
            'entry': price,
            'sl': sl,
            'tp': tp,
            'timeframe': 'H1',
            'explanation': (f'XAUUSD: {direction} | EMA200✓ | sep={ema_sep:.3f} | RSI {rsi:.1f}'),
            'expires': datetime.now(timezone.utc) + timedelta(minutes=cfg['expires_minutes']),
            'setup_strength': setup_strength,
            'context': {
                'strategy': 'xauusd_simple',
                'confirmations': [
                    {'name': 'EMA_TREND',   'passed': True, 'value': ema_sep,  'description': f'EMA sep={ema_sep:.3f}'},
                    {'name': 'EMA200',      'passed': True, 'value': 1.0,      'description': 'Precio lado EMA200'},
                    {'name': 'RSI_MOMENTUM','passed': True, 'value': rsi,      'description': f'RSI={rsi:.1f}'},
                    {'name': 'ATR_OK',      'passed': True, 'value': atr_current/atr_mean, 'description': 'Volatilidad ok'},
                ],
                'market_conditions': {
                    'ema20': ema20, 'ema50': ema50, 'ema200': ema200,
                    'ema_separation': ema_sep,
                    'rsi': rsi,
                    'atr_current': atr_current,
                    'atr_mean': atr_mean,
                },
                'risk_reward': tp_distance / sl_distance if sl_distance > 0 else 0,
                'simple_strategy': True
            }
        }

        logger.info("[XAUUSD][SIGNAL] type=%s | price=%.2f | rsi=%.1f | sep=%.3f | ema200_ok=True",
                   direction, price, rsi, ema_sep)
        return signal


class XAUUSDReversalStrategy(BaseStrategy):
    """
    Estrategia XAUUSD: Ultra-selectiva con reversión en niveles clave
    
    Setup Principal:
    - RSI en zona extrema (< 25 o > 75)
    - Precio cerca de EMA200 (nivel de reversión)
    - Confirmación de momentum con MACD
    
    Confirmaciones:
    - Patrón de velas de reversión
    - ATR elevado (volatilidad)
    - Divergencia RSI (si disponible)
    - Soporte/Resistencia cercano
    """
    
    def __init__(self):
        super().__init__("XAUUSD_Reversal")
    
    def _get_default_config(self) -> Dict:
        return {
            'ema_period': 200,
            'rsi_period': 14,
            'rsi_oversold': 25,
            'rsi_overbought': 75,
            'macd_fast': 12,
            'macd_slow': 26,
            'macd_signal': 9,
            'atr_period': 14,
            'atr_threshold': 1.2,  # ATR debe ser 20% mayor que la media
            'ema_distance_max': 0.005,  # Máximo 0.5% de distancia de EMA200
            'sl_atr_multiplier': 2.0,  # SL más amplio para oro
            'tp_atr_multiplier': 4.0,  # TP más amplio, R:R = 2.0
            'expires_minutes': 60,  # Más tiempo para oro
            'min_confirmations': 4,  # Muy selectivo
            'volume_threshold': 1.2  # Si hay volumen disponible
        }
    
    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        """Añade indicadores específicos para XAUUSD"""
        # EMA200 para nivel de reversión
        df['ema200'] = self._ema(df['close'], config['ema_period'])
        
        # MACD para confirmación de momentum
        df['macd'], df['macd_signal'], df['macd_hist'] = self._macd(
            df['close'], config['macd_fast'], config['macd_slow'], config['macd_signal']
        )
        
        # Bollinger Bands para contexto de volatilidad
        df['bb_upper'], df['bb_middle'], df['bb_lower'] = self._bollinger_bands(df['close'])
        
        # Stochastic para confirmación adicional
        df['stoch_k'], df['stoch_d'] = self._stochastic(df['high'], df['low'], df['close'])
        
        return df
    
    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[Dict]:
        """
        Detecta setup de reversión XAUUSD ultra-selectivo
        """
        cfg = {**self.default_config, **(config or {})}
        
        # Validar datos
        if not self.validate_data(df) or len(df) < cfg['ema_period']:
            return None
        
        # Añadir indicadores
        df = self.add_indicators(df, cfg)
        
        # Datos actuales
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        price = float(last['close'])
        ema200 = float(last['ema200'])
        rsi = float(last['rsi'])
        atr_current = float(last['atr'])
        
        # ========================================================================
        # SETUP PRINCIPAL: RSI extremo + cerca de EMA200
        # ========================================================================
        
        # RSI en zona extrema
        rsi_oversold = rsi < cfg['rsi_oversold']
        rsi_overbought = rsi > cfg['rsi_overbought']
        
        if not (rsi_oversold or rsi_overbought):
            return None
        
        # Precio cerca de EMA200 (nivel de reversión)
        ema_distance = abs(price - ema200) / ema200
        near_ema200 = ema_distance <= cfg['ema_distance_max']
        
        if not near_ema200:
            return None
        
        # Determinar dirección basada en RSI
        direction = 'BUY' if rsi_oversold else 'SELL'
        
        # ========================================================================
        # CONFIRMACIONES ULTRA-SELECTIVAS
        # ========================================================================
        
        confirmations = []
        
        # Confirmación 1: MACD divergencia/confirmación
        macd_hist = float(last['macd_hist'])
        macd_hist_prev = float(prev['macd_hist'])
        
        if direction == 'BUY':
            # Para BUY: MACD histograma debe estar mejorando
            macd_ok = macd_hist > macd_hist_prev and macd_hist > -0.5
        else:
            # Para SELL: MACD histograma debe estar empeorando
            macd_ok = macd_hist < macd_hist_prev and macd_hist < 0.5
        
        confirmations.append({
            'name': 'MACD_MOMENTUM',
            'passed': macd_ok,
            'value': macd_hist,
            'description': f"MACD momentum favorable para {direction}: {macd_hist:.4f}"
        })
        
        # Confirmación 2: ATR elevado (volatilidad necesaria)
        atr_mean = df['atr'].tail(20).mean()
        atr_high = atr_current > atr_mean * cfg['atr_threshold']
        
        confirmations.append({
            'name': 'ATR_HIGH',
            'passed': atr_high,
            'value': atr_current / atr_mean if atr_mean > 0 else 0,
            'description': f"ATR elevado: {atr_current:.2f} vs {atr_mean:.2f}"
        })
        
        # Confirmación 3: Patrón de velas de reversión
        reversal_pattern = self._detect_reversal_pattern(df.tail(5), direction)
        confirmations.append({
            'name': 'REVERSAL_PATTERN',
            'passed': reversal_pattern['valid'],
            'value': reversal_pattern['strength'],
            'description': reversal_pattern['description']
        })
        
        # Confirmación 4: Stochastic en zona extrema
        stoch_k = float(last['stoch_k'])
        
        if direction == 'BUY':
            stoch_ok = stoch_k < 30  # Oversold
        else:
            stoch_ok = stoch_k > 70  # Overbought
        
        confirmations.append({
            'name': 'STOCHASTIC_EXTREME',
            'passed': stoch_ok,
            'value': stoch_k,
            'description': f"Stochastic extremo para {direction}: {stoch_k:.1f}"
        })
        
        # Confirmación 5: Posición en Bollinger Bands
        bb_position = (price - last['bb_lower']) / (last['bb_upper'] - last['bb_lower'])
        
        if direction == 'BUY':
            bb_ok = bb_position < 0.2  # Cerca del límite inferior
        else:
            bb_ok = bb_position > 0.8  # Cerca del límite superior
        
        confirmations.append({
            'name': 'BB_EXTREME',
            'passed': bb_ok,
            'value': bb_position,
            'description': f"BB posición extrema: {bb_position:.2f}"
        })
        
        # Confirmación 6: Volumen (si disponible)
        if 'volume' in df.columns:
            volume_current = float(last['volume'])
            volume_mean = df['volume'].tail(20).mean()
            volume_high = volume_current > volume_mean * cfg['volume_threshold']
            
            confirmations.append({
                'name': 'VOLUME_HIGH',
                'passed': volume_high,
                'value': volume_current / volume_mean if volume_mean > 0 else 0,
                'description': f"Volumen elevado: {volume_current:.0f} vs {volume_mean:.0f}"
            })
        
        # Verificar mínimo de confirmaciones (ultra-selectivo)
        passed_confirmations = sum(1 for c in confirmations if c['passed'])
        if passed_confirmations < cfg['min_confirmations']:
            return None
        
        # ========================================================================
        # CALCULAR NIVELES ADAPTADOS AL ORO
        # ========================================================================
        
        # Distancias más amplias para oro debido a su volatilidad
        sl_distance = atr_current * cfg['sl_atr_multiplier']
        tp_distance = atr_current * cfg['tp_atr_multiplier']
        
        # Ajustar SL al EMA200 si está más cerca
        if direction == 'BUY':
            sl_ema_based = ema200 * 0.998  # 0.2% por debajo de EMA200
            sl = max(sl_ema_based, price - sl_distance)  # Usar el más conservador
            tp = price + tp_distance
        else:
            sl_ema_based = ema200 * 1.002  # 0.2% por encima de EMA200
            sl = min(sl_ema_based, price + sl_distance)  # Usar el más conservador
            tp = price - tp_distance
        
        # ========================================================================
        # CALCULAR FORTALEZA DEL SETUP (muy estricto)
        # ========================================================================
        
        # Factores de calidad para oro
        rsi_extremeness = 1.0 - (abs(rsi - 50) / 50)  # Qué tan extremo es el RSI
        ema_proximity = 1.0 - (ema_distance / cfg['ema_distance_max'])  # Qué tan cerca de EMA200
        confirmation_ratio = passed_confirmations / len(confirmations)
        volatility_factor = min(1.0, atr_current / atr_mean) if atr_mean > 0 else 0.5
        
        setup_strength = (
            (1.0 - rsi_extremeness) * 0.3 +  # RSI más extremo = mejor
            ema_proximity * 0.25 +
            confirmation_ratio * 0.3 +
            volatility_factor * 0.15
        )
        
        # ========================================================================
        # CREAR SEÑAL ULTRA-SELECTIVA
        # ========================================================================
        
        signal = {
            'type': direction,
            'entry': price,
            'sl': sl,
            'tp': tp,
            'timeframe': 'H1',
            'explanation': f'XAUUSD Ultra-Selectivo: {direction} + RSI {rsi:.1f} + EMA200 + {passed_confirmations}/{len(confirmations)} confirmaciones',
            'expires': datetime.now(timezone.utc) + timedelta(minutes=cfg['expires_minutes']),
            'setup_strength': setup_strength,
            'context': {
                'strategy': 'xauusd_reversal',
                'confirmations': confirmations,
                'market_conditions': {
                    'rsi': rsi,
                    'rsi_extremeness': 1.0 - rsi_extremeness,
                    'ema200': ema200,
                    'ema_distance': ema_distance,
                    'ema_proximity': ema_proximity,
                    'atr_current': atr_current,
                    'atr_mean': atr_mean,
                    'volatility_factor': volatility_factor,
                    'bb_position': bb_position,
                    'macd_histogram': macd_hist,
                    'stochastic': stoch_k
                },
                'risk_reward': tp_distance / abs(sl - price) if abs(sl - price) > 0 else 0,
                'reversal_setup': True,
                'ultra_selective': True,
                'quality_score': setup_strength
            }
        }
        
        return signal
    
    def _detect_reversal_pattern(self, candles: pd.DataFrame, direction: str) -> Dict:
        """
        Detecta patrones de velas de reversión específicos para oro
        """
        try:
            if len(candles) < 3:
                return {'valid': False, 'strength': 0.0, 'description': 'Datos insuficientes'}
            
            last = candles.iloc[-1]
            prev = candles.iloc[-2]
            prev2 = candles.iloc[-3]
            
            patterns_found = []
            total_strength = 0.0
            
            # Patrón 1: Hammer/Shooting Star
            if direction == 'BUY':
                # Hammer: cuerpo pequeño, sombra inferior larga
                body_size = abs(last['close'] - last['open'])
                lower_shadow = last['open'] - last['low'] if last['close'] > last['open'] else last['close'] - last['low']
                upper_shadow = last['high'] - last['close'] if last['close'] > last['open'] else last['high'] - last['open']
                total_range = last['high'] - last['low']
                
                if total_range > 0:
                    is_hammer = (
                        lower_shadow > body_size * 2 and  # Sombra inferior larga
                        upper_shadow < body_size * 0.5 and  # Sombra superior corta
                        body_size / total_range < 0.3  # Cuerpo pequeño
                    )
                    
                    if is_hammer:
                        patterns_found.append('Hammer')
                        total_strength += 0.8
            
            else:  # SELL
                # Shooting Star: cuerpo pequeño, sombra superior larga
                body_size = abs(last['close'] - last['open'])
                lower_shadow = last['open'] - last['low'] if last['close'] > last['open'] else last['close'] - last['low']
                upper_shadow = last['high'] - last['close'] if last['close'] > last['open'] else last['high'] - last['open']
                total_range = last['high'] - last['low']
                
                if total_range > 0:
                    is_shooting_star = (
                        upper_shadow > body_size * 2 and  # Sombra superior larga
                        lower_shadow < body_size * 0.5 and  # Sombra inferior corta
                        body_size / total_range < 0.3  # Cuerpo pequeño
                    )
                    
                    if is_shooting_star:
                        patterns_found.append('Shooting Star')
                        total_strength += 0.8
            
            # Patrón 2: Engulfing
            if len(candles) >= 2:
                prev_body = abs(prev['close'] - prev['open'])
                last_body = abs(last['close'] - last['open'])
                
                if direction == 'BUY':
                    # Bullish Engulfing
                    is_engulfing = (
                        prev['close'] < prev['open'] and  # Vela anterior bajista
                        last['close'] > last['open'] and  # Vela actual alcista
                        last['open'] < prev['close'] and  # Abre por debajo del cierre anterior
                        last['close'] > prev['open'] and  # Cierra por encima de la apertura anterior
                        last_body > prev_body * 1.2  # Cuerpo más grande
                    )
                    
                    if is_engulfing:
                        patterns_found.append('Bullish Engulfing')
                        total_strength += 0.9
                
                else:  # SELL
                    # Bearish Engulfing
                    is_engulfing = (
                        prev['close'] > prev['open'] and  # Vela anterior alcista
                        last['close'] < last['open'] and  # Vela actual bajista
                        last['open'] > prev['close'] and  # Abre por encima del cierre anterior
                        last['close'] < prev['open'] and  # Cierra por debajo de la apertura anterior
                        last_body > prev_body * 1.2  # Cuerpo más grande
                    )
                    
                    if is_engulfing:
                        patterns_found.append('Bearish Engulfing')
                        total_strength += 0.9
            
            # Patrón 3: Doji en zona extrema
            if self._is_doji(last, threshold=0.15):  # Más tolerante para oro
                patterns_found.append('Doji')
                total_strength += 0.6
            
            # Evaluar resultado
            valid = len(patterns_found) > 0 and total_strength >= 0.6
            avg_strength = total_strength / len(patterns_found) if patterns_found else 0.0
            
            description = f"Patrones: {', '.join(patterns_found)}" if patterns_found else "Sin patrón de reversión"
            
            return {
                'valid': valid,
                'strength': min(1.0, avg_strength),
                'description': description,
                'patterns': patterns_found
            }
            
        except Exception as e:
            logger.warning(f"Error detectando patrón de reversión: {e}")
            return {'valid': False, 'strength': 0.0, 'description': 'Error en análisis'}


class XAUUSDMomentumStrategy(BaseStrategy):
    """
    Estrategia XAUUSD Momentum: Para tendencias fuertes en oro
    
    Complementa la estrategia de reversión capturando movimientos direccionales
    cuando el oro está en tendencia clara.
    """
    
    def __init__(self):
        super().__init__("XAUUSD_Momentum")
    
    def _get_default_config(self) -> Dict:
        return {
            'ema_fast': 21,
            'ema_slow': 50,
            'ema_filter': 200,
            'rsi_period': 14,
            'rsi_min': 45,
            'rsi_max': 55,
            'atr_period': 14,
            'momentum_threshold': 0.002,  # 0.2% de movimiento mínimo
            'sl_atr_multiplier': 1.8,
            'tp_atr_multiplier': 3.6,  # R:R = 2.0
            'expires_minutes': 45,
            'min_confirmations': 3
        }
    
    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        """Añade indicadores para momentum en oro"""
        df['ema21'] = self._ema(df['close'], config['ema_fast'])
        df['ema50'] = self._ema(df['close'], config['ema_slow'])
        df['ema200'] = self._ema(df['close'], config['ema_filter'])
        
        # Rate of Change para momentum
        df['roc'] = df['close'].pct_change(periods=5)
        
        return df
    
    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[Dict]:
        """
        Detecta setup de momentum para XAUUSD
        """
        cfg = {**self.default_config, **(config or {})}
        
        if not self.validate_data(df) or len(df) < cfg['ema_filter']:
            return None
        
        df = self.add_indicators(df, cfg)
        
        last = df.iloc[-1]
        price = float(last['close'])
        ema21 = float(last['ema21'])
        ema50 = float(last['ema50'])
        ema200 = float(last['ema200'])
        rsi = float(last['rsi'])
        roc = float(last['roc'])
        
        # Setup: EMAs alineadas + momentum + filtro de tendencia
        bullish_momentum = (
            ema21 > ema50 and  # EMAs alineadas
            price > ema200 and  # Por encima de filtro de tendencia
            roc > cfg['momentum_threshold'] and  # Momentum positivo
            cfg['rsi_min'] <= rsi <= cfg['rsi_max']  # RSI neutral
        )
        
        bearish_momentum = (
            ema21 < ema50 and  # EMAs alineadas
            price < ema200 and  # Por debajo de filtro de tendencia
            roc < -cfg['momentum_threshold'] and  # Momentum negativo
            cfg['rsi_min'] <= rsi <= cfg['rsi_max']  # RSI neutral
        )
        
        if not (bullish_momentum or bearish_momentum):
            return None
        
        direction = 'BUY' if bullish_momentum else 'SELL'
        
        # Confirmaciones básicas
        confirmations = []
        
        # Confirmación 1: Separación de EMAs
        ema_separation = abs(ema21 - ema50) / ema50 if ema50 > 0 else 0
        ema_sep_ok = ema_separation > 0.001  # 0.1% mínimo
        
        confirmations.append({
            'name': 'EMA_SEPARATION',
            'passed': ema_sep_ok,
            'value': ema_separation,
            'description': f"Separación EMAs: {ema_separation:.4f}"
        })
        
        # Confirmación 2: Momentum sostenido
        momentum_sustained = abs(roc) > cfg['momentum_threshold'] * 1.5
        confirmations.append({
            'name': 'MOMENTUM_SUSTAINED',
            'passed': momentum_sustained,
            'value': abs(roc),
            'description': f"Momentum sostenido: {roc:.4f}"
        })
        
        # Confirmación 3: ATR adecuado
        atr_current = float(last['atr'])
        atr_mean = df['atr'].tail(20).mean()
        atr_ok = atr_current > atr_mean * 0.8
        
        confirmations.append({
            'name': 'ATR_ADEQUATE',
            'passed': atr_ok,
            'value': atr_current / atr_mean if atr_mean > 0 else 0,
            'description': f"ATR adecuado: {atr_current:.2f}"
        })
        
        passed_confirmations = sum(1 for c in confirmations if c['passed'])
        if passed_confirmations < cfg['min_confirmations']:
            return None
        
        # Calcular niveles
        sl_distance = atr_current * cfg['sl_atr_multiplier']
        tp_distance = atr_current * cfg['tp_atr_multiplier']
        
        if direction == 'BUY':
            sl = price - sl_distance
            tp = price + tp_distance
        else:
            sl = price + sl_distance
            tp = price - tp_distance
        
        # Setup strength
        confirmation_ratio = passed_confirmations / len(confirmations)
        momentum_strength = min(1.0, abs(roc) / (cfg['momentum_threshold'] * 3))
        ema_strength = min(1.0, ema_separation * 100)
        
        setup_strength = (
            confirmation_ratio * 0.4 +
            momentum_strength * 0.4 +
            ema_strength * 0.2
        )
        
        signal = {
            'type': direction,
            'entry': price,
            'sl': sl,
            'tp': tp,
            'timeframe': 'H1',
            'explanation': f'XAUUSD Momentum: {direction} + EMAs + ROC {roc:.3f} + {passed_confirmations}/{len(confirmations)} conf',
            'expires': datetime.now(timezone.utc) + timedelta(minutes=cfg['expires_minutes']),
            'setup_strength': setup_strength,
            'context': {
                'strategy': 'xauusd_momentum',
                'confirmations': confirmations,
                'market_conditions': {
                    'ema_alignment': direction.lower(),
                    'momentum': roc,
                    'ema_separation': ema_separation,
                    'rsi': rsi,
                    'trend_filter': 'bullish' if price > ema200 else 'bearish'
                },
                'risk_reward': tp_distance / sl_distance if sl_distance > 0 else 0,
                'momentum_setup': True
            }
        }
        
        return signal


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_xauusd_strategy(strategy_type: str = 'reversal') -> BaseStrategy:
    """
    Factory function para crear estrategia XAUUSD
    
    Args:
        strategy_type: 'reversal' o 'momentum'
        
    Returns:
        Instancia de la estrategia XAUUSD
    """
    if strategy_type == 'momentum':
        return XAUUSDMomentumStrategy()
    else:
        return XAUUSDStrategy()