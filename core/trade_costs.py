"""
Trade Costs — core/trade_costs.py

Modela los costes reales de trading para una cuenta Professional de FXLiveCapital:
  - Spread (variable, usamos valores conservadores promedio)
  - Comisión por lote ($3 por lote completo para Forex y Spot Metals)

Los costes se expresan en PIPS para ser compatibles con el sistema de
profit_pips del replay engine.

Valores conservadores para cuenta Professional (average spread):
  EURUSD : spread 1.2 pips + comisión ~0.3 pips (0.1 lotes) = 1.5 pips round-trip
  XAUUSD : spread 35 cents + comisión ~0.3 pips (0.01 lotes) = ~3.8 pips round-trip
  BTCEUR : spread 25 EUR  + comisión ~0.3 pips (0.01 lotes) = ~25 pips round-trip

Nota: los costes se aplican como penalización al profit_pips de cada trade
(se restan del beneficio o se suman a la pérdida).
"""

from typing import Dict

# ── Spreads promedio en pips (valores conservadores para cuenta Professional) ─
# Fuente: FXLiveCapital Professional account, spread average
SPREAD_PIPS: Dict[str, float] = {
    'EURUSD': 1.2,    # 1.2 pips promedio (puede bajar a 0.5 en horas líquidas)
    'XAUUSD': 3.5,    # 35 cents / 0.1 $/pip = 3.5 pips
    'BTCEUR': 25.0,   # 25 EUR / 1 EUR/pip = 25 pips
}

# ── Comisión por lote completo (USD) ──────────────────────────────────────────
COMMISSION_PER_LOT_USD: Dict[str, float] = {
    'EURUSD': 3.0,   # $3 por lote completo (Forex)
    'XAUUSD': 3.0,   # $3 por lote completo (Spot Metals)
    'BTCEUR': 3.0,   # $3 por lote completo (Spot Commodities)
    'US30': 6.0,     # $6 por lote completo (Indexes)
}

# ── Tamaño de lote por defecto para el cálculo de comisión ───────────────────
# En paper trading no ejecutamos órdenes reales, así que usamos el lote
# mínimo típico para estimar el coste de comisión en pips.
DEFAULT_LOT_SIZE: Dict[str, float] = {
    'EURUSD': 0.10,   # 0.10 lotes = $1/pip → comisión $0.30 = 0.3 pips
    'XAUUSD': 0.01,   # 0.01 lotes = $0.01/pip → comisión $0.03 ≈ 0.3 pips
    'BTCEUR': 0.01,   # 0.01 lotes = €0.01/pip → comisión $0.03 ≈ 0.3 pips
}

# ── Valor de pip por lote (USD) ───────────────────────────────────────────────
PIP_VALUE_PER_LOT_USD: Dict[str, float] = {
    'EURUSD': 10.0,   # $10 por pip por lote completo
    'XAUUSD': 1.0,    # $1 por pip (0.1$/pip) por lote completo
    'BTCEUR': 1.0,    # €1 por pip por lote completo (aprox $1)
}


def get_round_trip_cost_pips(symbol: str, lot_size: float = None) -> float:
    """
    Devuelve el coste total de un trade de ida y vuelta (entrada + salida)
    expresado en pips.

    Incluye:
      - Spread (pagado en la entrada)
      - Comisión de entrada + salida (round-trip)

    Args:
        symbol:   Par de trading (EURUSD, XAUUSD, BTCEUR)
        lot_size: Tamaño del lote. Si None, usa DEFAULT_LOT_SIZE.

    Returns:
        Coste total en pips (siempre positivo — se resta del profit)
    """
    sym = symbol.upper()

    spread = SPREAD_PIPS.get(sym, 1.5)

    if lot_size is None:
        lot_size = DEFAULT_LOT_SIZE.get(sym, 0.10)

    commission_usd = COMMISSION_PER_LOT_USD.get(sym, 3.0) * lot_size * 2  # ×2 = round-trip
    pip_value      = PIP_VALUE_PER_LOT_USD.get(sym, 10.0) * lot_size

    commission_pips = commission_usd / pip_value if pip_value > 0 else 0.0

    return round(spread + commission_pips, 2)


def apply_costs_to_profit(profit_pips: float, symbol: str,
                          lot_size: float = None) -> float:
    """
    Aplica los costes de trading al profit_pips de una señal.

    Si el trade ganó, reduce el beneficio.
    Si el trade perdió, aumenta la pérdida.

    Args:
        profit_pips: Pips brutos del trade (positivo = ganancia, negativo = pérdida)
        symbol:      Par de trading
        lot_size:    Tamaño del lote (None = usar default)

    Returns:
        profit_pips neto después de costes
    """
    cost = get_round_trip_cost_pips(symbol, lot_size)
    # El coste siempre se resta (reduce ganancia o aumenta pérdida)
    if profit_pips >= 0:
        return profit_pips - cost
    else:
        return profit_pips - cost   # pérdida se hace más negativa


def get_cost_summary() -> str:
    """Devuelve un resumen legible de los costes configurados."""
    lines = ["Costes de trading (cuenta Professional FXLiveCapital):"]
    for sym in ('EURUSD', 'XAUUSD', 'BTCEUR'):
        cost = get_round_trip_cost_pips(sym)
        lot  = DEFAULT_LOT_SIZE[sym]
        lines.append(f"  {sym}: {cost:.1f} pips round-trip "
                     f"(spread {SPREAD_PIPS[sym]} + comisión {lot} lotes)")
    return "\n".join(lines)
