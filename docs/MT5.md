# LastEdge Trading Engine — MetaTrader 5 Integration & Driver

> **Module:** `LastEdge Trading Engine`  
> **Source Files:** `mt5_client.py`, `services/reconnection_system.py`, `services/market_opening_system.py`  

---

## 1. MT5 Low-Level Client Overview

The `mt5_client.py` module wraps the official `MetaTrader5` Python package with thread safety, connection validation, error code translation, and automatic reconnection.

```text
[Bot Loop] ──► [mt5_client.py] ──► [MetaTrader 5 Windows Terminal (IPC)] ──► [Broker Server]
```

---

## 2. Reconnection System & Health Checks

`services/reconnection_system.py` maintains continuous connection stability:
- **Ping Interval**: Heartbeat check every 15 seconds.
- **Disconnection Trigger**: If `mt5.terminal_info()` is `None` or `connected == False`.
- **Backoff Strategy**: Exponential backoff ($2^n$ seconds, up to max 60s).
- **Auto-Recovery**: Automatically re-initializes and re-authenticates with MT5 credentials.

---

## 3. Retcode Reference & Error Handling

| MT5 Retcode | Constant | Description | LastEdge Action |
|---|---|---|---|
| `10009` | `TRADE_RETCODE_DONE` | Order executed successfully | Record to Trade Journal |
| `10004` | `TRADE_RETCODE_REQUOTE` | Requote received | Retry with current market tick price |
| `10013` | `TRADE_RETCODE_INVALID_REQUEST` | Invalid order parameters | Log error & reject trade |
| `10014` | `TRADE_RETCODE_INVALID_VOLUME` | Invalid volume/lot size | Adjust to min/max lot size |
| `10018` | `TRADE_RETCODE_MARKET_CLOSED` | Market is closed | Pause trading loop until market open |
| `10019` | `TRADE_RETCODE_NO_MONEY` | Insufficient margin | Block trade; alert Risk Engine |
| `10027` | `TRADE_RETCODE_AUTOTRADING_DISABLED` | Algo trading disabled | Log CRITICAL error |
