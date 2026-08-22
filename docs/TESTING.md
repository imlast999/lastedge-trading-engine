# LastEdge Trading Engine — Testing Guide

> **Module:** `LastEdge Trading Engine`  
> **Framework:** `pytest`  
> **Current Status:** 69 / 69 Passed (100% Green)  

---

## 1. Running Test Suites

```powershell
# Run all Trading Engine tests
python -m pytest tests/

# Run with verbose output
python -m pytest tests/ -v

# Run specific test file (e.g. Risk Engine)
python -m pytest tests/test_risk_engine.py -v
```

---

## 2. Test Coverage Inventory

| Test Module | Tests | Focus Area |
|---|:---:|---|
| `tests/test_risk_engine.py` | 34 | Position sizing, margin checks, portfolio limits, circuit breakers |
| `tests/test_api_server.py` | 1 | REST API endpoints, health check, position closure responses |
| `tests/test_bot_service.py` | 4 | Bot service facade, account equity, open positions |
| `tests/test_execution_quality_p11.py`| 5 | Spread tracking, slippage calculation, execution latency |
| `tests/test_observability_p04.py` | 4 | Telemetry, logging metrics, broker scoring |
| `tests/test_p51_go_live_checklist.py`| 4 | Pre-flight certification, configuration validation |
| `tests/test_p52_production_verifier.py`| 2 | Component status verification, subsystem health |
| `tests/test_p54_broker_certification.py`| 2 | Broker speed, spread bounds, order execution latency |
| `tests/test_p55_stability_verification.py`| 2 | Reconnection resilience, long-running stability |
| `tests/test_p56_operational_readiness.py`| 4 | Backup creation, database recovery, audit checks |
| `tests/test_p57_production_monitoring.py`| 2 | Continuous background monitoring, resource usage |
| `tests/test_promoted_strategies.py`| 1 | Dynamic loading and contract conformity of promoted strategies |
| `tests/test_signals_p01_quality.py`| 4 | Signal validation, ATR calculation, EMA cross logic |
