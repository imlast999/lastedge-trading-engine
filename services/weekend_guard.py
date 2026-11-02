"""
Weekend Exposure Guard (Friday Flat Rule & Entry Blackout)
services/weekend_guard.py

Protects trading capital against weekend gaps and high Monday morning volatility
by enforcing risk protocols before traditional markets close on Friday night:
1. Entry Blackout: Blocks new trade signals for guarded symbols on Friday evening (>= 18:00 UTC).
2. Friday Flat / Flattening: Automatically closes open positions on guarded symbols
   at Friday 21:30 UTC to secure accumulated profit and eliminate gap risk.
3. 24/7 Exemption for Crypto: Assets like BTCEUR/BTCUSD operate continuously and are exempt.
4. Per-Strategy Autonomy: Strategy authors can explicitly set `weekend_exposure_guard = False`
   in their strategy template or class to opt out of the guard.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, time
from typing import Optional, Dict, Any, List, Tuple, Set

logger = logging.getLogger(__name__)


class WeekendExposureGuard:
    """
    Weekend Exposure Guard manager.
    Enforces Friday market-close exit rules and Friday evening entry blackouts.
    """

    DEFAULT_CLOSE_DAY = 4             # Friday (0=Mon, ..., 4=Fri, 6=Sun)
    DEFAULT_CLOSE_HOUR = 21           # 21:30 UTC
    DEFAULT_CLOSE_MINUTE = 30
    DEFAULT_BLOCK_ENTRY_HOUR = 18     # 18:00 UTC
    DEFAULT_BLOCK_ENTRY_MINUTE = 0
    DEFAULT_REOPEN_DAY = 6            # Sunday
    DEFAULT_REOPEN_HOUR = 22          # 22:00 UTC
    DEFAULT_REOPEN_MINUTE = 0

    DEFAULT_EXCLUDED_SYMBOLS = [
        "BTCEUR", "BTCUSD", "ETHUSD", "ETHEUR", "SOLUSD", "SOLEUR"
    ]

    def __init__(
        self,
        rules_config_path: Optional[str] = None,
        bot_service: Optional[Any] = None,
        mt5_module: Optional[Any] = None,
    ):
        if rules_config_path is None:
            rules_config_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "rules_config.json"
            )
        self.rules_config_path = rules_config_path
        self._bot_service = bot_service
        self._mt5 = mt5_module
        self._closed_tickets_this_weekend: Set[int] = set()
        self._last_reset_week: Optional[int] = None
        self.reload_config()

    def reload_config(self) -> None:
        """Loads configuration from rules_config.json with graceful defaults."""
        self.config: Dict[str, Any] = {}
        self.global_settings: Dict[str, Any] = {}
        self.guard_settings: Dict[str, Any] = {}

        try:
            if os.path.exists(self.rules_config_path):
                with open(self.rules_config_path, "r", encoding="utf-8") as f:
                    self.config = json.load(f)
                self.global_settings = self.config.get("GLOBAL_SETTINGS", {})
                self.guard_settings = self.global_settings.get("weekend_exposure_guard", {})
            else:
                logger.warning(
                    "[WeekendExposureGuard] Config file not found at %s. Using defaults.",
                    self.rules_config_path
                )
        except Exception as e:
            logger.error("[WeekendExposureGuard] Failed to parse %s: %e", self.rules_config_path, e)

        self.enabled: bool = bool(self.guard_settings.get("enabled", True))
        self.close_day: int = int(self.guard_settings.get("close_day_of_week", self.DEFAULT_CLOSE_DAY))
        self.close_hour: int = int(self.guard_settings.get("close_hour_utc", self.DEFAULT_CLOSE_HOUR))
        self.close_minute: int = int(self.guard_settings.get("close_minute_utc", self.DEFAULT_CLOSE_MINUTE))
        self.block_entry_hour: int = int(self.guard_settings.get("block_new_signals_hour_utc", self.DEFAULT_BLOCK_ENTRY_HOUR))
        self.block_entry_minute: int = int(self.guard_settings.get("block_new_signals_minute_utc", self.DEFAULT_BLOCK_ENTRY_MINUTE))
        self.reopen_day: int = int(self.guard_settings.get("reopen_day_of_week", self.DEFAULT_REOPEN_DAY))
        self.reopen_hour: int = int(self.guard_settings.get("reopen_hour_utc", self.DEFAULT_REOPEN_HOUR))
        self.reopen_minute: int = int(self.guard_settings.get("reopen_minute_utc", self.DEFAULT_REOPEN_MINUTE))

        excluded = self.guard_settings.get("excluded_symbols", self.DEFAULT_EXCLUDED_SYMBOLS)
        self.excluded_symbols: Set[str] = {s.upper() for s in excluded}

    # ── Asset Classification & Strategy Switch ───────────────────────────────

    def is_crypto(self, symbol: str) -> bool:
        """Determines if an asset is a 24/7 continuous cryptocurrency."""
        if not symbol:
            return False
        sym = symbol.upper()
        if sym in self.excluded_symbols:
            return True
        for prefix in ("BTC", "ETH", "SOL", "XRP", "ADA", "DOGE"):
            if sym.startswith(prefix):
                return True
        return False

    def is_symbol_guarded(
        self,
        symbol: str,
        strategy: Optional[Any] = None
    ) -> bool:
        """
        Evaluates whether a symbol (and optionally its strategy) is subject to the weekend guard.
        
        Resolution Priority:
        1. Global master switch disabled -> False
        2. Crypto symbol -> False (operates 24/7)
        3. Strategy instance / class explicit switch:
           If `strategy.weekend_exposure_guard` is defined, its value takes precedence.
        4. Symbol config in rules_config.json (`"weekend_exposure_guard": true/false`).
        5. Default: True for traditional markets (Forex, Metals, CFDs), False for Crypto.
        """
        if not self.enabled:
            return False

        sym_upper = symbol.upper() if symbol else ""
        if self.is_crypto(sym_upper):
            return False

        # Check explicit strategy setting (Strategy-level switch requested by user)
        if strategy is not None:
            strat_switch = self._extract_strategy_guard_switch(strategy)
            if strat_switch is not None:
                return strat_switch

        # Check per-symbol configuration in rules_config.json
        sym_cfg = self.config.get(sym_upper) or self.config.get(symbol, {})
        if isinstance(sym_cfg, dict) and "weekend_exposure_guard" in sym_cfg:
            return bool(sym_cfg["weekend_exposure_guard"])

        # Default: guarded for traditional assets
        return True

    def _extract_strategy_guard_switch(self, strategy: Any) -> Optional[bool]:
        """Extracts weekend_exposure_guard toggle from a strategy instance, class, or name."""
        try:
            # Case A: Object or instance
            if hasattr(strategy, "weekend_exposure_guard"):
                return bool(strategy.weekend_exposure_guard)

            # Case B: Object metadata
            metadata = getattr(strategy, "metadata", None)
            if metadata and hasattr(metadata, "weekend_exposure_guard"):
                return bool(metadata.weekend_exposure_guard)

            # Case C: Strategy config dict
            config = getattr(strategy, "config", None) or getattr(strategy, "default_config", None)
            if isinstance(config, dict) and "weekend_exposure_guard" in config:
                return bool(config["weekend_exposure_guard"])

            # Case D: Strategy name string - attempt registry lookup
            if isinstance(strategy, str):
                from strategies import STRATEGY_REGISTRY, get_strategy
                strat_inst = get_strategy(strategy)
                if strat_inst is not None:
                    return self._extract_strategy_guard_switch(strat_inst)
        except Exception as e:
            logger.debug("[WeekendExposureGuard] Error extracting strategy switch: %s", e)

        return None

    # ── Time Boundaries ──────────────────────────────────────────────────────

    def is_entry_allowed(
        self,
        symbol: str,
        strategy: Optional[Any] = None,
        now: Optional[datetime] = None
    ) -> Tuple[bool, str]:
        """
        Checks whether opening new positions/signals is permitted right now.
        
        Returns:
            (is_allowed: bool, reason: str)
        """
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # If symbol/strategy is not guarded (e.g. BTC or switch=off), entries are always permitted
        if not self.is_symbol_guarded(symbol, strategy):
            return True, "Weekend guard disabled for this symbol/strategy (Exempt/Crypto)"

        weekday = now.weekday()
        current_time = now.time()

        # Friday: check evening entry blackout
        if weekday == self.close_day:
            blackout_start = time(self.block_entry_hour, self.block_entry_minute)
            if current_time >= blackout_start:
                return (
                    False,
                    f"Friday entry blackout active: no new positions after "
                    f"{self.block_entry_hour:02d}:{self.block_entry_minute:02d} UTC "
                    f"(current UTC: {now.strftime('%H:%M')})"
                )
            return True, "Friday session active (before entry blackout)"

        # Saturday: traditional markets completely closed
        if weekday == 5:
            return False, "Saturday: Traditional markets closed for the weekend"

        # Sunday: closed until reopen time (22:00 UTC)
        if weekday == self.reopen_day:
            reopen_time = time(self.reopen_hour, self.reopen_minute)
            if current_time < reopen_time:
                return (
                    False,
                    f"Sunday: Traditional markets closed until "
                    f"{self.reopen_hour:02d}:{self.reopen_minute:02d} UTC "
                    f"(current UTC: {now.strftime('%H:%M')})"
                )
            return True, "Sunday: Markets reopened for new trading week"

        # Monday through Thursday: unrestricted trading
        return True, "Weekday trading session open"

    def is_flattening_time(self, now: Optional[datetime] = None) -> bool:
        """
        Checks whether it is time to force-close open positions for guarded symbols.
        
        Active window:
        - Friday >= 21:30 UTC
        - Saturday all day (safety net for stuck positions)
        - Sunday < 22:00 UTC
        """
        if not self.enabled:
            return False

        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        weekday = now.weekday()
        current_time = now.time()

        if weekday == self.close_day:
            close_time = time(self.close_hour, self.close_minute)
            return current_time >= close_time

        if weekday == 5:  # Saturday
            return True

        if weekday == self.reopen_day:  # Sunday
            reopen_time = time(self.reopen_hour, self.reopen_minute)
            return current_time < reopen_time

        return False

    # ── Execution: Position Flattening ────────────────────────────────────────

    def check_and_flatten_positions(
        self,
        now: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Scans open MT5 positions and closes any position on a guarded symbol
        if currently in the weekend flattening window.
        
        Returns:
            List of dictionaries describing each closed position and secured P&L.
        """
        if now is None:
            now = datetime.now(timezone.utc)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Reset cache on Monday to prepare for next week
        current_week = now.isocalendar()[1]
        if self._last_reset_week != current_week and now.weekday() < 4:
            self._closed_tickets_this_weekend.clear()
            self._last_reset_week = current_week

        if not self.is_flattening_time(now):
            return []

        # Get MT5 positions
        mt5_lib = self._get_mt5()
        if mt5_lib is None:
            return []

        try:
            positions = mt5_lib.positions_get()
            if not positions:
                return []
        except Exception as e:
            logger.error("[WeekendExposureGuard] Failed to fetch MT5 positions: %s", e)
            return []

        closed_results: List[Dict[str, Any]] = []
        bot_svc = self._get_bot_service()

        for pos in positions:
            pos_dict = pos._asdict() if hasattr(pos, "_asdict") else dict(pos)
            ticket = pos_dict.get("ticket")
            symbol = pos_dict.get("symbol", "")
            volume = pos_dict.get("volume", 0.0)
            profit = pos_dict.get("profit", 0.0)
            pos_type = pos_dict.get("type", 0)
            price_current = pos_dict.get("price_current", 0.0)

            # Skip if already closed this weekend
            if ticket in self._closed_tickets_this_weekend:
                continue

            # Evaluate if this position is guarded
            if not self.is_symbol_guarded(symbol):
                continue

            # Execute market close
            type_label = "BUY" if pos_type == 0 else "SELL"
            logger.info(
                "🛡️ [WEEKEND EXPOSURE GUARD] Closing position #%s (%s %s %.2fL) @ %.5f | Secured P&L: %+.2f €",
                ticket, symbol, type_label, volume, price_current, profit
            )

            close_res = self._execute_close(bot_svc, mt5_lib, ticket, symbol, volume, pos_type)
            if close_res.get("ok"):
                self._closed_tickets_this_weekend.add(ticket)
                result_entry = {
                    "ticket": ticket,
                    "symbol": symbol,
                    "volume": volume,
                    "type": type_label,
                    "profit": profit,
                    "price": price_current,
                    "status": "CLOSED",
                    "closed_at": now.isoformat(),
                    "reason": "Weekend Exposure Guard (Friday Flat Rule)",
                }
                closed_results.append(result_entry)
                self._notify_flatten(result_entry)
            else:
                logger.error(
                    "❌ [WEEKEND EXPOSURE GUARD] Failed to close position #%s: %s",
                    ticket, close_res.get("message")
                )

        return closed_results

    def _execute_close(
        self,
        bot_svc: Optional[Any],
        mt5_lib: Any,
        ticket: int,
        symbol: str,
        volume: float,
        pos_type: int
    ) -> Dict[str, Any]:
        """Executes close order via BotService or directly through MT5 deal request."""
        # Preference 1: BotService
        if bot_svc and hasattr(bot_svc, "close_position"):
            try:
                res = bot_svc.close_position(ticket)
                if isinstance(res, dict) and res.get("ok"):
                    return res
            except Exception as e:
                logger.warning("[WeekendExposureGuard] BotService close failed for #%s: %s", ticket, e)

        # Preference 2: Direct MT5 order_send Deal
        try:
            order_type = mt5_lib.ORDER_TYPE_SELL if pos_type == mt5_lib.ORDER_TYPE_BUY else mt5_lib.ORDER_TYPE_BUY
            tick = mt5_lib.symbol_info_tick(symbol)
            if not tick:
                return {"ok": False, "message": f"No tick price for {symbol}"}

            price = tick.bid if order_type == mt5_lib.ORDER_TYPE_SELL else tick.ask

            request = {
                "action": mt5_lib.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "price": price,
                "deviation": 25,
                "magic": 100001,
                "comment": "Weekend Exposure Guard",
                "type_time": mt5_lib.ORDER_TIME_GTC,
                "type_filling": mt5_lib.ORDER_FILLING_IOC,
            }

            result = mt5_lib.order_send(request)
            if result and result.retcode == mt5_lib.TRADE_RETCODE_DONE:
                return {"ok": True, "message": f"Closed #{ticket} via MT5 direct deal."}
            else:
                retcode = getattr(result, "retcode", "unknown")
                return {"ok": False, "message": f"MT5 direct deal rejected with retcode {retcode}"}
        except Exception as ex:
            return {"ok": False, "message": f"Exception executing direct deal: {ex}"}

    def _notify_flatten(self, entry: Dict[str, Any]) -> None:
        """Sends operational log and push notification for flattened positions."""
        try:
            from services.logging import log_event
            msg = (
                f"🛡️ Weekend Exposure Guard: Posición #{entry['ticket']} cerrada "
                f"({entry['symbol']} {entry['type']} {entry['volume']}L) "
                f"P&L Asegurado: {entry['profit']:+.2f} €"
            )
            log_event(msg, "INFO", "WEEKEND_GUARD")
        except Exception:
            pass

    def _get_mt5(self) -> Optional[Any]:
        if self._mt5 is not None:
            return self._mt5
        try:
            import MetaTrader5 as mt5
            if mt5.terminal_info() is None:
                mt5.initialize()
            self._mt5 = mt5
            return mt5
        except Exception as e:
            logger.debug("[WeekendExposureGuard] MT5 not available: %s", e)
            return None

    def _get_bot_service(self) -> Optional[Any]:
        if self._bot_service is not None:
            return self._bot_service
        try:
            from services.bot_service import BotService
            self._bot_service = BotService()
            return self._bot_service
        except Exception as e:
            logger.debug("[WeekendExposureGuard] BotService not available: %s", e)
            return None


# Global singleton instance
_weekend_guard_instance: Optional[WeekendExposureGuard] = None

def get_weekend_guard() -> WeekendExposureGuard:
    global _weekend_guard_instance
    if _weekend_guard_instance is None:
        _weekend_guard_instance = WeekendExposureGuard()
    return _weekend_guard_instance
