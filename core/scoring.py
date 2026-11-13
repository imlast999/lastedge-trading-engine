"""
Sistema de Scoring Consolidado

Consolida toda la lógica de scoring que estaba fragmentada en signals.py
y otros archivos, proporcionando un sistema unificado y configurable.
"""

import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict
import pandas as pd

logger = logging.getLogger(__name__)

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
    """
    Sistema de scoring flexible consolidado desde signals.py
    
    Proporciona evaluación consistente de señales con configuración
    específica por símbolo y logging inteligente integrado.
    """
    
    def __init__(self):
        # Cargar configuración desde rules_config.json
        self._load_config()
        
        # Estadísticas para logging inteligente
        self.stats = defaultdict(int)
        self.rejection_reasons = defaultdict(int)
        self.failed_rules = defaultdict(int)
        self.last_dump = datetime.now()
    
    def _load_config(self):
        """Carga configuración desde rules_config.json"""
        import json
        import os
        
        try:
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules_config.json')
            with open(config_path, 'r') as f:
                rules = json.load(f)
            
            # Configuración por símbolo desde archivo
            self.symbol_config = {}
            
            for symbol in ['EURUSD', 'XAUUSD', 'BTCEUR']:
                symbol_rules = rules.get(symbol, {})
                
                # Cargar thresholds de confianza desde config
                confidence_thresholds = symbol_rules.get('confidence_thresholds', {
                    'medium': 0.60,
                    'high': 0.75,
                    'very_high': 0.85
                })
                
                self.symbol_config[symbol] = {
                    'min_score': symbol_rules.get('min_score', 0.60),
                    'show_threshold': confidence_thresholds.get('medium', 0.60),
                    'setup_weight': 0.4 if symbol in ['EURUSD', 'BTCEUR'] else 0.5,
                    'rsi_range': (35, 75) if symbol == 'EURUSD' else (30, 70) if symbol == 'XAUUSD' else (40, 80),
                    'atr_multiplier': 0.9 if symbol == 'EURUSD' else 1.0 if symbol == 'XAUUSD' else 0.8,
                    'confidence_thresholds': confidence_thresholds,
                    'strategy_settings': symbol_rules.get('strategy_settings', {})
                }
            
            logger.info("✓ Configuración de scoring cargada desde rules_config.json")
            
        except Exception as e:
            logger.warning(f"Error cargando configuración, usando valores por defecto: {e}")
            # Fallback a configuración por defecto
            self.symbol_config = {
                'EURUSD': {
                    'min_score': 0.60, 
                    'show_threshold': 0.50, 
                    'setup_weight': 0.4,
                    'rsi_range': (35, 75),
                    'atr_multiplier': 0.9,
                    'confidence_thresholds': {'medium': 0.60, 'high': 0.75, 'very_high': 0.85}
                },
                'XAUUSD': {
                    'min_score': 0.65, 
                    'show_threshold': 0.60, 
                    'setup_weight': 0.5,
                    'rsi_range': (30, 70),
                    'atr_multiplier': 1.0,
                    'confidence_thresholds': {'medium': 0.55, 'high': 0.70, 'very_high': 0.80}
                },
                'BTCEUR': {
                    'min_score': 0.55, 
                    'show_threshold': 0.45, 
                    'setup_weight': 0.4,
                    'rsi_range': (40, 80),
                    'atr_multiplier': 0.8,
                    'confidence_thresholds': {'medium': 0.55, 'high': 0.72, 'very_high': 0.85}
                }
            }
    
    def evaluate_signal_context(self, context) -> ScoringResult:
        """Evalúa señal usando contexto completo"""
        from core.engine import SignalContext  # Import local para evitar circular
        
        symbol = context.symbol
        signal = context.raw_signal
        df = context.dataframe
        strategy = getattr(context, 'strategy', None)
        
        # Extraer confirmaciones dinámicas y no redundantes
        confirmations = self._extract_confirmations_from_signal(signal, df, symbol)
        
        # Extraer calidad intrínseca del setup evaluada por la propia estrategia
        setup_quality = self._extract_setup_quality(signal)
        
        return self.evaluate_signal(symbol, True, confirmations, setup_quality=setup_quality, strategy=strategy)

    def _extract_setup_quality(self, signal: Dict) -> float:
        """
        Extrae la calidad intrínseca del setup calculada por la estrategia nativa.
        - BTCEUR: signal['score'] (ej. 0.88 o 0.82)
        - XAUUSD / EURUSD: signal['setup_strength'] (ej. 0.70 a 0.85)
        - Genérico: signal['score'] o signal['quality_score']
        Si no está presente o no es válido, usa 0.75 como baseline estándar de setup aprobado.
        """
        if not signal or not isinstance(signal, dict):
            return 0.75
            
        raw_val = (
            signal.get('score')
            or signal.get('setup_strength')
            or signal.get('quality_score')
        )
        
        if raw_val is not None:
            try:
                val = float(raw_val)
                if val > 1.0:
                    val = val / 100.0
                if 0.0 < val <= 1.0:
                    return val
            except (ValueError, TypeError):
                pass
                
        return 0.75

    def _extract_confirmations_from_signal(self, signal: Dict, df: pd.DataFrame, symbol: str) -> List[Tuple[bool, ConfirmationRule]]:
        """
        Extrae confirmaciones dinámicas y no redundantes de una señal.
        Evalúa factores reales de mercado (disciplina de entrada respecto a EMA20, flujo
        de momentum previo, salud de volatilidad, perfil R:R y volumen institucional)
        en lugar de duplicar los filtros de entrada que la estrategia ya verificó.
        """
        confirmations = []
        
        try:
            if df is None or len(df) == 0:
                return [(True, ConfirmationRule("SETUP_VALID", 1.0, "Setup técnico validado"))]

            last = df.iloc[-1]
            direction = str(signal.get('type') or signal.get('direction') or 'BUY').upper()
            
            # Confirmación 1: Disciplina de entrada respecto a EMA dinámica (evita chasing)
            ema_col = None
            for col in ['ema20', 'h1_ema20', 'ema_entry', 'ema50']:
                if col in df.columns:
                    ema_col = col
                    break
                    
            if ema_col:
                ema_val = float(last[ema_col])
                price = float(last['close'])
                if ema_val > 0:
                    dist_ema = abs(price - ema_val) / ema_val
                    max_dist = 0.012 if symbol == 'BTCEUR' else 0.005 if symbol == 'XAUUSD' else 0.0025
                    entry_ok = dist_ema <= max_dist
                    confirmations.append((entry_ok, ConfirmationRule(
                        "ENTRY_DISCIPLINE", 1.0, f"Distancia a {ema_col}: {dist_ema:.2%} (max {max_dist:.2%})"
                    )))
            
            # Confirmación 2: Alineación de momentum en las velas previas (flujo direccional vs espiga aislada)
            if len(df) >= 4:
                recent = df.iloc[-4:-1]
                if direction == 'BUY':
                    flow_aligned = (recent['close'] >= recent['open']).sum() >= 2
                else:
                    flow_aligned = (recent['close'] <= recent['open']).sum() >= 2
                confirmations.append((bool(flow_aligned), ConfirmationRule(
                    "MOMENTUM_ALIGNMENT", 0.9, f"Flujo direccional previo continuo para {direction}"
                )))
            
            # Confirmación 3: Salud de volatilidad (expansión sin clímax/agotamiento de mercado)
            if 'atr' in df.columns:
                atr_current = float(last['atr'])
                atr_mean = float(df['atr'].tail(20).mean())
                if atr_mean > 0:
                    ratio = atr_current / atr_mean
                    vol_healthy = 0.85 <= ratio <= 1.85
                    confirmations.append((vol_healthy, ConfirmationRule(
                        "VOLATILITY_HEALTH", 0.8, f"Volatilidad saludable ({ratio:.2f}x media de 20)"
                    )))
            
            # Confirmación 4: Perfil de Riesgo/Beneficio (R:R favorable)
            entry = float(signal.get('entry') or signal.get('price') or last['close'])
            sl = float(signal.get('sl') or signal.get('sl_price') or 0.0)
            tp = float(signal.get('tp') or signal.get('tp_price') or 0.0)
            if sl > 0 and tp > 0 and entry > 0:
                sl_dist = abs(entry - sl)
                tp_dist = abs(tp - entry)
                rr = (tp_dist / sl_dist) if sl_dist > 0 else 0.0
                rr_ok = rr >= 1.5
                confirmations.append((rr_ok, ConfirmationRule(
                    "RR_PROFILE", 0.7, f"R:R favorable: 1:{rr:.2f}"
                )))
            
            # Confirmación 5: Volumen institucional (si está presente y activo en el feed)
            vol_col = 'volume' if 'volume' in df.columns else 'tick_volume' if 'tick_volume' in df.columns else None
            if vol_col and df[vol_col].tail(20).sum() > 0:
                vol_current = float(last[vol_col])
                vol_mean = float(df[vol_col].tail(20).mean())
                if vol_mean > 0:
                    vol_ok = vol_current >= vol_mean * 0.90
                    confirmations.append((vol_ok, ConfirmationRule(
                        "VOLUME_SUPPORT", 0.6, f"Volumen relativo: {vol_current/vol_mean:.2f}x"
                    )))
                    
        except Exception as e:
            logger.warning(f"Error extrayendo confirmaciones: {e}")
            
        if not confirmations:
            confirmations.append((True, ConfirmationRule("SETUP_VALID", 1.0, "Setup técnico validado")))
            
        return confirmations
    
    def evaluate_signal(self, symbol: str, setup_valid: bool, 
                       confirmations: List[Tuple[bool, ConfirmationRule]],
                       setup_quality: Optional[float] = None,
                       strategy: Optional[str] = None) -> ScoringResult:
        """
        Evalúa una señal usando scoring flexible
        
        Args:
            symbol: Símbolo del instrumento
            setup_valid: Si el setup básico es válido
            confirmations: Lista de (resultado, regla) para confirmaciones
            setup_quality: Calidad intrínseca calculada por la estrategia (0.0 a 1.0)
            strategy: Nombre opcional de la estrategia para filtros específicos
            
        Returns:
            ScoringResult con evaluación completa
        """
        
        config = self.symbol_config.get(symbol, self.symbol_config['EURUSD'])
        strategy_settings = config.get('strategy_settings', {})
        strat_key = (strategy or '').lower().strip()
        strat_cfg = strategy_settings.get(strat_key, {}) if strat_key else {}
        
        # Actualizar estadísticas
        self.stats['signals_evaluated'] += 1
        
        if not setup_valid:
            self.stats['signals_rejected'] += 1
            self.rejection_reasons['setup_invalid'] += 1
            return ScoringResult(
                setup_valid=False, 
                confirmations_passed=0, 
                confirmations_total=len(confirmations),
                final_score=0.0, 
                confidence_level='NONE', 
                should_show=False,
                details={'reason': 'Setup principal no válido'}, 
                failed_confirmations=['SETUP_INVALID']
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
                self.failed_rules[rule.name] += 1
        
        # Score ponderado de confirmaciones dinámicas
        weighted_score = passed_weight / total_weight if total_weight > 0 else 0.0
        
        # Calidad nativa del setup (sin forzar 1.0 artificial)
        quality = 1.0 if setup_quality is None else max(0.1, min(1.0, float(setup_quality)))
        
        # Score final (setup nativo + confirmaciones dinámicas, sin techo artificial)
        setup_weight = config.get('setup_weight', 0.5)
        final_score = (setup_weight * quality) + ((1 - setup_weight) * weighted_score)
        final_score = round(final_score, 4)
        
        # Determinar confianza usando thresholds configurables
        confidence_level = self._calculate_confidence_level(final_score, symbol)
        
        # Determinar si mostrar (soporta umbral por estrategia específica o símbolo)
        show_threshold = strat_cfg.get('show_threshold') or strat_cfg.get('min_score') or config.get('show_threshold', 0.50)
        should_show = final_score >= show_threshold
        
        if should_show:
            self.stats['signals_shown'] += 1
        else:
            self.stats['signals_rejected'] += 1
            self.rejection_reasons['score_insufficient'] += 1
        
        # Volcado periódico de estadísticas
        self._maybe_dump_stats()
        
        return ScoringResult(
            setup_valid=setup_valid,
            confirmations_passed=len(passed_confirmations),
            confirmations_total=len(confirmations),
            final_score=final_score,
            confidence_level=confidence_level,
            should_show=should_show,
            details={
                'symbol': symbol,
                'setup_quality': quality,
                'passed_confirmations': passed_confirmations,
                'failed_confirmations': failed_confirmations,
                'weighted_score': weighted_score,
                'show_threshold': show_threshold,
                'config_used': config
            },
            failed_confirmations=failed_confirmations
        )
    
    def create_standard_confirmations(self, signal: Dict, df: pd.DataFrame, symbol: str) -> List[Tuple[bool, ConfirmationRule]]:
        """
        Crea confirmaciones estándar para una señal
        
        Consolida la lógica de confirmaciones que estaba duplicada
        en múltiples estrategias.
        """
        confirmations = []
        config = self.symbol_config.get(symbol, self.symbol_config['EURUSD'])
        
        try:
            last = df.iloc[-1]
            
            # Confirmación 1: RSI en zona operativa
            if 'rsi' in df.columns:
                rsi = last['rsi']
                rsi_min, rsi_max = config.get('rsi_range', (35, 75))
                rsi_ok = rsi_min <= rsi <= rsi_max
                confirmations.append((rsi_ok, ConfirmationRule(
                    "RSI_OPERATIVE", 1.0, f"RSI operativo ({rsi_min}-{rsi_max}): {rsi:.1f}"
                )))
            
            # Confirmación 2: ATR por encima de media (volatilidad)
            if 'atr' in df.columns:
                atr_current = last['atr']
                atr_mean = df['atr'].tail(20).mean()
                atr_multiplier = config.get('atr_multiplier', 0.9)
                atr_high = atr_current > atr_mean * atr_multiplier
                confirmations.append((atr_high, ConfirmationRule(
                    "ATR_HIGH", 0.8, f"ATR alto: {atr_current:.5f} vs {atr_mean:.5f}"
                )))
            
            # Confirmación 3: Dirección de vela
            direction = signal.get('type', 'BUY')
            candle_body = last['close'] - last['open']
            if direction == 'BUY':
                candle_ok = candle_body > 0
                desc = "Vela alcista para BUY"
            else:
                candle_ok = candle_body < 0
                desc = "Vela bajista para SELL"
            
            confirmations.append((candle_ok, ConfirmationRule(
                "CANDLE_DIRECTION", 0.6, desc
            )))
            
            # Confirmación 4: No retroceso fuerte (específica por dirección)
            if direction == 'BUY':
                recent_high = df['high'].tail(10).max()
                price = float(last['close'])
                no_pullback = price >= recent_high * 0.998  # Tolerancia 0.2%
                desc = f"Sin retroceso fuerte para BUY"
            else:
                recent_low = df['low'].tail(10).min()
                price = float(last['close'])
                no_pullback = price <= recent_low * 1.002  # Tolerancia 0.2%
                desc = f"Sin retroceso fuerte para SELL"
            
            confirmations.append((no_pullback, ConfirmationRule(
                "NO_PULLBACK", 0.6, desc
            )))
            
        except Exception as e:
            logger.warning(f"Error creando confirmaciones estándar para {symbol}: {e}")
            # Confirmación mínima en caso de error
            confirmations = [(True, ConfirmationRule("FALLBACK", 0.5, "Confirmación básica"))]
        
        return confirmations
    
    def _calculate_confidence_level(self, score: float, symbol: str = 'EURUSD') -> str:
        """Mapea score numérico a nivel de confianza usando thresholds configurables"""
        config = self.symbol_config.get(symbol, self.symbol_config['EURUSD'])
        thresholds = config.get('confidence_thresholds', {
            'medium': 0.60,
            'high': 0.67,
            'very_high': 0.85
        })
        
        if score >= thresholds.get('very_high', 0.85):
            return 'VERY_HIGH'
        elif score >= thresholds.get('high', 0.67):
            return 'HIGH'
        elif score >= thresholds.get('medium', 0.60):
            return 'MEDIUM'
        elif score >= 0.30:
            return 'LOW'
        else:
            return 'VERY_LOW'
    
    def _maybe_dump_stats(self):
        """Volcado inteligente de estadísticas (cada 15 minutos)"""
        now = datetime.now()
        if (now - self.last_dump).total_seconds() > 900:  # 15 minutos
            self._dump_stats()
    
    def _dump_stats(self):
        """Volcado de estadísticas agregadas"""
        duration = (datetime.now() - self.last_dump).total_seconds() / 60
        
        if self.stats['signals_evaluated'] > 0:
            show_rate = (self.stats['signals_shown'] / self.stats['signals_evaluated']) * 100
            logger.info(f"📊 SCORING RESUMEN {duration:.0f}min: {self.stats['signals_evaluated']} evaluadas, "
                       f"{self.stats['signals_shown']} mostradas ({show_rate:.1f}%), "
                       f"{self.stats['signals_rejected']} rechazadas")
            
            # Top 3 razones de rechazo
            if self.rejection_reasons:
                top_rejections = sorted(self.rejection_reasons.items(), key=lambda x: x[1], reverse=True)[:3]
                rejection_summary = ", ".join([f"{reason}({count})" for reason, count in top_rejections])
                logger.info(f"Top rechazos: {rejection_summary}")
        
        # Reset contadores
        self.stats.clear()
        self.rejection_reasons.clear()
        self.failed_rules.clear()
        self.last_dump = datetime.now()
    
    def get_statistics(self) -> Dict:
        """Obtiene estadísticas actuales del sistema de scoring"""
        total_evaluated = self.stats['signals_evaluated']
        
        return {
            'total_evaluated': total_evaluated,
            'signals_shown': self.stats['signals_shown'],
            'signals_rejected': self.stats['signals_rejected'],
            'show_rate': (self.stats['signals_shown'] / total_evaluated * 100) if total_evaluated > 0 else 0,
            'rejection_reasons': dict(self.rejection_reasons),
            'failed_rules': dict(self.failed_rules),
            'symbol_configs': self.symbol_config
        }

# Instancia global del sistema de scoring
flexible_scoring = FlexibleScoring()

def get_scoring_system() -> FlexibleScoring:
    """Obtiene la instancia global del sistema de scoring"""
    return flexible_scoring