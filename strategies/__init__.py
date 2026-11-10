"""
Trading Strategies Module

Provides access to all trading strategies and strategy management functions.
Operates on an Open-Core architecture:
- Public benchmark strategies (strategies/public/) serve as open baseline models.
- Proprietary algorithms (strategies/vault/) are loaded dynamically when present.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, Optional
from .base import BaseStrategy

logger = logging.getLogger(__name__)

# ── 1. Import baseline benchmark strategies for open-core / self-hosted users ──
try:
    from .public.eurusd_public_trend import EURUSDPublicTrendStrategy
    from .public.xauusd_public_breakout import XAUUSDPublicBreakoutStrategy
    from .public.btceur_public_momentum import BTCEURPublicMomentumStrategy
    PUBLIC_BENCHMARKS_AVAILABLE = True
except ImportError as e:
    logger.warning("Public benchmark strategies not available: %s", e)
    EURUSDPublicTrendStrategy = None
    XAUUSDPublicBreakoutStrategy = None
    BTCEURPublicMomentumStrategy = None
    PUBLIC_BENCHMARKS_AVAILABLE = False

# ── 2. Initialize open-core baseline registry ──
STRATEGY_REGISTRY: Dict[str, Any] = {}

if EURUSDPublicTrendStrategy is not None:
    STRATEGY_REGISTRY['EURUSD'] = EURUSDPublicTrendStrategy
    STRATEGY_REGISTRY['EURUSD_LEGACY'] = EURUSDPublicTrendStrategy
    STRATEGY_REGISTRY['eurusd_public_trend'] = EURUSDPublicTrendStrategy

if XAUUSDPublicBreakoutStrategy is not None:
    STRATEGY_REGISTRY['XAUUSD'] = XAUUSDPublicBreakoutStrategy
    STRATEGY_REGISTRY['XAUUSD_LEGACY'] = XAUUSDPublicBreakoutStrategy
    STRATEGY_REGISTRY['xauusd_public_breakout'] = XAUUSDPublicBreakoutStrategy

if BTCEURPublicMomentumStrategy is not None:
    STRATEGY_REGISTRY['BTCEUR'] = BTCEURPublicMomentumStrategy
    STRATEGY_REGISTRY['btceur_public_momentum'] = BTCEURPublicMomentumStrategy

# ── 3. Dynamic ingestion of promoted packages and private vault strategies ──────
# If strategies/vault is present (Eugenio / authorized private deployment),
# proprietary algorithms are activated and override the public baseline with maximum priority.
try:
    from services.strategy_loader import (
        register_promoted_strategies,
        register_vault_strategies,
        register_public_strategies
    )
    register_promoted_strategies(STRATEGY_REGISTRY)
    register_public_strategies(STRATEGY_REGISTRY)
    vault_count = register_vault_strategies(STRATEGY_REGISTRY)
    if vault_count > 0:
        logger.info("[StrategyVault] %d proprietary strategies activated from private vault.", vault_count)
except Exception as _loader_err:
    logger.debug("StrategyLoader / Vault auto-discovery deferred/skipped: %s", _loader_err)

# ── 4. Backward-compatible class exports and canonical references ───────────────
EURUSDStrategy = STRATEGY_REGISTRY.get('EURUSD_LEGACY', STRATEGY_REGISTRY.get('EURUSD', EURUSDPublicTrendStrategy))
EURUSDPartialStrategy = STRATEGY_REGISTRY.get('eurusd_partial', STRATEGY_REGISTRY.get('EURUSD', EURUSDPublicTrendStrategy))
XAUUSDStrategy = STRATEGY_REGISTRY.get('XAUUSD_LEGACY', STRATEGY_REGISTRY.get('XAUUSD', XAUUSDPublicBreakoutStrategy))
XAUUSDPartialStrategy = STRATEGY_REGISTRY.get('xauusd_partial', STRATEGY_REGISTRY.get('XAUUSD', XAUUSDPublicBreakoutStrategy))
BTCEURStrategy = STRATEGY_REGISTRY.get('BTCEUR', BTCEURPublicMomentumStrategy)
BTCEURPartialStrategy = STRATEGY_REGISTRY.get('btceur_partial', STRATEGY_REGISTRY.get('BTCEUR', BTCEURPublicMomentumStrategy))

# Ensure STRATEGY_REGISTRY primary symbols point to active production classes
STRATEGY_REGISTRY['EURUSD'] = EURUSDPartialStrategy
STRATEGY_REGISTRY['XAUUSD'] = XAUUSDPartialStrategy
STRATEGY_REGISTRY['BTCEUR'] = BTCEURPartialStrategy
STRATEGY_REGISTRY['eurusd_partial'] = EURUSDPartialStrategy
STRATEGY_REGISTRY['xauusd_partial'] = XAUUSDPartialStrategy
STRATEGY_REGISTRY['btceur_partial'] = BTCEURPartialStrategy

BTCEUR_AVAILABLE = BTCEURPartialStrategy is not None


def get_strategy(symbol: str) -> Optional[BaseStrategy]:
    """
    Get strategy instance for a given symbol.
    
    Args:
        symbol: Trading symbol (e.g., 'EURUSD', 'XAUUSD', 'BTCEUR')
        
    Returns:
        Strategy instance or None if not found
    """
    symbol_upper = symbol.upper()
    symbol_lower = symbol.lower()
    strategy_class = (
        STRATEGY_REGISTRY.get(symbol_upper) or
        STRATEGY_REGISTRY.get(symbol_lower) or
        STRATEGY_REGISTRY.get(symbol)
    )

    if strategy_class:
        return strategy_class()

    # PROTECCIÓN BTCEUR: nunca hacer fallback silencioso a EURUSD
    if symbol_upper == 'BTCEUR':
        err_msg = "Estrategia no disponible (BTCEUR no registrado o import fallido)."
        logger.error("[CRITICAL][BTCEUR] %s", err_msg)
        try:
            from core import set_btceur_health
            set_btceur_health(status="ERROR", last_error=err_msg)
        except Exception:
            pass
        return None
    
    # Fallback a EURUSD solo para otros símbolos desconocidos
    if symbol_upper != 'EURUSD':
        logger.warning("Strategy for %s not found, using EURUSD fallback", symbol)
        eur_cls = STRATEGY_REGISTRY.get('EURUSD')
        if eur_cls:
            return eur_cls()
    
    return None


def get_available_symbols() -> list[str]:
    """Get list of symbols with available strategies"""
    return list(STRATEGY_REGISTRY.keys())


def register_strategy(symbol: str, strategy_class: Any) -> None:
    """Register a new strategy for a symbol"""
    STRATEGY_REGISTRY[symbol] = strategy_class
    STRATEGY_REGISTRY[symbol.upper()] = strategy_class
    STRATEGY_REGISTRY[symbol.lower()] = strategy_class


__all__ = [
    'BaseStrategy',
    'EURUSDStrategy',
    'EURUSDPartialStrategy',
    'XAUUSDStrategy',
    'XAUUSDPartialStrategy',
    'BTCEURStrategy',
    'BTCEURPartialStrategy',
    'get_strategy',
    'get_available_symbols',
    'register_strategy',
    'STRATEGY_REGISTRY',
    'BTCEUR_AVAILABLE'
]
