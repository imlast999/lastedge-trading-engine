# LastEdge Trading Engine — Production Strategies

> **Module:** `LastEdge Trading Engine`  
> **Source Package:** `strategies/`  

---

## 1. Active Production Strategies Overview

Every production strategy inherits from `BaseStrategy` and specifies exact parameters, indicator definitions, and entry/exit setups extracted directly from source code:

| Strategy Name | Source File | Class Name | Symbol | Timeframe | Version | Required History |
|---|---|---|---|---|---|:---:|
| `eurusd_simple` | `strategies/eurusd.py` | `EURUSDStrategy` | EURUSD | H1 | `2.0` | 200 bars |
| `xauusd_simple` | `strategies/xauusd.py` | `XAUUSDStrategy` | XAUUSD | H1 | `1.0` | 200 bars |
| `btceur_simple` | `strategies/btceur_new.py` | `BTCEURStrategy` | BTCEUR | H1 | `1.0` | 210 bars |
| `btceur_partial`| `strategies/btceur_partial.py` | `BTCEURPartialStrategy` | BTCEUR | H1 | `1.1` | 210 bars |
| `xauusd_partial`| `strategies/xauusd_partial.py` | `XAUUSDPartialStrategy` | XAUUSD | H1 | `2.0` | 200 bars |

---

## 2. Quantitative Strategy Specifications

### 2.1 EURUSD Strategy (`strategies/eurusd.py`)
- **Metadata**: `StrategyMetadata(required_history=200, symbol='EURUSD', timeframe='H1', strategy_name='eurusd_simple', version='2.0')`
- **Indicators**:
  - `ema_fast`: Period 20 (`ema20`)
  - `ema_slow`: Period 50 (`ema50`)
  - `ema_trend`: Period 200 (`ema200`)
  - `rsi`: Period 14 (Operational zone: 38 to 62)
  - `atr`: Period 14
- **Entry Rules**:
  - **BUY**: `ema20 > ema50` AND `Close > ema200` AND `RSI in [38, 62]` AND `EMA separation >= 0.01%` AND `Price near EMA20 (<= 0.3%)`.
  - **SELL**: `ema20 < ema50` AND `Close < ema200` AND `RSI in [38, 62]` AND `EMA separation >= 0.01%` AND `Price near EMA20 (<= 0.3%)`.
- **Exit Rules**:
  - **Stop Loss**: `2.0 * ATR14`
  - **Take Profit**: `4.0 * ATR14` (Risk:Reward ratio 1:2.0)
  - **Expiry**: 30 minutes

### 2.2 XAUUSD Strategy (`strategies/xauusd.py`)
- **Metadata**: `StrategyMetadata(required_history=200, symbol='XAUUSD', timeframe='H1', strategy_name='xauusd_simple', version='1.0')`
- **Indicators**:
  - `ema_fast`: Period 20 (`ema20`)
  - `ema_slow`: Period 50 (`ema50`)
  - `ema_trend`: Period 200 (`ema200`)
  - `rsi`: Period 14 (`rsi_buy_threshold=55`, `rsi_sell_threshold=45`)
  - `atr`: Period 14
- **Entry Rules**:
  - **Session Filter**: Active strictly between 06:00 and 22:00 UTC.
  - **BUY**: `ema20 > ema50` AND `Close > ema200` AND `RSI > 55` AND `EMA separation >= 0.1%` AND `ATR > Mean ATR * 0.8`.
  - **SELL**: `ema20 < ema50` AND `Close < ema200` AND `RSI < 45` AND `EMA separation >= 0.1%` AND `ATR > Mean ATR * 0.8`.
- **Exit Rules**:
  - **Stop Loss**: `2.0 * ATR14`
  - **Take Profit**: `5.0 * ATR14` (Risk:Reward ratio 1:2.5)
  - **Expiry**: 60 minutes

### 2.3 BTCEUR Strategy (`strategies/btceur_new.py`)
- **Metadata**: `StrategyMetadata(required_history=210, symbol='BTCEUR', timeframe='H1', strategy_name='btceur_simple', version='1.0')`
- **Indicators**:
  - `ema_fast`: Period 20 (`ema20`)
  - `ema_slow`: Period 50 (`ema50`)
  - `ema_trend`: Period 200 (`ema200`)
  - `macd`: Fast 12, Slow 26, Signal 9 (`macd_hist`)
  - `atr`: Period 14
- **Entry Rules**:
  - **BUY**: `ema20 > ema50` AND `Close > ema200` AND `macd_hist > 0` AND `EMA separation >= 0.5%` AND `ATR > Mean ATR * 0.8` AND `Overextension (3 candles) <= 2.5%`.
  - **SELL**: `ema20 < ema50` AND `Close < ema200` AND `macd_hist < 0` AND `EMA separation >= 0.5%` AND `ATR > Mean ATR * 0.8` AND `Overextension (3 candles) <= 2.5%`.
- **Exit Rules**:
  - **Stop Loss**: `2.0 * ATR14`
  - **Take Profit**: `3.0 * ATR14` (Risk:Reward ratio 1:1.5)
  - **Expiry**: 90 minutes


---

## 3. Parallel Strategy Execution & Opposing Market Regimes

### 3.1 Coexistencia de Modelos Complementarios
El sistema permite desplegar dos estrategias concurrentes en el mismo par cuando operan regímenes de mercado opuestos o complementarios:

1. **BTC/EUR (Tendencia vs Ruptura de Rango)**:
   - `btceur_trend_surge`: Captura retrocesos a la EMA20 cuando la tendencia macro ya está en curso (R:R 1:3.0, alta asimetría).
   - `btceur_volatility_breakout`: Detecta la compresión de volatilidad (Squeeze Donchian/ATR) y entra en el primer disparo explosivo fuera del rango, con un drawdown de solo 11.216 pips (-55% vs Trend Surge).
   - **Resultado**: Cobertura del 100% del ciclo de volatilidad sin duplicar riesgo.

2. **Gestión de Riesgo en Paralelo**:
   - Cada estrategia recibe **0.50% de riesgo por operación** en lugar del 1.00% habitual, garantizando que el riesgo total sobre el instrumento permanezca estrictamente limitado al **1.00%**.
   - Los tickets se aíslan mediante **Magic Numbers** diferenciados (ej. `100301` y `100302`).
