"""
Portfolio Risk — Control del riesgo total del portfolio

Responsabilidades:
- Calcular el riesgo abierto total sumando todas las posiciones activas
- Verificar que abrir una nueva operación no supere el límite configurado
- Reportar el detalle por símbolo para logging/dashboard

El riesgo de cada posición abierta se calcula como:
    riesgo_pct = (distancia_SL_en_ticks * tick_value * volumen) / balance * 100

Si no hay SL en la posición, se usa el peor escenario del 2% del precio actual.
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class PositionRisk:
    """Riesgo de una posición individual."""
    symbol: str
    ticket: int
    volume: float
    risk_pct: float         # % del balance arriesgado
    risk_amount: float      # Dinero arriesgado en moneda cuenta
    has_sl: bool            # True si tiene SL configurado
    note: str = ""


@dataclass
class PortfolioRiskResult:
    """Resultado del análisis de riesgo del portfolio."""
    approved: bool
    reason: str
    total_risk_pct: float               # Riesgo total actual (posiciones abiertas)
    new_trade_risk_pct: float           # Riesgo de la nueva operación
    combined_risk_pct: float            # Total + nueva
    max_risk_pct: float                 # Límite configurado
    positions: List[PositionRisk] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class PortfolioRisk:
    """
    Analiza el riesgo total del portfolio antes de abrir una nueva posición.

    Suma el riesgo de todas las posiciones abiertas y verifica que añadir
    la nueva operación no supere el límite de riesgo máximo del portfolio.
    """

    def __init__(self, max_portfolio_risk_pct: float = 2.0, enabled: bool = True):
        """
        Args:
            max_portfolio_risk_pct: Límite de riesgo total en % del balance
            enabled:                Si False, siempre aprueba (útil para tests)
        """
        self.max_portfolio_risk_pct = max_portfolio_risk_pct
        self.enabled = enabled

    def check(
        self,
        new_trade_risk_pct: float,
        balance: float,
        positions: Optional[List[Any]] = None,  # mt5.positions_get() o lista de dicts para tests
        symbol_info_provider: Optional[Any] = None,  # callable(symbol) -> symbol_info, para tests
    ) -> PortfolioRiskResult:
        """
        Verifica si añadir una nueva operación supera el límite de riesgo del portfolio.

        Args:
            new_trade_risk_pct:    Riesgo de la nueva operación en % del balance
            balance:               Balance actual de la cuenta
            positions:             Lista de posiciones abiertas. Si None, se obtiene de MT5.
            symbol_info_provider:  Función para obtener symbol_info por símbolo (para tests/mock)

        Returns:
            PortfolioRiskResult con el análisis completo
        """
        if not self.enabled:
            return PortfolioRiskResult(
                approved=True,
                reason="Portfolio risk check desactivado",
                total_risk_pct=0.0,
                new_trade_risk_pct=new_trade_risk_pct,
                combined_risk_pct=new_trade_risk_pct,
                max_risk_pct=self.max_portfolio_risk_pct,
            )

        try:
            # ── Obtener posiciones abiertas ───────────────────────────────────
            if positions is None:
                positions = self._get_open_positions()

            # ── Calcular riesgo de cada posición ──────────────────────────────
            position_risks = []
            total_risk_pct = 0.0

            for pos in positions:
                pr = self._calc_position_risk(pos, balance, symbol_info_provider)
                if pr is not None:
                    position_risks.append(pr)
                    total_risk_pct += pr.risk_pct

            combined_risk_pct = total_risk_pct + new_trade_risk_pct
            warnings = []

            # ── Posiciones sin SL ─────────────────────────────────────────────
            no_sl_positions = [p for p in position_risks if not p.has_sl]
            if no_sl_positions:
                symbols_no_sl = [p.symbol for p in no_sl_positions]
                warnings.append(
                    f"Posiciones sin SL detectadas: {symbols_no_sl} — "
                    f"riesgo estimado al 2% del precio"
                )

            # ── Verificar límite ──────────────────────────────────────────────
            if combined_risk_pct > self.max_portfolio_risk_pct:
                return PortfolioRiskResult(
                    approved=False,
                    reason=(
                        f"Riesgo del portfolio excedería el límite: "
                        f"{combined_risk_pct:.2f}% > {self.max_portfolio_risk_pct:.2f}% "
                        f"(actual: {total_risk_pct:.2f}% + nueva: {new_trade_risk_pct:.2f}%)"
                    ),
                    total_risk_pct=total_risk_pct,
                    new_trade_risk_pct=new_trade_risk_pct,
                    combined_risk_pct=combined_risk_pct,
                    max_risk_pct=self.max_portfolio_risk_pct,
                    positions=position_risks,
                    warnings=warnings,
                )

            # ── Aprobado ──────────────────────────────────────────────────────
            return PortfolioRiskResult(
                approved=True,
                reason="Riesgo del portfolio dentro del límite",
                total_risk_pct=total_risk_pct,
                new_trade_risk_pct=new_trade_risk_pct,
                combined_risk_pct=combined_risk_pct,
                max_risk_pct=self.max_portfolio_risk_pct,
                positions=position_risks,
                warnings=warnings,
            )

        except Exception as e:
            logger.exception("[PortfolioRisk] Error calculando riesgo del portfolio: %s", e)
            # En caso de error, aprobamos con warning para no bloquear el sistema
            return PortfolioRiskResult(
                approved=True,
                reason=f"Error calculando portfolio risk — aprobando (fallback): {e}",
                total_risk_pct=0.0,
                new_trade_risk_pct=new_trade_risk_pct,
                combined_risk_pct=new_trade_risk_pct,
                max_risk_pct=self.max_portfolio_risk_pct,
                warnings=[f"Error en portfolio risk check: {e}"],
            )

    def _calc_position_risk(
        self,
        pos: Any,
        balance: float,
        symbol_info_provider: Optional[Any] = None,
    ) -> Optional[PositionRisk]:
        """
        Calcula el riesgo de una posición abierta.

        Returns:
            PositionRisk o None si no se pudo calcular.
        """
        try:
            ticket   = int(self._attr(pos, "ticket", 0))
            symbol   = str(self._attr(pos, "symbol", "UNKNOWN"))
            volume   = float(self._attr(pos, "volume", 0.0))
            sl       = float(self._attr(pos, "sl", 0.0))
            price    = float(self._attr(pos, "price_open", 0.0))
            pos_type = self._attr(pos, "type", 0)  # 0=BUY, 1=SELL

            if volume <= 0 or price <= 0:
                return None

            # ── Obtener symbol_info ───────────────────────────────────────────
            if symbol_info_provider is not None:
                si = symbol_info_provider(symbol)
            else:
                si = self._get_symbol_info(symbol)

            if si is None:
                logger.debug("[PortfolioRisk] No symbol_info para %s — omitiendo posición", symbol)
                return None

            tick_size  = self._float_attr(si, "trade_tick_size",  0.0001)
            tick_value = self._float_attr(si, "trade_tick_value", 10.0)

            # ── Distancia al SL ───────────────────────────────────────────────
            has_sl = sl > 0.0
            if has_sl:
                sl_distance = abs(price - sl)
            else:
                # Sin SL: asumir peor caso de 2% del precio
                sl_distance = price * 0.02
                logger.debug(
                    "[PortfolioRisk] %s ticket=%d sin SL — usando estimación 2%%",
                    symbol, ticket
                )

            # ── Calcular riesgo ───────────────────────────────────────────────
            if tick_size > 0:
                sl_ticks = sl_distance / tick_size
                risk_amount = sl_ticks * tick_value * volume
            else:
                risk_amount = 0.0

            risk_pct = (risk_amount / balance * 100.0) if balance > 0 else 0.0

            return PositionRisk(
                symbol=symbol,
                ticket=ticket,
                volume=volume,
                risk_pct=round(risk_pct, 4),
                risk_amount=round(risk_amount, 2),
                has_sl=has_sl,
                note="" if has_sl else "SL ausente — estimación 2%",
            )

        except Exception as e:
            logger.debug("[PortfolioRisk] Error calculando riesgo de posición: %s", e)
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Utilidades
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_open_positions() -> List[Any]:
        """Obtiene posiciones abiertas de MT5."""
        try:
            import MetaTrader5 as mt5
            positions = mt5.positions_get()
            return list(positions) if positions else []
        except Exception as e:
            logger.warning("[PortfolioRisk] Error obteniendo posiciones MT5: %s", e)
            return []

    @staticmethod
    def _get_symbol_info(symbol: str) -> Optional[Any]:
        """Obtiene symbol_info de MT5."""
        try:
            import MetaTrader5 as mt5
            return mt5.symbol_info(symbol)
        except Exception:
            return None

    @staticmethod
    def _attr(obj: Any, name: str, default: Any) -> Any:
        """Extrae atributo de object o dict con default."""
        try:
            if isinstance(obj, dict):
                return obj.get(name, default)
            return getattr(obj, name, default)
        except Exception:
            return default

    @staticmethod
    def _float_attr(obj: Any, name: str, default: float) -> float:
        """Extrae atributo float de object o dict."""
        try:
            if isinstance(obj, dict):
                return float(obj.get(name, default))
            return float(getattr(obj, name, default))
        except (TypeError, ValueError):
            return default

    def get_portfolio_snapshot(
        self,
        balance: float,
        positions: Optional[List[Any]] = None,
        symbol_info_provider: Optional[Any] = None,
    ) -> Dict:
        """
        Devuelve un snapshot del riesgo actual del portfolio.
        Útil para dashboard y logging periódico.
        """
        if positions is None:
            positions = self._get_open_positions()

        position_risks = []
        total_risk_pct = 0.0

        for pos in positions:
            pr = self._calc_position_risk(pos, balance, symbol_info_provider)
            if pr is not None:
                position_risks.append(pr)
                total_risk_pct += pr.risk_pct

        return {
            "total_risk_pct": round(total_risk_pct, 4),
            "max_risk_pct": self.max_portfolio_risk_pct,
            "remaining_capacity_pct": max(0.0, self.max_portfolio_risk_pct - total_risk_pct),
            "positions": [
                {
                    "symbol": pr.symbol,
                    "ticket": pr.ticket,
                    "volume": pr.volume,
                    "risk_pct": pr.risk_pct,
                    "risk_amount": pr.risk_amount,
                    "has_sl": pr.has_sl,
                }
                for pr in position_risks
            ],
        }
