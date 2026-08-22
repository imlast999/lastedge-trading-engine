# LastEdge Trading Engine

High-performance MetaTrader 5 execution engine and Risk Engine v2 for LastEdge quantitative trading platform.

## Overview
- **MT5 Execution Engine**: Sub-second order execution with automatic exponential reconnection.
- **Risk Engine v2**: Strict position sizing, margin limits, daily loss limits, and dynamic trailing stops.
- **Production REST API**: Local control and telemetry endpoints on port `8081`.
- **Approved Strategies**: Execution of validated and promoted production strategies (`strategies/`).

## Quick Start
```bash
pip install -r requirements.txt
cp .env.example .env
python bot.py
```
