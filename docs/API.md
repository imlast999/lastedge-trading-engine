# LastEdge Trading Engine — REST API Reference

> **Module:** `LastEdge Trading Engine`  
> **Server:** `services/api_server.py`  
> **Default Port:** `8081`  

---

## 1. Overview & Authentication

Trading Engine exposes a lightweight, multi-threaded REST API server built on Python's standard library `http.server.ThreadingHTTPServer`.

- **Base URL**: `http://localhost:8081`
- **Authentication**: Optional header `X-API-Key: <TRADING_API_KEY>`
- **Response Format**: `application/json`

---

## 2. Endpoints Reference

### 2.1 Health Check
- **`GET /api/trading/health`**
- **Description**: Verifies service status and MT5 terminal connectivity.
- **Response**:
```json
{
  "ok": true,
  "service": "LastEdge Trading Engine",
  "status": "ONLINE",
  "mt5_connected": true,
  "account": 12345678,
  "timestamp": "2026-08-22T18:00:00Z"
}
```

### 2.2 System Status
- **`GET /api/trading/status`**
- **Description**: Detailed status including uptime, monitored symbols, and circuit breaker state.
- **Response**:
```json
{
  "ok": true,
  "status": "ONLINE",
  "uptime": "14h 22m",
  "mt5_connected": true,
  "account_number": 12345678,
  "monitored_symbols": ["EURUSD", "XAUUSD", "BTCEUR"],
  "circuit_breaker": {
    "can_trade": true,
    "risk_multiplier": 1.0,
    "consecutive_losses": 0
  },
  "autosignals_enabled": true
}
```

### 2.3 Account Metrics & Telemetry
- **`GET /api/trading/metrics`**
- **Description**: Real-time account equity, balance, floating PnL, win rate, and total trades today.

### 2.4 Open Positions
- **`GET /api/trading/positions`**
- **Description**: List of all open MT5 positions managed by LastEdge.
- **Response**:
```json
{
  "ok": true,
  "positions": [
    {
      "ticket": 98765432,
      "symbol": "EURUSD",
      "type": "BUY",
      "volume": 0.50,
      "open_price": 1.08500,
      "current_price": 1.08720,
      "profit": 110.00,
      "sl": 1.08100,
      "tp": 1.09300
    }
  ]
}
```

### 2.5 Close Position
- **`POST /api/trading/positions/close`**
- **Payload**: `{"ticket": 98765432}`
- **Description**: Manually closes an open MT5 position by ticket.
