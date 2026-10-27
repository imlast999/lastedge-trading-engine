<div align="center">

<img src="branding/LastEdge_Banner.png" alt="LastEdge Trading Engine Banner" width="100%">

# LastEdge Trading Engine

[![Trading Engine CI](https://github.com/imlast999/lastedge-trading-engine/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/imlast999/lastedge-trading-engine/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/Tests-108%2F108%20Passed-success)](https://github.com/imlast999/lastedge-trading-engine)
[![Risk Engine](https://img.shields.io/badge/Risk%20Engine-v2%20Active-blue)](https://github.com/imlast999/lastedge-trading-engine)

> **Repository:** [`imlast999/lastedge-trading-engine`](https://github.com/imlast999/lastedge-trading-engine)  
> **Role:** Production Execution Engine, Risk Engine v2, Dynamic Strategy Loader & MT5 Driver  
> **Status:** Production Ready  
> **Tests:** 108 / 108 Passed (100% Green)  

</div>

---

> [!NOTE]
> **Part of the [LastEdge](https://github.com/imlast999/LastEdge) Ecosystem**  
> This repository is a core component of the **LastEdge** quantitative trading framework. While it is fully capable of standalone operation (e.g. running on a headless VPS), **we strongly recommend running the complete LastEdge suite** via the main orchestrator repository ([`imlast999/LastEdge`](https://github.com/imlast999/LastEdge)) using its automated clone script (`setup.bat` / `clone_repos.bat`) to enable synchronized strategy promotion, real-time dashboard telemetry, and cross-platform controls.

---

## 1. Overview

**LastEdge Trading Engine** is the high-performance, rock-solid execution core of the LastEdge quantitative platform. It connects directly to MetaTrader 5 (MT5), enforces strict risk boundaries via **Risk Engine v2**, dynamically ingests and verifies cryptographically promoted strategies from Strategy Lab, executes trades with sub-second latency, and exposes a local REST API for telemetry.

### Key Capabilities:
- **Sub-Second MT5 Execution**: Ultra-low latency order entry, modification, and partial exits via official MT5 Python API, with high-resolution historical candle queries for technical chart delivery and visual audit.
- **Risk Engine v2**: Pre-trade position sizing, leverage and margin limit checks, daily drawdown circuit breakers, and dynamic trailing stops.
- **Cryptographic Package Ingestion**: Dynamic verification and loading of promoted strategy packages (`.py` + `.json` sidecars) via `services/strategy_loader.py` with `code_sha256` and `config_hash` validation.
- **Vault & Private Strategy Support**: Secure isolation of proprietary alpha models in `strategies/vault/` and `strategies/private/`.
- **Broker Quality Certification**: Real-time measurement and telemetry of average latency, slippage, and fill rate.
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
| 🧭 [**LastEdge (Main Suite)**](https://github.com/imlast999/LastEdge) | Ecosystem Orchestrator & CLI | **Unified Workspace**: Automated setup script (`setup.bat` / `clone_repos.bat`) to synchronize and run the complete three-repository trading suite. |
| 🧪 [**LastEdge Strategy Lab**](https://github.com/imlast999/lastedge-strategy-lab) | Quantitative Research & Validation | **Strategy Promotion**: Strategy Lab researches and validates candidates (WFA, Monte Carlo, Exit Research) and promotes verified packages (`.py` + `.json`) with `code_sha256` into this engine's `strategies/` directory. |
| 📱 [**LastEdge App**](https://github.com/imlast999/lastedge-app) | Web Dashboard, Mobile & Bots | **REST Telemetry & Control**: LastEdge App queries this engine's REST API (`http://localhost:8081`) for account equity, active positions, open orders, risk state, and live MT5 rates for visual technical chart generation. |

Both the Trading Engine and Strategy Lab share the exact canonical strategy contract [`strategies/base.py`](strategies/base.py) with typed `SignalIntent` parity.

---

## 3. Architecture & Directory Structure

```text
LastEdge Trading Engine/
├── main.py                         # Production Trading Engine entry point (API + Market Scanner)
├── mt5_client.py                   # Low-level MetaTrader 5 connection driver
├── services/
│   ├── api_server.py               # REST API Server (:8081)
│   ├── risk_engine.py              # Pre-trade sizing, leverage checks & circuit breakers
│   ├── strategy_loader.py          # Cryptographic package verifier & vault loader
│   ├── execution_quality.py        # Latency, slippage & fill-rate certifier
│   └── reconnection_system.py      # Exponential backoff auto-reconnector
├── strategies/                     # Production trading strategies
│   ├── base.py                     # Canonical BaseStrategy & SignalIntent contract
│   ├── vault/                      # Proprietary strategy vault
│   └── private/                    # Local git-ignored custom strategies
├── tests/                          # 108 automated execution & risk tests
└── docs/                           # Engine technical documentation
```

---

## 4. Running Tests & Continuous Integration

```bash
# Run all Trading Engine tests locally
python -m pytest tests/ -v
```
Current test suite status: **108 / 108 passed (100% Green)**.

### CI / Continuous Integration:
- **Trading Engine CI**: Automated on every push and pull request via [GitHub Actions](.github/workflows/ci.yml).
- **Environment**: Multi-Python matrix on Windows and Linux runners with mock MT5 drivers.

---

## 5. Documentation Index

For exhaustive technical guides, refer to [`docs/`](docs/):

- 📐 [**Architecture**](docs/ARCHITECTURE.md): Microservice execution model and IPC interfaces.
- 🛡️ [**Risk Engine v2**](docs/RISK_ENGINE.md): Dynamic sizing, margin thresholds, and circuit breakers.
- 🔌 [**MetaTrader 5 Driver**](docs/MT5_INTEGRATION.md): Connection management, retries, and order dispatch.
- 🧪 [**Testing & CI/CD**](docs/TESTING.md): Verification checklist and operational readiness tests.
