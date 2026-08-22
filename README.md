# LastEdge Trading Engine

> **Repository:** `lastedge-trading-engine`  
> **Role:** Production Execution Engine, Risk Engine v2 & MT5 Driver  
> **Status:** Production Ready  

---

## 1. Overview

**LastEdge Trading Engine** is the high-performance, rock-solid execution core of the LastEdge quantitative platform. It connects directly to MetaTrader 5 (MT5), enforces strict risk rules via **Risk Engine v2**, executes signals from approved quantitative strategies, and provides a local REST API for telemetry and monitoring.

### Key Capabilities:
- **Sub-Second Execution**: Ultra-low latency order entry, modification, and partial exits.
- **Risk Engine v2**: Pre-trade position sizing, margin limit checks, daily drawdown circuit breakers, and dynamic trailing stops.
- **Fail-Safe Operation**: Automatic reconnection with exponential backoff (`reconnection_system.py`) and market opening guards.
- **Trade Journal**: High-integrity SQLite database (`data/trading.db`) operating in WAL mode.
- **Production REST API**: Local HTTP server on port `8081` for secure external telemetry.
- **VPS Independence**: Runs completely standalone in a headless VPS environment without requiring `Strategy Lab` or `App`.

---

## 2. Architecture & Modules

```text
LastEdge Trading Engine/
├── bot.py                          # Main trading loop & signal scanner
├── mt5_client.py                   # Low-level MetaTrader 5 connection driver
├── reconnection_system.py          # Auto-reconnection & MT5 health checker
├── secrets_store.py                # Secure credential storage
├── rules_config.json               # Symbol & strategy parameters
├── core/
│   ├── circuit_breaker.py          # Daily drawdown & consecutive loss limiter
│   ├── journal.py                  # Trade Journal and execution logger
│   └── risk/                       # Risk Engine v2
│       ├── engine.py               # Risk engine orchestrator
│       ├── position_sizer.py       # Lot sizing based on balance & SL distance
│       ├── margin_checker.py       # Account leverage & free margin checker
│       ├── portfolio_risk.py       # Portfolio-wide exposure limits
│       └── config.py               # Risk constants & thresholds
├── services/
│   ├── api_server.py               # REST API server (port 8081)
│   ├── bot_service.py              # Unified bot service façade
│   ├── database.py                 # SQLite database manager (trading.db)
│   ├── execution.py                # Order dispatch & ticket tracker
│   ├── observability.py            # Latency, spread & broker scoring
│   ├── trailing_stops.py           # Dynamic trailing stop manager
│   └── autosignals.py              # Automated background signal scanner
├── strategies/
│   ├── base.py                     # Canonical BaseStrategy & StrategyMetadata contract
│   ├── eurusd.py                   # EURUSD production strategy
│   ├── xauusd.py                   # XAUUSD production strategy
│   └── btceur_new.py               # BTCEUR production strategy
├── tests/                          # 69 automated unit & integration tests
└── docs/                           # Technical documentation
```

---

## 3. Quick Start & Installation

### Requirements:
- Python 3.10+ (Windows with MetaTrader 5 terminal installed)
- Active MetaTrader 5 trading account (Demo or Live)

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Configure Environment
```bash
cp .env.example .env
```
Edit `.env` with your MT5 broker credentials:
```ini
MT5_LOGIN=12345678
MT5_PASSWORD=your_password
MT5_SERVER=YourBroker-Server
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
TRADING_API_PORT=8081
```

### Step 3: Run Trading Engine
```bash
python bot.py
```
To run the REST API server independently:
```bash
python -m services.api_server 8081
```

---

## 4. Running Tests

```bash
python -m pytest tests/
```
Current test suite status: **69 / 69 passed (100% Green)**.

---

## 5. Documentation Index

For detailed guides, refer to the documentation in [`docs/`](docs/):

- 🏛️ [**Architecture**](docs/ARCHITECTURE.md): Comprehensive module breakdown and data flow.
- ⚙️ [**Installation**](docs/INSTALLATION.md): Setup, dependencies, and virtual environments.
- 🔧 [**Configuration**](docs/CONFIGURATION.md): Environment variables, `rules_config.json`, and secrets.
- ⚡ [**Execution Lifecycle**](docs/EXECUTION.md): Order lifecycle, tick scanning, and signal generation.
- 🛡️ [**Risk Engine v2**](docs/RISK_ENGINE.md): Position sizing formulas, margin checks, and circuit breakers.
- 📈 [**Strategies**](docs/STRATEGIES.md): EURUSD, XAUUSD, BTCEUR specifications and parameter tables.
- 📜 [**Strategy Contract**](docs/STRATEGY_CONTRACT.md): Interface definition for `BaseStrategy` and metadata.
- 🔌 [**MetaTrader 5 Driver**](docs/MT5.md): Low-level MT5 connection, error codes, and reconnection.
- 🌐 [**REST API**](docs/API.md): Endpoint definitions, schemas, and payload examples for port `8081`.
- 🧪 [**Testing Guide**](docs/TESTING.md): Running unit, integration, and risk test suites.
- 🚀 [**Deployment & VPS**](docs/DEPLOYMENT.md): Headless VPS setup, process watchdog, and auto-start.
- 🛠️ [**Operations & Certification**](docs/OPERATIONS.md): Operational readiness, broker certification, and backups.
