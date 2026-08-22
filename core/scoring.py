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
                    'confidence_thresholds': confidence_thresholds
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
        
        # Extraer confirmaciones del contexto de la señal
        confirmations = self._extract_confirmations_from_signal(signal, df, symbol)
        
        return self.evaluate_signal(symbol, True, confirmations)
    
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
    
    def evaluate_signal(self, symbol: str, setup_valid: bool, 
                       confirmations: List[Tuple[bool, ConfirmationRule]]) -> ScoringResult:
        """
        Evalúa una señal usando scoring flexible
        
        Args:
            symbol: Símbolo del instrumento
            setup_valid: Si el setup básico es válido
            confirmations: Lista de (resultado, regla) para confirmaciones
            
        Returns:
            ScoringResult con evaluación completa
        """
        
        config = self.symbol_config.get(symbol, self.symbol_config['EURUSD'])
        
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
        
        # Score ponderado
        weighted_score = passed_weight / total_weight if total_weight > 0 else 0.0
        
        # Score final (setup + confirmaciones)
        setup_weight = config.get('setup_weight', 0.5)
        final_score = (setup_weight * 1.0) + ((1 - setup_weight) * weighted_score)
        
        # Determinar confianza usando thresholds configurables
        confidence_level = self._calculate_confidence_level(final_score, symbol)
        
        # Determinar si mostrar
        show_threshold = config.get('show_threshold', 0.50)
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
            'high': 0.75,
            'very_high': 0.85
        })
        
        if score >= thresholds.get('very_high', 0.85):
            return 'VERY_HIGH'
        elif score >= thresholds.get('high', 0.75):
            return 'HIGH'
        elif score >= thresholds.get('medium', 0.60):
            return 'MEDIUM-HIGH'
        elif score >= 0.50:
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