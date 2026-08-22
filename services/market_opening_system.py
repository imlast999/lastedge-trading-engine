"""
Sistema de Anticipación a Apertura de Mercados
Detecta oportunidades en las primeras horas de trading
"""

import pandas as pd
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

class MarketOpeningSystem:
    """Sistema completo de análisis y alertas de apertura de mercados"""
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        
        # Horarios de apertura por mercado (GMT)
        self.market_sessions = {
            'TOKYO': {
                'open': 0,   # 00:00 GMT (09:00 JST)
                'close': 9,  # 09:00 GMT (18:00 JST)
                'pairs': ['USDJPY', 'EURJPY', 'GBPJPY', 'AUDJPY'],
                'main_pairs': []  # No tenemos pares asiáticos principales
            },
            'LONDON': {
                'open': 8,   # 08:00 GMT (09:00 CET)
                'close': 17, # 17:00 GMT (18:00 CET)
                'pairs': ['EURUSD', 'GBPUSD', 'EURGBP', 'XAUUSD'],
                'main_pairs': ['EURUSD', 'XAUUSD']
            },
            'NEWYORK': {
                'open': 13,  # 13:00 GMT (08:00 EST)
                'close': 22, # 22:00 GMT (17:00 EST)
                'pairs': ['EURUSD', 'GBPUSD', 'USDCAD', 'XAUUSD'],
                'main_pairs': ['EURUSD', 'XAUUSD']
            },
            'CRYPTO': {
                'open': 0,   # 24/7
                'close': 24,
                'pairs': ['BTCEUR', 'BTCUSD', 'ETHUSD'],
                'main_pairs': ['BTCEUR']
            }
        }
        
        # Configuración de alertas
        self.alert_times = {
            'pre_market': 30,    # 30 min antes de apertura
            'opening': 15,       # 15 min antes de apertura
            'post_opening': 60   # 60 min después de apertura
        }
    
    def get_next_market_opening(self) -> Tuple[str, datetime, int]:
        """
        Obtiene la próxima apertura de mercado
        Returns: (market_name, opening_time, minutes_until_open)
        """
        try:
            now = datetime.now(timezone.utc)
            current_hour = now.hour
            current_minute = now.minute
            
            # Buscar la próxima apertura
            next_openings = []
            
            for market, info in self.market_sessions.items():
                if market == 'CRYPTO':  # Crypto es 24/7
                    continue
                    
                open_hour = info['open']
                
                # Calcular próxima apertura
                if current_hour < open_hour:
                    # Hoy
                    next_open = now.replace(hour=open_hour, minute=0, second=0, microsecond=0)
                else:
                    # Mañana
                    next_open = (now + timedelta(days=1)).replace(hour=open_hour, minute=0, second=0, microsecond=0)
                
                minutes_until = int((next_open - now).total_seconds() / 60)
                next_openings.append((market, next_open, minutes_until))
            
            # Ordenar por tiempo hasta apertura
            next_openings.sort(key=lambda x: x[2])
            
            if next_openings:
                return next_openings[0]
            else:
                return None, None, None
                
        except Exception as e:
            logger.exception(f"Error getting next market opening: {e}")
            return None, None, None
    
    def analyze_pre_market_conditions(self, symbol: str) -> Dict:
        """
        Analiza las condiciones pre-mercado para un símbolo
        """
        try:
            # Obtener datos de las últimas 24 horas
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 24)
            if rates is None or len(rates) < 10:
                return {'error': 'Datos insuficientes'}
            
            df = pd.DataFrame(rates)
            df['time'] = pd.to_datetime(df['time'], unit='s')
            
            # Análisis de cierre anterior
            last_close = df['close'].iloc[-1]
            prev_close = df['close'].iloc[-2]
            
            # Rango de las últimas 8 horas
            recent_high = df['high'].iloc[-8:].max()
            recent_low = df['low'].iloc[-8:].min()
            range_size = recent_high - recent_low
            
            # Volatilidad reciente
            volatility = df['close'].pct_change().std() * 100
            
            # Momentum
            ema_fast = df['close'].ewm(span=5).mean().iloc[-1]
            ema_slow = df['close'].ewm(span=12).mean().iloc[-1]
            momentum = 'BULLISH' if ema_fast > ema_slow else 'BEARISH'
            
            # Niveles clave
            resistance = recent_high
            support = recent_low
            
            # Distancia a niveles clave
            dist_to_resistance = (resistance - last_close) / last_close * 100
            dist_to_support = (last_close - support) / last_close * 100
            
            # Predicción de gap
            gap_potential = self.calculate_gap_potential(df, symbol)
            
            return {
                'symbol': symbol,
                'last_close': last_close,
                'range_size': range_size,
                'volatility': volatility,
                'momentum': momentum,
                'resistance': resistance,
                'support': support,
                'dist_to_resistance': dist_to_resistance,
                'dist_to_support': dist_to_support,
                'gap_potential': gap_potential,
                'analysis_time': datetime.now(timezone.utc)
            }
            
        except Exception as e:
            logger.exception(f"Error analyzing pre-market for {symbol}: {e}")
            return {'error': str(e)}
    
    def calculate_gap_potential(self, df: pd.DataFrame, symbol: str) -> Dict:
        """
        Calcula el potencial de gap al abrir
        """
        try:
            # Obtener datos de cierre del viernes vs apertura del lunes
            # Para simplificar, usamos volatilidad reciente
            
            recent_ranges = (df['high'] - df['low']).iloc[-5:]
            avg_range = recent_ranges.mean()
            max_range = recent_ranges.max()
            
            # Calcular probabilidad de gap basada en volatilidad
            current_volatility = df['close'].pct_change().iloc[-5:].std()
            
            if current_volatility > 0.02:  # 2%
                gap_probability = 'HIGH'
            elif current_volatility > 0.01:  # 1%
                gap_probability = 'MEDIUM'
            else:
                gap_probability = 'LOW'
            
            # Dirección esperada del gap
            momentum_score = 0
            for i in range(1, 4):
                if df['close'].iloc[-i] > df['close'].iloc[-i-1]:
                    momentum_score += 1
                else:
                    momentum_score -= 1
            
            expected_direction = 'UP' if momentum_score > 0 else 'DOWN'
            
            return {
                'probability': gap_probability,
                'expected_direction': expected_direction,
                'avg_range': avg_range,
                'max_range': max_range,
                'momentum_score': momentum_score
            }
            
        except Exception as e:
            logger.exception(f"Error calculating gap potential: {e}")
            return {'probability': 'UNKNOWN', 'expected_direction': 'NEUTRAL'}
    
    def generate_opening_strategy(self, symbol: str, market: str) -> Dict:
        """
        Genera estrategia específica para apertura de mercado
        """
        try:
            analysis = self.analyze_pre_market_conditions(symbol)
            
            if 'error' in analysis:
                return analysis
            
            # Estrategia basada en análisis pre-mercado
            strategy = {
                'symbol': symbol,
                'market': market,
                'strategy_type': 'MARKET_OPENING',
                'confidence': 'MEDIUM',
                'recommendations': []
            }
            
            # Análisis de momentum
            if analysis['momentum'] == 'BULLISH':
                if analysis['dist_to_resistance'] > 0.5:  # Lejos de resistencia
                    strategy['recommendations'].append({
                        'type': 'BUY',
                        'reason': 'Momentum alcista con espacio hasta resistencia',
                        'entry_zone': f"{analysis['last_close']:.5f} - {analysis['last_close'] * 1.002:.5f}",
                        'target': analysis['resistance'],
                        'stop_loss': analysis['support'],
                        'confidence': 'HIGH'
                    })
            
            elif analysis['momentum'] == 'BEARISH':
                if analysis['dist_to_support'] > 0.5:  # Lejos de soporte
                    strategy['recommendations'].append({
                        'type': 'SELL',
                        'reason': 'Momentum bajista con espacio hasta soporte',
                        'entry_zone': f"{analysis['last_close']:.5f} - {analysis['last_close'] * 0.998:.5f}",
                        'target': analysis['support'],
                        'stop_loss': analysis['resistance'],
                        'confidence': 'HIGH'
                    })
            
            # Estrategia de gap
            gap_info = analysis['gap_potential']
            if gap_info['probability'] == 'HIGH':
                strategy['recommendations'].append({
                    'type': 'GAP_PLAY',
                    'direction': gap_info['expected_direction'],
                    'reason': f"Alta probabilidad de gap {gap_info['expected_direction']}",
                    'strategy': 'Esperar gap y tradear el fill o continuación',
                    'confidence': 'MEDIUM'
                })
            
            # Estrategia de breakout
            if analysis['volatility'] < 1.0:  # Baja volatilidad = posible breakout
                strategy['recommendations'].append({
                    'type': 'BREAKOUT',
                    'reason': 'Baja volatilidad sugiere posible breakout en apertura',
                    'buy_above': analysis['resistance'],
                    'sell_below': analysis['support'],
                    'confidence': 'MEDIUM'
                })
            
            return strategy
            
        except Exception as e:
            logger.exception(f"Error generating opening strategy: {e}")
            return {'error': str(e)}
    
    def should_send_alert(self, market: str, minutes_until_open: int) -> Tuple[bool, str]:
        """
        Determina si debe enviar alerta basada en tiempo hasta apertura
        """
        try:
            # Alertas pre-mercado (30 min antes)
            if 25 <= minutes_until_open <= 35:
                return True, 'PRE_MARKET'
            
            # Alertas de apertura (15 min antes)
            elif 10 <= minutes_until_open <= 20:
                return True, 'OPENING'
            
            # Alertas post-apertura (15 min después de abrir)
            elif -20 <= minutes_until_open <= -10:
                return True, 'POST_OPENING'
            
            return False, None
            
        except Exception as e:
            logger.exception(f"Error checking alert timing: {e}")
            return False, None
    
    def format_opening_alert(self, market: str, alert_type: str, strategies: List[Dict]) -> str:
        """
        Formatea el mensaje de alerta de apertura
        """
        try:
            now_utc = datetime.now(timezone.utc)
            now_spain = now_utc + timedelta(hours=1)
            
            if alert_type == 'PRE_MARKET':
                title = f"🚨 **ALERTA PRE-MERCADO {market}**"
                subtitle = "⏰ Apertura en ~30 minutos"
            elif alert_type == 'OPENING':
                title = f"🔥 **APERTURA INMINENTE {market}**"
                subtitle = "⚡ Apertura en ~15 minutos - ¡Prepárate!"
            else:  # POST_OPENING
                title = f"📊 **MERCADO ABIERTO {market}**"
                subtitle = "🎯 Primeros movimientos detectados"
            
            message = [
                title,
                subtitle,
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"🕐 **Hora España:** {now_spain.strftime('%H:%M')} | GMT: {now_utc.strftime('%H:%M')}",
                ""
            ]
            
            if strategies:
                message.append("🎯 **OPORTUNIDADES DETECTADAS:**")
                message.append("")
                
                for i, strategy in enumerate(strategies, 1):
                    if 'error' not in strategy and strategy.get('recommendations'):
                        symbol = strategy['symbol']
                        emoji = {"EURUSD": "🇪🇺", "XAUUSD": "🥇", "BTCEUR": "₿"}.get(symbol, "📈")
                        
                        message.append(f"{emoji} **{symbol}**")
                        
                        for rec in strategy['recommendations']:
                            if rec['type'] == 'BUY':
                                message.append(f"   📈 **COMPRA** - {rec['reason']}")
                                message.append(f"   • Zona entrada: {rec['entry_zone']}")
                                message.append(f"   • Objetivo: {rec['target']:.5f}")
                                message.append(f"   • SL: {rec['stop_loss']:.5f}")
                            elif rec['type'] == 'SELL':
                                message.append(f"   📉 **VENTA** - {rec['reason']}")
                                message.append(f"   • Zona entrada: {rec['entry_zone']}")
                                message.append(f"   • Objetivo: {rec['target']:.5f}")
                                message.append(f"   • SL: {rec['stop_loss']:.5f}")
                            elif rec['type'] == 'GAP_PLAY':
                                message.append(f"   🎯 **GAP {rec['direction']}** - {rec['reason']}")
                                message.append(f"   • Estrategia: {rec['strategy']}")
                            elif rec['type'] == 'BREAKOUT':
                                message.append(f"   💥 **BREAKOUT** - {rec['reason']}")
                                message.append(f"   • Compra sobre: {rec['buy_above']:.5f}")
                                message.append(f"   • Venta bajo: {rec['sell_below']:.5f}")
                            
                            confidence_emoji = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "🔴"}.get(rec['confidence'], "⚪")
                            message.append(f"   {confidence_emoji} Confianza: {rec['confidence']}")
                            message.append("")
            else:
                message.append("📊 **Sin oportunidades claras detectadas**")
                message.append("⏳ Esperar confirmación post-apertura")
                message.append("")
            
            message.extend([
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "💡 **Consejos para Apertura:**",
                "• Espera confirmación de dirección",
                "• Usa stops más amplios por volatilidad",
                "• Considera volumen en primeros 30 min",
                "• Mantente alerta a noticias",
                "",
                "🎮 **Comandos útiles:**",
                "`/signal [símbolo]` | `/chart [símbolo]` | `/market_overview`"
            ])
            
            return "\n".join(message)
            
        except Exception as e:
            logger.exception(f"Error formatting opening alert: {e}")
            return f"Error formateando alerta: {e}"


def create_market_opening_system(config: dict = None) -> MarketOpeningSystem:
    """Factory function para crear el sistema de apertura de mercados"""
    return MarketOpeningSystem(config)