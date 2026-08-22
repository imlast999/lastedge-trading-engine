"""
System Health Monitor & Internal Telemetry Service (P4.2 Observability)
=======================================================================
Servicio centralizado de monitoreo de salud del sistema, telemetría de proceso,
recursos de base de datos, conexión MT5 y estado de servicios.
"""

from __future__ import annotations

import os
import sys
try:
    import psutil
except ImportError:
    psutil = None
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timedelta, timezone

from services.database import get_database_manager

logger = logging.getLogger(__name__)


class HealthMonitorService:
    """
    Servicio de monitoreo interno y telemetría de salud de la plataforma.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_manager = get_database_manager(db_path)
        self.start_time = datetime.now(timezone.utc)

    def get_full_health_report(self, mt5_client: Any = None, state_obj: Any = None) -> Dict[str, Any]:
        """
        Genera un informe completo de salud del sistema y componentes.
        """
        process_health = self.get_process_health()
        database_health = self.get_database_health()
        mt5_health = self.get_mt5_health(mt5_client)
        autosignals_health = self.get_autosignals_health(state_obj)

        overall_status = "HEALTHY"
        if not mt5_health.get('connected', False) and not mt5_health.get('demo_mode', True):
            overall_status = "DEGRADED"
        if process_health.get('memory_mb', 0) > 1024:  # Warn if RSS > 1GB
            overall_status = "DEGRADED"

        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'status': overall_status,
            'process': process_health,
            'database': database_health,
            'mt5': mt5_health,
            'autosignals': autosignals_health
        }

    def get_process_health(self) -> Dict[str, Any]:
        """Obtiene métricas de proceso (memoria, uptime, threads, pid)."""
        uptime = datetime.now(timezone.utc) - self.start_time
        base_info = {
            'pid': os.getpid(),
            'uptime_seconds': int(uptime.total_seconds()),
            'uptime_formatted': str(timedelta(seconds=int(uptime.total_seconds()))),
            'python_version': sys.version.split()[0]
        }

        if psutil is not None:
            try:
                process = psutil.Process(os.getpid())
                mem_info = process.memory_info()
                base_info.update({
                    'memory_mb': round(mem_info.rss / (1024 * 1024), 2),
                    'vms_mb': round(mem_info.vms / (1024 * 1024), 2),
                    'cpu_percent': process.cpu_percent(interval=None),
                    'num_threads': process.num_threads(),
                })
            except Exception as e:
                logger.debug(f"[HealthMonitor] psutil process error: {e}")
                base_info.update({'memory_mb': 0.0, 'cpu_percent': 0.0, 'num_threads': 1})
        else:
            base_info.update({'memory_mb': 0.0, 'cpu_percent': 0.0, 'num_threads': 1})

        return base_info

    def get_database_health(self) -> Dict[str, Any]:
        """Obtiene métricas y estado del archivo SQLite."""
        db_path = self.db_manager.db_path
        size_mb = 0.0
        exists = os.path.exists(db_path)
        if exists:
            size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 2)

        wal_mode = False
        table_count = 0
        try:
            with self.db_manager.get_connection() as conn:
                r = conn.execute("PRAGMA journal_mode;").fetchone()
                if r and str(r[0]).lower() == 'wal':
                    wal_mode = True
                
                t_row = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table';").fetchone()
                if t_row:
                    table_count = t_row[0]
        except Exception as e:
            logger.warning(f"[HealthMonitor] Error consultando PRAGMA DB: {e}")

        return {
            'db_path': db_path,
            'exists': exists,
            'size_mb': size_mb,
            'wal_mode': wal_mode,
            'table_count': table_count
        }

    def get_mt5_health(self, mt5_client: Any = None) -> Dict[str, Any]:
        """Obtiene estado y telemetría del terminal MT5."""
        try:
            import MetaTrader5 as mt5
            terminal_info = mt5.terminal_info()
            account_info = mt5.account_info()

            connected = bool(terminal_info and terminal_info.connected)
            demo_mode = os.getenv('DEMO_MODE', '1') == '1'

            if account_info:
                return {
                    'connected': connected,
                    'demo_mode': demo_mode,
                    'login': account_info.login,
                    'server': account_info.server,
                    'balance': round(account_info.balance, 2),
                    'equity': round(account_info.equity, 2),
                    'free_margin': round(account_info.margin_free, 2),
                    'leverage': account_info.leverage,
                    'currency': account_info.currency,
                    'ping_ms': getattr(terminal_info, 'ping_last', 0) if terminal_info else 0
                }
            else:
                return {
                    'connected': connected,
                    'demo_mode': demo_mode,
                    'login': None,
                    'server': None,
                    'balance': 0.0,
                    'equity': 0.0,
                    'free_margin': 0.0,
                    'leverage': 0,
                    'ping_ms': 0
                }
        except Exception as e:
            return {
                'connected': False,
                'demo_mode': os.getenv('DEMO_MODE', '1') == '1',
                'error': str(e)
            }

    def get_autosignals_health(self, state_obj: Any = None) -> Dict[str, Any]:
        """Obtiene estado del motor de auto-señales."""
        enabled = bool(getattr(state_obj, 'autosignals', True)) if state_obj else True
        symbols = getattr(state_obj, 'symbols', ["EURUSD", "XAUUSD", "BTCEUR"]) if state_obj else ["EURUSD", "XAUUSD", "BTCEUR"]
        return {
            'enabled': enabled,
            'symbols': symbols,
            'scan_interval_sec': int(os.getenv('AUTOSIGNAL_INTERVAL', '20'))
        }


# Instancia global del servicio
_health_monitor_instance: Optional[HealthMonitorService] = None


def get_health_monitor_service(db_path: Optional[str] = None) -> HealthMonitorService:
    global _health_monitor_instance
    if _health_monitor_instance is None or (db_path and _health_monitor_instance.db_manager.db_path != db_path):
        _health_monitor_instance = HealthMonitorService(db_path)
    return _health_monitor_instance
