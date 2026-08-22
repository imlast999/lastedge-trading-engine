"""
Margin Checker — Validación de margen antes de enviar órdenes

Responsabilidades:
- Calcular el margen real requerido para una orden usando mt5.order_calc_margin()
- Comparar con el margen libre disponible
- Reducir automáticamente el lote hasta encontrar uno viable
- Bloquear la orden si ni el lote mínimo cabe en el margen

Este módulo es el guardián que evita que XAUUSD (u otro activo) consuma
todo el margen y bloquee el portfolio completo.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


@dataclass
class MarginCheckResult:
    """Resultado de la verificación de margen."""

    approved: bool
    lot: float                    # Lote final aprobado (puede ser menor al solicitado)
    reason: str
    warnings: List[str] = field(default_factory=list)

    # Métricas
    requested_lot: float = 0.0   # Lote originalmente solicitado
    margin_required: float = 0.0 # Margen requerido para el lote aprobado
    free_margin: float = 0.0     # Margen libre disponible
    free_margin_pct: float = 0.0 # % del equity que es margen libre
    equity: float = 0.0
    was_reduced: bool = False     # True si el lote fue reducido automáticamente


class MarginChecker:
    """
    Verifica que existe margen suficiente para abrir una orden.

    Si el lote solicitado no cabe en el margen libre, intenta reducirlo
    automáticamente usando la secuencia configurada.

    Si ni el volumen mínimo del símbolo cabe en el margen disponible,
    bloquea la operación y registra el motivo.
    """

    def __init__(
        self,
        allow_auto_reduce: bool = True,
        reduction_sequence: Optional[List[float]] = None,
        minimum_free_margin_pct: float = 20.0,
    ):
        """
        Args:
            allow_auto_reduce:       Si True, reduce el lote automáticamente
            reduction_sequence:      Fracciones del lote a intentar [1.0, 0.5, 0.25, ...]
            minimum_free_margin_pct: % mínimo de margen libre a mantener sobre equity
        """
        self.allow_auto_reduce = allow_auto_reduce
        self.reduction_sequence = reduction_sequence or [1.0, 0.5, 0.25, 0.12, 0.08, 0.05, 0.03, 0.01]
        self.minimum_free_margin_pct = minimum_free_margin_pct

    def check(
        self,
        symbol: str,
        order_type: str,       # 'BUY' or 'SELL'
        lot: float,
        price: float,
        vol_min: float = 0.01,
        account_info: Any = None,  # mt5.AccountInfo o dict-like para tests
        symbol_info: Any = None,   # mt5.SymbolInfo o dict-like para tests
    ) -> MarginCheckResult:
        """
        Verifica si hay margen suficiente y, si no, intenta reducir el lote.

        Args:
            symbol:       Símbolo del instrumento
            order_type:   'BUY' o 'SELL'
            lot:          Volumen deseado
            price:        Precio de entrada (ask para BUY, bid para SELL)
            vol_min:      Volumen mínimo del símbolo
            account_info: mt5.account_info() — si None se obtiene de MT5
            symbol_info:  mt5.symbol_info() — si None se obtiene de MT5

        Returns:
            MarginCheckResult con el lote aprobado o motivo de rechazo
        """
        try:
            # ── Obtener info de cuenta ────────────────────────────────────────
            if account_info is None:
                account_info = self._get_account_info()
            if account_info is None:
                return MarginCheckResult(
                    approved=False, lot=0.0,
                    reason="No se pudo obtener información de la cuenta MT5",
                    requested_lot=lot,
                )

            equity       = float(self._attr(account_info, "equity", 0.0))
            free_margin  = float(self._attr(account_info, "margin_free", 0.0))
            balance      = float(self._attr(account_info, "balance", 0.0))

            if equity <= 0:
                return MarginCheckResult(
                    approved=False, lot=0.0,
                    reason=f"Equity inválido: {equity}",
                    requested_lot=lot, equity=equity, free_margin=free_margin,
                )

            free_margin_pct = (free_margin / equity * 100.0) if equity > 0 else 0.0

            # ── Verificar margen mínimo global ────────────────────────────────
            if free_margin_pct < self.minimum_free_margin_pct:
                return MarginCheckResult(
                    approved=False, lot=0.0,
                    reason=(
                        f"Margen libre insuficiente: {free_margin_pct:.1f}% "
                        f"< mínimo configurado {self.minimum_free_margin_pct:.1f}%"
                    ),
                    requested_lot=lot,
                    free_margin=free_margin,
                    free_margin_pct=free_margin_pct,
                    equity=equity,
                )

            requested_lot = lot

            # ── Intentar con lote solicitado, luego con secuencia reducida ────
            lots_to_try = self._build_lot_sequence(lot, vol_min)

            for candidate_lot in lots_to_try:
                margin_needed = self._calc_margin(symbol, order_type, candidate_lot, price, symbol_info)

                if margin_needed is None:
                    # mt5.order_calc_margin falló — no podemos verificar, dejar pasar con warning
                    logger.warning(
                        "[MarginChecker] %s: order_calc_margin() falló para lot=%.4f — "
                        "aprobando sin verificación de margen",
                        symbol, candidate_lot
                    )
                    warnings = ["Verificación de margen omitida: order_calc_margin() no disponible"]
                    if candidate_lot < requested_lot:
                        warnings.append(f"Lote reducido de {requested_lot} a {candidate_lot}")
                    return MarginCheckResult(
                        approved=True,
                        lot=candidate_lot,
                        reason="Aprobado (sin verificación de margen — fallback)",
                        warnings=warnings,
                        requested_lot=requested_lot,
                        margin_required=0.0,
                        free_margin=free_margin,
                        free_margin_pct=free_margin_pct,
                        equity=equity,
                        was_reduced=(candidate_lot < requested_lot),
                    )

                if margin_needed <= free_margin:
                    # Este lote cabe en el margen disponible
                    warnings = []
                    was_reduced = candidate_lot < requested_lot

                    if was_reduced:
                        warnings.append(
                            f"Lote reducido automáticamente: "
                            f"{requested_lot:.4f} → {candidate_lot:.4f} "
                            f"(margen requerido para lote original superaba el disponible)"
                        )

                    return MarginCheckResult(
                        approved=True,
                        lot=candidate_lot,
                        reason="Margen suficiente",
                        warnings=warnings,
                        requested_lot=requested_lot,
                        margin_required=margin_needed,
                        free_margin=free_margin,
                        free_margin_pct=free_margin_pct,
                        equity=equity,
                        was_reduced=was_reduced,
                    )
                else:
                    logger.debug(
                        "[MarginChecker] %s: lot=%.4f requiere %.2f USD de margen, "
                        "disponible=%.2f USD — intentando lote menor",
                        symbol, candidate_lot, margin_needed, free_margin
                    )

                if not self.allow_auto_reduce:
                    # No está permitida la reducción automática
                    break

            # ── Ningún lote de la secuencia cabe en el margen ─────────────────
            return MarginCheckResult(
                approved=False,
                lot=0.0,
                reason=(
                    f"Margen insuficiente para {symbol}: "
                    f"ningún lote de la secuencia de reducción cabe. "
                    f"Free margin: {free_margin:.2f} USD ({free_margin_pct:.1f}%)"
                ),
                requested_lot=requested_lot,
                free_margin=free_margin,
                free_margin_pct=free_margin_pct,
                equity=equity,
            )

        except Exception as e:
            logger.exception("[MarginChecker] Error verificando margen para %s: %s", symbol, e)
            return MarginCheckResult(
                approved=False, lot=0.0,
                reason=f"Error interno en verificación de margen: {e}",
                requested_lot=lot,
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Utilidades
    # ──────────────────────────────────────────────────────────────────────────

    def _build_lot_sequence(self, lot: float, vol_min: float) -> List[float]:
        """
        Construye la secuencia de lotes a intentar.

        Empieza con el lote solicitado (fracción 1.0 de él) y luego
        aplica cada fracción de la secuencia de reducción.
        """
        sequence = []
        for fraction in self.reduction_sequence:
            candidate = round(lot * fraction, 8)
            if candidate >= vol_min:
                sequence.append(candidate)

        # Asegurar que el vol_min esté siempre al final como último intento
        if vol_min not in sequence:
            sequence.append(vol_min)

        # Eliminar duplicados preservando orden
        seen = set()
        result = []
        for v in sequence:
            key = round(v, 8)
            if key not in seen:
                seen.add(key)
                result.append(v)

        return result

    @staticmethod
    def _calc_margin(
        symbol: str,
        order_type: str,
        lot: float,
        price: float,
        symbol_info: Any = None,
    ) -> Optional[float]:
        """
        Calcula el margen requerido para una orden usando MT5.

        Returns:
            Margen en moneda de la cuenta, o None si no se pudo calcular.
        """
        try:
            import MetaTrader5 as mt5

            mt5_type = (
                mt5.ORDER_TYPE_BUY if order_type.upper() == "BUY"
                else mt5.ORDER_TYPE_SELL
            )

            margin = mt5.order_calc_margin(mt5_type, symbol, lot, price)
            return float(margin) if margin is not None else None

        except Exception as e:
            logger.debug("[MarginChecker] order_calc_margin falló: %s", e)
            return None

    @staticmethod
    def _get_account_info() -> Optional[Any]:
        """Obtiene account_info de MT5."""
        try:
            import MetaTrader5 as mt5
            return mt5.account_info()
        except Exception as e:
            logger.error("[MarginChecker] Error obteniendo account_info: %s", e)
            return None

    @staticmethod
    def _attr(obj: Any, name: str, default: float) -> float:
        """Extrae atributo de object o dict con default."""
        try:
            if isinstance(obj, dict):
                return obj.get(name, default)
            return getattr(obj, name, default)
        except Exception:
            return default
