"""
Sample Strategy Template — Reference Implementation for LastEdge
strategies/sample_template.py

Demonstrates how to implement a custom strategy compliant with the Unified Strategy Contract.
Traders can copy this template into strategies/vault/ or their private repository.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any

from strategies.base import (
    BaseStrategy,
    Signal,
    SignalType,
    SignalIntent,
    StrategyMetadata
)


class SampleBreakoutStrategy(BaseStrategy):
    """
    Sample Trend/Breakout Strategy Template.
    
    Can be mapped to any symbol by changing `symbol` or instantiating with custom config.
    """
    symbol = "EURUSD"
    strategy_name = "SampleBreakout"
    version = "1.0.0"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(
            symbol=self.symbol,
            timeframe="H1",
            config=config or {}
        )
        self.metadata = StrategyMetadata(
            required_history=100,
            symbol=self.symbol,
            timeframe="H1",
            strategy_name=self.strategy_name,
            version=self.version
        )
        self.fast_period = self.config.get("fast_period", 20)
        self.slow_period = self.config.get("slow_period", 50)
        self.atr_period = self.config.get("atr_period", 14)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate technical indicators needed for signal logic."""
        df = df.copy()
        
        # Exponential moving averages
        df["ema_fast"] = df["close"].ewm(span=self.fast_period, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=self.slow_period, adjust=False).mean()
        
        # ATR for dynamic risk sizing
        high_low = df["high"] - df["low"]
        high_close = (df["high"] - df["close"].shift(1)).abs()
        low_close = (df["low"] - df["close"].shift(1)).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["atr"] = true_range.rolling(window=self.atr_period).mean()

        return df

    def generate_signal(self, df: pd.DataFrame) -> Optional[Signal]:
        """
        Evaluate current candle against strategy entry rules.
        """
        if len(df) < self.metadata.required_history:
            return None

        df = self.calculate_indicators(df)
        curr = df.iloc[-1]
        prev = df.iloc[-2]

        close = curr["close"]
        atr = curr.get("atr", 0.0015)
        if pd.isna(atr) or atr <= 0:
            atr = 0.0015

        # Bullish Crossover
        if prev["ema_fast"] <= prev["ema_slow"] and curr["ema_fast"] > curr["ema_slow"]:
            sl = close - (1.5 * atr)
            tp = close + (3.0 * atr)
            return Signal(
                symbol=self.symbol,
                signal_type=SignalType.BUY,
                price=close,
                sl=sl,
                tp=tp,
                comment=f"{self.strategy_name} Bullish Crossover",
                strategy_name=self.strategy_name,
                timeframe=self.timeframe
            )

        # Bearish Crossover
        if prev["ema_fast"] >= prev["ema_slow"] and curr["ema_fast"] < curr["ema_slow"]:
            sl = close + (1.5 * atr)
            tp = close - (3.0 * atr)
            return Signal(
                symbol=self.symbol,
                signal_type=SignalType.SELL,
                price=close,
                sl=sl,
                tp=tp,
                comment=f"{self.strategy_name} Bearish Crossover",
                strategy_name=self.strategy_name,
                timeframe=self.timeframe
            )

        return None
