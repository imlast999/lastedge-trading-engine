"""
Risk Engine — Configuración centralizada

Carga y valida los parámetros de risk_engine_config.json.
Proporciona acceso tipado a todos los parámetros de riesgo.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

_CONFIG_FILENAME = "risk_engine_config.json"
_RULES_FILENAME = "rules_config.json"

# Ruta base: directorio raíz del proyecto (un nivel arriba de core/risk/)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@dataclass
class RiskConfig:
    """
    Configuración completa del Risk Engine.
    Cargada desde rules_config.json.
    """

    # Riesgo por operación
    default_risk_pct: float = 0.5
    use_symbol_override: bool = True
    symbol_risk_overrides: dict = field(default_factory=dict)  # {symbol: pct}

    # Portfolio risk
    max_portfolio_risk_pct: float = 2.0
    portfolio_risk_enabled: bool = True

    # Protección de margen
    margin_protection_enabled: bool = True
    minimum_free_margin_pct: float = 20.0
    allow_auto_reduce_lot: bool = True
    lot_reduction_sequence: List[float] = field(
        default_factory=lambda: [1.0, 0.5, 0.25, 0.12, 0.08, 0.05, 0.03, 0.01]
    )

    # Límites de posiciones
    max_simultaneous_positions: int = 3
    max_positions_per_symbol: int = 1

    # Logging
    verbose_logging: bool = True
    log_approved: bool = True
    log_rejected: bool = True

    def get_risk_pct_for_symbol(self, symbol: str) -> float:
        """
        Devuelve el porcentaje de riesgo para un símbolo específico.
        """
        if self.use_symbol_override and symbol in self.symbol_risk_overrides:
            return self.symbol_risk_overrides[symbol]
        return self.default_risk_pct


def load_risk_config(rules_config_path: Optional[str] = None) -> RiskConfig:
    """
    Carga la configuración completa del Risk Engine desde rules_config.json.
    """
    if rules_config_path is None:
        rules_config_path = os.path.join(_PROJECT_ROOT, _RULES_FILENAME)

    rules = {}
    try:
        with open(rules_config_path, "r", encoding="utf-8") as f:
            rules = json.load(f)
    except FileNotFoundError:
        logger.warning("[RiskConfig] %s no encontrado, usando defaults", rules_config_path)
    except Exception as e:
        logger.error("[RiskConfig] Error cargando %s: %s", rules_config_path, e)

    # Extraer overrides por símbolo
    overrides = {}
    for symbol, cfg in rules.items():
        if symbol in ("GLOBAL_SETTINGS", "risk_engine"):
            continue
        if isinstance(cfg, dict) and "risk_per_trade" in cfg:
            overrides[symbol] = float(cfg["risk_per_trade"])

    # Extraer configuración del risk_engine de rules_config.json
    # Intentar leer desde rules_config.json['GLOBAL_SETTINGS']['risk_engine'] o rules_config.json['risk_engine']
    global_settings = rules.get("GLOBAL_SETTINGS", {})
    engine_cfg = global_settings.get("risk_engine", rules.get("risk_engine", {}))

    config = RiskConfig(
        default_risk_pct=float(global_settings.get("risk_per_trade", 0.5)),
        use_symbol_override=True,
        symbol_risk_overrides=overrides,
        max_portfolio_risk_pct=float(engine_cfg.get("max_portfolio_risk_pct", 2.0)),
        portfolio_risk_enabled=True,
        margin_protection_enabled=True,
        minimum_free_margin_pct=float(engine_cfg.get("minimum_free_margin_pct", 20.0)),
        allow_auto_reduce_lot=bool(engine_cfg.get("allow_auto_reduce_lot", True)),
        lot_reduction_sequence=engine_cfg.get(
            "lot_reduction_sequence", [1.0, 0.5, 0.25, 0.12, 0.08, 0.05, 0.03, 0.01]
        ),
        max_simultaneous_positions=int(engine_cfg.get("max_simultaneous_positions", 3)),
        max_positions_per_symbol=int(global_settings.get("max_positions_per_symbol", 1)),
        verbose_logging=True,
        log_approved=True,
        log_rejected=True,
    )

    logger.info(
        "[RiskConfig] Configuración unificada cargada | risk_default=%.2f%% | max_portfolio=%.2f%% "
        "| margin_min=%.1f%% | auto_reduce=%s | symbol_overrides=%s",
        config.default_risk_pct,
        config.max_portfolio_risk_pct,
        config.minimum_free_margin_pct,
        config.allow_auto_reduce_lot,
        list(config.symbol_risk_overrides.keys()),
    )

    return config
