"""
BTC/EUR Trend + Pullback Strategy v1  (btc_trend_pullback_v1)

Estrategia de swing trading para BTCEUR basada en:
- H4: filtro de tendencia (EMA50 > EMA200, precio > EMA50)
- H1: entrada en pullback a EMA20 con RSI en zona neutral

Activación en rules_config.json:
  "BTCEUR": { "strategy": "btc_trend_pullback_v1" }

Para volver a la baseline:
  "BTCEUR": { "strategy": "btceur_simple" }

Datos de entrada: H1 (el H4 se construye resampleando internamente).
Lookback mínimo recomendado: 900 velas H1 (~37 días).
"""

import logging
from typing import Dict, Optional
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from .base import BaseStrategy

logger = logging.getLogger(__name__)


class BTCTrendPullbackV1Strategy(BaseStrategy):
    """
    BTC/EUR Trend + Pullback v1

    Lógica:
    ─────────────────────────────────────────────────────────────
    H4 (resampleado desde H1):
      Tendencia alcista : EMA50_H4 > EMA200_H4 AND price_H4 > EMA50_H4
      Tendencia bajista : EMA50_H4 < EMA200_H4 AND price_H4 < EMA50_H4
      Sin tendencia     : no operar

    H1 (entrada):
      BUY  : tendencia alcista + precio toca EMA20_H1 (dist ≤ ema_touch_pct)
             + RSI entre 45-60 + vela alcista
      SELL : tendencia bajista + precio toca EMA20_H1
             + RSI entre 40-55 + vela bajista

    Filtros de volatilidad:
      No operar si ATR_H1 < atr_min o ATR_H1 > atr_max

    SL  : entry ± ATR_H1 × sl_atr_multiplier
    TP  : entry ± ATR_H1 × tp_atr_multiplier  (R:R configurable)
    ─────────────────────────────────────────────────────────────
    """

    def __init__(self):
        super().__init__("BTC_TrendPullback_v1")

    # ── Configuración ─────────────────────────────────────────────────────────

    def _get_default_config(self) -> Dict:
        return {
            # H4 indicadores
            'h4_ema_fast':  50,
            'h4_ema_slow':  200,

            # H1 indicadores
            'h1_ema_entry': 20,
            'h1_rsi_period': 14,
            'h1_atr_period': 14,

            # Entrada
            'ema_touch_pct': 0.012,   # 1.2% distancia máxima a EMA20 H1 (BTC es volátil)

            # RSI rangos
            'rsi_buy_min':  45,
            'rsi_buy_max':  60,
            'rsi_sell_min': 40,
            'rsi_sell_max': 55,

            # Filtros de volatilidad ATR H1
            # BTC en este broker cotiza ~63000, ATR típico ~500-2000
            'atr_min_pct': 0.003,   # ATR mínimo = 0.3% del precio (mercado activo)
            'atr_max_pct': 0.060,   # ATR máximo = 6.0% del precio (demasiado volátil)

            # Gestión de riesgo
            'sl_atr_multiplier': 1.5,
            'tp_atr_multiplier': 4.5,   # R:R 3.0

            # Mínimo de velas H1 (EMA200 H4 × 4 H1/H4 = 800 + margen)
            'min_h1_candles': 850,
            'expires_minutes': 240,   # 4h (una vela H4)
        }

    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        """Indicadores H1 base."""
        df['h1_ema20'] = self._ema(df['close'], config['h1_ema_entry'])
        return df

    # ── Resampleo H1 → H4 ────────────────────────────────────────────────────

    def _build_h4(self, df_h1: pd.DataFrame) -> pd.DataFrame:
        """Construye velas H4 desde H1."""
        if 'time' in df_h1.columns:
            try:
                df = df_h1.copy()
                df['time'] = pd.to_datetime(df['time'])
                df = df.set_index('time')
                h4 = df.resample('4h').agg(
                    {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}
                ).dropna().reset_index()
                return h4
            except Exception:
                pass
        # Fallback: agrupar cada 4 velas H1
        rows = []
        for i in range(0, len(df_h1) - 4, 4):
            chunk = df_h1.iloc[i:i + 4]
            rows.append({
                'open':  float(chunk.iloc[0]['open']),
                'high':  float(chunk['high'].max()),
                'low':   float(chunk['low'].min()),
                'close': float(chunk.iloc[-1]['close']),
            })
        return pd.DataFrame(rows)

    # ── Lógica principal ──────────────────────────────────────────────────────

    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[Dict]:
        cfg = {**self.default_config, **(config or {})}

        if not self.validate_data(df) or len(df) < cfg['min_h1_candles']:
            logger.debug("[BTC_TP][REJECT] insufficient_data | len=%d min=%d",
                        len(df), cfg['min_h1_candles'])
            return None

        # ── Construir H4 y calcular indicadores ──────────────────────────────
        df_h4 = self._build_h4(df)

        min_h4 = cfg['h4_ema_slow'] + 5
        if len(df_h4) < min_h4:
            logger.debug("[BTC_TP][REJECT] insufficient_h4 | h4=%d need=%d",
                        len(df_h4), min_h4)
            return None

        df_h4 = df_h4.copy()
        df_h4['ema50']  = self._ema(df_h4['close'], cfg['h4_ema_fast'])
        df_h4['ema200'] = self._ema(df_h4['close'], cfg['h4_ema_slow'])

        last_h4   = df_h4.iloc[-1]
        price_h4  = float(last_h4['close'])
        ema50_h4  = float(last_h4['ema50'])
        ema200_h4 = float(last_h4['ema200'])

        # ── Tendencia H4 ─────────────────────────────────────────────────────
        bullish_h4 = ema50_h4 > ema200_h4 and price_h4 > ema50_h4
        bearish_h4 = ema50_h4 < ema200_h4 and price_h4 < ema50_h4

        if not (bullish_h4 or bearish_h4):
            logger.debug("[BTC_TP][REJECT] no_h4_trend | ema50=%.0f ema200=%.0f price=%.0f",
                        ema50_h4, ema200_h4, price_h4)
            return None

        direction = 'BUY' if bullish_h4 else 'SELL'

        # ── Indicadores H1 ───────────────────────────────────────────────────
        df = self.add_indicators(df, cfg)
        last_h1 = df.iloc[-1]
        prev_h1 = df.iloc[-2]

        price_h1  = float(last_h1['close'])
        ema20_h1  = float(last_h1['h1_ema20'])
        rsi_h1    = float(last_h1['rsi'])
        atr_h1    = float(last_h1['atr'])

        # ── Filtro: precio H1 del lado correcto de EMA200 H4 ─────────────────
        if direction == 'BUY' and price_h1 < ema200_h4:
            logger.debug("[BTC_TP][REJECT] h1_below_h4_ema200_buy")
            return None
        if direction == 'SELL' and price_h1 > ema200_h4:
            logger.debug("[BTC_TP][REJECT] h1_above_h4_ema200_sell")
            return None

        atr_pct = atr_h1 / price_h1 if price_h1 > 0 else 0
        if atr_pct < cfg['atr_min_pct']:
            logger.debug("[BTC_TP][REJECT] atr_too_low | atr_pct=%.4f min=%.4f",
                        atr_pct, cfg['atr_min_pct'])
            return None
        if atr_pct > cfg['atr_max_pct']:
            logger.debug("[BTC_TP][REJECT] atr_too_high | atr_pct=%.4f max=%.4f",
                        atr_pct, cfg['atr_max_pct'])
            return None

        # ── Precio toca EMA20 H1 (pullback) ──────────────────────────────────
        dist_ema20 = abs(price_h1 - ema20_h1) / ema20_h1
        if dist_ema20 > cfg['ema_touch_pct']:
            logger.debug("[BTC_TP][REJECT] price_far_from_ema20 | dist=%.4f max=%.4f",
                        dist_ema20, cfg['ema_touch_pct'])
            return None

        # ── RSI en zona neutral ───────────────────────────────────────────────
        if direction == 'BUY':
            rsi_ok = cfg['rsi_buy_min'] <= rsi_h1 <= cfg['rsi_buy_max']
        else:
            rsi_ok = cfg['rsi_sell_min'] <= rsi_h1 <= cfg['rsi_sell_max']

        if not rsi_ok:
            logger.debug("[BTC_TP][REJECT] rsi_out_of_range | rsi=%.1f dir=%s", rsi_h1, direction)
            return None

        # ── Dirección de vela H1 ─────────────────────────────────────────────
        bullish_candle = float(last_h1['close']) > float(last_h1['open'])
        bearish_candle = float(last_h1['close']) < float(last_h1['open'])

        if direction == 'BUY' and not bullish_candle:
            logger.debug("[BTC_TP][REJECT] bearish_candle_on_buy")
            return None
        if direction == 'SELL' and not bearish_candle:
            logger.debug("[BTC_TP][REJECT] bullish_candle_on_sell")
            return None

        # ── Niveles ───────────────────────────────────────────────────────────
        sl_distance = atr_h1 * cfg['sl_atr_multiplier']
        tp_distance = atr_h1 * cfg['tp_atr_multiplier']

        if direction == 'BUY':
            sl = price_h1 - sl_distance
            tp = price_h1 + tp_distance
        else:
            sl = price_h1 + sl_distance
            tp = price_h1 - tp_distance

        rr = tp_distance / sl_distance if sl_distance > 0 else 0

        # ── Fortaleza ─────────────────────────────────────────────────────────
        ema_sep_h4 = abs(ema50_h4 - ema200_h4) / ema200_h4
        rsi_neutral = 1.0 - abs(rsi_h1 - 52.5) / 52.5   # más cerca del centro = mejor
        strength = (min(1.0, ema_sep_h4 * 20) * 0.5) + (rsi_neutral * 0.5)

        logger.info(
            "[BTC_TP][SIGNAL] %s | price=%.0f | ema20=%.0f | rsi=%.1f | "
            "atr_pct=%.3f | h4_sep=%.3f | R:R=%.1f",
            direction, price_h1, ema20_h1, rsi_h1, atr_pct, ema_sep_h4, rr
        )

        return {
            'type': direction,
            'entry': price_h1,
            'sl': sl,
            'tp': tp,
            'timeframe': 'H1',
            'explanation': (
                f'BTC TrendPullback v1: {direction} | '
                f'H4 {"alcista" if bullish_h4 else "bajista"} | '
                f'Pullback EMA20 H1 | RSI={rsi_h1:.0f} | R:R={rr:.1f}'
            ),
            'expires': datetime.now(timezone.utc) + timedelta(minutes=cfg['expires_minutes']),
            'setup_strength': strength,
            'context': {
                'strategy': 'btc_trend_pullback_v1',
                'confirmations': [
                    {'name': 'H4_TREND',    'passed': True, 'value': ema_sep_h4,
                     'description': f'H4 {"bull" if bullish_h4 else "bear"} | sep={ema_sep_h4:.3f}'},
                    {'name': 'H1_PULLBACK', 'passed': True, 'value': dist_ema20,
                     'description': f'Dist EMA20={dist_ema20:.4f}'},
                    {'name': 'RSI_NEUTRAL', 'passed': True, 'value': rsi_h1,
                     'description': f'RSI={rsi_h1:.1f}'},
                    {'name': 'CANDLE_DIR',  'passed': True, 'value': 1.0,
                     'description': f'Vela {direction}'},
                    {'name': 'VOLATILITY',  'passed': True, 'value': atr_pct,
                     'description': f'ATR%={atr_pct:.3f}'},
                ],
                'market_conditions': {
                    'h4_ema50':    ema50_h4,
                    'h4_ema200':   ema200_h4,
                    'h4_trend':    direction.lower(),
                    'h4_ema_sep':  ema_sep_h4,
                    'h1_ema20':    ema20_h1,
                    'h1_rsi':      rsi_h1,
                    'h1_atr':      atr_h1,
                    'h1_atr_pct':  atr_pct,
                    'dist_ema20':  dist_ema20,
                },
                'risk_reward': rr,
                'trend_pullback': True,
            }
        }
