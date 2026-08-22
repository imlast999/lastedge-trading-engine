# LastEdge Trading Engine — Production Strategies

> **Module:** `LastEdge Trading Engine`  
> **Source Package:** `strategies/`  

---

## 1. Active Production Strategies Overview

Every production strategy inherits from `BaseStrategy` and specifies exact parameters, indicator definitions, and entry/exit setups.

| Strategy | File | Symbol | Timeframe | Version | Strategy Type |
|---|---|---|---|---|---|
| **EURUSD Simple** | `strategies/eurusd.py` | EURUSD | H1 | `2.0` | EMA Trend Pullback + ATR Filter |
| **XAUUSD Simple** | `strategies/xauusd.py` | XAUUSD | H1 | `2.0` | Volatility Breakout + ATR Trailing |
| **BTCEUR New** | `strategies/btceur_new.py` | BTCEUR | H1 | `1.1` | Regime Momentum & Dynamic Bands |
| **BTCEUR Partial** | `strategies/btceur_partial.py` | BTCEUR | H1 | `1.1` | Regime Momentum with Partial Take Profit |
| **XAUUSD Partial** | `strategies/xauusd_partial.py` | XAUUSD | H1 | `2.0` | Volatility Breakout with Partial Take Profit |

---

## 2. Strategy Technical Specifications

### 2.1 EURUSD Strategy (`strategies/eurusd.py`)
- **Instrument**: `EURUSD` | **Timeframe**: `H1` | **Warmup History**: 200 bars.
- **Indicators**:
  - Fast EMA: Period 21
  - Slow EMA: Period 55
  - Trend Filter EMA: Period 200
  - ATR: Period 14
  - RSI: Period 14
- **Entry Rules**:
  - **BUY**: `Close > EMA200` AND `EMA21 > EMA55` AND `RSI > 50` AND `Pullback low touches EMA21`.
  - **SELL**: `Close < EMA200` AND `EMA21 < EMA55` AND `RSI < 50` AND `Pullback high touches EMA21`.
- **Exit Rules**:
  - Stop Loss: `Entry - (1.5 * ATR14)`
  - Take Profit: `Entry + (2.5 * ATR14)`

### 2.2 XAUUSD Strategy (`strategies/xauusd.py`)
- **Instrument**: `XAUUSD` (Gold) | **Timeframe**: `H1` | **Warmup History**: 200 bars.
- **Indicators**:
  - Donchian Channel: Period 20
  - ATR: Period 14
  - Volume MA: Period 20
- **Entry Rules**:
  - **BUY**: Price breaks above 20-bar Donchian High with Volume > Volume MA.
  - **SELL**: Price breaks below 20-bar Donchian Low with Volume > Volume MA.
- **Exit Rules**:
  - Stop Loss: `2.0 * ATR14`
  - Trailing Stop: Activates at `1.0 * ATR` profit, trailing behind `1.5 * ATR`.

### 2.3 BTCEUR Strategy (`strategies/btceur_new.py`)
- **Instrument**: `BTCEUR` | **Timeframe**: `H1` | **Warmup History**: 200 bars.
- **Indicators**:
  - Bollinger Bands: Period 20, StdDev 2.0
  - ADX: Period 14 (Regime filter ADX > 25)
  - EMA: Period 50
- **Entry Rules**:
  - **BUY**: ADX > 25, price pulls back into EMA50 in an upward Bollinger Expansion.
  - **SELL**: ADX > 25, price pulls back into EMA50 in a downward Bollinger Expansion.
- **Exit Rules**:
  - Stop Loss: Low/High of setup candle or `2.0 * ATR`.
  - Partial Take Profit: 50% closed at 1.5R, remainder trailed to opposite Bollinger Band.
