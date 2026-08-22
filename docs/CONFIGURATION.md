# LastEdge Trading Engine — Configuration Guide

> **Module:** `LastEdge Trading Engine`  
> **Config Files:** `.env`, `rules_config.json`, `secrets_store.py`  

---

## 1. Environment Variables (`.env`)

| Variable | Type | Default | Description |
|---|---|---|---|
| `MT5_LOGIN` | `int` | *None* | MT5 account account number (e.g. `12345678`). |
| `MT5_PASSWORD` | `str` | *None* | MT5 trading password. |
| `MT5_SERVER` | `str` | *None* | MT5 Broker server name. |
| `MT5_PATH` | `str` | *Auto* | Path to `terminal64.exe` executable. |
| `TRADING_API_PORT` | `int` | `8081` | Port for the local REST API server. |
| `TRADING_API_KEY` | `str` | *None* | Optional secret API key for `X-API-Key` authentication. |
| `TRADING_DB_PATH` | `str` | `data/trading.db` | Path to SQLite trading database. |
| `LOG_LEVEL` | `str` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `MAX_DAILY_LOSS_PCT`| `float` | `3.0` | Circuit breaker max daily loss percentage before auto-pause. |
| `SCAN_INTERVAL` | `int` | `60` | Loop scan frequency in seconds. |

---

## 2. Rules Configuration (`rules_config.json`)

Controls symbol-specific parameters, indicator windows, and execution thresholds:

```json
{
  "monitored_symbols": ["EURUSD", "XAUUSD", "BTCEUR"],
  "magic_number": 100001,
  "default_risk_pct": 1.0,
  "max_open_positions": 5,
  "max_spread_pips": {
    "EURUSD": 2.0,
    "XAUUSD": 35.0,
    "BTCEUR": 150.0
  },
  "circuit_breaker": {
    "max_consecutive_losses": 3,
    "risk_multiplier_after_loss": 0.5,
    "daily_loss_limit_pct": 3.0
  }
}
```

---

## 3. Secrets Management (`secrets_store.py`)

For headless or cloud deployments where plaintext passwords in `.env` are prohibited, `secrets_store.py` provides an encrypted key-value store using Windows DPAPI or standard AES-GCM encryption.
