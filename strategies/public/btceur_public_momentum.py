"""
BTCEUR Public Momentum Strategy - Baseline Open-Source Model
============================================================
Robust momentum and trend-continuation strategy for BTC/EUR on H1 timeframe.
Designed as an educational and benchmark strategy for open-source users.

Logic:
1. Macro Filter: Price vs EMA100 (Establishes primary trend).
2. Momentum Trigger: MACD Line (12, 26, 9) crossing Signal Line in trend direction.
3. Overbought/Oversold Filter: RSI(14) between 40 and 70 (avoids entering at extreme tops/bottoms).
4. Volatility Exit: Dynamic ATR(14) Stop Loss and Take Profit adjusted for crypto volatility (1:2 Risk/Reward).
"""

from typing import Dict, Optional
import pandas as pd
from strategies.base import BaseStrategy, StrategyMetadata, SignalIntent


class BTCEURPublicMomentumStrategy(BaseStrategy):
    """Estrategia de momentum pública y educativa para BTC/EUR."""

    def __init__(self):
        super().__init__("btceur_public_momentum")
        self.strategy_name = "btceur_public_momentum"

    @property
    def metadata(self) -> StrategyMetadata:
        return StrategyMetadata(
            required_history=150,
            symbol="BTCEUR",
            timeframe="H1",
            strategy_name="btceur_public_momentum",
            version="1.0",
        )

    def _get_default_config(self) -> Dict:
        return {
            "ema_trend": 100,
            "macd_fast": 12,
            "macd_slow": 26,
            "macd_signal": 9,
            "rsi_period": 14,
            "atr_period": 14,
            "sl_mult_atr": 2.0,
            "tp_mult_atr": 4.0,
        }

    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        c = df["close"]
        df["ema_trend"] = self._ema(c, config.get("ema_trend", 100))
        macd_line, macd_sig, macd_hist = self._macd(
            c,
            fast=config.get("macd_fast", 12),
            slow=config.get("macd_slow", 26),
            signal=config.get("macd_signal", 9),
        )
        df["macd_line"] = macd_line
        df["macd_sig"] = macd_sig
        df["macd_hist"] = macd_hist
        df["rsi"] = self._rsi(c, config.get("rsi_period", 14))
        df["atr"] = self._atr(df, config.get("atr_period", 14))
        return df

    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[SignalIntent]:
        if len(df) < self.metadata.required_history:
            return None

        cfg = {**self.default_config, **(config or {})}
        df = self.add_indicators(df, cfg)

        curr = df.iloc[-1]
        prev = df.iloc[-2]

        price = float(curr["close"])
        atr = float(curr["atr"])
        if atr <= 0:
            return None

        # BUY SETUP
        macd_cross_up = (prev["macd_line"] <= prev["macd_sig"]) and (curr["macd_line"] > curr["macd_sig"])
        macro_bull = price > curr["ema_trend"]
        rsi_bull = 40 <= curr["rsi"] <= 70

        if macd_cross_up and macro_bull and rsi_bull:
            return SignalIntent(
                signal_type="BUY",
                entry_price=price,
                stop_loss=price - (atr * cfg["sl_mult_atr"]),
                take_profit=price + (atr * cfg["tp_mult_atr"]),
                symbol=self.metadata.symbol,
                timeframe=self.metadata.timeframe,
                strategy=self.metadata.strategy_name,
                explanation=f"Cruce MACD alcista con precio sobre EMA{cfg['ema_trend']} y RSI en {curr['rsi']:.1f}",
                setup_strength=0.80,
            )

        # SELL SETUP
        macd_cross_down = (prev["macd_line"] >= prev["macd_sig"]) and (curr["macd_line"] < curr["macd_sig"])
        macro_bear = price < curr["ema_trend"]
        rsi_bear = 30 <= curr["rsi"] <= 60

        if macd_cross_down and macro_bear and rsi_bear:
            return SignalIntent(
                signal_type="SELL",
                entry_price=price,
                stop_loss=price + (atr * cfg["sl_mult_atr"]),
                take_profit=price - (atr * cfg["tp_mult_atr"]),
                symbol=self.metadata.symbol,
                timeframe=self.metadata.timeframe,
                strategy=self.metadata.strategy_name,
                explanation=f"Cruce MACD bajista con precio bajo EMA{cfg['ema_trend']} y RSI en {curr['rsi']:.1f}",
                setup_strength=0.80,
            )

        return None
