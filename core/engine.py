"""
Core Trading Engine - Orquestador principal de señales

Este módulo consolida toda la lógica de detección, scoring, confianza y filtros
en un solo lugar, eliminando la fragmentación del código anterior.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
import pandas as pd

logger = logging.getLogger(__name__)

def get_current_period_start() -> datetime:
    """Obtiene el inicio del período actual (00:00 o 12:00 UTC)"""
    now = datetime.now(timezone.utc)
    if now.hour < 12:
        # Período 00:00-12:00
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        # Período 12:00-24:00
        return now.replace(hour=12, minute=0, second=0, microsecond=0)

@dataclass
class BotState:
    """Estado global del bot consolidado"""
    pending_signals: Dict[int, dict] = field(default_factory=dict)
    trades_today: int = 0
    trades_current_period: int = 0  # Trades en el período actual (12h)
    current_period_start: datetime = field(default_factory=get_current_period_start)
    mt5_credentials: Dict[str, Any] = field(default_factory=dict)
    autosignals: bool = field(default_factory=lambda: os.getenv('AUTOSIGNALS', '0') == '1')
    last_auto_sent: Dict[str, Any] = field(default_factory=dict)

# Estado global de símbolos activos (punto único de verdad)
active_symbols: Dict[str, bool] = {
    "EURUSD": True,
    "XAUUSD": True,
    "BTCEUR": True,
}

# Estado de salud por símbolo (visibilidad; OK/DISABLED/ERROR + actividad)
# Inicializado para los tres pares principales; last_signal_time y signals_count se actualizan al generar señales
_symbol_health_default = {
    "status": "OK",
    "last_signal_time": None,
    "last_error": None,
    "signals_count": 0,
}
symbol_health: Dict[str, Dict] = {
    "EURUSD": dict(_symbol_health_default),
    "XAUUSD": dict(_symbol_health_default),
    "BTCEUR": {
        "status": "OK",
        "last_signal_time": None,
        "last_error": None,
        "signals_count": 0,
    },
}

def set_btceur_health(
    status: str = None,
    last_signal_time: Any = None,
    last_error: str = None,
) -> None:
    """Actualiza el estado de salud de BTCEUR para visibilidad."""
    try:
        h = symbol_health.get("BTCEUR", {})
        if status is not None:
            h["status"] = status
        if last_signal_time is not None:
            h["last_signal_time"] = last_signal_time
        if last_error is not None:
            h["last_error"] = last_error[:200] if last_error else None  # limitar longitud
        symbol_health["BTCEUR"] = h
    except Exception:
        pass


def record_signal(symbol: str) -> None:
    """Registra que se generó una señal válida para el símbolo (solo tracking, no lógica de trading)."""
    try:
        sym = symbol.upper()
        h = symbol_health.get(sym)
        if h is None:
            h = {"status": "OK", "last_signal_time": None, "last_error": None, "signals_count": 0}
        else:
            h = dict(h)
        h["signals_count"] = h.get("signals_count", 0) + 1
        now = datetime.now(timezone.utc)
        h["last_signal_time"] = now
        symbol_health[sym] = h
        if sym == "BTCEUR":
            set_btceur_health(status="OK", last_signal_time=now)
    except Exception:
        pass

def is_symbol_active(symbol: str) -> bool:
    """Indica si un símbolo está actualmente activo en la configuración dinámica."""
    try:
        return active_symbols.get(symbol.upper(), False)
    except Exception:
        return False

@dataclass
class SignalContext:
    """Contexto completo de una señal para evaluación"""
    symbol: str
    strategy: str
    raw_signal: Dict
    dataframe: pd.DataFrame
    market_conditions: Dict
    risk_info: Dict

@dataclass
class SignalResult:
    """Resultado final de evaluación de señal"""
    signal: Optional[Dict]
    should_show: bool
    should_execute: bool
    confidence: str
    score: float
    rejection_reason: Optional[str]
    details: Dict

class TradingEngine:
    """
    Motor principal de trading que orquesta:
    1. Detección de señales
    2. Scoring y confianza
    3. Filtros y validaciones
    4. Decisión final
    """
    
    def __init__(self):
        from core.scoring import get_scoring_system
        self.scoring_system = get_scoring_system()
        self.confidence_system = ConfidenceSystem()
        self.duplicate_filter = DuplicateFilter()
        
        # Sistema de cooldown por símbolo
        self.cooldown_state = {}  # {symbol: {'last_signal_index': int, 'cooldown_bars': int}}
        self._load_cooldown_config()
        
        # Estadísticas internas para logging inteligente
        self.stats = defaultdict(int)
        self.rejection_reasons = defaultdict(int)
        self.last_dump = datetime.now()
    
    def _load_cooldown_config(self):
        """Carga configuración de cooldown desde rules_config.json"""
        import json
        import os
        
        try:
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules_config.json')
            with open(config_path, 'r') as f:
                rules = json.load(f)
            
            # Inicializar cooldown para cada símbolo
            for symbol in ['EURUSD', 'XAUUSD', 'BTCEUR']:
                symbol_rules = rules.get(symbol, {})
                cooldown_bars = symbol_rules.get('cooldown_bars', 10)  # Default: 10 velas
                
                self.cooldown_state[symbol] = {
                    'last_signal_index': None,
                    'cooldown_bars': cooldown_bars
                }
            
            logger.info("✓ Configuración de cooldown cargada desde rules_config.json")
            
        except Exception as e:
            logger.warning(f"Error cargando configuración de cooldown, usando valores por defecto: {e}")
            # Fallback a valores por defecto
            for symbol in ['EURUSD', 'XAUUSD', 'BTCEUR']:
                self.cooldown_state[symbol] = {
                    'last_signal_index': None,
                    'cooldown_bars': 10
                }
    
    def _check_cooldown(self, symbol: str, current_index: int) -> Tuple[bool, Optional[str]]:
        """
        Verifica si una señal está en período de cooldown
        
        Args:
            symbol: Símbolo del instrumento
            current_index: Índice de la vela actual
            
        Returns:
            Tuple (is_in_cooldown, reason)
        """
        if symbol not in self.cooldown_state:
            # Símbolo no configurado, permitir señal
            return False, None
        
        state = self.cooldown_state[symbol]
        last_index = state.get('last_signal_index')
        cooldown_bars = state.get('cooldown_bars', 10)
        
        if last_index is None:
            # Primera señal, no hay cooldown
            return False, None
        
        bars_since_last = current_index - last_index

        # Nueva ventana de replay / walk-forward: índices reinician, no aplicar cooldown
        if bars_since_last < 0:
            return False, None
        
        if bars_since_last < cooldown_bars:
            # Aún en cooldown
            remaining = cooldown_bars - bars_since_last
            return True, f"Cooldown activo: {remaining} velas restantes (última señal en vela {last_index})"
        
        # Cooldown expirado, permitir señal
        return False, None
    
    def reset_replay_state(self, symbol: Optional[str] = None) -> None:
        """
        Reinicia TODO el estado acumulado entre ventanas de backtest / walk-forward.
        Limpia: cooldown, filtro de duplicados, instancias de estrategias cacheadas.
        Sin esto, las ventanas 2+ de walk-forward producen 0 señales porque el
        filtro de duplicados retiene señales de ventanas anteriores.
        """
        # 1. Reset cooldown state
        symbols = [symbol.upper()] if symbol else list(self.cooldown_state.keys())
        for sym in symbols:
            if sym in self.cooldown_state:
                self.cooldown_state[sym]['last_signal_index'] = None
        
        # 2. Reset duplicate filter — esta es la causa raíz del bug de walk-forward
        #    El DuplicateFilter guarda señales recientes y sin resetearlas, las
        #    ventanas 2+ detectan TODAS las señales como duplicadas de la ventana 1.
        self.duplicate_filter.recent_signals.clear()
        
        # 3. Reset cached strategy instances (stateful strategies como asian_breakout)
        try:
            from signals import reset_strategy_instances
            reset_strategy_instances()
        except Exception:
            pass
        
        logger.debug(f"Replay state reset for {symbol or 'ALL symbols'}")

    def _update_cooldown(self, symbol: str, current_index: int):
        """
        Actualiza el estado de cooldown después de generar una señal válida
        
        Args:
            symbol: Símbolo del instrumento
            current_index: Índice de la vela actual
        """
        if symbol not in self.cooldown_state:
            # Inicializar si no existe
            self.cooldown_state[symbol] = {
                'last_signal_index': current_index,
                'cooldown_bars': 10
            }
        else:
            self.cooldown_state[symbol]['last_signal_index'] = current_index
    
    def evaluate_signal(self, df: pd.DataFrame, symbol: str, strategy: str = 'ema50_200', 
                       config: Dict = None, skip_duplicate_filter: bool = False, 
                       current_index: Optional[int] = None,
                       current_bar_time: Optional[datetime] = None) -> SignalResult:
        """
        Evaluación completa de señal con pipeline integrado:
        1. Detectar setup básico
        2. Calcular scoring y confianza  
        3. Aplicar filtros (duplicados y cooldown)
        4. Decisión final
        
        Args:
            df: DataFrame con datos OHLCV
            symbol: Símbolo del instrumento
            strategy: Nombre de la estrategia a usar
            config: Configuración específica (opcional)
            skip_duplicate_filter: Si True, omite el filtro de duplicados (para diagnóstico)
            current_index: Índice de la vela actual (para cooldown en replay)
            current_bar_time: Timestamp de la vela actual (para deduplicación en backtest).
                             Si es None, usa datetime.now() (producción).
        """
        try:
            # 0. Verificar si el símbolo está activo antes de cualquier cálculo
            if not is_symbol_active(symbol):
                return self._create_rejection_result(
                    symbol, strategy, "Símbolo desactivado en configuración dinámica"
                )

            # 1. Detectar señal básica
            from signals import detect_signal
            raw_signal, df_with_indicators = detect_signal(df, strategy, config, symbol=symbol)
            
            if not raw_signal:
                return self._create_rejection_result(
                    symbol, strategy, "No setup básico detectado"
                )
            
            # Asegurar símbolo correcto
            raw_signal['symbol'] = symbol
            
            # 2. Crear contexto para evaluación
            context = SignalContext(
                symbol=symbol,
                strategy=strategy,
                raw_signal=raw_signal,
                dataframe=df_with_indicators,
                market_conditions=self._analyze_market_conditions(df_with_indicators),
                risk_info={}
            )
            
            # 3. Calcular scoring y confianza
            scoring_result = self.scoring_system.evaluate_signal_context(context)
            confidence_result = self.confidence_system.calculate_confidence_context(context)
            
            # 4. Verificar filtro de duplicados (solo si no se omite)
            if not skip_duplicate_filter:
                is_duplicate, duplicate_reason = self.duplicate_filter.is_duplicate(
                    raw_signal, symbol, current_time=current_bar_time
                )
                if is_duplicate:
                    return self._create_rejection_result(
                        symbol, strategy, f"Duplicado: {duplicate_reason}"
                    )
            
            # 5. Decisión final
            should_show = scoring_result.should_show and confidence_result.should_show
            should_execute = should_show and confidence_result.should_execute
            
            # 6. Verificar cooldown ANTES de crear señal final (solo si pasó scoring y confianza)
            if should_show and current_index is not None:
                is_in_cooldown, cooldown_reason = self._check_cooldown(symbol, current_index)
                if is_in_cooldown:
                    return self._create_rejection_result(
                        symbol, strategy, cooldown_reason
                    )
            
            # 7. Crear señal final enriquecida
            if should_show:
                final_signal = self._enrich_signal(
                    raw_signal, scoring_result, confidence_result, context
                )
                
                # Actualizar cooldown si se proporcionó índice
                if current_index is not None:
                    self._update_cooldown(symbol, current_index)
                
                # Actualizar estadísticas
                self.stats['signals_shown'] += 1
                
                return SignalResult(
                    signal=final_signal,
                    should_show=True,
                    should_execute=should_execute,
                    confidence=confidence_result.confidence_level,
                    score=scoring_result.final_score,
                    rejection_reason=None,
                    details={
                        'scoring': scoring_result.details,
                        'confidence': confidence_result.details,
                        'market_conditions': context.market_conditions
                    }
                )
            else:
                # Señal rechazada por scoring/confianza
                reason = "Score insuficiente" if not scoring_result.should_show else "Confianza insuficiente"
                return self._create_rejection_result(symbol, strategy, reason)
                
        except Exception as e:
            logger.error(f"Error evaluando señal {symbol}: {e}")
            return self._create_rejection_result(symbol, strategy, f"Error: {str(e)}")
    
    def _analyze_market_conditions(self, df: pd.DataFrame) -> Dict:
        """Analiza condiciones generales del mercado"""
        try:
            last = df.iloc[-1]
            
            # Volatilidad (ATR)
            if 'atr' in df.columns:
                atr_current = last['atr']
                atr_mean = df['atr'].tail(20).mean()
                volatility_ratio = atr_current / atr_mean if atr_mean > 0 else 1.0
            else:
                volatility_ratio = 1.0
            
            # Tendencia (EMA200 si existe)
            trend_direction = 'NEUTRAL'
            if 'ema200' in df.columns:
                price = last['close']
                ema200 = last['ema200']
                if price > ema200 * 1.001:
                    trend_direction = 'BULLISH'
                elif price < ema200 * 0.999:
                    trend_direction = 'BEARISH'
            
            return {
                'volatility_ratio': volatility_ratio,
                'trend_direction': trend_direction,
                'price': float(last['close']),
                'volume_available': 'volume' in df.columns
            }
            
        except Exception as e:
            logger.warning(f"Error analizando condiciones de mercado: {e}")
            return {'error': str(e)}
    
    def _enrich_signal(self, raw_signal: Dict, scoring_result, confidence_result, context: SignalContext) -> Dict:
        """Enriquece la señal con información de scoring y confianza"""
        enriched = raw_signal.copy()
        
        # Información de scoring
        enriched['confidence'] = confidence_result.confidence_level
        enriched['confidence_score'] = confidence_result.confidence_score
        enriched['score'] = scoring_result.final_score
        
        # Detalles para debugging
        enriched['scoring_details'] = scoring_result.details
        enriched['confidence_details'] = confidence_result.details
        enriched['market_conditions'] = context.market_conditions
        
        # Metadatos
        enriched['strategy_used'] = context.strategy
        enriched['evaluation_time'] = datetime.now(timezone.utc).isoformat()
        
        return enriched
    
    def _create_rejection_result(self, symbol: str, strategy: str, reason: str) -> SignalResult:
        """Crea resultado de rechazo con estadísticas"""
        self.stats['signals_rejected'] += 1
        self.rejection_reasons[reason] += 1
        
        return SignalResult(
            signal=None,
            should_show=False,
            should_execute=False,
            confidence='NONE',
            score=0.0,
            rejection_reason=reason,
            details={'symbol': symbol, 'strategy': strategy, 'reason': reason}
        )
    
    def get_statistics(self) -> Dict:
        """Obtiene estadísticas del engine"""
        total_evaluated = self.stats['signals_shown'] + self.stats['signals_rejected']
        
        return {
            'total_evaluated': total_evaluated,
            'signals_shown': self.stats['signals_shown'],
            'signals_rejected': self.stats['signals_rejected'],
            'show_rate': (self.stats['signals_shown'] / total_evaluated * 100) if total_evaluated > 0 else 0,
            'top_rejection_reasons': dict(sorted(self.rejection_reasons.items(), key=lambda x: x[1], reverse=True)[:5])
        }
    
    async def get_market_data(self, symbol: str, timeframe: str = 'H1', count: int = 100) -> Optional[pd.DataFrame]:
        """
        Obtiene datos de mercado para un símbolo
        
        Args:
            symbol: Símbolo del instrumento (e.g., 'EURUSD')
            timeframe: Marco temporal (e.g., 'H1', 'M15')
            count: Número de velas a obtener
            
        Returns:
            DataFrame con datos OHLCV o None si hay error
        """
        try:
            # Importar MT5 client functions
            from services import mt5_client
            
            # Obtener datos usando la función get_candles
            df = mt5_client.get_candles(symbol, timeframe, count)
            
            if df is None or len(df) == 0:
                logger.warning(f"No data received for {symbol} {timeframe}")
                return None
            
            # Asegurar que tenemos las columnas básicas
            required_columns = ['open', 'high', 'low', 'close']
            if not all(col in df.columns for col in required_columns):
                logger.error(f"Missing required columns in data for {symbol}")
                return None
            
            return df
            
        except Exception as e:
            logger.error(f"Error getting market data for {symbol}: {e}")
            return None


# ============================================================================
# SISTEMA DE SCORING INTEGRADO (consolidado de signals.py)
# ============================================================================

@dataclass
class ConfirmationRule:
    """Regla de confirmación con peso y descripción"""
    name: str
    weight: float = 1.0
    description: str = ""
    critical: bool = False

@dataclass
class ScoringResult:
    """Resultado del sistema de scoring"""
    setup_valid: bool
    confirmations_passed: int
    confirmations_total: int
    final_score: float
    confidence_level: str
    should_show: bool
    details: Dict
    failed_confirmations: List[str]

class FlexibleScoring:
    """Sistema de scoring flexible consolidado"""
    
    def __init__(self):
        # Configuración por símbolo
        self.symbol_config = {
            'EURUSD': {'min_score': 0.60, 'show_threshold': 0.50, 'setup_weight': 0.4},
            'XAUUSD': {'min_score': 0.65, 'show_threshold': 0.60, 'setup_weight': 0.5},
            'BTCEUR': {'min_score': 0.55, 'show_threshold': 0.45, 'setup_weight': 0.4}
        }
    
    def evaluate_signal_context(self, context: SignalContext) -> ScoringResult:
        """Evalúa señal usando contexto completo"""
        symbol = context.symbol
        signal = context.raw_signal
        df = context.dataframe
        
        # Extraer confirmaciones del contexto de la señal
        confirmations = self._extract_confirmations_from_signal(signal, df, symbol)
        
        return self.evaluate_signal(symbol, True, confirmations)
    
    def evaluate_signal(self, symbol: str, setup_valid: bool, 
                       confirmations: List[Tuple[bool, ConfirmationRule]]) -> ScoringResult:
        """Evalúa una señal usando scoring flexible"""
        
        config = self.symbol_config.get(symbol, self.symbol_config['EURUSD'])
        
        if not setup_valid:
            return ScoringResult(
                setup_valid=False, confirmations_passed=0, confirmations_total=len(confirmations),
                final_score=0.0, confidence_level='NONE', should_show=False,
                details={'reason': 'Setup principal no válido'}, failed_confirmations=['SETUP_INVALID']
            )
        
        # Evaluar confirmaciones
        passed_confirmations = []
        failed_confirmations = []
        total_weight = sum(rule.weight for _, rule in confirmations)
        passed_weight = sum(rule.weight for result, rule in confirmations if result)
        
        for result, rule in confirmations:
            if result:
                passed_confirmations.append(rule.name)
            else:
                failed_confirmations.append(rule.name)
        
        # Score ponderado
        weighted_score = passed_weight / total_weight if total_weight > 0 else 0.0
        
        # Score final (setup + confirmaciones)
        setup_weight = config.get('setup_weight', 0.5)
        final_score = (setup_weight * 1.0) + ((1 - setup_weight) * weighted_score)
        
        # Determinar confianza
        if final_score >= 0.75:
            confidence = 'HIGH'
        elif final_score >= 0.65:
            confidence = 'MEDIUM-HIGH'
        elif final_score >= 0.50:
            confidence = 'MEDIUM'
        else:
            confidence = 'LOW'
        
        # Determinar si mostrar
        show_threshold = config.get('show_threshold', 0.50)
        should_show = final_score >= show_threshold
        
        return ScoringResult(
            setup_valid=setup_valid,
            confirmations_passed=len(passed_confirmations),
            confirmations_total=len(confirmations),
            final_score=final_score,
            confidence_level=confidence,
            should_show=should_show,
            details={
                'symbol': symbol,
                'passed_confirmations': passed_confirmations,
                'failed_confirmations': failed_confirmations,
                'weighted_score': weighted_score,
                'show_threshold': show_threshold
            },
            failed_confirmations=failed_confirmations
        )
    
    def _extract_confirmations_from_signal(self, signal: Dict, df: pd.DataFrame, symbol: str) -> List[Tuple[bool, ConfirmationRule]]:
        """Extrae confirmaciones básicas de una señal"""
        confirmations = []
        
        try:
            last = df.iloc[-1]
            
            # Confirmación 1: RSI en rango operativo
            if 'rsi' in df.columns:
                rsi = last['rsi']
                rsi_ok = 30 <= rsi <= 70
                confirmations.append((rsi_ok, ConfirmationRule(
                    "RSI_RANGE", 1.0, f"RSI en rango: {rsi:.1f}"
                )))
            
            # Confirmación 2: ATR adecuado
            if 'atr' in df.columns:
                atr_current = last['atr']
                atr_mean = df['atr'].tail(20).mean()
                atr_ok = atr_current > atr_mean * 0.8
                confirmations.append((atr_ok, ConfirmationRule(
                    "ATR_ADEQUATE", 0.8, f"ATR: {atr_current:.5f} vs {atr_mean:.5f}"
                )))
            
            # Confirmación 3: Dirección de vela
            direction = signal.get('type', 'BUY')
            candle_body = last['close'] - last['open']
            if direction == 'BUY':
                candle_ok = candle_body > 0
            else:
                candle_ok = candle_body < 0
            
            confirmations.append((candle_ok, ConfirmationRule(
                "CANDLE_DIRECTION", 0.6, f"Vela en dirección {direction}"
            )))
            
        except Exception as e:
            logger.warning(f"Error extrayendo confirmaciones: {e}")
        
        return confirmations


# ============================================================================
# SISTEMA DE CONFIANZA INTEGRADO (consolidado de confidence_system.py)
# ============================================================================

@dataclass
class ConfidenceResult:
    """Resultado del sistema de confianza"""
    confidence_level: str
    confidence_score: float
    should_show: bool
    should_execute: bool
    details: Dict

class ConfidenceSystem:
    """Sistema de confianza consolidado"""
    
    def __init__(self):
        self.confidence_thresholds = {
            'VERY_HIGH': 0.85,
            'HIGH': 0.70,
            'MEDIUM-HIGH': 0.60,
            'MEDIUM': 0.50,
            'LOW': 0.30
        }
    
    def calculate_confidence_context(self, context: SignalContext) -> ConfidenceResult:
        """Calcula confianza usando contexto completo"""
        signal = context.raw_signal
        df = context.dataframe
        symbol = context.symbol
        
        # Factores de confianza
        factors = self._calculate_confidence_factors(signal, df, symbol)
        
        # Score ponderado
        confidence_score = sum(factors.values()) / len(factors)
        
        # Determinar nivel
        confidence_level = self._score_to_level(confidence_score)
        
        # Decisiones
        should_show = confidence_score >= 0.40  # Umbral más bajo para mostrar
        should_execute = confidence_score >= 0.65  # Umbral alto para ejecución
        
        return ConfidenceResult(
            confidence_level=confidence_level,
            confidence_score=confidence_score,
            should_show=should_show,
            should_execute=should_execute,
            details={
                'factors': factors,
                'symbol': symbol,
                'thresholds': {
                    'show': 0.40,
                    'execute': 0.65
                }
            }
        )
    
    def _calculate_confidence_factors(self, signal: Dict, df: pd.DataFrame, symbol: str) -> Dict[str, float]:
        """Calcula factores individuales de confianza"""
        factors = {}
        
        try:
            last = df.iloc[-1]
            
            # Factor 1: Calidad del setup (basado en score si existe)
            setup_score = signal.get('score', 0.5)
            factors['setup_quality'] = min(1.0, setup_score)
            
            # Factor 2: Condiciones de mercado
            if 'atr' in df.columns:
                atr_current = last['atr']
                atr_mean = df['atr'].tail(20).mean()
                volatility_factor = min(1.0, atr_current / atr_mean) if atr_mean > 0 else 0.5
                factors['market_volatility'] = volatility_factor
            else:
                factors['market_volatility'] = 0.5
            
            # Factor 3: Fortaleza de la señal (basado en indicadores)
            signal_strength = 0.5
            if 'rsi' in df.columns:
                rsi = last['rsi']
                # RSI extremo = mayor confianza
                if rsi < 30 or rsi > 70:
                    signal_strength = 0.8
                elif 35 <= rsi <= 65:
                    signal_strength = 0.6
            factors['signal_strength'] = signal_strength
            
            # Factor 4: Consistencia temporal
            # Mide si las últimas velas fluyen en la dirección de la señal.
            # Ventana: 5 velas (H1 = ~5h). Más eficiente que lookbacks largos.
            signal_direction = signal.get('type', 'BUY')
            lookback = min(5, len(df) - 1)
            if lookback >= 2:
                recent_candles = df.iloc[-(lookback + 1):-1]  # excluir la vela actual
                if signal_direction == 'BUY':
                    # Vela alcista: close > open
                    aligned = (recent_candles['close'] > recent_candles['open']).sum()
                else:
                    # Vela bajista: close < open
                    aligned = (recent_candles['close'] < recent_candles['open']).sum()
                ratio = aligned / lookback  # 0.0 – 1.0
                # Mapeo no lineal: mayoría alineada = alta consistencia
                if ratio >= 0.8:
                    factors['temporal_consistency'] = 0.85
                elif ratio >= 0.6:
                    factors['temporal_consistency'] = 0.70
                elif ratio >= 0.4:
                    factors['temporal_consistency'] = 0.50
                else:
                    factors['temporal_consistency'] = 0.25
            else:
                factors['temporal_consistency'] = 0.50  # datos insuficientes → neutro
            
        except Exception as e:
            logger.warning(f"Error calculando factores de confianza: {e}")
            # Factores por defecto en caso de error
            factors = {
                'setup_quality': 0.5,
                'market_volatility': 0.5,
                'signal_strength': 0.5,
                'temporal_consistency': 0.5
            }
        
        return factors
    
    def _score_to_level(self, score: float) -> str:
        """Convierte score numérico a nivel de confianza"""
        for level, threshold in self.confidence_thresholds.items():
            if score >= threshold:
                return level
        return 'VERY_LOW'


# ============================================================================
# FILTRO DE DUPLICADOS INTEGRADO (consolidado de duplicate_filter.py)
# ============================================================================

class DuplicateFilter:
    """Filtro de duplicados consolidado"""
    
    def __init__(self):
        self.recent_signals = {}  # symbol -> list of recent signals
        self.max_history = 10
        self.time_window_minutes = 30
    
    def is_duplicate(self, signal: Dict, symbol: str, current_time: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Verifica si una señal es duplicada.
        
        Args:
            signal: Señal a verificar
            symbol: Símbolo de la señal
            current_time: Timestamp de la vela actual. Si es None, usa datetime.now() (producción).
                         En backtest/walk-forward, pasar el timestamp de la vela para evitar
                         que señales de ventanas anteriores se consideren duplicadas.
        """
        try:
            if current_time is None:
                current_time = datetime.now(timezone.utc)
            
            # Limpiar señales antiguas
            self._cleanup_old_signals(symbol, current_time)
            
            # Obtener señales recientes para este símbolo
            recent = self.recent_signals.get(symbol, [])
            
            # Verificar duplicados
            for recent_signal in recent:
                if self._signals_are_similar(signal, recent_signal['signal']):
                    time_diff = (current_time - recent_signal['timestamp']).total_seconds() / 60
                    return True, f"Similar signal {time_diff:.1f}min ago"
            
            # Agregar señal actual al historial
            if symbol not in self.recent_signals:
                self.recent_signals[symbol] = []
            
            self.recent_signals[symbol].append({
                'signal': signal.copy(),
                'timestamp': current_time
            })
            
            # Mantener solo las más recientes
            if len(self.recent_signals[symbol]) > self.max_history:
                self.recent_signals[symbol] = self.recent_signals[symbol][-self.max_history:]
            
            return False, "Not duplicate"
            
        except Exception as e:
            logger.warning(f"Error verificando duplicados: {e}")
            return False, f"Error: {str(e)}"
    
    def _cleanup_old_signals(self, symbol: str, current_time: datetime):
        """Limpia señales antiguas fuera de la ventana de tiempo"""
        if symbol not in self.recent_signals:
            return
        
        cutoff_time = current_time - timedelta(minutes=self.time_window_minutes)
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
            
            # Precios similares (tolerancia de 5 pips)
            entry1 = float(signal1.get('entry', 0))
            entry2 = float(signal2.get('entry', 0))
            
            # Tolerancia dinámica basada en el precio
            tolerance = entry1 * 0.0005  # 0.05% del precio
            
            if abs(entry1 - entry2) > tolerance:
                return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Error comparando señales: {e}")
            return False


# ============================================================================
# INSTANCIA GLOBAL DEL ENGINE
# ============================================================================

# Crear instancia global del engine
trading_engine = TradingEngine()

def get_trading_engine() -> TradingEngine:
    """Obtiene la instancia global del trading engine"""
    return trading_engine