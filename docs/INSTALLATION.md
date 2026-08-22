# LastEdge Trading Engine — Installation Guide

> **Module:** `LastEdge Trading Engine`  
> **Requirements:** Python 3.10+, MetaTrader 5 (Windows 10/11 / Windows Server)  

---

## 1. Prerequisites

1. **Operating System**: Windows 10, Windows 11, or Windows Server 2019/2022 (Required for MetaTrader 5 native Python API).
2. **MetaTrader 5 Terminal**: Installed and logged in with your broker account (Algotrading enabled in MT5 Options).
3. **Python**: Version 3.10, 3.11, 3.12, or 3.13.

---

## 2. Step-by-Step Installation

### Step 1: Clone Repository
```bash
git clone https://github.com/imlast999/lastedge-trading-engine.git
cd lastedge-trading-engine
```

### Step 2: Create and Activate Virtual Environment
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### Step 3: Install Dependencies
```powershell
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 4: Verify Environment Configuration
```powershell
cp .env.example .env
```
Edit `.env` with your MT5 credentials:
```ini
MT5_LOGIN=12345678
MT5_PASSWORD=YourTradingPassword
MT5_SERVER=YourBroker-Live
MT5_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
TRADING_API_PORT=8081
```

### Step 5: Test MT5 Connectivity
```powershell
python -c "import MetaTrader5 as mt5; print('MT5 Version:', mt5.version() if mt5.initialize() else 'Failed to connect')"
```

### Step 6: Run Automated Tests
```powershell
python -m pytest tests/
```
All 69 unit tests should pass with 100% green.
