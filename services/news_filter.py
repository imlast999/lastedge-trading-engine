"""
News Filter Service

Pausa el trading 30 minutos antes y después de eventos de alto impacto
para evitar slippage y movimientos erráticos alrededor de publicaciones clave.

Estrategia de fechas:
  - FOMC, CPI, NFP, ECB: fechas exactas hardcodeadas para 2025 y 2026.
    Las aproximaciones por "2º miércoles del mes" son incorrectas y pueden
    fallar silenciosamente. Las fechas exactas se obtienen de los calendarios
    oficiales de la Fed, BLS y BCE.
  - Si el año no está en el calendario, cae back al método aproximado
    con un warning en el log.

Symbol mapping:
  - EURUSD: afectado por USD y EUR
  - XAUUSD: afectado por USD
  - BTCEUR: no afectado por noticias macro
"""

import logging
from datetime import datetime, date, timezone, timedelta
from typing import Tuple, List, Dict, Optional

logger = logging.getLogger(__name__)

# Ventana de blackout en minutos antes y después de cada evento
BLACKOUT_MINUTES = 30

# ── Calendarios exactos ───────────────────────────────────────────────────────
# Fuentes: federalreserve.gov, bls.gov, ecb.europa.eu
# Formato: (año, mes, día)

# Fed FOMC — decisión de tipos, 19:00 UTC (comunicado) / 18:30 UTC (statement)
# Usamos 19:00 UTC como hora del comunicado principal
_FOMC_DATES: List[Tuple[int, int, int]] = [
    # 2025
    (2025, 1, 29),
    (2025, 3, 19),
    (2025, 5, 7),
    (2025, 6, 18),
    (2025, 7, 30),
    (2025, 9, 17),
    (2025, 10, 29),
    (2025, 12, 10),
    # 2026
    (2026, 1, 28),
    (2026, 3, 18),
    (2026, 4, 29),
    (2026, 6, 17),
    (2026, 7, 29),
    (2026, 9, 16),
    (2026, 11, 4),
    (2026, 12, 16),
]

# CPI USA — publicación BLS, 13:30 UTC
_CPI_DATES: List[Tuple[int, int, int]] = [
    # 2025
    (2025, 1, 15),
    (2025, 2, 12),
    (2025, 3, 12),
    (2025, 4, 10),
    (2025, 5, 13),
    (2025, 6, 11),
    (2025, 7, 15),
    (2025, 8, 12),
    (2025, 9, 10),
    (2025, 10, 15),
    (2025, 11, 13),
    (2025, 12, 10),
    # 2026
    (2026, 1, 14),
    (2026, 2, 11),
    (2026, 3, 11),
    (2026, 4, 9),
    (2026, 5, 13),
    (2026, 6, 10),
    (2026, 7, 14),
    (2026, 8, 12),
    (2026, 9, 9),
    (2026, 10, 14),
    (2026, 11, 12),
    (2026, 12, 9),
]

# NFP (Non-Farm Payrolls) — primer viernes del mes, 13:30 UTC
# Se calcula dinámicamente pero se listan las fechas exactas para verificación
_NFP_DATES: List[Tuple[int, int, int]] = [
    # 2025
    (2025, 1, 10),
    (2025, 2, 7),
    (2025, 3, 7),
    (2025, 4, 4),
    (2025, 5, 2),
    (2025, 6, 6),
    (2025, 7, 3),  # jueves por festivo 4 de julio
    (2025, 8, 1),
    (2025, 9, 5),
    (2025, 10, 3),
    (2025, 11, 7),
    (2025, 12, 5),
    # 2026
    (2026, 1, 9),
    (2026, 2, 6),
    (2026, 3, 6),
    (2026, 4, 3),
    (2026, 5, 8),
    (2026, 6, 5),
    (2026, 7, 2),
    (2026, 8, 7),
    (2026, 9, 4),
    (2026, 10, 2),
    (2026, 11, 6),
    (2026, 12, 4),
]

# ECB — decisión de tipos, 12:15 UTC (comunicado) + 12:45 UTC (rueda de prensa)
_ECB_DATES: List[Tuple[int, int, int]] = [
    # 2025
    (2025, 1, 30),
    (2025, 3, 6),
    (2025, 4, 17),
    (2025, 6, 5),
    (2025, 7, 24),
    (2025, 9, 11),
    (2025, 10, 30),
    (2025, 12, 18),
    # 2026
    (2026, 1, 22),
    (2026, 3, 5),
    (2026, 4, 16),
    (2026, 6, 4),
    (2026, 7, 23),
    (2026, 9, 10),
    (2026, 10, 29),
    (2026, 12, 17),
]

# Convertir a sets de date para búsqueda O(1)
_FOMC_SET = {date(y, m, d) for y, m, d in _FOMC_DATES}
_CPI_SET   = {date(y, m, d) for y, m, d in _CPI_DATES}
_NFP_SET   = {date(y, m, d) for y, m, d in _NFP_DATES}
_ECB_SET   = {date(y, m, d) for y, m, d in _ECB_DATES}

# Años cubiertos por el calendario exacto
_COVERED_YEARS = {2025, 2026}


class NewsFilter:
    """
    Comprueba si el momento actual está dentro de una ventana de blackout
    de noticias de alto impacto para un símbolo dado.
    """

    SYMBOL_CURRENCIES: Dict[str, List[str]] = {
        'EURUSD': ['USD', 'EUR'],
        'XAUUSD': ['USD'],
        'BTCEUR': [],
    }

    def is_news_blackout(self, symbol: str) -> Tuple[bool, str]:
        """
        Devuelve (True, razón) si el momento actual está dentro de la ventana
        de blackout de algún evento de alto impacto que afecte al símbolo.
        """
        try:
            affected = self.SYMBOL_CURRENCIES.get(symbol.upper(), [])
            if not affected:
                return False, ""

            now    = datetime.now(timezone.utc)
            events = self._get_events_near(now, affected)

            for ev in events:
                delta_min = abs((now - ev['time']).total_seconds() / 60)
                if delta_min <= BLACKOUT_MINUTES:
                    direction = "antes de" if now < ev['time'] else "después de"
                    reason = (
                        f"{ev['name']} ({ev['currency']}) "
                        f"a las {ev['time'].strftime('%H:%M')} UTC — "
                        f"{int(delta_min)} min {direction} del evento"
                    )
                    logger.info("[NewsFilter] BLACKOUT %s: %s", symbol, reason)
                    return True, reason

            return False, ""

        except Exception as e:
            logger.warning(f"NewsFilter error for {symbol}: {e}")
            return False, ""

    def _get_events_near(self, now: datetime, currencies: List[str]) -> List[Dict]:
        """
        Devuelve eventos dentro de ±24h del momento actual que afecten
        a las divisas indicadas.
        """
        events: List[Dict] = []
        window = timedelta(hours=24)

        # Revisar hoy, ayer y mañana para cubrir bordes de medianoche
        for offset in (-1, 0, 1):
            check = (now + timedelta(days=offset)).date()
            year  = check.year

            if year not in _COVERED_YEARS:
                # Año no cubierto: usar método aproximado con aviso
                logger.warning(
                    "[NewsFilter] Año %d no en calendario exacto — usando aproximación", year
                )
                events.extend(self._approximate_events(check, currencies))
                continue

            # ── NFP ──────────────────────────────────────────────────────────
            if 'USD' in currencies and check in _NFP_SET:
                events.append({
                    'name': 'NFP (Non-Farm Payrolls)',
                    'currency': 'USD',
                    'time': datetime(check.year, check.month, check.day, 13, 30, tzinfo=timezone.utc),
                })

            # ── CPI USA ───────────────────────────────────────────────────────
            if 'USD' in currencies and check in _CPI_SET:
                events.append({
                    'name': 'CPI USA',
                    'currency': 'USD',
                    'time': datetime(check.year, check.month, check.day, 13, 30, tzinfo=timezone.utc),
                })

            # ── FOMC ──────────────────────────────────────────────────────────
            if 'USD' in currencies and check in _FOMC_SET:
                events.append({
                    'name': 'Fed FOMC',
                    'currency': 'USD',
                    'time': datetime(check.year, check.month, check.day, 19, 0, tzinfo=timezone.utc),
                })

            # ── ECB ───────────────────────────────────────────────────────────
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

        # Filtrar a ±24h
        return [e for e in events if abs((now - e['time']).total_seconds()) <= window.total_seconds()]

    # ── Fallback aproximado para años no cubiertos ────────────────────────────

    def _approximate_events(self, check: date, currencies: List[str]) -> List[Dict]:
        """Método aproximado original — solo se usa si el año no está en el calendario."""
        events = []
        year = check.year; month = check.month; day = check.day

        if 'USD' in currencies:
            # NFP: primer viernes
            first_friday = self._first_weekday_of_month(year, month, 4)
            if check == first_friday:
                events.append({'name': 'NFP (aprox)', 'currency': 'USD',
                                'time': datetime(year, month, day, 13, 30, tzinfo=timezone.utc)})
            # CPI: 2º martes
            second_tuesday = self._nth_weekday_of_month(year, month, 1, 2)
            if check == second_tuesday:
                events.append({'name': 'CPI USA (aprox)', 'currency': 'USD',
                                'time': datetime(year, month, day, 13, 30, tzinfo=timezone.utc)})
            # FOMC: 2º miércoles de meses con reunión
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
