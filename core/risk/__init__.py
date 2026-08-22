"""
core/risk/ — Paquete Risk Engine de LastEdge

Punto de entrada público del sistema de gestión de riesgo.

Exports principales:
    RiskEngine, get_risk_engine()       — Motor principal (usar esto)
    RiskDecision                        — Resultado de cada evaluación

Exports de compatibilidad (no romper imports existentes en execution.py, bot.py…):
    RiskManager, get_risk_manager()     — Alias de RiskEngine / get_risk_engine()
    RiskParameters, RiskAssessment      — Dataclasses legacy (mantenidos para compatibilidad)
    create_risk_manager()               — Crea nueva instancia (alias de create_risk_engine)
"""

# ── Nuevo Risk Engine ──────────────────────────────────────────────────────────
from .engine import (
    RiskEngine,
    RiskDecision,
    get_risk_engine,
    create_risk_engine,
)

from .config import (
    RiskConfig,
    load_risk_config,
)

from .position_sizer import (
    PositionSizer,
    SizingResult,
)

from .margin_checker import (
    MarginChecker,
    MarginCheckResult,
)

from .portfolio_risk import (
    PortfolioRisk,
    PortfolioRiskResult,
    PositionRisk,
)

# ── Aliases de compatibilidad backward ────────────────────────────────────────
# Los módulos existentes importan RiskManager / get_risk_manager() desde core.risk
# Estos aliases aseguran que esos imports sigan funcionando sin cambios.

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class RiskParameters:
    """
    Dataclass legacy — mantenido para compatibilidad.
    Internamente el RiskEngine usa RiskDecision.
    """
    suggested_lot: float
    risk_amount: float
    rr_ratio: float
    max_loss: float
    expected_profit: float
    risk_pct: float


@dataclass
class RiskAssessment:
    """
    Dataclass legacy — mantenido para compatibilidad.
    Internamente el RiskEngine usa RiskDecision.
    """
    approved: bool
    reason: str
    parameters: Optional[RiskParameters]
    warnings: list
    details: Dict


class RiskManager:
    """
    Clase legacy — Thin wrapper sobre RiskEngine.

    Mantenida para no romper:
        - services/execution.py
        - core/__init__.py
        - bot.py
        - cualquier otra referencia existente

    Nuevos módulos deben usar directamente get_risk_engine().evaluate(signal).
    """

    def __init__(self):
        self._engine = get_risk_engine()

    def assess_signal_risk(self, signal: Dict, current_balance: float = None) -> RiskAssessment:
        """
        Legacy API. Evalúa el riesgo de una señal.

        Internamente delega a RiskEngine.evaluate() y convierte el resultado
        al formato RiskAssessment para compatibilidad.
        """
        decision = self._engine.evaluate(signal)

        params = None
        if decision.approved:
            # Calcular R:R básico para compatibilidad
            try:
                entry = float(signal.get("entry", 0))
                sl    = float(signal.get("sl", 0))
                tp    = float(signal.get("tp", entry))
                risk_pts   = abs(entry - sl)
                reward_pts = abs(tp - entry) if tp != entry else 0
                rr_ratio   = reward_pts / risk_pts if risk_pts > 0 else 0.0
            except Exception:
                rr_ratio = 0.0

            params = RiskParameters(
                suggested_lot=decision.lot,
                risk_amount=decision.risk_amount,
                rr_ratio=rr_ratio,
                max_loss=decision.risk_amount,
                expected_profit=decision.risk_amount * rr_ratio,
                risk_pct=decision.risk_pct,
            )

        return RiskAssessment(
            approved=decision.approved,
            reason=decision.reason,
            parameters=params,
            warnings=decision.warnings,
            details={
                "symbol": decision.symbol,
                "balance": decision.balance,
                "equity": decision.equity,
                "lot": decision.lot,
                "portfolio_risk_pct": decision.portfolio_risk_pct,
            },
        )

    def calculate_position_size(self, symbol: str, entry: float, sl: float, risk_pct: float = None):
        """Legacy API. Calcula tamaño de posición. Retorna (lot, risk_amount, rr_ratio)."""
        signal = {"symbol": symbol, "type": "BUY", "entry": entry, "sl": sl}
        decision = self._engine.evaluate(signal)
        if decision.approved:
            return decision.lot, decision.risk_amount, 0.0
        return 0.01, 0.0, 0.0

    def get_risk_statistics(self) -> Dict:
        """Legacy API. Retorna estadísticas básicas de configuración."""
        cfg = self._engine.config
        return {
            "default_risk_pct": cfg.default_risk_pct,
            "max_portfolio_risk_pct": cfg.max_portfolio_risk_pct,
            "min_free_margin_pct": cfg.minimum_free_margin_pct,
            "allow_auto_reduce": cfg.allow_auto_reduce_lot,
            "symbol_overrides": cfg.symbol_risk_overrides,
        }


def get_risk_manager() -> RiskManager:
    """Legacy function — retorna instancia de RiskManager (wrapper de RiskEngine)."""
    return RiskManager()


def create_risk_manager() -> RiskManager:
    """Legacy function — crea instancia de RiskManager."""
    return RiskManager()


__all__ = [
    # Nuevo Risk Engine
    "RiskEngine",
    "RiskDecision",
    "get_risk_engine",
    "create_risk_engine",
    "RiskConfig",
    "load_risk_config",
    "PositionSizer",
    "SizingResult",
    "MarginChecker",
    "MarginCheckResult",
    "PortfolioRisk",
    "PortfolioRiskResult",
    "PositionRisk",
    # Legacy (backward compat)
    "RiskManager",
    "RiskParameters",
    "RiskAssessment",
    "get_risk_manager",
    "create_risk_manager",
]
