"""
BTCEUR Weekly Range Breakout Strategy  (btceur_weekly_breakout)

Estrategia de ruptura del rango semanal para capturar impulsos de BTC.

Lógica:
  1. Calcular rango de la semana anterior (high/low)
  2. BUY  si precio cierra > weekly_high + buffer (0.5%)
  3. SELL si precio cierra < weekly_low  - buffer
  4. SL dentro del rango, TP = range × 1.5

Filtros:
  - Rango mínimo (evita semanas laterales)
  - Rango máximo (evita semanas de crash)
  - Solo 1 trade por semana

Datos de entrada: H1 (el W1 se construye resampleando internamente).
Lookback mínimo: 900 velas H1 (~5 semanas + margen para EMA confirmación).
"""

import logging
from typing import Dict, Optional
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from .base import BaseStrategy

logger = logging.getLogger(__name__)


class BTCEURWeeklyBreakoutStrategy(BaseStrategy):

    def __init__(self):
        super().__init__("BTCEUR_WeeklyBreakout")
        self._last_signal_week: Optional[str] = None

    def reset_state(self) -> None:
        """Reinicia estado interno (backtest / walk-forward)."""
        self._last_signal_week = None

    def _get_default_config(self) -> Dict:
        return {
            # Breakout
            'buffer_pct':       0.007,   # 0.7% más allá del rango

            # Filtros de rango
            'min_range_pct':    0.03,    # rango mínimo 3% del precio
            'max_range_pct':    0.25,    # rango máximo 25% (semanas de crash)

            # Confirmación: EMA20 H1 en dirección del breakout
            'use_ema_confirm':  True,
            'ema_period':       20,

            # Gestión
            'tp_multiplier':    1.5,     # TP = range × 1.5
            'sl_buffer_pct':    0.005,   # SL 0.5% dentro del rango

            # Mínimo de velas H1
            'min_h1_candles':   900,
            'expires_minutes':  10080,   # 1 semana
        }

    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        if config.get('use_ema_confirm', True):
            df['ema20'] = self._ema(df['close'], config['ema_period'])
        return df

    def _build_weekly_range(self, df_h1: pd.DataFrame) -> Optional[Dict]:
        """Calcula el rango de la semana anterior."""
        if 'time' not in df_h1.columns:
            # Fallback: agrupar cada 168 velas H1
            if len(df_h1) < 336:
                return None
            prev_week = df_h1.iloc[-336:-168]
            return {
                'high': float(prev_week['high'].max()),
                'low':  float(prev_week['low'].min()),
                'week': 'prev',
            }

        try:
            df = df_h1.copy()
            df['time'] = pd.to_datetime(df['time'])
            df = df.set_index('time')

            weekly = df.resample('W').agg(
                {'high': 'max', 'low': 'min', 'close': 'last'}
            ).dropna()

            if len(weekly) < 2:
                return None

            # Semana anterior (índice -2, la última completa)
            prev = weekly.iloc[-2]
            return {
                'high': float(prev['high']),
                'low':  float(prev['low']),
                'week': str(weekly.index[-2].date()),
            }

        except Exception as e:
            logger.debug("[WEEKLY_BO] Error calculando rango semanal: %s", e)
            return None

    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[Dict]:
        cfg = {**self.default_config, **(config or {})}

        if not self.validate_data(df) or len(df) < cfg['min_h1_candles']:
            logger.debug("[WEEKLY_BO][REJECT] insufficient_data | len=%d", len(df))
            return None

        # ── Calcular rango semanal ────────────────────────────────────────────
        weekly = self._build_weekly_range(df)
        if weekly is None:
            logger.debug("[WEEKLY_BO][REJECT] no_weekly_range")
            return None

        weekly_high = weekly['high']
        weekly_low  = weekly['low']
        week_id     = weekly.get('week', 'unknown')

        # ── Filtro: solo 1 señal por semana ──────────────────────────────────
        if self._last_signal_week == week_id:
            logger.debug("[WEEKLY_BO][REJECT] already_signaled_this_week | week=%s", week_id)
            return None

        # ── Indicadores H1 ───────────────────────────────────────────────────
        df = self.add_indicators(df, cfg)
        last = df.iloc[-1]
        price = float(last['close'])

        # ── Filtros de rango ──────────────────────────────────────────────────
        range_size = weekly_high - weekly_low
        range_pct  = range_size / weekly_low if weekly_low > 0 else 0

        if range_pct < cfg['min_range_pct']:
            logger.debug("[WEEKLY_BO][REJECT] range_too_small | pct=%.3f", range_pct)
            return None
        if range_pct > cfg['max_range_pct']:
            logger.debug("[WEEKLY_BO][REJECT] range_too_large | pct=%.3f", range_pct)
            return None

        # ── Condición de breakout ─────────────────────────────────────────────
        buffer    = price * cfg['buffer_pct']
        buy_level  = weekly_high + buffer
        sell_level = weekly_low  - buffer

        if price > buy_level:
            direction = 'BUY'
        elif price < sell_level:
            direction = 'SELL'
        else:
            logger.debug("[WEEKLY_BO][REJECT] no_breakout | price=%.0f high=%.0f low=%.0f",
                        price, buy_level, sell_level)
            return None

        # ── Confirmación EMA20 H1 ─────────────────────────────────────────────
        if cfg['use_ema_confirm'] and 'ema20' in df.columns:
            ema20 = float(last['ema20'])
            if direction == 'BUY' and price < ema20:
                logger.debug("[WEEKLY_BO][REJECT] price_below_ema20_on_buy")
                return None
            if direction == 'SELL' and price > ema20:
                logger.debug("[WEEKLY_BO][REJECT] price_above_ema20_on_sell")
                return None

        # ── Niveles ───────────────────────────────────────────────────────────
        sl_buffer = price * cfg['sl_buffer_pct']
        tp_distance = range_size * cfg['tp_multiplier']

        if direction == 'BUY':
            sl = weekly_high - sl_buffer   # SL dentro del rango
            tp = price + tp_distance
        else:
            sl = weekly_low + sl_buffer    # SL dentro del rango
            tp = price - tp_distance

        sl_distance = abs(price - sl)
        rr = tp_distance / sl_distance if sl_distance > 0 else 0

        # ── Fortaleza ─────────────────────────────────────────────────────────
        range_strength = min(1.0, range_pct / 0.10)   # normalizado a 10%
        strength = range_strength

        # Registrar semana
        self._last_signal_week = week_id

        logger.info(
            "[WEEKLY_BO][SIGNAL] %s | price=%.0f | range=%.1f%% | "
            "high=%.0f low=%.0f | R:R=%.1f",
            direction, price, range_pct * 100, weekly_high, weekly_low, rr
        )

        return {
            'type': direction,
            'entry': price,
            'sl': sl,
            'tp': tp,
            'timeframe': 'H1',
            'explanation': (
                f'BTCEUR Weekly Breakout: {direction} | '
                f'Rango semanal {range_pct*100:.1f}% | '
                f'Breakout {"alcista" if direction=="BUY" else "bajista"} | R:R={rr:.1f}'
            ),
            'expires': datetime.now(timezone.utc) + timedelta(minutes=cfg['expires_minutes']),
            'setup_strength': strength,
            'context': {
                'strategy': 'btceur_weekly_breakout',
                'confirmations': [
                    {'name': 'WEEKLY_RANGE',  'passed': True, 'value': range_pct,
                     'description': f'Rango: {range_pct*100:.1f}%'},
                    {'name': 'BREAKOUT',      'passed': True, 'value': price,
                     'description': f'Breakout {">" if direction=="BUY" else "<"} {buy_level if direction=="BUY" else sell_level:.0f}'},
                ],
                'market_conditions': {
                    'weekly_high':  weekly_high,
                    'weekly_low':   weekly_low,
                    'range_size':   range_size,
                    'range_pct':    range_pct,
                    'buy_level':    buy_level,
                    'sell_level':   sell_level,
                    'week':         week_id,
                },
                'risk_reward': rr,
                'weekly_breakout': True,
            }
        }
