"""
LastEdge Trading Engine — Dynamic Order Tagger & Comment Generator
services/order_tagger.py

Generates standardized, institutional comments and magic numbers for MetaTrader 5 orders:
- Guarantees strict <= 31 characters limit for MqlTradeRequest.comment
- Auto-extracts symbol, strategy abbreviation, setup/trigger, and calculated R:R
- Handles lifecycle events: Entry, Partial Close, Trailing Stop, Breakeven, Stop Loss
"""

from typing import Dict, Any, Optional


class OrderTagger:
    """Generador autónomo y dinámico de comentarios y magic numbers para MT5."""

    SYMBOL_MAP = {
        "EURUSD": "EUR",
        "XAUUSD": "XAU",
        "BTCEUR": "BTC",
        "BTCUSD": "BTC",
        "GBPUSD": "GBP",
        "USDJPY": "JPY",
        "US500": "SP500",
        "NAS100": "NAS",
    }

    MAGIC_BASE = {
        "EURUSD": 110000,
        "XAUUSD": 120000,
        "BTCEUR": 130000,
        "BTCUSD": 130000,
        "GBPUSD": 140000,
        "USDJPY": 150000,
    }

    @classmethod
    def get_symbol_abbr(cls, symbol: str) -> str:
        sym = symbol.upper().strip()
        if sym in cls.SYMBOL_MAP:
            return cls.SYMBOL_MAP[sym]
        for suffix in ("USD", "EUR", "USDT"):
            if sym.endswith(suffix) and len(sym) > len(suffix):
                return sym[:-len(suffix)][:4]
        return sym[:4]

    @classmethod
    def get_strategy_abbr(cls, strat_name: str) -> str:
        if not strat_name or strat_name.lower() in ("unknown", "none", "default"):
            return "ALGO"
        s = strat_name.lower().replace("strategy", "").replace("strat", "")
        for prefix in ("eurusd_", "xauusd_", "btceur_", "btcusd_", "gbpusd_"):
            if s.startswith(prefix):
                s = s[len(prefix):]
        s = s.strip("_")
        
        known = {
            "partial": "PART",
            "flow": "FLOW",
            "trend_surge": "TRND",
            "volatility_breakout": "VOLB",
            "vol_breakout": "VOLB",
            "asian_london": "ASIA",
            "statistical_reversal": "SREV",
            "surge": "SURG",
            "simple": "SMPL",
            "momentum": "MMTM",
            "pullback": "PLBK",
            "breakout": "BRK",
        }
        if s in known:
            return known[s]
            
        parts = s.split("_")
        if len(parts) >= 2:
            abbr = "".join(p[:2].upper() for p in parts[:2])
            return abbr[:4]
        return s[:4].upper()

    @classmethod
    def get_setup_abbr(cls, signal: Dict[str, Any]) -> str:
        setup = signal.get("setup_type") or signal.get("context", {}).get("setup_type") or ""
        if not setup and "metadata" in signal and isinstance(signal["metadata"], dict):
            setup = signal["metadata"].get("setup_type", "")
        
        setup_str = str(setup).lower()
        if "squeeze" in setup_str or "compression" in setup_str:
            return "Squeeze"
        if "pullback" in setup_str or "touch" in setup_str:
            return "Pullback"
        if "breakout" in setup_str or "expansion" in setup_str:
            return "Breakout"
        if "reversal" in setup_str or "bounce" in setup_str:
            return "Reversal"
        if "wick" in setup_str or "rejection" in setup_str:
            return "Rejection"
        if "flow" in setup_str or "momentum" in setup_str:
            return "Momentum"
        if "session" in setup_str:
            return "Session"

        ctx = signal.get("context", {})
        if isinstance(ctx, dict):
            if "rsi" in ctx:
                return f"RSI{int(float(ctx['rsi']))}"
            if "asia_range_pips" in ctx:
                return f"Asia{int(float(ctx['asia_range_pips']))}p"

        return "Algo"

    @classmethod
    def calculate_rr(cls, signal: Dict[str, Any]) -> str:
        try:
            entry = float(signal.get("entry", 0))
            sl = float(signal.get("sl", 0))
            tp = float(signal.get("tp", 0))
            if entry > 0 and sl > 0 and tp > 0:
                sl_dist = abs(entry - sl)
                tp_dist = abs(tp - entry)
                if sl_dist > 0:
                    rr = tp_dist / sl_dist
                    return f"RR{rr:.1f}"
        except Exception:
            pass
        return "RR1.5"

    @classmethod
    def generate_entry_comment(cls, signal: Dict[str, Any]) -> str:
        """
        Genera un comentario estructurado de entrada, ej:
        'BTC-TRND·Pullback·RR3.0' (23 chars)
        'XAU-PART·Rejection·RR2.5' (24 chars)
        'EUR-FLOW·Momentum·RR2.0' (23 chars)
        Garantiza estrictamente <= 31 caracteres.
        """
        symbol = str(signal.get("symbol", "SYM"))
        sym_abbr = cls.get_symbol_abbr(symbol)
        
        strat = (
            signal.get("strategy")
            or signal.get("strategy_name")
            or signal.get("name")
            or signal.get("context", {}).get("strategy")
            or "algo"
        )
        strat_abbr = cls.get_strategy_abbr(str(strat))
        setup_abbr = cls.get_setup_abbr(signal)
        rr_str = cls.calculate_rr(signal)

        comment = f"{sym_abbr}-{strat_abbr}·{setup_abbr}·{rr_str}"
        if len(comment) > 31:
            comment = f"{sym_abbr}-{strat_abbr}·{rr_str}"[:31]
        return comment[:31]

    @classmethod
    def generate_magic_number(cls, signal: Dict[str, Any], default_magic: int = 123456) -> int:
        """
        Genera un Magic Number único y determinista por símbolo y estrategia.
        """
        symbol = str(signal.get("symbol", "")).upper().strip()
        strat = str(
            signal.get("strategy")
            or signal.get("strategy_name")
            or signal.get("name")
            or ""
        ).lower().strip()

        base = cls.MAGIC_BASE.get(symbol, 200000)
        
        if "flow" in strat:
            return base + 102
        if "partial" in strat or "simple" in strat:
            return base + 101
        if "trend_surge" in strat or "trend" in strat:
            return base + 101
        if "volatility" in strat or "breakout" in strat or "squeeze" in strat:
            return base + 102
        if "reversal" in strat:
            return base + 103
        if "asian" in strat:
            return base + 104

        strat_hash = abs(hash(strat)) % 900 + 100
        return base + strat_hash

    @classmethod
    def generate_partial_close_comment(cls, pct: int = 50) -> str:
        """Comentario institucional para el cierre parcial en MT5 y Myfxbook."""
        return f"PARTIAL:{pct}%·BE-LOCKED"[:31]

    @classmethod
    def generate_trailing_exit_comment(cls) -> str:
        """Comentario institucional para cierre por trailing stop."""
        return "TRAIL:ATR-PROFIT-LOCK"[:31]

    @classmethod
    def generate_breakeven_comment(cls) -> str:
        """Comentario para salida en breakeven."""
        return "EXIT:BE-PROTECTED"[:31]

    @classmethod
    def generate_stoploss_comment(cls) -> str:
        """Comentario para salida por Stop Loss."""
        return "EXIT:STOPLOSS-HIT"[:31]
