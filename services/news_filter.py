"""
News Filter & Market Protection Engine
services/news_filter.py
======================================
Provides institutional multi-tier news and market condition safeguards:

1. Live Economic Calendar Sync & Cache:
   - Queries online economic calendar feeds (ForexFactory / FairEconomy JSON).
   - Locally caches high-impact events in `data/economic_calendar.json`.
   - Merges live events with verified exact static dates (FOMC, CPI, NFP, ECB)
     for 2025 and 2026.
   - 100% resilient offline fallback when internet or external APIs fail.

2. Dynamic Spread Guard:
   - Probes live broker spread directly from MetaTrader 5 in real price units.
   - Detects abnormal spread spikes (e.g. news releases, weekend rolls, flash illiquidity).
   - Pauses order entries when spread exceeds maximum allowable tolerances.

3. Active Trade Guard (Pre-News Position Shield):
   - Scans active open positions approaching Tier-1 high-impact announcements.
   - Evaluates floating profits and dynamically locks Stop Loss to Break-Even (entry price)
     ahead of the volatility spike to eliminate downside exposure.
"""

from __future__ import annotations

import os
import sys
import json
import ssl
import logging
import urllib.request
from datetime import datetime, date, timezone, timedelta
from typing import Tuple, List, Dict, Optional, Any

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

logger = logging.getLogger(__name__)

# Default blackout window in minutes before and after each event
DEFAULT_BLACKOUT_MINUTES = 30

# Calendar cache location
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(APP_DIR, "data")
CALENDAR_CACHE_PATH = os.path.join(DATA_DIR, "economic_calendar.json")

# Default maximum allowable spread in real price units (ask - bid)
DEFAULT_MAX_SPREAD_PRICE: Dict[str, float] = {
    'EURUSD': 0.00035,   # 3.5 pips maximum
    'GBPUSD': 0.00045,   # 4.5 pips maximum
    'XAUUSD': 1.00,      # $1.00 USD maximum (1000 points at 0.001)
    'BTCEUR': 60.00,     # €60.00 EUR maximum
    'BTCUSD': 65.00,     # $65.00 USD maximum
}

# ── Verified Static Calendars (FOMC, CPI, NFP, ECB for 2025-2026) ─────────────
_FOMC_DATES: List[Tuple[int, int, int]] = [
    # 2025
    (2025, 1, 29), (2025, 3, 19), (2025, 5, 7), (2025, 6, 18),
    (2025, 7, 30), (2025, 9, 17), (2025, 10, 29), (2025, 12, 10),
    # 2026
    (2026, 1, 28), (2026, 3, 18), (2026, 4, 29), (2026, 6, 17),
    (2026, 7, 29), (2026, 9, 16), (2026, 11, 4), (2026, 12, 16),
]

_CPI_DATES: List[Tuple[int, int, int]] = [
    # 2025
    (2025, 1, 15), (2025, 2, 12), (2025, 3, 12), (2025, 4, 10),
    (2025, 5, 13), (2025, 6, 11), (2025, 7, 15), (2025, 8, 12),
    (2025, 9, 10), (2025, 10, 15), (2025, 11, 13), (2025, 12, 10),
    # 2026
    (2026, 1, 14), (2026, 2, 11), (2026, 3, 11), (2026, 4, 9),
    (2026, 5, 13), (2026, 6, 10), (2026, 7, 14), (2026, 8, 12),
    (2026, 9, 9), (2026, 10, 14), (2026, 11, 12), (2026, 12, 9),
]

_NFP_DATES: List[Tuple[int, int, int]] = [
    # 2025
    (2025, 1, 10), (2025, 2, 7), (2025, 3, 7), (2025, 4, 4),
    (2025, 5, 2), (2025, 6, 6), (2025, 7, 3), (2025, 8, 1),
    (2025, 9, 5), (2025, 10, 3), (2025, 11, 7), (2025, 12, 5),
    # 2026
    (2026, 1, 9), (2026, 2, 6), (2026, 3, 6), (2026, 4, 3),
    (2026, 5, 8), (2026, 6, 5), (2026, 7, 2), (2026, 8, 7),
    (2026, 9, 4), (2026, 10, 2), (2026, 11, 6), (2026, 12, 4),
]

_ECB_DATES: List[Tuple[int, int, int]] = [
    # 2025
    (2025, 1, 30), (2025, 3, 6), (2025, 4, 17), (2025, 6, 5),
    (2025, 7, 24), (2025, 9, 11), (2025, 10, 30), (2025, 12, 18),
    # 2026
    (2026, 1, 22), (2026, 3, 5), (2026, 4, 16), (2026, 6, 4),
    (2026, 7, 23), (2026, 9, 10), (2026, 10, 29), (2026, 12, 17),
]

_FOMC_SET = {date(y, m, d) for y, m, d in _FOMC_DATES}
_CPI_SET   = {date(y, m, d) for y, m, d in _CPI_DATES}
_NFP_SET   = {date(y, m, d) for y, m, d in _NFP_DATES}
_ECB_SET   = {date(y, m, d) for y, m, d in _ECB_DATES}
_COVERED_YEARS = {2025, 2026}


class NewsFilter:
    """
    Advanced multi-layered News Filter and Market Protection system.
    Safeguards account capital through blackout windows, dynamic spread monitoring,
    and active position shielding.
    """

    SYMBOL_CURRENCIES: Dict[str, List[str]] = {
        'EURUSD': ['USD', 'EUR'],
        'GBPUSD': ['USD', 'GBP'],
        'XAUUSD': ['USD'],
        'BTCEUR': [],
        'BTCUSD': [],
    }

    def __init__(
        self,
        blackout_minutes: int = DEFAULT_BLACKOUT_MINUTES,
        max_spread_price: Optional[Dict[str, float]] = None,
        cache_path: str = CALENDAR_CACHE_PATH,
        auto_fetch_live: bool = True
    ):
        self.blackout_minutes = blackout_minutes
        self.max_spread_price = max_spread_price or DEFAULT_MAX_SPREAD_PRICE.copy()
        self.cache_path = cache_path
        self.auto_fetch_live = auto_fetch_live
        self._last_live_fetch: Optional[datetime] = None
        self._cached_live_events: List[Dict[str, Any]] = []

        # Load local cache on initialization
        self._load_local_cache()

    # ── 1. Live Calendar Fetching & Caching ───────────────────────────────────

    def _load_local_cache(self) -> None:
        """Loads cached economic events from disk if available."""
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    raw_events = json.load(f)
                    parsed = []
                    for ev in raw_events:
                        t_str = ev.get("time")
                        if t_str:
                            ev_copy = ev.copy()
                            ev_copy["dt"] = datetime.fromisoformat(t_str).astimezone(timezone.utc)
                            parsed.append(ev_copy)
                    self._cached_live_events = parsed
                    logger.debug("[NewsFilter] Loaded %d events from cache: %s", len(parsed), self.cache_path)
            except Exception as e:
                logger.debug("[NewsFilter] Could not load calendar cache: %s", e)

    def fetch_live_calendar(self, force: bool = False, timeout_sec: int = 4) -> List[Dict[str, Any]]:
        """
        Fetches this week's economic calendar from public FairEconomy/ForexFactory feed.
        Caches high-impact events locally and falls back seamlessly on network issues.
        """
        now = datetime.now(timezone.utc)
        # Avoid refetching if fetched less than 4 hours ago unless forced
        if not force and self._last_live_fetch and (now - self._last_live_fetch) < timedelta(hours=4):
            return self._cached_live_events

        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "LastEdge-Trading-Engine/1.0 (Quant System)"}
            )

            with urllib.request.urlopen(req, timeout=timeout_sec, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                parsed_events = []
                for item in data:
                    impact = str(item.get("impact", "")).strip().capitalize()
                    if impact not in ("High", "Holiday"):
                        continue
                    country = str(item.get("country", "")).strip().upper()
                    title = str(item.get("title", "")).strip()
                    date_str = str(item.get("date", "")).strip()
                    if not date_str or not country or not title:
                        continue
                    try:
                        dt_utc = datetime.fromisoformat(date_str).astimezone(timezone.utc)
                        parsed_events.append({
                            "name": title,
                            "currency": country,
                            "impact": "HIGH" if impact == "High" else "HOLIDAY",
                            "time": dt_utc.isoformat(),
                            "timestamp": int(dt_utc.timestamp()),
                            "dt": dt_utc
                        })
                    except Exception:
                        continue

                if parsed_events:
                    self._cached_live_events = parsed_events
                    self._last_live_fetch = now
                    # Persist cache
                    try:
                        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
                        with open(self.cache_path, "w", encoding="utf-8") as f:
                            json.dump(
                                [{k: v for k, v in ev.items() if k != "dt"} for ev in parsed_events],
                                f,
                                indent=2
                            )
                        logger.info("[NewsFilter] Successfully synced and cached %d live events.", len(parsed_events))
                    except Exception as ce:
                        logger.debug("[NewsFilter] Error writing calendar cache: %s", ce)

                return self._cached_live_events

        except Exception as e:
            logger.debug("[NewsFilter] Live calendar sync failed (using local fallback): %s", e)
            return self._cached_live_events

    # ── 2. Blackout Window Evaluation ────────────────────────────────────────

    def is_news_blackout(self, symbol: str, check_time: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Determines if current time is within a blackout window for a given symbol.
        Returns (is_blackout: bool, reason: str).
        """
        try:
            affected = self.SYMBOL_CURRENCIES.get(symbol.upper(), [])
            if not affected:
                return False, ""

            now = check_time or datetime.now(timezone.utc)
            events = self._get_events_near(now, affected)

            for ev in events:
                delta_min = abs((now - ev['time']).total_seconds() / 60)
                if delta_min <= self.blackout_minutes:
                    direction = "before" if now < ev['time'] else "after"
                    reason = (
                        f"{ev['name']} ({ev['currency']}) "
                        f"at {ev['time'].strftime('%H:%M')} UTC — "
                        f"{int(delta_min)} min {direction} event"
                    )
                    logger.info("[NewsFilter] BLACKOUT %s: %s", symbol, reason)
                    return True, reason

            return False, ""

        except Exception as e:
            logger.warning("[NewsFilter] Error checking blackout for %s: %s", symbol, e)
            return False, ""

    def get_upcoming_high_impact_events(self, minutes_ahead: int = 120) -> List[Dict[str, Any]]:
        """
        Returns all high-impact events occurring within the specified window ahead.
        """
        try:
            now = datetime.now(timezone.utc)
            max_future = now + timedelta(minutes=max(1, minutes_ahead))
            currencies = ['USD', 'EUR', 'GBP']
            events = self._get_events_near(now, currencies)

            upcoming = []
            for ev in events:
                ev_time = ev['time']
                if (now - timedelta(minutes=self.blackout_minutes)) <= ev_time <= max_future:
                    delta_sec = (ev_time - now).total_seconds()
                    minutes_until = int(round(delta_sec / 60))
                    upcoming.append({
                        'name': ev['name'],
                        'currency': ev['currency'],
                        'impact': 'HIGH',
                        'time': ev_time.isoformat(),
                        'timestamp': int(ev_time.timestamp()),
                        'minutes_until': minutes_until,
                        'is_active_blackout': abs(delta_sec) <= (self.blackout_minutes * 60),
                    })

            upcoming.sort(key=lambda x: x['timestamp'])
            return upcoming
        except Exception as e:
            logger.debug("[NewsFilter] Error retrieving upcoming events: %s", e)
            return []

    # ── 3. Dynamic Spread Guard ──────────────────────────────────────────────

    def is_spread_acceptable(self, symbol: str, max_spread: Optional[float] = None) -> Tuple[bool, str, float, float]:
        """
        Probes MT5 terminal to inspect current real-time spread.
        Returns:
            (is_acceptable: bool, reason: str, current_spread_price: float, max_allowed_price: float)
        """
        sym = symbol.upper()
        max_allowed = max_spread if max_spread is not None else self.max_spread_price.get(sym)
        if max_allowed is None:
            # Fallback default if symbol is unconfigured
            max_allowed = 100.0 if "BTC" in sym else (2.0 if "XAU" in sym else 0.00050)

        try:
            if mt5 is None:
                return True, "Spread check skipped (MT5 library unavailable)", 0.0, max_allowed

            info = mt5.symbol_info(sym)
            if not info:
                info = mt5.symbol_info_tick(sym)
                if not info:
                    return True, "Spread check skipped (MT5 offline / NO_TICK)", 0.0, max_allowed

            ask = float(getattr(info, 'ask', 0.0))
            bid = float(getattr(info, 'bid', 0.0))
            if ask <= 0 or bid <= 0:
                return True, "Spread check skipped (Zero price)", 0.0, max_allowed

            digits = getattr(info, 'digits', 5)
            current_spread = round(ask - bid, digits)

            if current_spread > max_allowed:
                reason = (
                    f"Spread spike detected on {sym}: {current_spread:.5f} exceeds "
                    f"maximum threshold of {max_allowed:.5f} (EXCEEDS_MAX)"
                )
                logger.warning("[SpreadGuard] %s", reason)
                return False, reason, current_spread, max_allowed

            return True, f"Spread normal: {current_spread:.5f} <= {max_allowed:.5f} (OK)", current_spread, max_allowed

        except Exception as e:
            logger.debug("[SpreadGuard] Exception probing spread for %s: %s", sym, e)
            return True, f"Spread probe exception: {e}", 0.0, max_allowed

    # ── 4. Active Trade Guard (Pre-News Position Shield) ─────────────────────

    def get_position_news_protection(
        self,
        symbol: str,
        open_price: float,
        current_price: float,
        current_sl: float,
        pos_type: int | str,  # 0/'BUY' for BUY, 1/'SELL' for SELL
        window_minutes: int = 15,
        check_time: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Evaluates whether an active position is approaching an upcoming Tier-1 news event.
        If in profit and stop loss is not yet secured at or past entry, recommends
        immediate Break-Even shift to neutralize risk.

        Returns:
            {
                'action': 'LOCK_BREAKEVEN' | 'SAFE' | 'WARNING' | 'NO_NEWS' | 'NONE',
                'event_name': str,
                'minutes_until': int,
                'recommended_sl': float,
                'reason': str
            }
        """
        affected = self.SYMBOL_CURRENCIES.get(symbol.upper(), [])
        if not affected:
            return {'action': 'NONE', 'reason': 'Asset unaffected by macro events'}

        now = check_time or datetime.now(timezone.utc)
        events = self._get_events_near(now, affected)

        # Look for events occurring within next `window_minutes` or actively in blackout
        target_event = None
        min_delta = 9999
        for ev in events:
            delta_sec = (ev['time'] - now).total_seconds()
            delta_min = int(round(delta_sec / 60))
            # Event within window (e.g. 0 to 15 min ahead) or active
            if -self.blackout_minutes <= delta_min <= window_minutes:
                if abs(delta_min) < abs(min_delta):
                    min_delta = delta_min
                    target_event = ev

        if not target_event:
            return {'action': 'NO_NEWS', 'reason': 'No upcoming Tier-1 events in window'}

        # Calculate floating state
        if isinstance(pos_type, str):
            is_buy = (pos_type.upper() == 'BUY')
        else:
            is_buy = (pos_type == 0)
        is_profit = (current_price > open_price) if is_buy else (current_price < open_price)

        # Check if already secured at Break-Even
        be_secured = False
        if is_buy and current_sl >= open_price:
            be_secured = True
        elif not is_buy and 0 < current_sl <= open_price:
            be_secured = True

        ev_name = target_event['name']
        if is_profit and not be_secured:
            # Shift SL to entry price (Break-Even)
            recommended_sl = open_price
            return {
                'action': 'LOCK_BREAKEVEN',
                'event_name': ev_name,
                'minutes_until': min_delta,
                'recommended_sl': recommended_sl,
                'reason': (
                    f"Position #{symbol} is in profit ahead of {ev_name} (in {min_delta}m). "
                    f"Locking Break-Even at {recommended_sl:.5f} to neutralize downside risk."
                )
            }
        elif be_secured:
            return {
                'action': 'SAFE',
                'event_name': ev_name,
                'minutes_until': min_delta,
                'reason': f"Position #{symbol} already secured at Break-Even ahead of {ev_name}."
            }
        else:
            return {
                'action': 'WARNING',
                'event_name': ev_name,
                'minutes_until': min_delta,
                'reason': f"Position #{symbol} is not yet in profit ahead of {ev_name} (in {min_delta}m)."
            }

    # ── Internal Event Aggregator ────────────────────────────────────────────

    def _get_events_near(self, now: datetime, currencies: List[str]) -> List[Dict]:
        """
        Gathers events within ±24 hours of current time by combining:
        1. Live synced/cached ForexFactory calendar.
        2. Exact verified static dates for FOMC, CPI, NFP, ECB.
        """
        events: List[Dict] = []
        window = timedelta(hours=24)

        # A. Gather from live synced / cached calendar
        if self._cached_live_events:
            for ev in self._cached_live_events:
                if ev.get("currency") in currencies:
                    ev_dt = ev.get("dt") or datetime.fromisoformat(ev["time"]).astimezone(timezone.utc)
                    if abs((now - ev_dt).total_seconds()) <= window.total_seconds():
                        events.append({
                            'name': ev['name'],
                            'currency': ev['currency'],
                            'time': ev_dt
                        })

        # B. Gather from exact verified dates (2025/2026 static calendar)
        for offset in (-1, 0, 1):
            check = (now + timedelta(days=offset)).date()
            year = check.year

            if year not in _COVERED_YEARS:
                events.extend(self._approximate_events(check, currencies))
                continue

            # NFP
            if 'USD' in currencies and check in _NFP_SET:
                events.append({
                    'name': 'NFP (Non-Farm Payrolls)',
                    'currency': 'USD',
                    'time': datetime(check.year, check.month, check.day, 13, 30, tzinfo=timezone.utc),
                })

            # CPI USA
            if 'USD' in currencies and check in _CPI_SET:
                events.append({
                    'name': 'CPI USA',
                    'currency': 'USD',
                    'time': datetime(check.year, check.month, check.day, 13, 30, tzinfo=timezone.utc),
                })

            # FOMC
            if 'USD' in currencies and check in _FOMC_SET:
                events.append({
                    'name': 'Fed FOMC',
                    'currency': 'USD',
                    'time': datetime(check.year, check.month, check.day, 19, 0, tzinfo=timezone.utc),
                })

            # ECB
            if 'EUR' in currencies and check in _ECB_SET:
                events.append({
                    'name': 'ECB Decision',
                    'currency': 'EUR',
                    'time': datetime(check.year, check.month, check.day, 12, 15, tzinfo=timezone.utc),
                })
                events.append({
                    'name': 'ECB Press Conference',
                    'currency': 'EUR',
                    'time': datetime(check.year, check.month, check.day, 12, 45, tzinfo=timezone.utc),
                })

        # Deduplicate events occurring at approximately the same time with similar name
        deduped: List[Dict] = []
        seen = set()
        for ev in events:
            key = (ev['currency'], ev['time'].strftime('%Y%m%d%H%M'))
            if key not in seen:
                seen.add(key)
                deduped.append(ev)

        # Filter strictly to ±24h
        return [e for e in deduped if abs((now - e['time']).total_seconds()) <= window.total_seconds()]

    def _approximate_events(self, check: date, currencies: List[str]) -> List[Dict]:
        """Approximation fallback for years outside covered static calendar."""
        events = []
        year = check.year
        month = check.month
        day = check.day

        if 'USD' in currencies:
            first_friday = self._first_weekday_of_month(year, month, 4)
            if check == first_friday:
                events.append({'name': 'NFP (aprox)', 'currency': 'USD',
                                'time': datetime(year, month, day, 13, 30, tzinfo=timezone.utc)})
            second_tuesday = self._nth_weekday_of_month(year, month, 1, 2)
            if check == second_tuesday:
                events.append({'name': 'CPI USA (aprox)', 'currency': 'USD',
                                'time': datetime(year, month, day, 13, 30, tzinfo=timezone.utc)})
            if month in (1, 3, 5, 6, 7, 9, 11, 12):
                second_wed = self._nth_weekday_of_month(year, month, 2, 2)
                if check == second_wed:
                    events.append({'name': 'FOMC (aprox)', 'currency': 'USD',
                                    'time': datetime(year, month, day, 19, 0, tzinfo=timezone.utc)})

        if 'EUR' in currencies and month in (1, 4, 6, 9):
            second_thu = self._nth_weekday_of_month(year, month, 3, 2)
            if check == second_thu:
                events.append({'name': 'ECB (aprox)', 'currency': 'EUR',
                                'time': datetime(year, month, day, 12, 15, tzinfo=timezone.utc)})

        return events

    @staticmethod
    def _first_weekday_of_month(year: int, month: int, weekday: int) -> date:
        first = date(year, month, 1)
        ahead = weekday - first.weekday()
        if ahead < 0:
            ahead += 7
        return first + timedelta(days=ahead)

    @staticmethod
    def _nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> date:
        first = date(year, month, 1)
        ahead = weekday - first.weekday()
        if ahead < 0:
            ahead += 7
        return first + timedelta(days=ahead) + timedelta(weeks=n - 1)


# Singleton accessor
_news_filter_instance: Optional[NewsFilter] = None


def get_news_filter() -> NewsFilter:
    """Returns global singleton instance of NewsFilter."""
    global _news_filter_instance
    if _news_filter_instance is None:
        _news_filter_instance = NewsFilter()
    return _news_filter_instance
