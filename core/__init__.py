"""
Core Trading System — LastEdge Trading Engine

Core modules for execution engine, scoring, filtering, risk management, and trade journaling.
"""

from .engine import (
    TradingEngine, 
    SignalContext, 
    SignalResult,
    BotState,
    get_trading_engine,
    get_current_period_start,
    active_symbols,
    is_symbol_active,
    symbol_health,
    set_btceur_health,
    record_signal,
)

from .scoring import (
    FlexibleScoring,
    ConfirmationRule,
    ScoringResult,
    get_scoring_system
)

from .filters import (
    ConsolidatedFilters,
    FilterResult,
    get_filters_system
)

from .risk import (
    RiskEngine,
    RiskDecision,
    get_risk_engine,
    create_risk_engine,
    RiskConfig,
    load_risk_config,
    PositionSizer,
    MarginChecker,
    PortfolioRisk,
    RiskManager,
    RiskParameters,
    RiskAssessment,
    get_risk_manager,
    create_risk_manager,
)

from .journal import (
    TradeJournal,
    get_journal,
)

from .circuit_breaker import (
    CircuitBreaker,
    get_circuit_breaker,
)

from .trade_costs import (
    get_round_trip_cost_pips,
    apply_costs_to_profit,
)

# Aliases for compatibility
get_engine = get_trading_engine

# Instancias globales para compatibilidad
trading_engine = get_trading_engine()
scoring_system = get_scoring_system()
filters_system = get_filters_system()
risk_manager = get_risk_manager()
risk_engine = get_risk_engine()

__all__ = [
    'TradingEngine',
    'SignalContext', 
    'SignalResult',
    'BotState',
    'get_trading_engine',
    'get_engine',
    'trading_engine',
    'get_current_period_start',
    'active_symbols',
    'is_symbol_active',
    'symbol_health',
    'set_btceur_health',
    'record_signal',
    'FlexibleScoring',
    'ConfirmationRule',
    'ScoringResult',
    'get_scoring_system',
    'scoring_system',
    'ConsolidatedFilters',
    'FilterResult',
    'get_filters_system',
    'filters_system',
    'RiskEngine',
    'RiskDecision',
    'get_risk_engine',
    'create_risk_engine',
    'risk_engine',
    'RiskConfig',
    'load_risk_config',
    'PositionSizer',
    'MarginChecker',
    'PortfolioRisk',
    'RiskManager',
    'RiskParameters',
    'RiskAssessment',
    'get_risk_manager',
    'risk_manager',
    'create_risk_manager',
    'TradeJournal',
    'get_journal',
    'CircuitBreaker',
    'get_circuit_breaker',
    'get_round_trip_cost_pips',
    'apply_costs_to_profit',
]