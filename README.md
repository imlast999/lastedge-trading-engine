<div align="center">

<img src="branding/LastEdge_Banner.png" alt="LastEdge Trading Engine Banner" width="100%">

# LastEdge Trading Engine

[![Trading Engine CI](https://github.com/imlast999/lastedge-trading-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/imlast999/lastedge-trading-engine/actions/workflows/ci.yml)

> **Repository:** [`imlast999/lastedge-trading-engine`](https://github.com/imlast999/lastedge-trading-engine)  
> **Role:** Production Execution Engine, Risk Engine v2, Dynamic Strategy Loader & MT5 Driver  
> **Status:** Production Ready  
> **Tests:** 89 / 89 Passed (100% Green)  

</div>

---

## 1. Overview

**LastEdge Trading Engine** is the high-performance, rock-solid execution core of the LastEdge quantitative platform. It connects directly to MetaTrader 5 (MT5), enforces strict risk boundaries via **Risk Engine v2**, dynamically ingests and verifies cryptographically promoted strategies from Strategy Lab, executes trades with sub-second latency, and exposes a local REST API for telemetry.

### Key Capabilities:
- **Sub-Second MT5 Execution**: Ultra-low latency order entry, modification, and partial exits via official MT5 Python API.
- **Risk Engine v2**: Pre-trade position sizing, leverage and margin limit checks, daily drawdown circuit breakers, and dynamic trailing stops.
- **Cryptographic Package Ingestion**: Dynamic verification and loading of promoted strategy packages (`.py` + `.json` sidecars) via `services/strategy_loader.py` with `code_sha256` and `config_hash` validation.
- **Typed Signal Contract**: Full support for typed [`SignalIntent`](strategies/base.py) objects and transparent mapping compatibility.
- **Unified Registries**: Automatic bidirectional synchronization between `strategies.STRATEGY_REGISTRY` and `services.signals.STRATEGY_REGISTRY`.
- **Fail-Safe Operation**: Automatic reconnection with exponential backoff (`reconnection_system.py`) and market opening safeguards.
- **Trade Journal**: High-integrity SQLite database (`data/trading.db`) operating in WAL mode.
- **Production REST API**: Local HTTP server on port `8081` for secure external telemetry.
- **VPS Independence**: Runs completely standalone in a headless VPS environment without requiring `Strategy Lab` or `App`.

---

## 2. Ecosystem & Sister Repositories

LastEdge is built as a tri-system decoupled architecture. This repository operates autonomously but integrates cleanly with its sister systems:

| Repository | Role | Integration Point |
| :--- | :--- | :--- |
| 🔬 [**LastEdge Strategy Lab**](https://github.com/imlast999/lastedge-strategy-lab) | Quantitative Research & Validation | **Strategy Promotion**: Strategy Lab researches and validates candidates (WFA, Monte Carlo, Exit Research) and promotes verified packages (`.py` + `.json`) with `code_sha256` into this engine's `strategies/` directory. |
| 📱 [**LastEdge App**](https://github.com/imlast999/lastedge-app) | Web Dashboard, Mobile & Bots | **REST Telemetry & Control**: LastEdge App queries this engine's REST API (`http://localhost:8081`) for account equity, active positions, open orders, and risk state. |

Both the Trading Engine and Strategy Lab share the exact canonical strategy contract [`strategies/base.py`](strategies/base.py) with typed `SignalIntent` parity.

---

## 3. Architecture & Directory Structure

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
│   ├── signals.py                  # Signal dispatcher & unified strategy registry
│   ├── strategy_loader.py          # Cryptographic package verifier & dynamic loader
│   ├── trailing_stops.py           # Dynamic trailing stop manager
│   └── autosignals.py              # Automated background signal scanner
├── strategies/
│   ├── base.py                     # Canonical BaseStrategy & SignalIntent contract
│   ├── eurusd.py                   # EURUSD production strategy
│   ├── xauusd.py                   # XAUUSD production strategy
│   ├── xauusd_partial.py           # XAUUSD partial exit strategy
│   ├── btceur_new.py               # BTCEUR production strategy
│   └── btceur_partial.py           # BTCEUR partial exit strategy
├── tests/                          # 89 automated unit, risk & ingestion tests
└── docs/                           # Comprehensive technical documentation
```

---

## 4. Quick Start & Installation

### Requirements:
- Python 3.10+ (Windows recommended for direct MetaTrader 5 connection)
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

## 5. Running Tests & Continuous Integration

```bash
# Run complete test suite locally
python -m pytest tests/ -v
```
Current test suite status: **89 / 89 passed (100% Green)**.

### CI / Continuous Integration:
- **Pipeline**: Automated on every push and pull request to `main` via [GitHub Actions](.github/workflows/ci.yml).
- **Environment**: Multi-Python matrix (3.10, 3.11, 3.12, 3.13) on Ubuntu and Windows.
- **Offline & Safe**: Uses mocked MT5 terminal drivers with zero external broker requirements.

---

## 6. Documentation Index

For detailed technical specifications, refer to [`docs/`](docs/):

- 🏛️ [**Architecture**](docs/ARCHITECTURE.md): Comprehensive module breakdown and data flow.
- ⚙️ [**Installation**](docs/INSTALLATION.md): Setup, dependencies, and virtual environments.
- 🔧 [**Configuration**](docs/CONFIGURATION.md): Environment variables, `rules_config.json`, and secrets.
- ⚡ [**Execution Lifecycle**](docs/EXECUTION.md): Order lifecycle, tick scanning, and signal generation.
- 🛡️ [**Risk Engine v2**](docs/RISK_ENGINE.md): Position sizing formulas, margin checks, and circuit breakers.
- 📈 [**Strategies**](docs/STRATEGIES.md): EURUSD, XAUUSD, BTCEUR specifications and parameter tables.
- 📜 [**Strategy Contract**](docs/STRATEGY_CONTRACT.md): Contract reference to Strategy Lab, `SignalIntent`, and loader.
- 🔌 [**MetaTrader 5 Driver**](docs/MT5.md): Low-level MT5 connection, error codes, and reconnection.
- 🌐 [**REST API**](docs/API.md): Endpoint definitions, schemas, and payload examples for port `8081`.
- 🛠️ [**Operations & Deployment**](docs/OPERATIONS.md): Operational readiness, broker certification, VPS setup, and backups.
- 🧪 [**Testing & CI/CD**](docs/TESTING.md): Running unit, integration, and risk test suites, and GitHub Actions.
