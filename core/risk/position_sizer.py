"""
Position Sizer — Cálculo de tamaño de posición

ÚNICO lugar en el sistema donde se calcula el lote.

Principio:
    Las estrategias indican únicamente BUY/SELL + entry + SL + TP.
    Este módulo decide el volumen usando exclusivamente datos objetivos
    de MT5 (account_info + symbol_info) y el porcentaje de riesgo configurado.

Fórmula (universal para cualquier activo):
    tick_value   = symbol_info.trade_tick_value   (en moneda cuenta)
    tick_size    = symbol_info.trade_tick_size     (en unidades de precio)
    sl_ticks     = abs(entry - sl) / tick_size
    risk_per_lot = sl_ticks * tick_value
    lot          = risk_amount / risk_per_lot

Esto funciona correctamente para Forex, Gold y Crypto sin lógica
específica por tipo de activo, porque MT5 resuelve internamente las
conversiones de divisa del tick_value.
"""

import logging
from dataclasses import dataclass
from math import floor
from typing import Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class SizingResult:
    """Resultado del cálculo de tamaño de posición."""

    success: bool
    lot: float
    reason: str

    # Métricas de detalle (para logging)
    risk_amount: float = 0.0          # USD/EUR arriesgado
    risk_pct: float = 0.0             # % del balance
    sl_ticks: float = 0.0             # Ticks de SL
    tick_value: float = 0.0           # Valor de 1 tick por lote
    risk_per_lot: float = 0.0         # Riesgo en dinero por lote con este SL
    raw_lot: float = 0.0              # Lote calculado antes de redondeo
    vol_min: float = 0.01
    vol_max: float = 100.0
    vol_step: float = 0.01


class PositionSizer:
    """
    Calcula el tamaño de posición óptimo basándose en:
    - Balance/equity de la cuenta
    - Porcentaje de riesgo configurado
    - Distancia real del Stop Loss
    - Información del símbolo de MT5 (tick_value, vol_min/max/step)

    No contiene ninguna constante específica por activo (ni pip_value = 10,
    ni fórmulas especiales para Gold/Crypto). Todo se obtiene de MT5.
    """

    def calculate(
        self,
        symbol: str,
        entry: float,
        sl: float,
        risk_pct: float,
        balance: float,
        symbol_info: Any = None,  # mt5.SymbolInfo o dict-like para tests
    ) -> SizingResult:
        """
        Calcula el tamaño de posición.

        Args:
            symbol:      Símbolo del instrumento (EURUSD, XAUUSD, BTCEUR…)
            entry:       Precio de entrada
            sl:          Precio del Stop Loss
            risk_pct:    Porcentaje del balance a arriesgar (ej: 0.5 = 0.5%)
            balance:     Balance actual de la cuenta en moneda base
            symbol_info: Objeto mt5.symbol_info(). Si None, se obtiene de MT5.

        Returns:
            SizingResult con el lote calculado y métricas de detalle.
        """
        try:
            # ── Validaciones básicas ──────────────────────────────────────────
            if entry <= 0 or sl <= 0:
                return SizingResult(False, 0.0, f"Precio inválido: entry={entry}, sl={sl}")

            sl_distance = abs(entry - sl)
            if sl_distance <= 0:
                return SizingResult(False, 0.0, "Entry y SL son iguales — distancia cero")

            if balance <= 0:
                return SizingResult(False, 0.0, f"Balance inválido: {balance}")

            if risk_pct <= 0 or risk_pct > 10:
                return SizingResult(
                    False, 0.0,
                    f"risk_pct fuera de rango: {risk_pct}% (esperado: 0–10%)"
                )

            # ── Obtener symbol_info de MT5 si no se proporcionó ──────────────
            if symbol_info is None:
                symbol_info = self._get_symbol_info(symbol)
                if symbol_info is None:
                    return SizingResult(False, 0.0, f"No se pudo obtener symbol_info para {symbol}")

            # ── Extraer parámetros del símbolo ────────────────────────────────
            tick_size  = self._get_attr(symbol_info, "trade_tick_size",  0.0001)
            tick_value = self._get_attr(symbol_info, "trade_tick_value", 10.0)
            vol_min    = self._get_attr(symbol_info, "volume_min",        0.01)
            vol_max    = self._get_attr(symbol_info, "volume_max",        100.0)
            vol_step   = self._get_attr(symbol_info, "volume_step",       0.01)

            if tick_size <= 0:
                return SizingResult(False, 0.0, f"tick_size inválido para {symbol}: {tick_size}")
            if tick_value <= 0:
                return SizingResult(False, 0.0, f"tick_value inválido para {symbol}: {tick_value}")

            # ── Calcular riesgo en dinero ─────────────────────────────────────
            risk_amount = balance * (risk_pct / 100.0)

            # ── Calcular ticks de SL ──────────────────────────────────────────
            sl_ticks = sl_distance / tick_size

            # ── Valor en dinero por lote con este SL ─────────────────────────
            risk_per_lot = sl_ticks * tick_value

            if risk_per_lot <= 0:
                return SizingResult(
                    False, 0.0,
                    f"risk_per_lot inválido: sl_ticks={sl_ticks:.4f}, tick_value={tick_value}"
                )

            # ── Lote raw ──────────────────────────────────────────────────────
            raw_lot = risk_amount / risk_per_lot

            # ── Redondear al step más cercano (hacia abajo, nunca redondear arriba) ──
            if vol_step > 0:
                steps = floor(raw_lot / vol_step)
                lot = steps * vol_step
            else:
                lot = raw_lot

            # ── Aplicar límites del símbolo ───────────────────────────────────
            if lot < vol_min:
                # No redondear a cero — usar mínimo si el cálculo lo requiere
                lot = vol_min
                logger.debug(
                    "[PositionSizer] %s: raw_lot=%.4f < vol_min=%.4f → usando vol_min",
                    symbol, raw_lot, vol_min
                )
            elif lot > vol_max:
                lot = vol_max
                logger.debug(
                    "[PositionSizer] %s: raw_lot=%.4f > vol_max=%.4f → capping a vol_max",
                    symbol, raw_lot, vol_max
                )

            # ── Redondear a la precisión del step ────────────────────────────
            precision = self._decimal_places(vol_step)
            lot = round(lot, precision)

            # Riesgo % real con el lote ajustado
            actual_risk_amount = lot * risk_per_lot
            actual_risk_pct = (actual_risk_amount / balance) * 100.0

            logger.debug(
                "[PositionSizer] %s | balance=%.2f | risk_pct=%.2f%% | "
                "sl_dist=%.5f | sl_ticks=%.2f | tick_value=%.4f | "
                "risk_per_lot=%.4f | raw_lot=%.4f | final_lot=%.4f",
                symbol, balance, risk_pct,
                sl_distance, sl_ticks, tick_value,
                risk_per_lot, raw_lot, lot
            )

            return SizingResult(
                success=True,
                lot=lot,
                reason="Lote calculado correctamente",
                risk_amount=actual_risk_amount,
                risk_pct=actual_risk_pct,
                sl_ticks=sl_ticks,
                tick_value=tick_value,
                risk_per_lot=risk_per_lot,
                raw_lot=raw_lot,
                vol_min=vol_min,
                vol_max=vol_max,
                vol_step=vol_step,
            )

        except Exception as e:
            logger.exception("[PositionSizer] Error calculando tamaño de posición para %s: %s", symbol, e)
            return SizingResult(False, 0.0, f"Error interno: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # Utilidades
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _get_symbol_info(symbol: str) -> Optional[Any]:
        """Obtiene symbol_info de MT5 de forma segura."""
        try:
            import MetaTrader5 as mt5
            si = mt5.symbol_info(symbol)
            if si is None:
                logger.error("[PositionSizer] mt5.symbol_info(%s) devolvió None", symbol)
            return si
        except Exception as e:
            logger.error("[PositionSizer] Error obteniendo symbol_info(%s): %s", symbol, e)
            return None

    @staticmethod
    def _get_attr(obj: Any, attr: str, default: float) -> float:
        """Extrae un atributo de forma segura de object o dict."""
        try:
            if isinstance(obj, dict):
                return float(obj.get(attr, default))
            return float(getattr(obj, attr, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _decimal_places(step: float) -> int:
        """Calcula los decimales necesarios para un dado step."""
        s = f"{step:.10f}".rstrip("0")
        if "." in s:
            return len(s.split(".")[1])
        return 0
