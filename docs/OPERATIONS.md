# LastEdge Trading Engine — Operations & Certification

> **Module:** `LastEdge Trading Engine`  
> **Operational Tools:** `run_go_live_checklist.py`, `run_broker_certification.py`, `run_operational_readiness.py`  

---

## 1. Operational CLI Tools

Trading Engine provides operational verification scripts before going live:

### 1.1 Pre-Flight Go-Live Checklist
```powershell
python run_go_live_checklist.py
```
Validates:
- MT5 terminal alive and authenticated.
- Risk parameters (`rules_config.json`) within safe ranges.
- Required historical data available for all symbols.
- Database write permissions in `data/trading.db`.

### 1.2 Broker Certification
```powershell
python run_broker_certification.py
```
Tests and scores:
- Ping latency to broker trading server.
- Current live spreads vs maximum allowed spread thresholds.
- Order fill speed on demo account.

### 1.3 Operational Readiness & Backup Recovery
```powershell
python run_operational_readiness.py
```
Performs:
- SQLite backup creation (`data/trading.db -> backups/trading_backup_TIMESTAMP.db`).
- SQLite integrity check (`PRAGMA integrity_check`).
- Disaster recovery simulation.
