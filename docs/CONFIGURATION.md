# LastEdge Trading Engine — Configuration & Secrets

> **Module:** `LastEdge Trading Engine`  
> **Source Files:** `main.py`, `rules_config.json`, `services/secrets_store.py`  

---

## 1. Environment Variables (`.env`)

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `MT5_LOGIN` | `int` | `None` | MetaTrader 5 account login number. |
| `MT5_PASSWORD` | `str` | `None` | MT5 trading account password. |
| `MT5_SERVER` | `str` | `None` | Broker server name (e.g. `FXLiveCapital-Server`). |
| `MT5_PATH` | `str` | `None` | Path to `terminal64.exe` executable. |
| `AUTO_EXECUTE_SIGNALS` | `bool` | `1` | `1` enables automated live MT5 trade dispatch; `0` forces signal-only alert mode. |
| `AUTO_EXECUTE_CONFIDENCE`| `str` | `HIGH` | Minimum confidence level required for direct execution (`HIGH` $\ge 0.67$ or `VERY_HIGH` $\ge 0.85$). |
| `DEMO_MODE` | `bool` | `True` | Forces demo account safety verification. |
| `MAX_RISK_PER_TRADE` | `float` | `1.0` | Maximum risk capital percentage per position. |
| `MAX_DAILY_LOSS_PCT`| `float` | `3.0` | Circuit breaker max daily loss percentage before auto-pause. |
| `SCAN_INTERVAL` | `int` | `60` | Loop scan frequency in seconds. |

---

## 2. Rules Configuration (`rules_config.json`)

Controls symbol-specific parameters, indicator windows, and execution thresholds:

```json
{
  "EURUSD": {
    "strategy": "eurusd_partial",
    "enabled": true,
    "risk_per_trade": 0.75,
    "min_score": 0.60,
    "confidence_thresholds": {
      "medium": 0.60,
      "high": 0.67,
      "very_high": 0.85
    },
    "min_rr_ratio": 1.5,
    "expires_minutes": 90
  },
  "XAUUSD": {
    "strategy": "xauusd_partial",
    "enabled": true,
    "risk_per_trade": 0.75,
    "min_score": 0.60,
    "confidence_thresholds": {
      "medium": 0.60,
      "high": 0.67,
      "very_high": 0.85
    },
    "min_rr_ratio": 1.5,
    "expires_minutes": 90
  },
  "BTCEUR": {
    "strategy": "btceur_partial",
    "enabled": true,
    "risk_per_trade": 0.50,
    "min_score": 0.60,
    "confidence_thresholds": {
      "medium": 0.60,
      "high": 0.67,
      "very_high": 0.85
    },
    "min_rr_ratio": 1.5,
    "expires_minutes": 90
  }
}
```

---

## 3. Secrets Management (`secrets_store.py`)

For headless or cloud deployments where plaintext passwords in `.env` are prohibited, `secrets_store.py` provides an encrypted key-value store using Windows DPAPI or standard AES-GCM encryption.
