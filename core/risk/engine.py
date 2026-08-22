"""
Risk Engine — Orquestador central de protección de capital

PUNTO DE ENTRADA ÚNICO para todo el sistema de gestión de riesgo.

Ninguna estrategia, ningún servicio y ningún comando debe decidir el
tamaño de lote por sí mismo. Toda orden pasa por aquí ANTES de enviarse
a MetaTrader 5.

Pipeline:
    1. PositionSizer  → calcula el lote óptimo basado en balance y SL
    2. MarginChecker  → verifica margen y reduce lote si es necesario
    3. PortfolioRisk  → verifica que el riesgo total no supere el límite

Logging:
    Emite un bloque de logging completo para cada evaluación, aprobada
    o rechazada, con todos los parámetros relevantes.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from .config import RiskConfig, load_risk_config
from .position_sizer import PositionSizer, SizingResult
from .margin_checker import MarginChecker, MarginCheckResult
from .portfolio_risk import PortfolioRisk, PortfolioRiskResult

logger = logging.getLogger(__name__)


@dataclass
class RiskDecision:
    """
    Decisión final del Risk Engine para una señal.

    Si approved=True, el campo `lot` es el volumen con el que se debe
    abrir la operación. Si approved=False, la operación debe cancelarse.
    """
    approved: bool
    lot: float
    reason: str
    warnings: List[str] = field(default_factory=list)

    # Métricas para logging y dashboard
    symbol: str = ""
    balance: float = 0.0
    equity: float = 0.0
    free_margin: float = 0.0
    free_margin_pct: float = 0.0
    risk_pct: float = 0.0
    risk_amount: float = 0.0
    sl_ticks: float = 0.0
    tick_value: float = 0.0
    margin_required: float = 0.0
    portfolio_risk_pct: float = 0.0
    new_trade_risk_pct: float = 0.0
    combined_risk_pct: float = 0.0
    lot_was_reduced: bool = False
    evaluated_at: str = ""


class RiskEngine:
    """
    Motor de gestión de riesgo de LastEdge.

    Orquesta el pipeline completo:
    1. PositionSizer  → lot óptimo por riesgo
    2. MarginChecker  → validación y ajuste por margen
    3. PortfolioRisk  → límite de riesgo total

    Uso:
        engine = get_risk_engine()
        decision = engine.evaluate(signal)
        if decision.approved:
            place_order(symbol, lot=decision.lot, ...)
        else:
            logger.warning(f"Orden bloqueada: {decision.reason}")
    """

    def __init__(self, config: Optional[RiskConfig] = None):
        if config is None:
            config = load_risk_config()
        self.config = config

        self._position_sizer = PositionSizer()
        self._margin_checker = MarginChecker(
            allow_auto_reduce=config.allow_auto_reduce_lot,
            reduction_sequence=config.lot_reduction_sequence,
            minimum_free_margin_pct=config.minimum_free_margin_pct,
        )
        self._portfolio_risk = PortfolioRisk(
            max_portfolio_risk_pct=config.max_portfolio_risk_pct,
            enabled=config.portfolio_risk_enabled,
        )

    def evaluate(
        self,
        signal: Dict,
        account_info: Optional[Any] = None,   # Para tests: mock de mt5.account_info()
        symbol_info: Optional[Any] = None,    # Para tests: mock de mt5.symbol_info()
        open_positions: Optional[List] = None, # Para tests: lista de posiciones
    ) -> RiskDecision:
        """
        Evalúa si una señal puede ejecutarse y con qué volumen.

        Args:
            signal: Dict con al menos {'symbol', 'type', 'entry', 'sl'}
            account_info:   Mock para tests — si None usa MT5 real
            symbol_info:    Mock para tests — si None usa MT5 real
            open_positions: Mock para tests — si None usa MT5 real

        Returns:
            RiskDecision con approved=True/False y lot
        """
        evaluated_at = datetime.now(timezone.utc).isoformat()

        # ── Extraer datos básicos de la señal ─────────────────────────────────
        symbol     = str(signal.get("symbol", "UNKNOWN"))
        order_type = str(signal.get("type", "BUY")).upper()
        entry      = float(signal.get("entry", 0.0))
        sl         = float(signal.get("sl", 0.0))

        if entry <= 0 or sl <= 0:
            return self._reject(
                f"Señal inválida: entry={entry}, sl={sl}",
                symbol=symbol, evaluated_at=evaluated_at,
            )

        # ── Obtener info de cuenta ─────────────────────────────────────────────
        if account_info is None:
            account_info = self._get_account_info()
        if account_info is None:
            return self._reject(
                "No se pudo obtener account_info de MT5",
                symbol=symbol, evaluated_at=evaluated_at,
            )

        balance     = float(self._attr(account_info, "balance", 0.0))
        equity      = float(self._attr(account_info, "equity", 0.0))
        free_margin = float(self._attr(account_info, "margin_free", 0.0))
        free_margin_pct = (free_margin / equity * 100.0) if equity > 0 else 0.0

        if balance <= 0:
            return self._reject(
                f"Balance inválido: {balance}",
                symbol=symbol, balance=balance, evaluated_at=evaluated_at,
            )

        # ── Obtener risk_pct para este símbolo ────────────────────────────────
        risk_pct = self.config.get_risk_pct_for_symbol(symbol)

        # ──────────────────────────────────────────────────────────────────────
        # FASE 1: Position Sizing
        # ──────────────────────────────────────────────────────────────────────
        sizing: SizingResult = self._position_sizer.calculate(
            symbol=symbol,
            entry=entry,
            sl=sl,
            risk_pct=risk_pct,
            balance=balance,
            symbol_info=symbol_info,
        )

        if not sizing.success:
            return self._reject(
                f"[PositionSizer] {sizing.reason}",
                symbol=symbol, balance=balance, equity=equity,
                free_margin=free_margin, free_margin_pct=free_margin_pct,
                risk_pct=risk_pct, evaluated_at=evaluated_at,
            )

        # ──────────────────────────────────────────────────────────────────────
        # FASE 2: Margin Check
        # ──────────────────────────────────────────────────────────────────────
        margin_check: MarginCheckResult = self._margin_checker.check(
            symbol=symbol,
            order_type=order_type,
            lot=sizing.lot,
            price=entry,
            vol_min=sizing.vol_min,
            account_info=account_info,
            symbol_info=symbol_info,
        )

        if not margin_check.approved:
            return self._reject(
                f"[MarginChecker] {margin_check.reason}",
                symbol=symbol, balance=balance, equity=equity,
                free_margin=free_margin, free_margin_pct=free_margin_pct,
                risk_pct=risk_pct,
                sl_ticks=sizing.sl_ticks, tick_value=sizing.tick_value,
                evaluated_at=evaluated_at,
            )

        # Actualizar lot con el resultado del margin checker (puede haber sido reducido)
        final_lot = margin_check.lot

        # ──────────────────────────────────────────────────────────────────────
        # FASE 3: Portfolio Risk
        # ──────────────────────────────────────────────────────────────────────
        portfolio: PortfolioRiskResult = self._portfolio_risk.check(
            new_trade_risk_pct=sizing.risk_pct,
            balance=balance,
            positions=open_positions,
        )

        if not portfolio.approved:
            return self._reject(
                f"[PortfolioRisk] {portfolio.reason}",
                symbol=symbol, balance=balance, equity=equity,
                free_margin=free_margin, free_margin_pct=free_margin_pct,
                risk_pct=risk_pct,
                sl_ticks=sizing.sl_ticks, tick_value=sizing.tick_value,
                margin_required=margin_check.margin_required,
                portfolio_risk_pct=portfolio.total_risk_pct,
                new_trade_risk_pct=portfolio.new_trade_risk_pct,
                combined_risk_pct=portfolio.combined_risk_pct,
                evaluated_at=evaluated_at,
            )

        # ──────────────────────────────────────────────────────────────────────
        # APROBADO
        # ──────────────────────────────────────────────────────────────────────
        warnings = list(margin_check.warnings) + list(portfolio.warnings)

        decision = RiskDecision(
            approved=True,
            lot=final_lot,
            reason="APPROVED",
            warnings=warnings,
            symbol=symbol,
            balance=balance,
            equity=equity,
            free_margin=free_margin,
            free_margin_pct=free_margin_pct,
            risk_pct=sizing.risk_pct,
            risk_amount=sizing.risk_amount,
            sl_ticks=sizing.sl_ticks,
            tick_value=sizing.tick_value,
            margin_required=margin_check.margin_required,
            portfolio_risk_pct=portfolio.total_risk_pct,
            new_trade_risk_pct=portfolio.new_trade_risk_pct,
            combined_risk_pct=portfolio.combined_risk_pct,
            lot_was_reduced=margin_check.was_reduced,
            evaluated_at=evaluated_at,
        )

        self._log_decision(decision, sizing)
        return decision

    # ──────────────────────────────────────────────────────────────────────────
    # Logging
    # ──────────────────────────────────────────────────────────────────────────

    def _log_decision(self, decision: RiskDecision, sizing: SizingResult):
        """Emite el bloque de logging completo del Risk Engine."""
        if not self.config.verbose_logging:
            return

        lines = [
            "=" * 56,
            "  RISK ENGINE — LastEdge",
            "=" * 56,
            f"  Symbol         : {decision.symbol}",
            f"  Balance        : {decision.balance:>12.2f}",
            f"  Equity         : {decision.equity:>12.2f}",
            f"  Free Margin    : {decision.free_margin:>12.2f}  ({decision.free_margin_pct:.1f}%)",
            f"  Risk per trade : {decision.risk_pct:>11.2f}%",
            f"  SL distance    : {sizing.sl_ticks:>10.2f} ticks",
            f"  Tick Value     : {decision.tick_value:>12.4f}",
            f"  Calculated Lot : {decision.lot:>12.4f}",
        ]

        if decision.margin_required > 0:
            lines.append(f"  Margin Required: {decision.margin_required:>12.2f}")

        lines += [
            f"  Portfolio Risk : {decision.portfolio_risk_pct:>11.2f}%  (antes de esta orden)",
            f"  Combined Risk  : {decision.combined_risk_pct:>11.2f}%  (incluye esta orden)",
            f"  Max Portfolio  : {self.config.max_portfolio_risk_pct:>11.2f}%",
        ]

        if decision.lot_was_reduced:
            lines.append(f"  [WARNING] Lote reducido por margen insuficiente")

        for w in decision.warnings:
            lines.append(f"  [WARNING] {w}")

        lines.append(f"  Status         : {decision.reason}")
        lines.append("=" * 56)

        log_fn = logger.info if decision.approved else logger.warning
        log_fn("\n%s", "\n".join(lines))

    def _reject(self, reason: str, **kwargs) -> RiskDecision:
        """Crea un RiskDecision rechazado y lo registra."""
        decision = RiskDecision(
            approved=False,
            lot=0.0,
            reason=reason,
            evaluated_at=kwargs.pop("evaluated_at", ""),
            **{k: v for k, v in kwargs.items() if k in RiskDecision.__dataclass_fields__},
        )

        if self.config.log_rejected:
            lines = [
                "=" * 56,
                "  RISK ENGINE — LastEdge  [BLOCKED]",
                "=" * 56,
                f"  Symbol  : {decision.symbol}",
                f"  Balance : {decision.balance:.2f}",
                f"  Equity  : {decision.equity:.2f}",
                f"  Reason  : {reason}",
                "=" * 56,
            ]
            logger.warning("\n%s", "\n".join(lines))

        return decision

    # ──────────────────────────────────────────────────────────────────────────
    # Utilidades
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_account_info() -> Optional[Any]:
        try:
            import MetaTrader5 as mt5
            return mt5.account_info()
        except Exception as e:
            logger.error("[RiskEngine] Error obteniendo account_info: %s", e)
            return None

    @staticmethod
    def _attr(obj: Any, name: str, default: float) -> float:
        try:
            if isinstance(obj, dict):
                return obj.get(name, default)
            return getattr(obj, name, default)
        except Exception:
            return default

    def reload_config(self):
        """Recarga la configuración desde disco (útil para hot-reload)."""
        self.config = load_risk_config()
        self._margin_checker.allow_auto_reduce = self.config.allow_auto_reduce_lot
        self._margin_checker.reduction_sequence = self.config.lot_reduction_sequence
        self._margin_checker.minimum_free_margin_pct = self.config.minimum_free_margin_pct
        self._portfolio_risk.max_portfolio_risk_pct = self.config.max_portfolio_risk_pct
        self._portfolio_risk.enabled = self.config.portfolio_risk_enabled
        logger.info("[RiskEngine] Configuración recargada desde disco")

    def get_portfolio_snapshot(self, balance: float) -> Dict:
        """Devuelve snapshot del riesgo actual del portfolio."""
        return self._portfolio_risk.get_portfolio_snapshot(balance)


# ──────────────────────────────────────────────────────────────────────────────
# Singleton global
# ──────────────────────────────────────────────────────────────────────────────

_risk_engine_instance: Optional[RiskEngine] = None


def get_risk_engine() -> RiskEngine:
    """Retorna la instancia global del Risk Engine (singleton lazy)."""
    global _risk_engine_instance
    if _risk_engine_instance is None:
        _risk_engine_instance = RiskEngine()
    return _risk_engine_instance


def create_risk_engine(config: Optional[RiskConfig] = None) -> RiskEngine:
    """Crea una nueva instancia del Risk Engine (para tests o configuraciones específicas)."""
    return RiskEngine(config=config)
