"""
EURUSD Public Trend Strategy - Baseline Open-Source Model
=========================================================
Simple, robust trend-following strategy for EUR/USD on H1 timeframe.
Designed as an educational and benchmark strategy for open-source users.

Logic:
1. Macro Filter: Price vs EMA200 (Ensures trading in the direction of the macro trend).
2. Entry Trigger: Fast EMA (20) crossing Slow EMA (50).
3. Momentum Confirmation: RSI(14) in neutral-to-momentum zone (45-65 for Buy, 35-55 for Sell).
4. Volatility Exit: Dynamic ATR(14) Stop Loss and Take Profit (1:2 Risk/Reward).
"""

from typing import Dict, Optional
import pandas as pd
from strategies.base import BaseStrategy, StrategyMetadata, SignalIntent


class EURUSDPublicTrendStrategy(BaseStrategy):
    """Estrategia de tendencia pública y educativa para EUR/USD."""

    def __init__(self):
        super().__init__("eurusd_public_trend")
        self.strategy_name = "eurusd_public_trend"

    @property
    def metadata(self) -> StrategyMetadata:
        return StrategyMetadata(
            required_history=200,
            symbol="EURUSD",
            timeframe="H1",
            strategy_name="eurusd_public_trend",
            version="1.0",
        )

    def _get_default_config(self) -> Dict:
        return {
            "ema_fast": 20,
            "ema_slow": 50,
            "ema_trend": 200,
            "rsi_period": 14,
            "atr_period": 14,
            "sl_mult_atr": 1.5,
            "tp_mult_atr": 3.0,
        }

    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        c = df["close"]
        df["ema_fast"] = self._ema(c, config.get("ema_fast", 20))
        df["ema_slow"] = self._ema(c, config.get("ema_slow", 50))
        df["ema_trend"] = self._ema(c, config.get("ema_trend", 200))
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
        bullish_cross = (prev["ema_fast"] <= prev["ema_slow"]) and (curr["ema_fast"] > curr["ema_slow"])
        macro_bull = price > curr["ema_trend"]
        rsi_bull = 45 <= curr["rsi"] <= 65

        if bullish_cross and macro_bull and rsi_bull:
            return SignalIntent(
                signal_type="BUY",
                entry_price=price,
                stop_loss=price - (atr * cfg["sl_mult_atr"]),
                take_profit=price + (atr * cfg["tp_mult_atr"]),
                symbol=self.metadata.symbol,
                timeframe=self.metadata.timeframe,
                strategy=self.metadata.strategy_name,
                explanation=f"Cruce Alcista EMA({cfg['ema_fast']}/{cfg['ema_slow']}) sobre EMA200 con RSI {curr['rsi']:.1f}",
                setup_strength=0.80,
            )

        # SELL SETUP
        bearish_cross = (prev["ema_fast"] >= prev["ema_slow"]) and (curr["ema_fast"] < curr["ema_slow"])
        macro_bear = price < curr["ema_trend"]
        rsi_bear = 35 <= curr["rsi"] <= 55

        if bearish_cross and macro_bear and rsi_bear:
            return SignalIntent(
                signal_type="SELL",
                entry_price=price,
                stop_loss=price + (atr * cfg["sl_mult_atr"]),
                take_profit=price - (atr * cfg["tp_mult_atr"]),
                symbol=self.metadata.symbol,
                timeframe=self.metadata.timeframe,
                strategy=self.metadata.strategy_name,
                explanation=f"Cruce Bajista EMA({cfg['ema_fast']}/{cfg['ema_slow']}) bajo EMA200 con RSI {curr['rsi']:.1f}",
                setup_strength=0.80,
            )

        return None
