# LastEdge Trading Engine — CI/CD Pipeline Specification

> **Module:** `LastEdge Trading Engine`  
> **Workflow:** `.github/workflows/ci.yml`  
> **Status:** CI ENABLED | CD NOT ENABLED  

---

## 1. Workflow Overview

The Continuous Integration (CI) pipeline automatically validates every pull request and push to the `main` branch across supported Python versions (3.10, 3.11, 3.12).

- **CI Status Badge**: `[![Trading Engine CI](https://github.com/imlast999/lastedge-trading-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/imlast999/lastedge-trading-engine/actions/workflows/ci.yml)`

---

## 2. Triggers & Permissions

- **Triggers**:
  - `push` to `main`
  - `pull_request` to `main`
- **Permissions**:
  - `contents: read` (Strict least-privilege security)
- **Timeout**: 10 minutes maximum execution limit.

---

## 3. Pipeline Stages & Checks

1. **Environment Setup**:
   - Runner: `ubuntu-latest`
   - Python setup via `actions/setup-python@v5` with native `pip` dependency caching.
2. **Dependency Installation**:
   - `pip install -r requirements.txt`
   - Note: The `MetaTrader5` package uses environment marker `platform_system == "Windows"` to install on Windows while enabling clean Linux CI runs.
3. **Static Syntax & Compilation Validation**:
   - `python -m compileall core services strategies tests bot.py`
4. **Strategy Contract & Risk Engine Verification**:
   - Direct verification that `BaseStrategy`, `StrategyMetadata`, and `RiskEngine` can be imported and initialized without errors.
5. **Automated Test Suite**:
   - `pytest tests/ -v --tb=short` (69/69 unit and integration tests).

---

## 4. External Dependencies & Secrets

- **No External Services Required**: The CI runs 100% deterministic and offline.
- **No MT5 / Broker Required**: Broker interactions and MT5 API calls are mocked via `tests/conftest.py`.
- **No Secrets Required**: Zero passwords, broker credentials, or tokens are required in CI.

---

## 5. Local / CI Parity

To run the exact same checks locally before pushing:

```bash
# 1. Compile check
python -m compileall core services strategies tests bot.py

# 2. Strategy contract check
python -c "from strategies.base import BaseStrategy, StrategyMetadata; from core.risk.engine import RiskEngine; print('OK')"

# 3. Run test suite
pytest tests/ -v
```

---

## 6. Continuous Deployment (CD)

> [!NOTE]
> Automatic Deployment (CD) is intentionally **NOT ENABLED** in this phase. Live trading on Windows VPS requires manual operational certification (`run_go_live_checklist.py`).
