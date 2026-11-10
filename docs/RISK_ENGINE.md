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

### 2.5 SpreadGuard & Rollover Blowout Protection (`services/execution.py` / `is_spread_acceptable`)
- **Real-Time Pre-Trade Check**: Before any order is dispatched to MT5, the engine queries the current live `ask - bid` spread directly from the broker book.
- **Rollover & Volatility Shield**: During daily bank rollover (21:55 - 22:15 UTC) or major economic releases, broker spreads can expand by 3x-10x, turning positive expected-value signals into instant losses.
- **Deterministic Blocking**: If `current_spread > max_allowed_spread` for the instrument (e.g. > 2.5 pips on EURUSD or > 50 cents on XAUUSD), order dispatch is rejected immediately with an audit log, eliminating live execution drawdown divergence from backtests.


---

## 3. Multi-Strategy Simultaneous Execution & Split-Risk Protocol

### 3.1 Dual Execution on the Same Instrument (Retail Hedging)
The trading engine operates on MetaTrader 5 **Retail Hedging** accounts (`ACCOUNT_MARGIN_MODE_RETAIL_HEDGING = 2`). This architecture allows executing two concurrent strategies on the same asset (for example, a trend-following pullback strategy alongside a volatility breakout model on `BTCEUR` or `EURUSD`) with completely independent tickets, Stop Loss, and Take Profit levels.

### 3.2 Split-Risk Protocol (0.50% / 0.50% Allocation)
When multiple strategies are configured to trade concurrently on the same instrument, the institutional risk engine **does NOT assign 1.0% risk per trade to each**. Instead, it enforces a strict split-risk allocation rule:

$$\text{Risk per Strategy} = \frac{\text{Max Risk per Symbol}}{N} = \frac{1.0\%}{2} = 0.50\%$$

- **Strategy A (e.g. Trend Following / Pullback)**: `risk_per_trade = 0.50%`
- **Strategy B (e.g. Volatility Breakout / Squeeze)**: `risk_per_trade = 0.50%`
- **Maximum Combined Symbol Exposure**: `1.00%`

### 3.3 Magic Number Isolation & Zero Cross-Interference
- Each active strategy is stamped with a deterministic **Magic Number** in MetaTrader 5 (e.g., `100301` for `btceur_trend_surge` and `100302` for `btceur_volatility_breakout`).
- Position tracking, Break-Even locks, dynamic ATR trailing stops, and partial closes managed by one strategy never interfere with or alter the order tickets of the other.
- If one strategy holds a long position (BUY) and the other triggers a short signal (SELL), the account maintains both open positions simultaneously with hedged margin protection according to broker margin specifications.
