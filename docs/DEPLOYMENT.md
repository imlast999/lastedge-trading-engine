# LastEdge Trading Engine — VPS & Production Deployment Guide

> **Module:** `LastEdge Trading Engine`  
> **Environment:** Windows VPS / Dedicated Server (Equinix / Forex VPS)  

---

## 1. Production VPS Requirements

- **OS**: Windows Server 2019 / 2022 (or Windows 10/11 Pro).
- **CPU / RAM**: Minimum 2 vCPU, 4 GB RAM.
- **Location**: Low latency to broker server (< 5ms recommended, e.g. London LD4, New York NY4).
- **Software**: MetaTrader 5 Terminal 64-bit, Python 3.10+ 64-bit.

---

## 2. Headless Production Setup

1. **Install MetaTrader 5**:
   - Log into MT5 account and check "Save password".
   - Under `Tools -> Options -> Expert Advisors`, enable **"Allow automated trading"**.
2. **Configure Windows Auto-Logon & Task Scheduler**:
   - Create a Task Scheduler action to start `bot.py` on system boot:
     ```powershell
     powershell -ExecutionPolicy Bypass -Command "cd C:\TradingEngine; .\venv\Scripts\Activate.ps1; python bot.py"
     ```
3. **Configure Windows Firewall**:
   - If querying REST API remotely from `LastEdge App`, allow TCP traffic on port `8081` with IP whitelisting.
