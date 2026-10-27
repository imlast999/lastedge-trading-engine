"""
XAUUSD Public Breakout Strategy - Baseline Open-Source Model
============================================================
Donchian channel breakout strategy with EMA trend filter for Gold (XAU/USD).
Designed as an educational and benchmark strategy for open-source users.

Logic:
1. Donchian Channel: Tracks the 20-period High and Low (excluding the current bar).
2. Trend Confirmation: Price relative to EMA50.
3. Volatility Trailing: Dynamic ATR(14) Stop Loss and Take Profit (1:2 Risk/Reward).
"""

from typing import Dict, Optional
import pandas as pd
from strategies.base import BaseStrategy, StrategyMetadata, SignalIntent


class XAUUSDPublicBreakoutStrategy(BaseStrategy):
    """Estrategia de ruptura de canal para Oro (XAU/USD)."""

    def __init__(self):
        super().__init__("xauusd_public_breakout")
        self.strategy_name = "xauusd_public_breakout"

    @property
    def metadata(self) -> StrategyMetadata:
        return StrategyMetadata(
            required_history=100,
            symbol="XAUUSD",
            timeframe="H1",
            strategy_name="xauusd_public_breakout",
            version="1.0",
        )

    def _get_default_config(self) -> Dict:
        return {
            "channel_period": 20,
            "ema_trend": 50,
            "rsi_period": 14,
            "atr_period": 14,
            "sl_mult_atr": 2.0,
            "tp_mult_atr": 4.0,
        }

    def _add_specific_indicators(self, df: pd.DataFrame, config: Dict) -> pd.DataFrame:
        p = config.get("channel_period", 20)
        # Shift 1 to prevent look-ahead bias
        df["donchian_high"] = df["high"].rolling(p).max().shift(1)
        df["donchian_low"] = df["low"].rolling(p).min().shift(1)
        df["ema_trend"] = self._ema(df["close"], config.get("ema_trend", 50))
        df["rsi"] = self._rsi(df["close"], config.get("rsi_period", 14))
        df["atr"] = self._atr(df, config.get("atr_period", 14))
        return df

    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[SignalIntent]:
        if len(df) < self.metadata.required_history:
            return None

        cfg = {**self.default_config, **(config or {})}
        df = self.add_indicators(df, cfg)

        curr = df.iloc[-1]
        price = float(curr["close"])
        atr = float(curr["atr"])
        if atr <= 0 or pd.isna(curr["donchian_high"]) or pd.isna(curr["donchian_low"]):
            return None

        # BUY BREAKOUT
        breakout_high = price > curr["donchian_high"]
        trend_bull = price > curr["ema_trend"]
        rsi_bull = curr["rsi"] > 50

        if breakout_high and trend_bull and rsi_bull:
            return SignalIntent(
                signal_type="BUY",
                entry_price=price,
                stop_loss=price - (atr * cfg["sl_mult_atr"]),
                take_profit=price + (atr * cfg["tp_mult_atr"]),
                symbol=self.metadata.symbol,
                timeframe=self.metadata.timeframe,
                strategy=self.metadata.strategy_name,
                explanation=f"Ruptura Alcista de Canal ({cfg['channel_period']} velas) sobre EMA{cfg['ema_trend']} con RSI {curr['rsi']:.1f}",
                setup_strength=0.82,
            )

        # SELL BREAKDOWN
        breakout_low = price < curr["donchian_low"]
        trend_bear = price < curr["ema_trend"]
        rsi_bear = curr["rsi"] < 50

        if breakout_low and trend_bear and rsi_bear:
            return SignalIntent(
                signal_type="SELL",
                entry_price=price,
                stop_loss=price + (atr * cfg["sl_mult_atr"]),
                take_profit=price - (atr * cfg["tp_mult_atr"]),
                symbol=self.metadata.symbol,
                timeframe=self.metadata.timeframe,
                strategy=self.metadata.strategy_name,
                explanation=f"Ruptura Bajista de Canal ({cfg['channel_period']} velas) bajo EMA{cfg['ema_trend']} con RSI {curr['rsi']:.1f}",
                setup_strength=0.82,
            )

        return None
