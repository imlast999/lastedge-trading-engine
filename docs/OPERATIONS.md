# LastEdge Trading Engine — Operations, Deployment & Verification

> **Module:** `LastEdge Trading Engine`  
> **Environment:** Windows VPS / Dedicated Server (Equinix / Forex VPS)  
> **Operational Tools:** `run_go_live_checklist.py`, `run_broker_certification.py`, `run_operational_readiness.py`  

---

## 1. Production VPS Requirements & Environment

- **Operating System:** Windows Server 2019 / 2022 (or Windows 10/11 Pro 64-bit).
- **Hardware:** Minimum 2 vCPUs, 4 GB RAM, SSD storage.
- **Network Latency:** Low latency to broker trading server (< 5ms recommended, e.g. London LD4, New York NY4).
- **Prerequisites:** MetaTrader 5 Terminal 64-bit, Python 3.10+ 64-bit.

---

## 2. Headless Production Setup & Autostart

1. **MetaTrader 5 Configuration:**
   - Log into trading account and check **"Save password"**.
   - Navigate to `Tools -> Options -> Expert Advisors` and enable **"Allow automated trading"**.
2. **Windows Task Scheduler Autostart:**
   - Create a startup task to launch `bot.py` on system boot:
     ```powershell
     powershell -ExecutionPolicy Bypass -Command "cd C:\TradingEngine; .\venv\Scripts\Activate.ps1; python bot.py"
     ```
3. **Firewall & Security:**
   - Allow incoming TCP connections on port `8081` only for whitelisted internal IP addresses (e.g. from `LastEdge App`).

---

## 3. Operational CLI Verification Tools

Trading Engine provides operational verification scripts before going live:

### 3.1 Pre-Flight Go-Live Checklist (`run_go_live_checklist.py`)
```powershell
python run_go_live_checklist.py
```
Validates:
- MT5 terminal alive and authenticated.
- Risk parameters (`rules_config.json`) within safe ranges.
- Required historical data available for all symbols.
- Database write permissions in `data/trading.db`.

### 3.2 Broker Certification (`run_broker_certification.py`)
```powershell
python run_broker_certification.py
```
Tests and scores:
- Ping latency to broker trading server.
- Current live spreads vs maximum allowed spread thresholds.
- Order fill speed on demo account.

### 3.3 Operational Readiness & Backup Recovery (`run_operational_readiness.py`)
```powershell
python run_operational_readiness.py
```
Performs:
- SQLite backup creation (`data/trading.db -> backups/trading_backup_TIMESTAMP.db`).
- SQLite integrity check (`PRAGMA integrity_check`).
- Disaster recovery simulation.
