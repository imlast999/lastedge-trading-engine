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
- Calculates required initial margin for the computed volume using `mt5.order_calc_margin()`.
- Ensures `free_margin >= margin_needed` and account free margin stays above `minimum_free_margin_pct` (default 20.0%).
- **Broker Exposure Limit (FXLiveCapital Hard Rule)**:
  - Enforces `max_symbol_margin_pct = 10.0` (Maximum 10% of account balance allocated to margin on any single instrument, taking into account any existing open positions on that symbol).
  - **Why exactly 10%?** This is the strict regulatory risk rule enforced by **FXLiveCapital** for prop challenge and funded accounts (*"Margin used on a single symbol cannot exceed 10% of your account balance. Opening just one lot too many can cost you the account"*). Breaking this threshold by even 0.01 lots leads to automatic challenge disqualification.
  - **Auto-Reduction Safeguard**: If a trade's optimal lot size requires > 10% margin (e.g. narrow stop loss leading to high volume), the `MarginChecker` automatically scales down the lot using the configured reduction sequence until the margin strictly complies with the broker's 10% threshold. If even `volume_min` exceeds 10%, the order is cleanly blocked.
  - **Account Verification & Testing**: Anyone wishing to test or paper-trade these strategies and risk controls on the exact execution environment can register a **completely free demo account without KYC** directly at: [FXLiveCapital Free Demo Registration](https://client.fxlivecapital.com/authentication/registration/IMLAST9992).

### 2.3 Portfolio Risk (`core/risk/portfolio_risk.py`)
- Restricts max concurrent open positions across all symbols (default max: 5).
- Prevents correlated overexposure (e.g., EURUSD and GBPUSD concurrent exposure limits).

### 2.4 Circuit Breaker (`core/circuit_breaker.py`)
- **Daily Loss Limit**: If realized + floating daily loss exceeds `3.0%`, all new entries are blocked until the next daily session.
- **Consecutive Loss Multiplier**: After 2 consecutive losses, dynamically scales down risk multiplier to `0.5x`.
