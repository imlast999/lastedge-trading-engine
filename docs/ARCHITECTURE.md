# LastEdge Trading Engine — Architecture & Subsystems

> **Module:** `LastEdge Trading Engine`  
> **Role:** Execution Core, Risk Enforcement & Broker Connectivity  

---

## 1. System Overview

`LastEdge Trading Engine` is designed around single-responsibility modules, defensive programming, and strict risk verification before any order hits the broker.

```text
               ┌──────────────────────────────┐
               │    MetaTrader 5 Terminal     │
               └──────────────┬───────────────┘
                              │
               ┌──────────────▼───────────────┐
               │   mt5_client / reconnection  │
               └──────────────┬───────────────┘
                              │
  ┌───────────────────────────┼───────────────────────────┐
  │                           │                           │
  ▼                           ▼                           ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ Active Strategies│ │  Risk Engine v2  │ │  Trade Journal   │
│ (detect_setup)   │ │  (pre-trade)     │ │  (trading.db)    │
└─────────┬────────┘ └────────┬─────────┘ └──────────────────┘
          │                   │
          └─────────► ┌───────▼────────┐
                      │  bot / service │
                      └───────┬────────┘
                              │
                      ┌───────▼────────┐
                      │ REST API :8081 │
                      └────────────────┘
```

---

## 2. Core Modules Breakdown

### 2.1 Execution Layer
- **`bot.py`**: The top-level orchestrator. Runs the main event loop, checks market opening schedules, triggers strategy scans across monitored symbols, passes candidates through Risk Engine v2, and executes trades.
- **`services/execution.py`**: Handles direct MT5 order submission (`ORDER_TYPE_BUY`, `ORDER_TYPE_SELL`), slippage deviation, magic numbers, and response parsing.
- **`services/reconnection_system.py`**: Monitors connection health with heartbeat checks. In case of disconnection, initiates exponential backoff retries without blocking other threads.

### 2.2 Risk Engine v2 (`core/risk/`)
- **`core/risk/engine.py`**: Primary risk orchestrator. Calls `position_sizer.py`, `margin_checker.py`, and `portfolio_risk.py` before any order is sent.
- **`core/risk/position_sizer.py`**: Computes lot sizing based on account equity, risk percentage (e.g. 1.0%), point value, and Stop Loss distance.
- **`core/risk/margin_checker.py`**: Validates available free margin, required margin, and maximum account leverage.
- **`core/risk/portfolio_risk.py`**: Enforces maximum open positions and portfolio-wide exposure limits.
- **`core/circuit_breaker.py`**: Automatically halts new entries if daily loss limits or consecutive loss thresholds are breached.

### 2.3 Persistence Layer (`services/database.py`, `core/journal.py`)
- **`services/database.py`**: SQLite connection manager targeting `data/trading.db`. Configured with `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` for high concurrency.
- **`core/journal.py`**: Records trade lifecycle events (Signal Generated -> Order Sent -> Order Filled -> Closed) with execution metrics (spread, slippage, latency).

### 2.4 Strategy Layer (`strategies/`)
- **`strategies/base.py`**: Abstract base class `BaseStrategy` and metadata class `StrategyMetadata`.
- **`strategies/eurusd.py`**, **`strategies/xauusd.py`**, **`strategies/btceur_new.py`**: Production strategies containing indicators and setup rules.

### 2.5 API Layer (`services/api_server.py`)
- Threaded HTTP server on port `8081` exposing endpoints for health, status, account metrics, open positions, equity, and position closure.
