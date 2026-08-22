"""
Services Package — LastEdge Trading Engine

Consolidated services for logging, MT5 execution, database management, and operational audits.
"""

from .logging import (
    IntelligentLogger,
    get_intelligent_logger,
    log_event,
    log_signal_evaluation,
    log_command,
    log_trading
)

from .execution import (
    ExecutionService,
    ExecutionResult,
    PositionInfo,
    get_execution_service
)

from .autosignals import (
    create_autosignals_service
)

from .database import (
    DatabaseManager,
    get_database_manager,
    get_database_service,
    init_db,
    load_db_state,
    save_autosignals_state,
    save_last_auto_sent,
    save_trades_today,
    reset_trades_today
)

from .mobile_store import get_mobile_store
from .api_server import TradingAPIServer, get_trading_api_server, start_trading_api_server

# Instancias globales para compatibilidad
intelligent_logger = get_intelligent_logger()
execution_service = get_execution_service()

__all__ = [
    'IntelligentLogger',
    'get_intelligent_logger',
    'intelligent_logger',
    'log_event',
    'log_signal_evaluation',
    'log_command',
    'log_trading',
    'ExecutionService',
    'ExecutionResult',
    'PositionInfo',
    'get_execution_service',
    'execution_service',
    'create_autosignals_service',
    'DatabaseManager',
    'get_database_manager',
    'get_database_service',
    'init_db',
    'load_db_state',
    'save_autosignals_state',
    'save_last_auto_sent',
    'save_trades_today',
    'reset_trades_today',
    'get_mobile_store',
    'TradingAPIServer',
    'get_trading_api_server',
    'start_trading_api_server',
]