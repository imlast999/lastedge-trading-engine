"""
BTCEUR Regime Momentum Breakout Strategy  (btceur_regime_momentum)

Estrategia de trend-following + breakout estructural para BTCEUR.

Lógica:
  Daily (resampleado desde H4):
    - Filtro de tendencia: EMA50 > EMA200 AND precio > EMA50
    - Filtro ADX: ADX(14) > 20 (tendencia con fuerza)
    - Filtro anti-extensión: distancia al EMA50 < ATR * 3

  H4 (datos de entrada):
    - Breakout Donchian(20): close > canal superior
    - Volumen relativo > 1.0 (volumen por encima de media)
    - Vela de momentum alcista (close > open, cuerpo > 40% del rango)
    - Filtro de sobreextensión: movimiento 3 velas < 4%

  Stop Loss:
    - entry - ATR_H4 * 2.5 (dinámico)

  Take Profit:
    - No TP fijo — se usa trailing EMA20 H4 como salida
    - Para el backtest se usa TP = entry + ATR * 4.0 (R:R ~1.6)

  Solo LONG (la estrategia es unidireccional — BTC tiene sesgo alcista estructural)

Datos de entrada: H4 (el Daily se construye resampleando internamente).
Lookback mínimo recomendado: 900 velas H4 (~150 días).
"""

import logging
from typing import Dict, Optional
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta

from .base import BaseStrategy

logger = logging.getLogger(__name__)


class BTCEURRegimeMomentumStrategy(BaseStrategy):
    """
    BTCEUR Regime Momentum Breakout

    Timeframes:
      Daily (resampleado) → filtro de régimen de tendencia
      H4 (datos de entrada) → señal de breakout

    Solo genera señales LONG. La estrategia asume que BTC tiene sesgo
    alcista estructural y solo opera en la dirección del régimen.
    """

    # Esta estrategia requiere datos H4 como mínimo, porque internamente
    # resamplea H4 → Daily para el filtro de régimen.
    required_timeframe: str = 'H4'

    def __init__(self):
        super().__init__("BTCEUR_RegimeMomentum")

    def _get_default_config(self) -> Dict:
        return {
            # Daily — filtro de régimen
            'daily_ema_fast':    50,
            'daily_ema_slow':    200,
            'adx_period':        14,
            'adx_threshold':     20,      # ADX mínimo para considerar tendencia válida
            'anti_ext_atr_mult': 3.0,     # distancia máxima al EMA50 en ATRs

            # H4 — entrada
            'donchian_length':   20,      # canal Donchian para breakout
            'vol_ma_period':     20,      # media de volumen para filtro relativo
            'momentum_body_pct': 0.40,    # cuerpo mínimo como % del rango de la vela
            'overext_pct':       0.04,    # rechazar si precio movió >4% en 3 velas H4

            # Gestión
            'sl_atr_multiplier': 2.5,
            'tp_atr_multiplier': 4.0,    # R:R ~1.6 para backtest (en real usar trailing)
            'expires_minutes':   480,    # 8h (2 velas H4)

            # Mínimos
            'min_h4_candles':    900,    # ~150 días de H4
        }

    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        """Indicadores H4 base."""
        # Donchian Channel
        df['donchian_high'] = df['high'].rolling(config['donchian_length']).max()
        df['donchian_low']  = df['low'].rolling(config['donchian_length']).min()

        # Volumen relativo (si hay volumen disponible)
        if 'volume' in df.columns and df['volume'].sum() > 0:
            df['vol_ma']  = df['volume'].rolling(config['vol_ma_period']).mean()
            df['vol_rel'] = df['volume'] / df['vol_ma'].replace(0, np.nan)
        else:
            df['vol_ma']  = 1.0
            df['vol_rel'] = 1.0   # sin datos de volumen, asumir neutral

        # EMA20 H4 (para trailing stop en producción)
        df['ema20_h4'] = self._ema(df['close'], 20)

        return df

    # ── Resampleo H4 → Daily ──────────────────────────────────────────────────

    def _build_daily(self, df_h4: pd.DataFrame) -> pd.DataFrame:
        """Construye velas Daily desde H4."""
        if 'time' in df_h4.columns:
            try:
                df = df_h4.copy()
                df['time'] = pd.to_datetime(df['time'])
                df = df.set_index('time')
                agg = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}
                if 'volume' in df.columns:
                    agg['volume'] = 'sum'
                daily = df.resample('1D').agg(agg).dropna().reset_index()
                return daily
            except Exception:
                pass
        # Fallback: agrupar cada 6 velas H4
        rows = []
        for i in range(0, len(df_h4) - 6, 6):
            chunk = df_h4.iloc[i:i + 6]
            row = {
                'open':  float(chunk.iloc[0]['open']),
                'high':  float(chunk['high'].max()),
                'low':   float(chunk['low'].min()),
                'close': float(chunk.iloc[-1]['close']),
            }
            if 'volume' in chunk.columns:
                row['volume'] = float(chunk['volume'].sum())
            rows.append(row)
        return pd.DataFrame(rows)

    def _adx(self, df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Average Directional Index (ADX)."""
        high  = df['high']
        low   = df['low']
        close = df['close']

        plus_dm  = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        # Cuando ambos son positivos, solo el mayor cuenta
        mask = plus_dm > minus_dm
        plus_dm  = plus_dm.where(mask, 0)
        minus_dm = minus_dm.where(~mask, 0)

        atr = self._atr(df, period)
        plus_di  = 100 * plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan)
        minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan)
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(alpha=1/period, adjust=False).mean()
        return adx

    # ── Lógica principal ──────────────────────────────────────────────────────

    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[Dict]:
        cfg = {**self.default_config, **(config or {})}

        if not self.validate_data(df) or len(df) < cfg['min_h4_candles']:
            logger.debug("[REGIME_MOM][REJECT] insufficient_data | len=%d min=%d",
                        len(df), cfg['min_h4_candles'])
            return None

        # ── Construir Daily y calcular indicadores de régimen ─────────────────
        df_daily = self._build_daily(df)
        min_daily = cfg['daily_ema_slow'] + cfg['adx_period'] + 5
        if len(df_daily) < min_daily:
            logger.debug("[REGIME_MOM][REJECT] insufficient_daily | daily=%d need=%d",
                        len(df_daily), min_daily)
            return None

        df_daily = df_daily.copy()
        df_daily['ema50_d']  = self._ema(df_daily['close'], cfg['daily_ema_fast'])
        df_daily['ema200_d'] = self._ema(df_daily['close'], cfg['daily_ema_slow'])
        df_daily['atr_d']    = self._atr(df_daily, cfg['adx_period'])
        df_daily['adx_d']    = self._adx(df_daily, cfg['adx_period'])

        last_d   = df_daily.iloc[-1]
        price_d  = float(last_d['close'])
        ema50_d  = float(last_d['ema50_d'])
        ema200_d = float(last_d['ema200_d'])
        adx_d    = float(last_d['adx_d'])
        atr_d    = float(last_d['atr_d'])

        # ── Filtro 1: Régimen alcista Daily ───────────────────────────────────
        if not (ema50_d > ema200_d and price_d > ema50_d):
            logger.debug("[REGIME_MOM][REJECT] no_bull_regime | ema50=%.0f ema200=%.0f price=%.0f",
                        ema50_d, ema200_d, price_d)
            return None

        # ── Filtro 2: ADX — tendencia con fuerza ──────────────────────────────
        if adx_d < cfg['adx_threshold']:
            logger.debug("[REGIME_MOM][REJECT] adx_weak | adx=%.1f threshold=%d",
                        adx_d, cfg['adx_threshold'])
            return None

        # ── Filtro 3: Anti-extensión Daily ────────────────────────────────────
        dist_ema50 = abs(price_d - ema50_d)
        if atr_d > 0 and dist_ema50 > atr_d * cfg['anti_ext_atr_mult']:
            logger.debug("[REGIME_MOM][REJECT] daily_overextended | dist=%.0f atr=%.0f mult=%.1f",
                        dist_ema50, atr_d, cfg['anti_ext_atr_mult'])
            return None

        # ── Indicadores H4 ───────────────────────────────────────────────────
        df = self.add_indicators(df, cfg)
        last_h4 = df.iloc[-1]
        prev_h4 = df.iloc[-2]

        price_h4      = float(last_h4['close'])
        donchian_high = float(last_h4['donchian_high'])
        atr_h4        = float(last_h4['atr'])
        vol_rel       = float(last_h4['vol_rel']) if not pd.isna(last_h4['vol_rel']) else 1.0

        # ── Filtro 4: Sobreextensión H4 ───────────────────────────────────────
        recent_3 = df.tail(3)
        move_3   = abs(float(recent_3.iloc[-1]['close']) - float(recent_3.iloc[0]['open']))
        ref_p    = float(recent_3.iloc[0]['open'])
        if ref_p > 0 and (move_3 / ref_p) > cfg['overext_pct']:
            logger.debug("[REGIME_MOM][REJECT] h4_overextended | move=%.2f%%",
                        (move_3 / ref_p) * 100)
            return None

        # ── Condición de entrada: Breakout Donchian ───────────────────────────
        if price_h4 <= donchian_high:
            logger.debug("[REGIME_MOM][REJECT] no_breakout | price=%.0f donchian=%.0f",
                        price_h4, donchian_high)
            return None

        # ── Filtro 5: Volumen relativo ─────────────────────────────────────────
        if vol_rel < 1.0:
            logger.debug("[REGIME_MOM][REJECT] low_volume | vol_rel=%.2f", vol_rel)
            return None

        # ── Filtro 6: Vela de momentum alcista ────────────────────────────────
        candle_range = float(last_h4['high']) - float(last_h4['low'])
        candle_body  = float(last_h4['close']) - float(last_h4['open'])
        if candle_body <= 0:
            logger.debug("[REGIME_MOM][REJECT] bearish_candle")
            return None
        if candle_range > 0 and (candle_body / candle_range) < cfg['momentum_body_pct']:
            logger.debug("[REGIME_MOM][REJECT] weak_momentum_candle | body_pct=%.2f",
                        candle_body / candle_range)
            return None

        # ── Niveles ───────────────────────────────────────────────────────────
        sl_distance = atr_h4 * cfg['sl_atr_multiplier']
        tp_distance = atr_h4 * cfg['tp_atr_multiplier']
        sl = price_h4 - sl_distance
        tp = price_h4 + tp_distance
        rr = tp_distance / sl_distance if sl_distance > 0 else 0

        # ── Fortaleza del setup ───────────────────────────────────────────────
        # Combina: fuerza del ADX, volumen relativo, distancia al Donchian
        adx_strength  = min(1.0, (adx_d - cfg['adx_threshold']) / 30.0)
        vol_strength  = min(1.0, (vol_rel - 1.0) / 1.0)
        break_strength = min(1.0, (price_h4 - donchian_high) / (atr_h4 + 0.001))
        setup_strength = (adx_strength * 0.4) + (vol_strength * 0.3) + (break_strength * 0.3)
        setup_strength = max(0.0, min(1.0, setup_strength))

        logger.info(
            "[REGIME_MOM][SIGNAL] BUY | price=%.0f | donchian=%.0f | "
            "adx=%.1f | vol_rel=%.2f | R:R=%.1f",
            price_h4, donchian_high, adx_d, vol_rel, rr
        )

        return {
            'type': 'BUY',
            'entry': price_h4,
            'sl': sl,
            'tp': tp,
            'timeframe': 'H4',
            'explanation': (
                f'BTCEUR Regime Momentum: BUY | '
                f'Breakout Donchian {donchian_high:.0f} | '
                f'ADX={adx_d:.1f} | VolRel={vol_rel:.2f} | R:R={rr:.1f}'
            ),
            'expires': datetime.now(timezone.utc) + timedelta(minutes=cfg['expires_minutes']),
            'setup_strength': setup_strength,
            'context': {
                'strategy': 'btceur_regime_momentum',
                'confirmations': [
                    {'name': 'BULL_REGIME',   'passed': True, 'value': ema50_d,
                     'description': f'Daily EMA50={ema50_d:.0f} > EMA200={ema200_d:.0f}'},
                    {'name': 'ADX_STRENGTH',  'passed': True, 'value': adx_d,
                     'description': f'ADX={adx_d:.1f} > {cfg["adx_threshold"]}'},
                    {'name': 'DONCHIAN_BREAK','passed': True, 'value': price_h4,
                     'description': f'Breakout {donchian_high:.0f}'},
                    {'name': 'VOLUME_OK',     'passed': True, 'value': vol_rel,
                     'description': f'VolRel={vol_rel:.2f}'},
                    {'name': 'MOMENTUM_CANDLE','passed': True, 'value': candle_body / candle_range,
                     'description': f'Body={candle_body/candle_range:.0%}'},
                ],
                'market_conditions': {
                    'daily_ema50':    ema50_d,
                    'daily_ema200':   ema200_d,
                    'daily_adx':      adx_d,
                    'daily_atr':      atr_d,
                    'donchian_high':  donchian_high,
                    'vol_rel':        vol_rel,
                    'atr_h4':         atr_h4,
                    'regime':         'BULL',
                },
                'risk_reward': rr,
                'regime_momentum': True,
            }
        }
