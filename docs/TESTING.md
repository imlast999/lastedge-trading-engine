# LastEdge Trading Engine — Testing & CI/CD Specification

> **Module:** `LastEdge Trading Engine`  
> **Framework:** `pytest`  
> **Workflow:** `.github/workflows/ci.yml`  
> **Test Status:** 69 / 69 Passed (100% Green)  

---

## 1. Running Automated Tests

```powershell
# Run all 69 Trading Engine test suites
python -m pytest tests/

# Run with verbose output
python -m pytest tests/ -v

# Run risk engine tests specifically
python -m pytest tests/test_risk_engine.py -v

# Run operational readiness tests
python -m pytest tests/test_p56_operational_readiness.py -v
```

---

## 2. Test Suite Inventory

| Test Module | Tests | Description |
|---|:---:|---|
| `tests/test_api_server.py` | 1 | Trading REST API endpoints (:8081) |
| `tests/test_bot_service.py` | 4 | System status, journal summaries, auto-signals toggles |
| `tests/test_execution_quality_p11.py` | 5 | Slippage calculation, telemetry, journal migration |
| `tests/test_observability_p04.py` | 4 | Observability metrics, health monitor reports |
| `tests/test_p51_go_live_checklist.py` | 4 | Pre-flight checklist and circuit breaker behavior |
| `tests/test_p52_production_verifier.py` | 2 | End-to-end subsystem verification |
| `tests/test_p54_broker_certification.py` | 2 | Latency and broker spread certification |
| `tests/test_p55_stability_verification.py` | 2 | System stability audit |
| `tests/test_p56_operational_readiness.py` | 4 | Backup/restore cycles, log rotation, database integrity |
| `tests/test_p57_production_monitoring.py` | 2 | Production monitoring telemetry |
| `tests/test_promoted_strategies.py` | 1 | Partial strategy registration and loadability |
| `tests/test_risk_engine.py` | 33 | Position sizing, margin verification, portfolio limits |
| `tests/test_signals_p01_quality.py` | 5 | Strategy instantiation, signal quality, and indicators |
| **Total** | **69** | **100% Automated Test Coverage** |

---

## 3. Continuous Integration (`.github/workflows/ci.yml`)

- **Trigger:** Pushes and pull requests to `main`.
- **Environment:** Ubuntu and Windows runners across Python `3.10`, `3.11`, `3.12`, `3.13`.
- **Mock Isolation:** Uses mock MT5 drivers to enable 100% test execution in headless CI environments without physical MT5 terminals.
