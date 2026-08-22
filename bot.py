import os
import logging
import signal
import sys

# Add signal handler for graceful shutdown
def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully"""
    print("\n🛑 Señal de interrupción recibida. Cerrando bot...")
    sys.exit(0)

# Register signal handler
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Parche para compatibilidad con Python 3.13
import audioop_patch

# Configurar matplotlib para evitar problemas de threading
import matplotlib
matplotlib.use('Agg')  # Usar backend sin GUI

import discord
import asyncio
import sqlite3
import json
from discord.ext import commands
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from math import floor
from typing import Optional

# Configurar logging ANTES de los imports opcionales
logging.basicConfig(
    level=logging.WARNING,  # Cambiar a WARNING para reducir ruido
    format='{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","message":"%(message)s"}'
)
logger = logging.getLogger(__name__)

# ============================================================================
# IMPORTS CONSOLIDADOS - NUEVA ARQUITECTURA
# ============================================================================

# Core system (consolidado)
from core import (
    trading_engine, 
    get_current_period_start, 
    BotState,
    get_risk_manager,
    get_filters_system,
    active_symbols,
    is_symbol_active,
    symbol_health,
    set_btceur_health,
)

# Services (consolidado)
from services import (
    log_event, 
    log_signal_evaluation, 
    log_command,
    execution_service,
    dashboard_service,
    start_enhanced_dashboard,
    stop_enhanced_dashboard,
    add_signal_to_enhanced_dashboard,
    update_dashboard_stats
)

# Import intelligent logger to access current_log_file
from services.logging import get_intelligent_logger

# Signals dispatcher
from services.signals import _detect_signal_wrapper, detect_signal, detect_signal_advanced

# Módulos específicos desde services/
from services.mt5_client import initialize as mt5_initialize, get_candles, shutdown as mt5_shutdown, login as mt5_login, place_order
from services.charts import generate_chart
from secrets_store import save_credentials, load_credentials, clear_credentials
from services.backtest_tracker import backtest_tracker
import MetaTrader5 as mt5
from services.position_manager import list_positions, close_position

# ============================================================================
# SISTEMAS OPCIONALES (desde services/)
# ============================================================================

# Importar sistema de apertura de mercados
try:
    from services.market_opening_system import create_market_opening_system
    market_opening_system = create_market_opening_system()
    MARKET_OPENING_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Sistema de apertura de mercados no disponible: {e}")
    market_opening_system = None
    MARKET_OPENING_AVAILABLE = False

# Importar sistema de trailing stops
try:
    from services.trailing_stops import get_trailing_manager
    trailing_manager = get_trailing_manager()
    TRAILING_STOPS_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Sistema de trailing stops no disponible: {e}")
    trailing_manager = None
    TRAILING_STOPS_AVAILABLE = False

# Importar sistema de reconexión
try:
    from services.reconnection_system import reconnection_system
    RECONNECTION_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Sistema de reconexión no disponible: {e}")
    reconnection_system = None
    RECONNECTION_AVAILABLE = False

# Importar sistema de resumen de sesión
try:
    from services.session_summary import session_summary
    SESSION_SUMMARY_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Sistema de resumen de sesión no disponible: {e}")
    session_summary = None
    SESSION_SUMMARY_AVAILABLE = False

# ======================
# CONFIGURACIÓN
# ======================

AUTHORIZED_USER_ID = int(os.getenv('AUTHORIZED_USER_ID', '739198540177473667'))
SIGNALS_CHANNEL_NAME = "signals"         # configurable
TIMEFRAME = mt5.TIMEFRAME_H1
SYMBOL = "EURUSD"
CANDLES = 100

# safety / limits
MAX_TRADES_PER_DAY = int(os.getenv('MAX_TRADES_PER_DAY', '3'))
MAX_TRADES_PER_PERIOD = int(os.getenv('MAX_TRADES_PER_PERIOD', '5'))  # 5 trades cada 12 horas
KILL_SWITCH = os.getenv('KILL_SWITCH', '0') == '1'

# auto-execution settings
AUTO_EXECUTE_SIGNALS = os.getenv('AUTO_EXECUTE_SIGNALS', '0') == '1'
AUTO_EXECUTE_CONFIDENCE = os.getenv('AUTO_EXECUTE_CONFIDENCE', 'HIGH')  # FIXED: HIGH instead of LOW

# ============================================================================
# ESTADO GLOBAL CONSOLIDADO
# ============================================================================

# Usar BotState consolidado del core
state = BotState()

# Configurar loggers específicos
mt5_logger = logging.getLogger('mt5_client')
mt5_logger.setLevel(logging.ERROR)  # Solo errores de MT5

signals_logger = logging.getLogger('signals')
signals_logger.setLevel(logging.INFO)  # Mantener info de señales


def validate_btceur_strategy() -> bool:
    """
    Valida en el arranque que BTCEUR use su estrategia específica.
    En caso de problema, desactiva BTCEUR en active_symbols y deja
    trazas claras en los logs.
    """
    try:
        from strategies import get_strategy  # import local para evitar ciclos
        strat = get_strategy("BTCEUR")
    except Exception as e:
        err_msg = f"Error obteniendo estrategia BTCEUR: {e}"
        log_event(f"[CRITICAL][BTCEUR] {err_msg}", "ERROR")
        set_btceur_health(status="ERROR", last_error=err_msg)
        active_symbols["BTCEUR"] = False
        return False

    if strat is None:
        err_msg = "Estrategia BTCEUR no disponible (get_strategy devolvió None)."
        log_event(f"[CRITICAL][BTCEUR] {err_msg}", "ERROR")
        set_btceur_health(status="ERROR", last_error=err_msg)
        active_symbols["BTCEUR"] = False
        return False

    valid_btceur_classes = ('BTCEURStrategy', 'BTCEURPartialStrategy', 'BTCTrendPullbackV1Strategy', 'BTCEURWeeklyBreakoutStrategy', 'BTCEURRegimeMomentumStrategy')
    # eurusd_asian_breakout descartada junio 2026 (PF<1.0 en 10k/15k/20k velas)
    # EURUSD ahora usa eurusd_simple con SL=1.5x ATR, TP=6.0x ATR, CB=3/72
    # btceur_regime_momentum desactivada: requiere H4+Daily, replay_engine usa H1
    if strat.__class__.__name__ not in valid_btceur_classes:
        err_msg = f"Estrategia incorrecta: {strat.__class__.__name__} (válidas: {valid_btceur_classes})."
        log_event(f"[CRITICAL][BTCEUR] {err_msg}", "ERROR")
        set_btceur_health(status="ERROR", last_error=err_msg)
        active_symbols["BTCEUR"] = False
        return False

    set_btceur_health(status="OK", last_error=None)
    return True

# ======================
# FUNCIONES DE PERÍODO (12 HORAS)
# ======================

# get_current_period_start ya está importado desde core

def is_new_period() -> bool:
    """Verifica si estamos en un nuevo período de 12 horas"""
    current_period_start = get_current_period_start()
    return current_period_start > state.current_period_start

def reset_period_if_needed():
    """Resetea el contador de trades si estamos en un nuevo período"""
    if is_new_period():
        old_count = state.trades_current_period
        state.trades_current_period = 0
        state.current_period_start = get_current_period_start()
        
        period_name = "00:00-12:00" if state.current_period_start.hour == 0 else "12:00-24:00"
        log_event(f"🔄 NUEVO PERÍODO: {period_name} UTC | Trades resetados: {old_count} → 0", "INFO", "PERIOD")

def get_period_status() -> dict:
    """Obtiene el estado actual del período"""
    reset_period_if_needed()  # Verificar si necesitamos resetear
    
    period_name = "00:00-12:00" if state.current_period_start.hour == 0 else "12:00-24:00"
    next_reset = state.current_period_start + timedelta(hours=12)
    time_until_reset = next_reset - datetime.now(timezone.utc)
    
    return {
        'current_period': period_name,
        'trades_current_period': state.trades_current_period,
        'max_trades_per_period': MAX_TRADES_PER_PERIOD,
        'trades_remaining': max(0, MAX_TRADES_PER_PERIOD - state.trades_current_period),
        'next_reset': next_reset,
        'time_until_reset': time_until_reset,
        'period_full': state.trades_current_period >= MAX_TRADES_PER_PERIOD
    }


# ======================
# DECORADOR PARA LOGGING DE COMANDOS
# ======================

def log_discord_command(func):
    """Decorador para loggear automáticamente comandos Discord"""
    import functools
    
    @functools.wraps(func)
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        # Obtener nombre del comando
        command_name = func.__name__.replace('slash_', '')
        
        # Construir argumentos para el log
        args_str = ' '.join(str(arg) for arg in args if arg)
        kwargs_str = ' '.join(f"{k}={v}" for k, v in kwargs.items() if v)
        full_args = f"{args_str} {kwargs_str}".strip()
        
        # Log inicial del comando
        log_event(f"🎮 COMMAND: /{command_name} {full_args} | User: {interaction.user.id} ({interaction.user.display_name})")
        
        try:
            # Ejecutar el comando original
            result = await func(interaction, *args, **kwargs)
            
            # Log de éxito (solo si no hubo excepción)
            log_event(f"✅ COMMAND SUCCESS: /{command_name} {full_args}")
            return result
            
        except Exception as e:
            # Log de error
            log_event(f"❌ COMMAND ERROR: /{command_name} {full_args} | Error: {e}")
            
            # Re-lanzar la excepción para que Discord la maneje
            raise
    
    return wrapper


# ======================
# LOGGING SYSTEM
# ======================
# get_intelligent_logger ya importado arriba
bot_logger = get_intelligent_logger()

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
# Use slash commands to avoid the Message Content privileged intent
intents.message_content = False
bot = commands.Bot(command_prefix="/", intents=intents)

# Optional: fast command registration to a test guild to avoid global sync delay
GUILD_ID = os.getenv('GUILD_ID')

# Global variables for session tracking
bot_start_time = None

AUTOSIGNAL_INTERVAL = int(os.getenv('AUTOSIGNAL_INTERVAL', '20'))  # seconds between scans
AUTOSIGNAL_SYMBOLS = [s.strip().upper() for s in os.getenv('AUTOSIGNAL_SYMBOLS', SYMBOL).split(',') if s.strip()]
# AUTOSIGNAL_TOLERANCE_PIPS used to detect duplicates
AUTOSIGNAL_TOLERANCE_PIPS = float(os.getenv('AUTOSIGNAL_TOLERANCE_PIPS', '1.0'))
DB_PATH = os.path.join(os.path.dirname(__file__), 'bot_state.db')
# default strategy name (can be overridden via .env)
DEFAULT_STRATEGY = os.getenv('DEFAULT_STRATEGY', 'ema50_200')
# default autosignal symbols: EURUSD and XAUUSD; BTCEUR can be added via env
if not AUTOSIGNAL_SYMBOLS or AUTOSIGNAL_SYMBOLS == ['']:
    AUTOSIGNAL_SYMBOLS = ['EURUSD', 'XAUUSD']  # Removed BTCEUR due to strategy issues

# parse per-symbol rules from env, format: EURUSD:ema,XAUUSD:macd
_rules_raw = os.getenv('AUTOSIGNAL_RULES', '')
AUTOSIGNAL_RULES = {}
if _rules_raw:
    for part in _rules_raw.split(','):
        if ':' in part:
            s, r = part.split(':', 1)
            AUTOSIGNAL_RULES[s.strip().upper()] = r.strip().lower()

# Optional per-symbol strategy config file (JSON). Keys should be symbol uppercased.
RULES_CONFIG_PATH = os.getenv('RULES_CONFIG_PATH', os.path.join(os.path.dirname(__file__), 'rules_config.json'))
RULES_CONFIG = {}
try:
    if os.path.exists(RULES_CONFIG_PATH):
        with open(RULES_CONFIG_PATH, 'r', encoding='utf-8') as f:
            rc = json.load(f)
            # normalize keys to upper
            for k, v in rc.items():
                try:
                    RULES_CONFIG[k.strip().upper()] = dict(v or {})
                except Exception:
                    RULES_CONFIG[k.strip().upper()] = {}
except Exception:
    logger.exception('Failed to load rules config from %s', RULES_CONFIG_PATH)

# Inicializar gestores después de cargar configuración
risk_manager = None
advanced_filter = None

def init_risk_managers():
    """Inicializa los gestores de riesgo después de cargar la configuración"""
    global risk_manager, advanced_filter
    try:
        from core import get_risk_manager, get_filters_system
        risk_manager = get_risk_manager()
        advanced_filter = get_filters_system()
        # Unificar contadores: ConsolidatedFilters leerá/escribirá desde BotState
        advanced_filter.set_bot_state(state)
        logger.info("Gestores de riesgo inicializados correctamente")
    except Exception as e:
        logger.error(f"Error inicializando gestores de riesgo: {e}")
        # Crear gestores dummy para evitar errores
        risk_manager = None
        advanced_filter = None


# Funciones de base de datos ahora están en services/database.py
# Importar funciones de compatibilidad
from services import (
    init_db, load_db_state, save_autosignals_state, 
    save_last_auto_sent, save_trades_today, reset_trades_today
)

# Funciones get_symbol_tolerance y signals_similar ahora están en core/filters.py

# ======================
# UTILIDADES MT5
# ======================

def connect_mt5():
    try:
        return mt5_initialize()
    except Exception as e:
        logger.exception("MT5 connection failed")
        raise

# ======================
# GRÁFICOS
# ======================

# Use `generate_chart` imported from `charts` module above.

# ======================
# LÓGICA DE SEÑALES (EJEMPLO)
# ======================

# _detect_signal_wrapper ya está importado desde signals.py - función eliminada para evitar duplicación
def compute_suggested_lot(signal, risk_pct: float = None):
    """Compute a suggested lot size given a signal dict.

    Uses MT5 account balance and symbol info. This is an approximation and
    should be reviewed by the user before executing.
    Returns (lot, risk_amount, rr_ratio) or (None, None, None) on failure.
    """
    try:
        mt5_initialize()
    except Exception as e:
        logger.error(f"MT5 initialization failed in compute_suggested_lot: {e}")
        return None, None, None

    try:
        acc = mt5.account_info()
        if acc is None:
            logger.error("No account info available in compute_suggested_lot")
            return None, None, None
        
        balance = float(acc.balance)
        
        # Ensure symbol is a string
        symbol = signal.get('symbol')
        if hasattr(symbol, 'iloc'):  # Es una Serie de pandas
            symbol = str(symbol.iloc[0]) if len(symbol) > 0 else 'EURUSD'
        elif not isinstance(symbol, str):
            symbol = str(symbol)
        
        logger.debug(f"Computing lot for symbol: {symbol}")
        
        si = mt5.symbol_info(symbol)
        if si is None:
            logger.error(f"No symbol info for {symbol} in compute_suggested_lot")
            return None, None, None

        # default risk percent from env if not provided
        if risk_pct is None:
            try:
                risk_pct = float(os.getenv('MT5_RISK_PCT', '0.5'))
            except Exception:
                risk_pct = 0.5

        risk_amount = balance * (risk_pct / 100.0)

        entry = float(signal['entry'])
        sl = float(signal['sl'])
        
        # point value and contract size
        point = si.point
        contract = getattr(si, 'trade_contract_size', getattr(si, 'lot_size', 100000))

        # compute SL in pips (in points)
        sl_points = abs(entry - sl) / point if point and point != 0 else None
        if not sl_points or sl_points <= 0:
            logger.error(f"Invalid SL points calculation: {sl_points}")
            return None, None, None

        # approximate pip value per lot in account currency
        pip_value_per_lot = contract * point
        # risk per lot = sl_points * pip_value_per_lot
        risk_per_lot = sl_points * pip_value_per_lot
        if risk_per_lot <= 0:
            logger.error(f"Invalid risk per lot calculation: {risk_per_lot}")
            return None, None, None

        raw_lot = risk_amount / risk_per_lot

        # clamp to symbol min/max and step
        vol_min = getattr(si, 'volume_min', 0.01)
        vol_max = getattr(si, 'volume_max', 100.0)
        vol_step = getattr(si, 'volume_step', 0.01)

        # round down to nearest step
        steps = floor(raw_lot / vol_step)
        lot = max(vol_min, min(vol_max, steps * vol_step)) if steps > 0 else vol_min

        # risk/reward ratio approx
        tp = float(signal.get('tp', entry))
        rr = abs((tp - entry) / (entry - sl)) if (entry - sl) != 0 else None

        logger.debug(f"Computed lot: {lot}, risk_amount: {risk_amount}, rr: {rr}")
        return lot, risk_amount, rr
        
    except Exception as e:
        logger.error(f"Error in compute_suggested_lot: {e}")
        return None, None, None

# Load persisted credentials if available
loaded = load_credentials()
if loaded:
    state.mt5_credentials.update(loaded)

# ======================
# BOT EVENTS
# ======================

@bot.event
async def on_ready():
    global bot_start_time
    bot_start_time = datetime.now(timezone.utc)

    # ── Limpiar estado de sesiones anteriores ─────────────────────────────────
    # Cada reinicio del bot es una sesión nueva y limpia.
    # Se borran: circuit breaker (pausa activa), cooldowns de autosignals.
    _session_state_files = [
        os.path.join(os.path.dirname(__file__), 'circuit_breaker_state.json'),
        os.path.join(os.path.dirname(__file__), 'autosignals_state.json'),
    ]
    for _f in _session_state_files:
        try:
            if os.path.exists(_f):
                os.remove(_f)
                logger.info(f"Estado de sesión anterior eliminado: {os.path.basename(_f)}")
        except Exception as _e:
            logger.warning(f"No se pudo eliminar {_f}: {_e}")

    log_event(f"Conectado como {bot.user}")

    # Inicializar gestores de riesgo
    init_risk_managers()
    log_event("Gestores de riesgo inicializados correctamente")

    # ── Comprobar e Informar Conexión MT5 en la Terminal ──────────────────────
    try:
        def _init_and_check_mt5():
            if mt5_initialize():
                import MetaTrader5 as mt5
                return mt5.account_info()
            return None

        acc_info = await asyncio.to_thread(_init_and_check_mt5)
        if acc_info:
            log_event(
                f"📈 MetaTrader 5: CONECTADO | Cuenta #{acc_info.login} ({acc_info.name}) | "
                f"Servidor: {acc_info.server} | Balance: ${acc_info.balance:.2f} {acc_info.currency}"
            )
        else:
            log_event("⚠️ MetaTrader 5: No se pudo conectar al servidor del broker en el arranque", "WARNING")
    except Exception as _mt5_err:
        log_event(f"❌ MetaTrader 5: Error comprobando conexión ({_mt5_err})", "ERROR")

    # Validar configuración de BTCEUR (fail-safe)
    try:
        if not validate_btceur_strategy():
            log_event("[BTCEUR FIX] BTCEUR desactivado automáticamente por configuración inválida.", "ERROR")
    except Exception as e:
        logger.error(f"Error validando estrategia BTCEUR: {e}")
    
    # Sync application commands (slash commands). If GUILD_ID is set, sync only to that guild for fast registration.
    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=int(GUILD_ID))
            # Sincronizar primero solo al guild (definición actual = única fuente de verdad)
            await bot.tree.sync(guild=guild_obj)
            log_event(f"Comandos sincronizados al servidor {GUILD_ID}")
            # Sincronizar también a global para que no quede versión antigua de comandos (ej. /autosignals con "enabled")
            await bot.tree.sync()
            log_event("Comandos sincronizados globalmente (evitar sugerencias antiguas)")
        else:
            await bot.tree.sync()
            log_event("Comandos sincronizados globalmente")
    except Exception:
        log_event("Error sincronizando comandos slash", "ERROR")
        logger.exception("Failed to sync slash commands")
    
    # load persisted autosignals state and last sent info
    try:
        load_db_state(state)
        log_event(f'Estado cargado: AUTOSIGNALS={state.autosignals}')
    except Exception:
        log_event("Error cargando estado de la base de datos", "ERROR")
        logger.exception('Failed to load DB state')
    
    # start autosignal background task using services
    try:
        from services.autosignals import create_autosignals_service
        autosignals_service = create_autosignals_service(bot, state, {
            'AUTOSIGNAL_SYMBOLS': AUTOSIGNAL_SYMBOLS,
            'AUTOSIGNAL_INTERVAL': AUTOSIGNAL_INTERVAL,
            'SIGNALS_CHANNEL_NAME': SIGNALS_CHANNEL_NAME,
            'MAX_TRADES_PER_DAY': MAX_TRADES_PER_DAY,
            'MAX_TRADES_PER_PERIOD': MAX_TRADES_PER_PERIOD,
            'KILL_SWITCH': KILL_SWITCH,
            'AUTO_EXECUTE_SIGNALS': AUTO_EXECUTE_SIGNALS
        })
        bot.loop.create_task(autosignals_service.start_auto_signal_loop())
        log_event("Servicio de autosignals iniciado")
    except Exception as e:
        log_event(f"Error iniciando servicio de autosignals: {e}", "ERROR")
        logger.exception("Failed to start autosignals service")
    
    # start trailing stops background task
    if TRAILING_STOPS_AVAILABLE:
        bot.loop.create_task(_trailing_stops_loop_simple())
        log_event("Sistema de trailing stops iniciado")
    
    # start market opening alerts background task
    if MARKET_OPENING_AVAILABLE:
        bot.loop.create_task(_market_opening_loop_simple())
        log_event("Sistema de alertas de apertura iniciado")
    
    # start enhanced dashboard
    try:
        start_enhanced_dashboard()
        log_event("Dashboard inteligente iniciado - Sistema de confianza integrado")
    except Exception as e:
        log_event(f"Error iniciando sistema de reconexión: {e}", "ERROR")
        logger.exception("Failed to start reconnection system")

    # Iniciar adaptador de Telegram (P2.5 & P2.6) de forma simultánea
    try:
        from services.telegram_adapter import TelegramAdapter
        telegram_adapter = TelegramAdapter()
        if telegram_adapter.is_configured():
            bot.loop.create_task(telegram_adapter.start_polling())
            log_event("Servicio de Telegram iniciado simultáneamente")
        else:
            log_event("Telegram no configurado (TELEGRAM_BOT_TOKEN no presente en .env)")
    except Exception as e:
        log_event(f"Error iniciando servicio de Telegram: {e}", "ERROR")

    # Registrar despachador de notificaciones simultáneas
    try:
        from services.notification_dispatcher import get_notification_dispatcher
        dispatcher = get_notification_dispatcher()
        async def _discord_broadcast(msg_text):
            for guild in bot.guilds:
                channel = discord.utils.get(guild.text_channels, name=SIGNALS_CHANNEL_NAME)
                if channel:
                    await channel.send(msg_text)
        dispatcher.register_discord_handler(_discord_broadcast)
        log_event("Despachador de notificaciones simultáneas (Discord + Telegram) registrado")
    except Exception as e:
        logger.error(f"Error registrando handler de notificaciones: {e}")
    
    # start terminal 10-min pulse verification task
    bot.loop.create_task(_terminal_pulse_loop())
    log_event("Terminal pulse loop iniciado (verificación cada 10 min: 'Escaneando...')")

    # start reconnection system — lightweight watchdog que no bloquea el event loop
    if RECONNECTION_AVAILABLE:
        bot.loop.create_task(_mt5_watchdog_loop())
        log_event("Sistema de reconexión MT5 iniciado (watchdog ligero)")

    # start weekly summary background task
    bot.loop.create_task(_weekly_summary_loop())
    log_event("Weekly summary loop iniciado (lunes 08:00 UTC)")

    # start session summary background task
    if SESSION_SUMMARY_AVAILABLE:
        bot.loop.create_task(_session_summary_loop())
        log_event("Session summary loop iniciado (cierre London 17h, NY 22h UTC)")
    
    # start backtest queue background task
    bot.loop.create_task(_backtest_queue_loop())
    log_event("Backtest queue loop iniciado (polling cada 5s)")
    
    # Print helpful invite URL for adding the bot with application commands scope
    try:
        app_id = bot.application_id or bot.user.id
        invite_url = f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot%20applications.commands&permissions=8"
        logger.info(f"Invite URL: {invite_url}")
        log_event("URL de invitación generada correctamente")
    except Exception:
        log_event("Error generando URL de invitación", "WARNING")
        logger.debug("Could not build invite URL")
    
    # Log configuración importante
    log_event(f"AUTO_EXECUTE_SIGNALS: {AUTO_EXECUTE_SIGNALS}")
    log_event(f"AUTO_EXECUTE_CONFIDENCE: {AUTO_EXECUTE_CONFIDENCE}")
    log_event(f"AUTOSIGNAL_INTERVAL: {AUTOSIGNAL_INTERVAL} segundos")
    log_event(f"Símbolos monitoreados: {AUTOSIGNAL_SYMBOLS}")
    
    # Log estado de módulos opcionales
    if TRAILING_STOPS_AVAILABLE:
        log_event("Módulo trailing stops: DISPONIBLE")
    else:
        log_event("Módulo trailing stops: NO DISPONIBLE", "WARNING")
    
    if MARKET_OPENING_AVAILABLE:
        log_event("Módulo market opening: DISPONIBLE")
    else:
        log_event("Módulo market opening: NO DISPONIBLE", "WARNING")
    
    if RECONNECTION_AVAILABLE:
        log_event("Módulo reconexión: DISPONIBLE")
    else:
        log_event("Módulo reconexión: NO DISPONIBLE", "WARNING")
    
    if SESSION_SUMMARY_AVAILABLE:
        log_event("Módulo resumen de sesión: DISPONIBLE")
    else:
        log_event("Módulo resumen de sesión: NO DISPONIBLE", "WARNING")
    
    log_event("Bot completamente inicializado y listo para operar")
    
    # Mostrar información del archivo de log
    intelligent_logger = get_intelligent_logger()
    current_log_file = intelligent_logger.current_log_file
    if current_log_file:
        log_filename = os.path.basename(current_log_file)
        log_event(f"📝 Archivo de log: {log_filename}")
        log_event(f"📁 Ruta completa: {current_log_file}")


# Simplified background loops for compatibility
async def _trailing_stops_loop_simple():
    """Simplified trailing stops loop"""
    await bot.wait_until_ready()
    logger.info('Trailing stops loop started')
    
    while True:
        try:
            if TRAILING_STOPS_AVAILABLE and trailing_manager:
                trailing_manager.update_all_trailing_stops()
            await asyncio.sleep(30)
        except Exception:
            logger.exception('Trailing stops loop crashed; retrying in 60s')
            await asyncio.sleep(60)


async def _market_opening_loop_simple():
    """
    Loop de alertas de apertura de mercado.
    Verifica cada 5 minutos si hay una apertura próxima y envía alertas
    al canal de signals en tres momentos: 30 min antes, 15 min antes,
    y 15 min después de abrir.
    """
    await bot.wait_until_ready()
    log_event("Sistema de alertas de apertura de mercado iniciado (verificación cada 5 min)")

    # Rastrear qué alertas ya se enviaron para no repetirlas
    # Clave: "{market}_{alert_type}_{fecha_hora_apertura_redondeada}"
    _sent_alerts: set = set()

    while True:
        try:
            await asyncio.sleep(300)  # verificar cada 5 minutos

            if not MARKET_OPENING_AVAILABLE or not market_opening_system:
                continue

            # Obtener próxima apertura en un thread separado (llama a MT5)
            def _get_opening():
                return market_opening_system.get_next_market_opening()

            market_name, opening_time, minutes_until = await asyncio.to_thread(_get_opening)

            if market_name is None or minutes_until is None:
                continue

            # ¿Hay que enviar alerta ahora?
            should_alert, alert_type = market_opening_system.should_send_alert(
                market_name, minutes_until
            )

            if not should_alert or alert_type is None:
                continue

            # Clave de deduplicación: misma alerta no se envía dos veces
            # Usamos la hora de apertura redondeada al minuto más cercano
            opening_key = opening_time.strftime('%Y%m%d%H%M') if opening_time else 'UNK'
            alert_key = f"{market_name}_{alert_type}_{opening_key}"

            if alert_key in _sent_alerts:
                continue  # ya enviada, saltar

            # Generar análisis pre-mercado para los pares activos de esta sesión
            session_info = market_opening_system.market_sessions.get(market_name, {})
            main_pairs = session_info.get('main_pairs', [])

            # Filtrar solo pares que tenemos activos en el bot
            active_pairs = [p for p in main_pairs if active_symbols.get(p, False)]

            def _generate_strategies():
                strategies = []
                for pair in active_pairs:
                    try:
                        result = market_opening_system.generate_opening_strategy(pair, market_name)
                        strategies.append(result)
                    except Exception as e:
                        logger.warning(f"Error generando estrategia de apertura para {pair}: {e}")
                return strategies

            strategies = await asyncio.to_thread(_generate_strategies)

            # Formatear y enviar mensaje
            message = market_opening_system.format_opening_alert(
                market_name, alert_type, strategies
            )

            channel = await _find_signals_channel()
            if channel:
                # Discord limita mensajes a 2000 chars; truncar si hace falta
                if len(message) > 1950:
                    message = message[:1950] + "\n…*(mensaje truncado)*"
                await channel.send(message)
                log_event(
                    f"📢 Alerta de apertura enviada: {market_name} | {alert_type} | "
                    f"{minutes_until:+d} min | pares: {active_pairs}"
                )
            else:
                logger.warning(
                    f"Market opening: no se encontró el canal '{SIGNALS_CHANNEL_NAME}'"
                )

            # Registrar como enviada para no repetir
            _sent_alerts.add(alert_key)

            # Limpiar alertas antiguas (más de 24h) para no acumular indefinidamente
            if len(_sent_alerts) > 100:
                _sent_alerts.clear()

        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception('Market opening loop crashed; retrying in 10 minutes')
            await asyncio.sleep(600)



async def _mt5_watchdog_loop():
    """
    Watchdog ligero para MT5: verifica la conexión cada 60s y reconecta
    si es necesario, sin bloquear el event loop de Discord.
    """
    await bot.wait_until_ready()
    log_event("MT5 watchdog iniciado (verificación cada 60s)")

    _consecutive_failures = 0

    while True:
        try:
            await asyncio.sleep(60)

            # Verificar conexión MT5 en un thread separado para no bloquear
            def _check_mt5():
                try:
                    import MetaTrader5 as mt5
                    info = mt5.terminal_info()
                    if info is not None and info.connected and mt5.account_info() is not None:
                        return True
                    from services.mt5_client import initialize as mt5_init
                    if mt5_init():
                        info = mt5.terminal_info()
                        return info is not None and info.connected and mt5.account_info() is not None
                    return False
                except Exception:
                    return False

            is_connected = await asyncio.to_thread(_check_mt5)

            if not is_connected:
                _consecutive_failures += 1
                log_event(
                    f"⚠️ MT5 desconectado (intento {_consecutive_failures}). Reconectando...",
                    "WARNING"
                )

                def _reconnect():
                    try:
                        from services.mt5_client import initialize as mt5_init
                        return mt5_init()
                    except Exception as e:
                        logger.error(f"MT5 reconnect error: {e}")
                        return False

                success = await asyncio.to_thread(_reconnect)

                if success:
                    _consecutive_failures = 0
                    log_event("✅ MT5 reconectado exitosamente")
                elif _consecutive_failures >= 5:
                    log_event(
                        "❌ MT5: 5 fallos de reconexión consecutivos. "
                        "Verifica que MT5 esté abierto.",
                        "ERROR"
                    )
                    # Send Discord notification to signals channel
                    try:
                        channel = await _find_signals_channel()
                        if channel:
                            await channel.send(
                                "🔴 **ALERTA MT5**: El bot ha fallado **5 veces consecutivas** al "
                                "intentar reconectarse a MetaTrader 5.\n"
                                "Las señales automáticas pueden estar interrumpidas. "
                                "Por favor verifica que MT5 esté abierto y conectado."
                            )
                    except Exception as notify_err:
                        logger.error(f"MT5 watchdog Discord notification error: {notify_err}")
                    _consecutive_failures = 0  # reset para no spamear
            else:
                _consecutive_failures = 0  # conexión ok

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"MT5 watchdog error: {e}")
            await asyncio.sleep(60)

# ======================
# TERMINAL PULSE LOOP (10-MIN HEARTBEAT)
# ======================

async def _terminal_pulse_loop():
    """
    Sistema de verificación cada 10 minutos en la terminal del bot de trading.
    Muestra 'Escaneando...' con marca temporal e información de MT5 para confirmar que el bot está activo.
    """
    await bot.wait_until_ready()
    log_event("Sistema de verificación de terminal (pulse 10-min) iniciado")

    pulse_interval_seconds = 600  # 10 minutos (600 segundos)
    while True:
        try:
            now_str = datetime.now().strftime('%H:%M:%S')

            def _get_mt5_status_str():
                try:
                    import MetaTrader5 as mt5
                    info = mt5.terminal_info()
                    acc = mt5.account_info()
                    if info and info.connected and acc:
                        return f"MT5 CONECTADO | Cuenta #{acc.login} | ${acc.balance:.2f} {acc.currency}"
                    return "MT5 DESCONECTADO"
                except Exception:
                    return "MT5 NO DISPONIBLE"

            mt5_status_msg = await asyncio.to_thread(_get_mt5_status_str)
            log_event(f"Escaneando... [{mt5_status_msg} | Bot activo | {now_str}]", "INFO", "SYSTEM")
            await asyncio.sleep(pulse_interval_seconds)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error en terminal pulse loop: {e}")
            await asyncio.sleep(60)

# ======================
# WEEKLY SUMMARY LOOP
# ======================

async def _weekly_summary_loop():
    """
    Background task: sends a weekly summary embed to the signals channel
    every Monday between 08:00-09:00 UTC.
    """
    await bot.wait_until_ready()
    log_event("Weekly summary loop iniciado")

    _last_summary_monday: Optional[str] = None  # ISO date of last Monday we sent

    while True:
        try:
            await asyncio.sleep(3600)  # check every hour

            now = datetime.now(timezone.utc)
            # Monday = weekday 0, between 08:00 and 09:00
            if now.weekday() != 0 or not (8 <= now.hour < 9):
                continue

            today_str = now.date().isoformat()
            if _last_summary_monday == today_str:
                continue  # already sent this Monday

            # Gather last 7 days of signal history
            try:
                from services.bot_service import get_bot_service
                history = get_bot_service().get_signal_history(limit=500)
            except Exception as e:
                logger.error(f"Weekly summary: error getting history: {e}")
                continue

            total = len(history)
            wins = sum(1 for s in history if s.get('final_status') == 'win')
            losses = sum(1 for s in history if s.get('final_status') == 'loss')
            closed = wins + losses
            winrate = (wins / closed * 100) if closed > 0 else 0.0

            # Best/worst pair by win rate
            pair_stats: dict = {}
            for s in history:
                sym = s.get('symbol', 'UNKNOWN')
                fs = s.get('final_status')
                if sym not in pair_stats:
                    pair_stats[sym] = {'wins': 0, 'losses': 0}
                if fs == 'win':
                    pair_stats[sym]['wins'] += 1
                elif fs == 'loss':
                    pair_stats[sym]['losses'] += 1

            best_pair = worst_pair = '—'
            best_wr = -1.0; worst_wr = 101.0
            for sym, ps in pair_stats.items():
                c = ps['wins'] + ps['losses']
                if c == 0:
                    continue
                wr = ps['wins'] / c * 100
                if wr > best_wr:
                    best_wr = wr; best_pair = f"{sym} ({wr:.0f}%)"
                if wr < worst_wr:
                    worst_wr = wr; worst_pair = f"{sym} ({wr:.0f}%)"

            channel = await _find_signals_channel()
            if channel:
                embed = discord.Embed(
                    title="📊 Resumen Semanal — Trading Bot",
                    description=f"Semana del {(now - timedelta(days=7)).strftime('%d/%m')} al {now.strftime('%d/%m/%Y')}",
                    color=0x58a6ff,
                    timestamp=now,
                )
                embed.add_field(name="📈 Señales totales", value=str(total), inline=True)
                embed.add_field(name="✅ Wins", value=str(wins), inline=True)
                embed.add_field(name="❌ Losses", value=str(losses), inline=True)
                embed.add_field(name="🎯 Winrate", value=f"{winrate:.1f}%", inline=True)
                embed.add_field(name="🏆 Mejor par", value=best_pair, inline=True)
                embed.add_field(name="📉 Peor par", value=worst_pair, inline=True)
                embed.set_footer(text="Auto-Signal System | Resumen semanal automático")
                await channel.send(embed=embed)
                log_event(f"📊 Resumen semanal enviado: {total} señales, WR={winrate:.1f}%")

            _last_summary_monday = today_str

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Weekly summary loop error: {e}")
            await asyncio.sleep(3600)


# ======================
# SESSION SUMMARY LOOP
# ======================

async def _session_summary_loop():
    """
    Background task: envía un resumen de señales al final de cada sesión
    de mercado (London 17h UTC, New York 22h UTC).
    Verifica cada 5 minutos si alguna sesión acaba de cerrar.
    """
    await bot.wait_until_ready()
    log_event("Session summary loop iniciado")

    from session_summary import SESSIONS, session_summary as _ss

    while True:
        try:
            await asyncio.sleep(300)  # verificar cada 5 minutos

            for session_name in SESSIONS:
                should_send, key = _ss.should_send_summary(session_name)
                if not should_send:
                    continue

                # Obtener historial de señales de las últimas 24h
                try:
                    from services.bot_service import get_bot_service
                    history = get_bot_service().get_signal_history(limit=100)
                except Exception as e:
                    logger.error(f"Session summary: error getting history: {e}")
                    history = []

                # Obtener estado del circuit breaker
                cb_status = None
                try:
                    from core.circuit_breaker import get_circuit_breaker
                    cb_status = get_circuit_breaker().get_status()
                except Exception as e:
                    logger.warning(f"Session summary: no se pudo obtener CB status: {e}")

                # Construir mensaje
                message = _ss.build_summary_message(
                    session_name=session_name,
                    signal_history=history,
                    circuit_breaker_status=cb_status,
                )

                # Enviar al canal
                channel = await _find_signals_channel()
                if channel:
                    await channel.send(message)
                    log_event(
                        f"📋 Resumen de sesión enviado: {session_name} | "
                        f"{len(history)} señales en historial"
                    )
                else:
                    logger.warning(
                        f"Session summary: no se encontró el canal '{SIGNALS_CHANNEL_NAME}'"
                    )

                # Marcar como enviado para no repetir
                _ss.mark_sent(key)

        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Session summary loop crashed; retrying in 5 minutes")
            await asyncio.sleep(300)


# ======================
# BACKTEST QUEUE LOOP
# ======================

async def _backtest_queue_loop():
    """
    Loop que procesa las tareas de backtesting y Monte Carlo que la app móvil
    o cualquier otro cliente inserte en la tabla backtest_tasks de SQLite.
    Verifica la cola cada 5 segundos.
    """
    await bot.wait_until_ready()
    log_event("Backtest queue loop iniciado (verificación cada 5 segundos)")

    db_path = os.path.join(os.path.dirname(__file__), 'bot_state.db')

    while True:
        try:
            await asyncio.sleep(5)

            # Buscar tareas PENDING
            def _check_queue():
                try:
                    conn = sqlite3.connect(db_path, timeout=10)
                    conn.row_factory = sqlite3.Row
                    c = conn.cursor()
                    c.execute(
                        "SELECT id, symbol, strategy, bars, cb_losses, cb_pause "
                        "FROM backtest_tasks WHERE status='PENDING' ORDER BY id ASC LIMIT 1"
                    )
                    row = c.fetchone()
                    if row:
                        task = dict(row)
                        # Cambiar a PROCESSING para reclamarla
                        c.execute(
                            "UPDATE backtest_tasks SET status='PROCESSING', updated_at=(datetime('now')) WHERE id=?",
                            (task['id'],)
                        )
                        conn.commit()
                        conn.close()
                        return task
                    conn.close()
                except Exception as e:
                    logger.error(f"[BacktestQueue] Error revisando cola: {e}")
                return None

            task = await asyncio.to_thread(_check_queue)
            if not task:
                continue

            log_event(f"🔄 Procesando backtest remoto ID {task['id']} ({task['symbol']} - {task['strategy']})")

            # Ejecutar el backtest en un hilo separado
            def _run_backtest(t):
                from core.replay_engine import ReplayEngine
                import json as _json

                try:
                    engine = ReplayEngine(
                        max_forward_bars=120,
                        cb_consecutive_losses=t['cb_losses'],
                        cb_pause_bars=t['cb_pause'],
                    )

                    stats = engine.run_replay(
                        symbol=t['symbol'],
                        bars=t['bars'],
                        strategy=t['strategy'],
                        timeframe='H1',
                        skip_duplicate_filter=True,
                    )

                    signals = engine.get_signals()
                    wins = [s for s in signals if s.result == 'WIN']
                    losses = [s for s in signals if s.result == 'LOSS']
                    closed = len(wins) + len(losses)
                    gp = sum(s.profit_pips or 0 for s in wins)
                    gl = abs(sum(s.profit_pips or 0 for s in losses))
                    pf = gp / gl if gl > 0 else float('inf')
                    pf_str = f"{pf:.2f}" if pf != float('inf') else "∞"

                    # Racha máxima de pérdidas
                    max_streak = cur = 0
                    for s in signals:
                        if s.result == 'LOSS':
                            cur += 1
                            max_streak = max(max_streak, cur)
                        elif s.result == 'WIN':
                            cur = 0

                    # Simulación Monte Carlo
                    mc_data = {"status": "omitted", "reason": "less_than_5_trades"}
                    if closed >= 5:
                        try:
                            from core.montecarlo import MonteCarlo, TradeRecord
                            mc_records = [TradeRecord.from_replay_signal(s) for s in signals if s.result in ('WIN', 'LOSS')]
                            ruin_threshold = -3000.0 if t['symbol'] == 'BTCEUR' else -300.0
                            mc = MonteCarlo(n_simulations=5000, ruin_threshold=ruin_threshold)
                            mc_report = mc.run(mc_records, symbol=t['symbol'])
                            
                            mc_data = {
                                "status": "success",
                                "prob_profitable": mc_report.prob_profitable,
                                "prob_ruin": mc_report.prob_ruin,
                                "ruin_threshold": ruin_threshold,
                                "p50_drawdown": mc_report.p50_drawdown,
                                "p75_drawdown": mc_report.p75_drawdown,
                                "p95_drawdown": mc_report.p95_drawdown,
                                "p5_equity": mc_report.p5_equity,
                                "p50_equity": mc_report.p50_equity,
                                "p95_equity": mc_report.p95_equity,
                            }
                        except Exception as mc_err:
                            logger.error(f"[BacktestQueue] Error MonteCarlo: {mc_err}")
                            mc_data = {"status": "error", "message": str(mc_err)}

                    # Serializar resultados
                    results = {
                        "symbol": t['symbol'],
                        "strategy": t['strategy'],
                        "bars_analyzed": stats.bars_analyzed,
                        "signals_final": stats.signals_final,
                        "buy_signals": stats.buy_signals,
                        "sell_signals": stats.sell_signals,
                        "tp_hits": stats.tp_hits,
                        "sl_hits": stats.sl_hits,
                        "pending": stats.pending,
                        "winrate": stats.winrate,
                        "profit_factor": pf_str,
                        "total_pips": stats.total_pips,
                        "avg_rr": stats.avg_rr,
                        "max_streak": max_streak,
                        "cb_activations": stats.cb_activations,
                        "bars_paused": stats.bars_paused,
                        "signals_blocked_by_cb": stats.signals_blocked_by_cb,
                        "monte_carlo": mc_data,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }

                    # Guardar en base de datos como COMPLETED
                    conn = sqlite3.connect(db_path, timeout=10)
                    c = conn.cursor()
                    c.execute(
                        "UPDATE backtest_tasks "
                        "SET status='COMPLETED', results_json=?, updated_at=(datetime('now')) "
                        "WHERE id=?",
                        (_json.dumps(results, ensure_ascii=False), t['id'])
                    )
                    conn.commit()
                    conn.close()
                    return True
                except Exception as run_err:
                    logger.error(f"[BacktestQueue] Error ejecutando backtest ID {t['id']}: {run_err}")
                    try:
                        conn = sqlite3.connect(db_path, timeout=10)
                        c = conn.cursor()
                        c.execute(
                            "UPDATE backtest_tasks "
                            "SET status='FAILED', error_message=?, updated_at=(datetime('now')) "
                            "WHERE id=?",
                            (str(run_err), t['id'])
                        )
                        conn.commit()
                        conn.close()
                    except Exception as db_err:
                        logger.error(f"[BacktestQueue] Error guardando fallo en BD: {db_err}")
                    return False

            success = await asyncio.to_thread(_run_backtest, task)
            if success:
                log_event(f"✅ Backtest remoto ID {task['id']} procesado exitosamente")
            else:
                log_event(f"❌ Falló el backtest remoto ID {task['id']}", "ERROR")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"[BacktestQueue] Excepción general en el loop: {e}")
            await asyncio.sleep(10)


async def _find_signals_channel():
    # find first channel matching SIGNALS_CHANNEL_NAME across guilds
    for g in bot.guilds:
        for ch in g.text_channels:
            if ch.name == SIGNALS_CHANNEL_NAME:
                return ch
    return None


# Legacy inline handlers refactored into services/commands_refactored.py


# ======================
# START
# ======================

if __name__ == '__main__':
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN no encontrado en el entorno. Añade .env con DISCORD_TOKEN=")
        raise SystemExit("DISCORD_TOKEN missing")

    if os.name == 'nt':
        import ctypes
        def _win_ctrl_handler(ctrl_type):
            if ctrl_type in (0, 1, 2, 5, 6):
                print("\n[Ctrl+C] Interrupción detectada. Cerrando bot de forma limpia...")
                try:
                    stop_enhanced_dashboard()
                    mt5_shutdown()
                except Exception:
                    pass
                os._exit(0)
            return True
        try:
            handler_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(handler_type(_win_ctrl_handler), True)
        except Exception:
            pass

    try:
        bot.run(DISCORD_TOKEN)
    except (KeyboardInterrupt, SystemExit):
        print("\n[Ctrl+C] Bot finalizado correctamente.")
    except discord.errors.PrivilegedIntentsRequired as exc:
        logger.error("Privileged intents required: %s", exc)
        logger.error("Enable the required privileged intents (Message Content) in the Discord Developer Portal for your application: https://discord.com/developers/applications")
        logger.error("Or remove/avoid using `message_content` intent by migrating commands to application (slash) commands.")
        print("ERROR: Privileged intents required. See logs for details.")
    except Exception:
        logger.exception("Unhandled exception while running bot")
    finally:
        # ensure MT5 is shutdown when process exits
        log_event("Bot cerrándose - Limpiando recursos...")
        try:
            stop_enhanced_dashboard()
            log_event("Dashboard inteligente detenido")
        except Exception:
            pass
        try:
            mt5_shutdown()
            log_event("MT5 desconectado")
        except Exception:
            pass
        
        # Información final del archivo de log
        intelligent_logger = get_intelligent_logger()
        current_log_file = intelligent_logger.current_log_file
        if current_log_file and os.path.exists(current_log_file):
            file_size = os.path.getsize(current_log_file)
            file_size_mb = file_size / (1024 * 1024)
            log_event(f"📝 Log final guardado: {os.path.basename(current_log_file)} ({file_size_mb:.2f} MB)")
        
        log_event("Bot cerrado completamente")
        print("=" * 60)
        print(f"📝 Sesión completa guardada en: {os.path.basename(current_log_file) if current_log_file else 'archivo desconocido'}")
        print("=" * 60)
        os._exit(0)
