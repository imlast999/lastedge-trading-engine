"""
LastEdge App — Chart Rendering Helper
services/chart_helper.py
=====================================
Unified utility for generating high-definition, institutional dark-mode
candlestick charts from MetaTrader 5 live candle feeds or historical fallback data.
"""

from __future__ import annotations

import os
import sys
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import matplotlib
matplotlib.use('Agg')
import pandas as pd

logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = APP_DIR / "logs" / "charts"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

from services.charts import generate_chart, fmt_price


def _fetch_candles_mt5(symbol: str, timeframe: str = "H1", bars: int = 80) -> Optional[pd.DataFrame]:
    """Fetches real-time candles directly from MetaTrader 5 terminal."""
    try:
        import MetaTrader5 as mt5
        if not mt5.initialize():
            logger.debug("[ChartHelper] MT5 initialize failed.")
            return None

        tf_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1,
        }
        mt5_tf = tf_map.get(timeframe.upper(), mt5.TIMEFRAME_H1)

        rates = mt5.copy_rates_from_pos(symbol.upper(), mt5_tf, 0, max(20, bars))
        if rates is None or len(rates) == 0:
            logger.debug(f"[ChartHelper] No rates returned from MT5 for {symbol}.")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df[["time", "open", "high", "low", "close", "tick_volume"]]
    except Exception as e:
        logger.debug(f"[ChartHelper] Error copying rates from MT5: {e}")
        return None


def _fetch_candles_fallback(symbol: str, timeframe: str = "H1", bars: int = 80) -> Optional[pd.DataFrame]:
    """Fallback to Strategy Lab parquet historical data if MT5 is offline."""
    try:
        data_dir = APP_DIR.parent / "LastEdge Strategy Lab" / "data"
        candidates = list(data_dir.glob(f"{symbol.upper()}*.parquet")) + list(data_dir.glob(f"{symbol.lower()}*.parquet"))
        if not candidates:
            candidates = list(data_dir.glob("*.parquet"))

        if candidates:
            df = pd.read_parquet(candidates[0])
            for t_col in ["time", "datetime", "timestamp"]:
                if t_col in df.columns:
                    df["time"] = pd.to_datetime(df[t_col])
                    break
            df = df.sort_values("time").tail(max(20, bars))
            return df[["time", "open", "high", "low", "close"]]
    except Exception as e:
        logger.debug(f"[ChartHelper] Fallback parquet error: {e}")
    return None


def get_chart_for_signal(
    symbol: Any,
    timeframe: str = "H1",
    signal_data: Optional[Dict[str, Any]] = None,
    bars: int = 80,
    title: Optional[str] = None,
    projection_mode: bool = False
) -> Optional[str]:
    """
    Generates a candlestick chart with Entry, SL, and TP levels plotted.
    Returns the absolute path to the generated PNG image.
    Supports either get_chart_for_signal('EURUSD', signal_data={...}) or get_chart_for_signal(signal_dict).
    """
    if isinstance(symbol, dict):
        signal_data = symbol
        symbol = signal_data.get("symbol", "EURUSD")
        timeframe = signal_data.get("timeframe", timeframe)
        if "projection_mode" in signal_data:
            projection_mode = bool(signal_data["projection_mode"])
    elif signal_data and "projection_mode" in signal_data:
        projection_mode = bool(signal_data["projection_mode"])
    sym = str(symbol).upper()

    df = _fetch_candles_mt5(sym, timeframe, bars)
    if df is None or len(df) < 5:
        df = _fetch_candles_fallback(sym, timeframe, bars)

    if df is None or len(df) < 5:
        logger.warning(f"[ChartHelper] Insufficient candle data for {sym}.")
        return None

    # Format signal parameters
    sig_param = None
    if signal_data:
        entry = signal_data.get("entry") or signal_data.get("price") or signal_data.get("entry_price")
        sl = signal_data.get("sl") or signal_data.get("sl_price") or signal_data.get("stopLoss")
        tp = signal_data.get("tp") or signal_data.get("tp_price") or signal_data.get("takeProfit")
        sig_type = signal_data.get("type") or signal_data.get("direction") or "SIGNAL"
        sig_param = {
            "entry": float(entry) if entry else None,
            "sl": float(sl) if sl else None,
            "tp": float(tp) if tp else None,
            "type": sig_type
        }

    now_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = str(LOGS_DIR / f"chart_{sym}_{now_tag}_{uuid.uuid4().hex[:6]}.png")

    if not title:
        sig_str = f" • {sig_param['type'].upper()}" if sig_param and sig_param.get("type") else ""
        entry_str = f" | Entry: {fmt_price(sig_param['entry'])}" if sig_param and sig_param.get("entry") else ""
        sl_str = f" | SL: {fmt_price(sig_param['sl'])}" if sig_param and sig_param.get("sl") else ""
        tp_str = f" | TP: {fmt_price(sig_param['tp'])}" if sig_param and sig_param.get("tp") else ""
        title = f"{sym} ({timeframe}){sig_str}{entry_str}{sl_str}{tp_str}"

    try:
        path = generate_chart(
            df=df,
            symbol=sym,
            signal=sig_param,
            filename=out_file,
            title=title,
            dark_mode=True,
            candlesticks=True,
            projection_mode=projection_mode
        )
        return path
    except Exception as e:
        logger.error(f"[ChartHelper] Failed generating chart for {sym}: {e}")
        return None


def get_chart_for_position(ticket: int, bars: int = 80) -> Optional[str]:
    """
    Fetches the live position by ticket, resolves symbol, entry, current SL & TP,
    and returns the rendered chart image path.
    """
    pos_data = None
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            positions = mt5.positions_get(ticket=int(ticket))
            if positions and len(positions) > 0:
                p = positions[0]
                pos_data = {
                    "symbol": str(p.symbol),
                    "type": "BUY" if p.type == 0 else "SELL",
                    "entry": float(p.price_open),
                    "sl": float(p.sl),
                    "tp": float(p.tp),
                    "profit": float(p.profit),
                    "volume": float(p.volume)
                }
    except Exception as e:
        logger.debug(f"[ChartHelper] MT5 query for ticket #{ticket} error: {e}")

    # Fallback to trading_client positions
    if not pos_data:
        try:
            t_client = trading_client
            if not t_client:
                from services.clients.trading_client import get_trading_client
                t_client = get_trading_client()
            res = t_client.get_positions()
            positions = res.get("positions", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
            for p in positions:
                if int(p.get("ticket", 0)) == int(ticket):
                    pos_data = {
                        "symbol": str(p.get("symbol", "EURUSD")),
                        "type": str(p.get("type", "BUY")).upper(),
                        "entry": float(p.get("open_price", 0.0)),
                        "sl": float(p.get("sl", 0.0)),
                        "tp": float(p.get("tp", 0.0)),
                        "profit": float(p.get("profit", 0.0)),
                        "volume": float(p.get("volume", 0.0))
                    }
                    break
        except Exception as e:
            logger.debug(f"[ChartHelper] TradingClient position query error: {e}")

    if not pos_data:
        logger.warning(f"[ChartHelper] Position #{ticket} not found.")
        return None

    sym = pos_data["symbol"]
    pnl_sign = "+" if pos_data["profit"] >= 0 else ""
    
    # Calculate R:R if SL and TP exist
    rr_str = ""
    entry = pos_data["entry"]
    sl = pos_data["sl"]
    tp = pos_data["tp"]
    if entry > 0 and sl > 0 and tp > 0:
        risk = abs(entry - sl)
        reward = abs(entry - tp)
        if risk > 0:
            rr_str = f" | R:R 1:{reward/risk:.2f}"

    title = (
        f"{sym} (H1) • #{ticket} {pos_data['type']} {pos_data['volume']}L • "
        f"PnL: {pnl_sign}${pos_data['profit']:.2f}{rr_str}"
    )

    return get_chart_for_signal(
        symbol=sym,
        timeframe="H1",
        signal_data=pos_data,
        bars=bars,
        title=title,
        projection_mode=False
    )


def get_candles_json(symbol: str, timeframe: str = "H1", bars: int = 100) -> List[Dict[str, Any]]:
    """Devuelve las ultimas velas formateadas en JSON para TradingView Lightweight Charts."""
    df = _fetch_candles_mt5(symbol, timeframe, bars)
    if df is None or len(df) == 0:
        df = _fetch_candles_fallback(symbol, timeframe, bars)
    if df is None or len(df) == 0:
        return []

    result = []
    for _, row in df.iterrows():
        t_val = row["time"]
        if hasattr(t_val, "timestamp"):
            t = int(t_val.timestamp())
        else:
            t = int(pd.to_datetime(t_val).timestamp())
        vol = float(row["tick_volume"]) if "tick_volume" in row and pd.notna(row["tick_volume"]) else 0.0
        result.append({
            "time": t,
            "open": round(float(row["open"]), 5),
            "high": round(float(row["high"]), 5),
            "low": round(float(row["low"]), 5),
            "close": round(float(row["close"]), 5),
            "volume": vol
        })
    result.sort(key=lambda x: x["time"])
    return result


def get_position_flow_data(ticket: int, bars: int = 100, trading_client: Any = None) -> Optional[Dict[str, Any]]:
    """Devuelve la posicion en vivo con sus niveles (Entry, SL, TP) y la serie de velas para el grafico de flujo."""
    pos_data = None
    try:
        import MetaTrader5 as mt5
        if mt5.initialize():
            positions = mt5.positions_get(ticket=int(ticket))
            if positions and len(positions) > 0:
                p = positions[0]
                pos_data = {
                    "ticket": int(ticket),
                    "symbol": str(p.symbol),
                    "type": "BUY" if p.type == 0 else "SELL",
                    "entry": float(p.price_open),
                    "current_price": float(p.price_current),
                    "sl": float(p.sl),
                    "tp": float(p.tp),
                    "profit": float(p.profit),
                    "volume": float(p.volume),
                    "time": datetime.fromtimestamp(p.time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                }
    except Exception as e:
        logger.debug(f"[ChartHelper] MT5 query for ticket #{ticket} error: {e}")

    if not pos_data:
        try:
            if trading_client is not None:
                t_client = trading_client
            else:
                from services.clients.trading_client import get_trading_client
                t_client = get_trading_client()
            res = t_client.get_positions()
            positions = res.get("positions", []) if isinstance(res, dict) else (res if isinstance(res, list) else [])
            for p in positions:
                if int(p.get("ticket", 0)) == int(ticket):
                    pos_data = {
                        "ticket": int(ticket),
                        "symbol": str(p.get("symbol", "EURUSD")),
                        "type": str(p.get("type", "BUY")).upper(),
                        "entry": float(p.get("open_price", 0.0)),
                        "current_price": float(p.get("current_price", 0.0)),
                        "sl": float(p.get("sl", 0.0)),
                        "tp": float(p.get("tp", 0.0)),
                        "profit": float(p.get("profit", 0.0)),
                        "volume": float(p.get("volume", 0.0)),
                        "time": str(p.get("time", ""))
                    }
                    break
        except Exception as e:
            logger.debug(f"[ChartHelper] TradingClient position query error: {e}")

    if not pos_data:
        return None

    candles = get_candles_json(pos_data["symbol"], "H1", bars)
    pos_data["candles"] = candles
    return pos_data


def get_signal_flow_data(signal_id: str, bars: int = 100, trading_client: Any = None) -> Optional[Dict[str, Any]]:
    """Devuelve la senal con sus niveles y las velas de MT5."""
    try:
        t_client = trading_client
        if not t_client:
            from services.clients.trading_client import get_trading_client
            t_client = get_trading_client()
        res = t_client.get_signals()
        signals = res if isinstance(res, list) else res.get("signals", [])
        target_sig = None
        for s in signals:
            if str(s.get("id")) == str(signal_id):
                target_sig = s
                break

        if not target_sig:
            return None

        sym = str(target_sig.get("symbol", "EURUSD"))
        candles = get_candles_json(sym, "H1", bars)
        return {
            "id": str(target_sig.get("id")),
            "symbol": sym,
            "type": str(target_sig.get("type", "BUY")).upper(),
            "entry": float(target_sig.get("entry", 0.0)),
            "sl": float(target_sig.get("stopLoss", target_sig.get("sl", 0.0))),
            "tp": float(target_sig.get("takeProfit", target_sig.get("tp", 0.0))),
            "status": str(target_sig.get("status", "pending")),
            "time": str(target_sig.get("timestamp", "")),
            "candles": candles
        }
    except Exception as e:
        logger.debug(f"[ChartHelper] Error getting signal flow: {e}")
        return None
