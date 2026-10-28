# LastEdge Trading Engine — Execution Lifecycle & Flow

> **Module:** `LastEdge Trading Engine`  
> **Source Files:** `main.py`, `services/execution.py`, `services/autosignals.py`  

---

## 1. Main Trading Loop Lifecycle

The live execution loop in `main.py` (via `AutoSignalsService`) operates on a deterministic pipeline:

```text
[Loop Wakeup] (Every SCAN_INTERVAL seconds)
       │
       ▼
[1. Health & Reconnection Check]
  - Checks MT5 connection (`mt5.terminal_info()`).
  - If disconnected -> initiates exponential backoff reconnect.
       │
       ▼
[2. Circuit Breaker Check]
  - Calculates daily PnL & consecutive losses.
  - If breached -> skips scanning and logs alert.
       │
       ▼
[3. Market Session & News Check]
  - Verifies broker market hours (`market_opening_system.py`).
  - Verifies high-impact news blackout window (`news_filter.py`).
       │
       ▼
[4. Strategy Scan (Multi-Symbol)]
  - Iterates over active strategies (`EURUSD`, `XAUUSD`, `BTCEUR`).
  - Fetches required historical bars (`required_history`).
  - Calculates indicators (`add_indicators`).
  - Checks for setup signal (`detect_setup`).
       │
       ▼
[5. Risk Engine v2 Pre-Trade Gate]
  - Computes exact lot size via `position_sizer.py`.
  - Checks margin requirement via `margin_checker.py`.
  - Checks portfolio exposure limit via `portfolio_risk.py`.
       │
       ▼
[6. Order Dispatch & Execution]
  - Submits IOC deal order via `services/execution.py`.
  - Attaches initial Stop Loss & Take Profit.
  - Verifies broker `TRADE_RETCODE_DONE` (10009).
       │
       ▼
[7. Trade Journal Logging]
  - Records ticket, entry price, slippage, spread, and timestamp in `data/trading.db`.
       │
       ▼
[8. Position Management & Trailing Stops]
  - Updates trailing stops and partial take profit exits (`trailing_stops.py`).
```

---

## 2. Order Submission Details

- **Action**: `TRADE_ACTION_DEAL`
- **Type**: `ORDER_TYPE_BUY` / `ORDER_TYPE_SELL`
- **Time In Force**: `ORDER_TIME_GTC`
- **Filling Type**: `ORDER_FILLING_IOC` (Immediate Or Cancel) or `ORDER_FILLING_FOK` based on broker symbol info.
- **Slippage Deviation**: Configurable per symbol (default 20 points).
- **Magic Number**: Unique identifier per strategy (e.g. `100001` for EURUSD, `100002` for XAUUSD).


---

## 3. Signal Scoring & Confidence Tiers

The engine evaluates every raw strategy signal using a multi-factor scoring model (trend alignment, ATR volatility regime, RSI momentum, and setup strength). Signals are deterministically categorized into four institutional tiers:

| Tier | Confluence Score | Execution Mode | Pipeline Routing |
| :--- | :---: | :--- | :--- |
| **`VERY_HIGH`** | **`0.85 – 1.00`** | **Automated (Direct MT5)** | Order is executed immediately in MT5 with IOC filling. Broadcast as `AUTO-APROBADA ✅` to Discord, Telegram & Web Dashboard. |
| **`HIGH`** | **`0.67 – 0.84`** | **Automated (Direct MT5)** | Order is executed immediately in MT5 (optimized threshold $\ge 0.67$). Captures high-conviction trades without manual delay. |
| **`MEDIUM`** | **`0.60 – 0.66`** | **Manual 1-Click Approval** | Saved in SQLite as `PROPOSED`. Sent to Web Dashboard & Mobile App in Hybrid Mode; automatically discarded when 100% Autonomous Mode is ON. |
| **`LOW`** | **`< 0.60`** | **Automatic Rejection** | Discarded at pre-filter. Zero alert noise, preventing execution in choppy or sub-optimal market conditions. |

### 🤖 Dual-Mode Autonomous Operation
The engine incorporates a runtime switch:
- **100% Autonomous (`ON`)**: Only signals with score $\ge 0.67$ execute into MT5; `MEDIUM` signals are filtered automatically to eliminate decision fatigue.
- **Hybrid Review (`OFF`)**: `MEDIUM` signals are stored and broadcast for manual discretionary approval.
State is persisted in `rules_config.json` (`GLOBAL_SETTINGS.autonomous_mode`) and `autosignals_state.json`.

### Configuration Mapping (`rules_config.json`):
```json
"confidence_thresholds": {
  "medium": 0.60,
  "high": 0.67,
  "very_high": 0.85
},
"min_score": 0.60
```
