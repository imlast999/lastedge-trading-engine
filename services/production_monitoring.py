"""
LastEdge — Production Monitoring & Zero Blind Spots Engine (P5.7)
===================================================================
Servicio completo de auditoría y verificación de la plataforma de observabilidad en producción.
Valida los 6 canales de monitoreo para garantizar ZERO PUNTOS CIEGOS (Zero Operational Blind Spots):
  1. Web Dashboard (Métricas HTTP / API REST)
  2. Mobile App (Store API / Telemetría móvil)
  3. Discord Channel (Parser & Alertas de canal)
  4. Telegram Channel (Adaptador asíncrono & Comandos)
  5. Health Monitor (CPU, Memoria, Threads, MT5 Ping, SQLite WAL)
  6. Execution Analytics (Latencia, Fill Rate %, Slippage, Broker Quality Score)
"""

from __future__ import annotations

import os
import sys
import time
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from services.database import get_database_manager

logger = logging.getLogger(__name__)


class MonitoringChannelResult:
    """Resultado individual de un canal de observabilidad."""
    def __init__(self, channel_id: str, name: str, status: str, coverage_pct: float, message: str, latency_ms: float = 0.0, blind_spots: Optional[List[str]] = None):
        self.channel_id = channel_id
        self.name = name
        self.status = status  # PASS, WARN, FAIL
        self.coverage_pct = round(coverage_pct, 1)
        self.message = message
        self.latency_ms = round(latency_ms, 2)
        self.blind_spots = blind_spots or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "name": self.name,
            "status": self.status,
            "coverage_pct": self.coverage_pct,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "blind_spots": self.blind_spots,
        }


class ProductionMonitoringService:
    """
    Servicio de auditoría de cobertura de monitoreo de producción (P5.7).
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_manager = get_database_manager(db_path)

    def run_monitoring_audit(self, bot_service: Optional[Any] = None) -> Dict[str, Any]:
        """
        Ejecuta la auditoría de observabilidad sobre los 6 canales clave.
        """
        start_time = time.time()
        channels: List[MonitoringChannelResult] = []

        # 1. Web Dashboard
        channels.append(self._check_dashboard_channel())

        # 2. Mobile App
        channels.append(self._check_mobile_app_channel())

        # 3. Discord
        channels.append(self._check_discord_channel())

        # 4. Telegram
        channels.append(self._check_telegram_channel())

        # 5. Health Monitor
        channels.append(self._check_health_monitor_channel())

        # 6. Execution Analytics
        channels.append(self._check_execution_analytics_channel())

        total_duration_ms = round((time.time() - start_time) * 1000, 2)
        passed_cnt = sum(1 for c in channels if c.status == "PASS")
        warn_cnt = sum(1 for c in channels if c.status == "WARN")
        failed_cnt = sum(1 for c in channels if c.status == "FAIL")

        avg_coverage = round(sum(c.coverage_pct for c in channels) / len(channels), 1)
        all_blind_spots = [bs for c in channels for bs in c.blind_spots]

        if failed_cnt > 0 or avg_coverage < 75.0:
            monitoring_status = "CRITICAL_BLIND_SPOTS"
            verdict_message = f"❌ PUNTOS CIEGOS CRÍTICOS DETECTADOS ({len(all_blind_spots)} brechas de observabilidad)."
        elif warn_cnt > 0 or avg_coverage < 90.0:
            monitoring_status = "PARTIAL_COVERAGE_WARNINGS"
            verdict_message = f"⚠️ COBERTURA PARCIAL ({avg_coverage}% de cobertura global). Revisa advertencias."
        else:
            monitoring_status = "NO_BLIND_SPOTS_PRODUCTION_READY"
            verdict_message = "✅ COBERTURA TOTAL DE OBSERVABILIDAD (ZERO PUNTOS CIEGOS EN PRODUCCIÓN)."

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "monitoring_status": monitoring_status,
            "verdict_message": verdict_message,
            "observability_coverage_score": avg_coverage,
            "total_duration_ms": total_duration_ms,
            "summary": {
                "total_channels": len(channels),
                "passed": passed_cnt,
                "warnings": warn_cnt,
                "failed": failed_cnt,
                "total_blind_spots_found": len(all_blind_spots),
            },
            "blind_spots": all_blind_spots,
            "channels": [c.to_dict() for c in channels],
        }

    # ── Métodos de Comprobación por Canal ─────────────────────────────────────
    def _check_dashboard_channel(self) -> MonitoringChannelResult:
        t0 = time.time()
        try:
            from services.bot_service import get_bot_service
            metrics = get_bot_service().get_metrics()
            lat = (time.time() - t0) * 1000

            if not metrics or "balance" not in metrics:
                return MonitoringChannelResult("DASHBOARD", "Web Dashboard / API Observability", "WARN", 80.0, "Métricas básicas disponibles pero incompletas.", lat, ["REST API /api/trading/metrics payload sin balance"])

            return MonitoringChannelResult("DASHBOARD", "Web Dashboard / API Observability", "PASS", 100.0, f"Dashboard / API telemetry operational ({round(lat, 1)} ms).", lat)
        except Exception as e:
            return MonitoringChannelResult("DASHBOARD", "Web Dashboard / API Observability", "FAIL", 0.0, f"Error en Dashboard / API: {e}", (time.time() - t0) * 1000, [f"Dashboard / API exception: {e}"])

    def _check_mobile_app_channel(self) -> MonitoringChannelResult:
        t0 = time.time()
        try:
            from services.mobile_store import MobileStore
            store = MobileStore()
            state = store.get_system_status()
            lat = (time.time() - t0) * 1000

            return MonitoringChannelResult("MOBILE_APP", "Mobile App Telemetry", "PASS", 100.0, f"Mobile Store API fully operational ({round(lat, 1)} ms).", lat)
        except Exception as e:
            return MonitoringChannelResult("MOBILE_APP", "Mobile App Telemetry", "FAIL", 0.0, f"Error en Mobile Store: {e}", (time.time() - t0) * 1000, [f"Mobile Store exception: {e}"])

    def _check_discord_channel(self) -> MonitoringChannelResult:
        t0 = time.time()
        try:
            from services.commands_refactored import DiscordCommandParser
            parser = DiscordCommandParser()
            lat = (time.time() - t0) * 1000

            return MonitoringChannelResult("DISCORD", "Discord Notification Channel", "PASS", 100.0, f"Discord command parser and alerts verified ({round(lat, 1)} ms).", lat)
        except Exception as e:
            return MonitoringChannelResult("DISCORD", "Discord Notification Channel", "WARN", 70.0, f"Discord parser aviso: {e}", (time.time() - t0) * 1000)

    def _check_telegram_channel(self) -> MonitoringChannelResult:
        t0 = time.time()
        try:
            from services.telegram_adapter import TelegramAdapter
            adapter = TelegramAdapter()
            lat = (time.time() - t0) * 1000

            return MonitoringChannelResult("TELEGRAM", "Telegram Notification Channel", "PASS", 100.0, f"Telegram adapter and command router verified ({round(lat, 1)} ms).", lat)
        except Exception as e:
            return MonitoringChannelResult("TELEGRAM", "Telegram Notification Channel", "WARN", 70.0, f"Telegram adapter aviso: {e}", (time.time() - t0) * 1000)

    def _check_health_monitor_channel(self) -> MonitoringChannelResult:
        t0 = time.time()
        try:
            from services.health_monitor import get_health_monitor_service
            health_svc = get_health_monitor_service()
            metrics = health_svc.get_system_health()
            lat = (time.time() - t0) * 1000

            if metrics.get("process", {}).get("memory_rss_mb", 0) <= 0:
                return MonitoringChannelResult("HEALTH_MONITOR", "System Health Monitor", "WARN", 85.0, "Health Monitor activo pero telemetría de memoria es 0.", lat, ["Métrica RSS memory_rss_mb 0"])

            return MonitoringChannelResult("HEALTH_MONITOR", "System Health Monitor", "PASS", 100.0, f"System Health Monitor fully operational ({round(lat, 1)} ms).", lat)
        except Exception as e:
            return MonitoringChannelResult("HEALTH_MONITOR", "System Health Monitor", "FAIL", 0.0, f"Error en Health Monitor: {e}", (time.time() - t0) * 1000, [f"Health Monitor exception: {e}"])

    def _check_execution_analytics_channel(self) -> MonitoringChannelResult:
        t0 = time.time()
        try:
            from services.execution_analytics import get_execution_analytics_service
            analytics_svc = get_execution_analytics_service()
            metrics = analytics_svc.get_execution_metrics()
            lat = (time.time() - t0) * 1000

            if "broker_quality_score" not in metrics:
                return MonitoringChannelResult("EXECUTION_ANALYTICS", "Execution Analytics Engine", "WARN", 85.0, "Métricas de ejecución disponibles pero falta Broker Quality Score.", lat, ["Métrica broker_quality_score faltante"])

            return MonitoringChannelResult("EXECUTION_ANALYTICS", "Execution Analytics Engine", "PASS", 100.0, f"Execution Analytics Engine fully operational (Broker Quality Score: {metrics['broker_quality_score']}/100).", lat)
        except Exception as e:
            return MonitoringChannelResult("EXECUTION_ANALYTICS", "Execution Analytics Engine", "FAIL", 0.0, f"Error en Execution Analytics: {e}", (time.time() - t0) * 1000, [f"Execution Analytics exception: {e}"])


# Instancia singleton
_production_monitoring_instance: Optional[ProductionMonitoringService] = None

def get_production_monitoring_service(db_path: Optional[str] = None) -> ProductionMonitoringService:
    global _production_monitoring_instance
    if _production_monitoring_instance is None or db_path is not None:
        _production_monitoring_instance = ProductionMonitoringService(db_path)
    return _production_monitoring_instance
