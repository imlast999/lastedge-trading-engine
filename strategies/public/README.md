# LastEdge Public Benchmark Strategies 🌐

This directory contains the **public reference benchmark strategies** for LastEdge. They are designed with an open and educational architecture to allow any developer or quantitative trader cloning the repository to:

1. **Verify the End-to-End Execution Pipeline**: Test historical data ingestion, indicator calculations, and signal generation across all 3 supported symbols (`EURUSD`, `XAUUSD`, `BTCEUR`).
2. **Execute Benchmark Backtests**: Run historical replays and Walk-Forward audits in the **Strategy Lab** without requiring access to private vault algorithms.
3. **Serve as Clean Blueprints**: Each strategy strictly adheres to the unified [`BaseStrategy`](../base.py) interface and [`SignalIntent`](../base.py) signal contract.

---

## 📊 Available Benchmark Models

| Strategy | Symbol | Timeframe | Quantitative Logic | Primary Indicators |
| :--- | :---: | :---: | :--- | :--- |
| **`eurusd_public_trend`** | `EURUSD` | `H1` | Classical trend following with macro filter and momentum confirmation. | EMA(20/50) cross, EMA(200) macro filter, RSI(14) [45-65], ATR(14) |
| **`xauusd_public_breakout`** | `XAUUSD` | `H1` | Donchian range breakout aligned with the intermediate trend. | Donchian Channels(20), EMA(50) filter, ATR(14) volatility exit |
| **`btceur_public_momentum`** | `BTCEUR` | `H1` | Trend continuation and momentum calibrated for crypto volatility. | MACD(12,26,9) signal cross, EMA(100) trend filter, RSI(14), ATR(14) |

---

## 🚀 Running Backtests with Public Strategies

### From the REST API / Strategy Lab:
Strategies located in `strategies/public/` are dynamically scanned and auto-registered by `discover_dynamic_strategies()`.
You can initiate an instant backtest simulation via:
```http
POST /api/research/backtest
Content-Type: application/json

{
  "strategy": "eurusd_public_trend",
  "symbol": "EURUSD",
  "timeframe": "H1",
  "bars": 1000
}
```

### From the Mobile App or Web Dashboard:
Navigate to the **Strategy Lab** tab, select the symbol (`EURUSD`, `XAUUSD`, or `BTCEUR`), and the public strategy will appear in the selector ready for historical simulation, Monte Carlo stress testing, and parameter optimization.

---

## 🔒 Open-Core Architecture vs Private Vault

LastEdge operates under an **Open-Core** philosophy:
- **`strategies/public/` (This Directory)**: Open-source, transparent, reproducible, and fully documented baseline models.
- **`strategies/vault/` & `strategies/private/`**: Excluded from public git history via `.gitignore`. Contains proprietary multi-factor alpha models, dynamic liquidity sweep heuristics, institutional execution algorithms, and machine-learning optimized parameters.
