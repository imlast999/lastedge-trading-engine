# LastEdge Trading Engine — Risk Engine v2 Specification

> **Module:** `LastEdge Trading Engine`  
> **Source Package:** `core/risk/`  

---

## 1. Overview & Core Philosophy

**Risk Engine v2** is the central safety guard of LastEdge. It enforces mathematically sound capital allocation, margin sufficiency, and dynamic trade management. **No trade can be placed if any Risk Engine rule fails.**

```text
Trade Signal (Entry, SL, TP)
           │
           ▼
┌───────────────────────────────────────┐
│          core/risk/engine.py          │
│                                       │
│  1. position_sizer.py                 │
│     Lot Size = (Equity * Risk%) /     │
│                (SL_pips * PipValue)   │
│                                       │
│  2. margin_checker.py                 │
│     Required Margin < Free Margin     │
│     Leverage Check & Margin Level %   │
│                                       │
│  3. portfolio_risk.py                 │
│     Open Positions <= Max Positions   │
│     Total Portfolio Risk <= Max Limit │
│                                       │
│  4. circuit_breaker.py                │
│     Daily Loss < Max Daily Loss %     │
└──────────────────┬────────────────────┘
                   │
         [PASS / REJECT & REASON]
                   │
                   ▼
         Order Execution Loop
```

---

## 2. Component Specifications

### 2.1 Position Sizer (`core/risk/position_sizer.py`)
- **Formula**:
  $$\text{Risk Amount} = \text{Account Equity} \times \frac{\text{Risk Pct}}{100}$$
  $$\text{Lot Size} = \frac{\text{Risk Amount}}{\text{SL Distance (price)} \times \text{Contract Size} \times \text{Tick Value}}$$
- **Lot Clamping**: Clamped strictly between `symbol_info.volume_min` and `symbol_info.volume_max` in increments of `symbol_info.volume_step`.

### 2.2 Margin Checker (`core/risk/margin_checker.py`)
- Calculates required initial margin for the computed volume.
- Ensures `free_margin > required_margin * margin_safety_buffer` (default 1.25x).
- Ensures account margin level remains above safety threshold (e.g. `margin_level > 200%`).

### 2.3 Portfolio Risk (`core/risk/portfolio_risk.py`)
- Restricts max concurrent open positions across all symbols (default max: 5).
- Prevents correlated overexposure (e.g., EURUSD and GBPUSD concurrent exposure limits).

### 2.4 Circuit Breaker (`core/circuit_breaker.py`)
- **Daily Loss Limit**: If realized + floating daily loss exceeds `3.0%`, all new entries are blocked until the next daily session.
- **Consecutive Loss Multiplier**: After 2 consecutive losses, dynamically scales down risk multiplier to `0.5x`.
