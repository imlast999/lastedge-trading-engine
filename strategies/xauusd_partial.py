"""
XAUUSD Partial Close Strategy

Entrada: idéntica a XAUUSDStrategy (xauusd_simple).
Salida: gestión parcial + trailing, activada para producción tras validación
LastEdge Exit Research.
"""

from typing import Dict, Optional
import pandas as pd

from .xauusd import XAUUSDStrategy


class XAUUSDPartialStrategy(XAUUSDStrategy):
    """
    XAUUSD v1.1 — Partial Close.

    Promoted to production after LastEdge Exit Research validation.
    La lógica de entrada permanece idéntica a xauusd_simple.
    La diferencia es la gestión de salida mediante cierre parcial + trailing.
    """

    VARIANT = "partial_close"

    def __init__(self):
        super().__init__()
        self.strategy_name = "XAUUSD_Partial"

    def _get_default_config(self) -> Dict:
        cfg = super()._get_default_config()
        cfg.update({
            'partial_close_enabled': True,
            'partial_close_atr_mult': 2.0,
            'trailing_atr_mult': 1.5,
            'strategy_variant': self.VARIANT,
        })
        return cfg

    def detect_setup(self, df: pd.DataFrame, config: Dict = None) -> Optional[Dict]:
        signal = super().detect_setup(df, config)
        if signal is None:
            return None

        signal['context']['strategy'] = 'xauusd_partial'
        signal['context']['exit_variant'] = self.VARIANT
        return signal
