"""
BotService — Core Business Logic Layer (Agnóstica de Plataforma)
=================================================================
Módulo agnóstico de la plataforma que centraliza toda la lógica de negocio,
consultas a MT5, Risk Engine v2, Journal, Research Database y News Filter.

Este servicio es consumido por los adaptadores de interfaz (Discord, Telegram, Web, CLI)
garantizando cero duplicación de código y separación limpia de responsabilidades.
"""

import os
import sys
import subprocess
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import MetaTrader5 as mt5

logger = logging.getLogger(__name__)

class BotService:
    """Servicio agnóstico de negocio para bots de control (Discord, Telegram, etc.)."""

    def __init__(self, mt5_client=None, risk_engine=None, start_time: Optional[datetime] = None):
        self.mt5_client = mt5_client
        self.risk_engine = risk_engine
        self.start_time = start_time or datetime.now(timezone.utc)
        self.autosignals_enabled = os.getenv("AUTOSIGNALS_ENABLED", "true").lower() in ("true", "1", "yes")

    # ── 1. Estado del Sistema & Uptime ────────────────────────────────────────

    def get_system_status(self) -> Dict[str, Any]:
        """Obtiene el estado general del bot, uptime, conexión MT5, Circuit Breaker e indicador de noticias."""
        now = datetime.now(timezone.utc)
        uptime_seconds = int((now - self.start_time).total_seconds())
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        
        uptime_str = f"{days}d {hours}h {minutes}m" if days > 0 else f"{hours}h {minutes}m {seconds}s"

        mt5_connected = False
        account_info = None
        if mt5.terminal_info() is not None:
            mt5_connected = True
            account_info = mt5.account_info()

        # Circuit Breaker state
        cb_status = {"can_trade": True, "consecutive_losses": 0, "consecutive_wins": 0, "risk_multiplier": 1.0, "reason": ""}
        try:
            from services.mobile_store import get_mobile_store
            store = get_mobile_store()
            cb_data = store.get_circuit_breaker_status()
            if cb_data:
                cb_status.update(cb_data)
        except Exception as e:
            logger.debug(f"Error fetching circuit breaker status in BotService: {e}")

        # News indicator
        news_indicator = "🟢 Sin noticias de alto impacto inmediatas"
        try:
            upcoming_news = self.get_upcoming_news()
            if upcoming_news:
                first_evt = upcoming_news[0]
                news_indicator = f"⚠️ Noticia próxima: {first_evt.get('currency')} - {first_evt.get('title')} ({first_evt.get('time')})"
        except Exception:
            pass

        symbols_list = os.getenv("AUTOSIGNAL_SYMBOLS", "EURUSD,XAUUSD,BTCEUR").split(",")

        return {
            "ok": True,
            "system_status": "RUNNING",
            "uptime_seconds": uptime_seconds,
            "uptime_formatted": uptime_str,
            "mt5_connected": mt5_connected,
            "autosignals_enabled": self.autosignals_enabled,
            "monitored_symbols": [s.strip() for s in symbols_list],
            "scan_interval_seconds": int(os.getenv("AUTOSIGNAL_INTERVAL", "20")),
            "account_number": account_info.login if account_info else None,
            "server": account_info.server if account_info else None,
            "circuit_breaker": cb_status,
            "news_indicator": news_indicator,
            "timestamp": now.isoformat(),
        }

    # ── 2. Posiciones & Operaciones en MT5 ────────────────────────────────────

    def get_open_positions(self) -> List[Dict[str, Any]]:
        """Obtiene todas las posiciones abiertas en MT5."""
        if mt5.terminal_info() is None:
            if not mt5.initialize():
                return []

        positions = mt5.positions_get()
        if positions is None:
            return []

        result = []
        for pos in positions:
            p_dict = pos._asdict()
            p_type = "BUY" if p_dict.get("type") == 0 else "SELL"
            result.append({
                "ticket": p_dict.get("ticket"),
                "symbol": p_dict.get("symbol"),
                "type": p_type,
                "volume": p_dict.get("volume"),
                "open_price": p_dict.get("price_open"),
                "current_price": p_dict.get("price_current"),
                "sl": p_dict.get("sl"),
                "tp": p_dict.get("tp"),
                "profit": p_dict.get("profit"),
                "swap": p_dict.get("swap"),
                "magic": p_dict.get("magic"),
                "comment": p_dict.get("comment"),
                "time": datetime.fromtimestamp(p_dict.get("time", 0), tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
            })
        return result

    def close_position(self, ticket: int) -> Dict[str, Any]:
        """Cierra una posición abierta por ticket."""
        if mt5.terminal_info() is None:
            if not mt5.initialize():
                return {"ok": False, "message": "No se pudo conectar a MT5."}

        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return {"ok": False, "message": f"Posición #{ticket} no encontrada en MT5."}

        pos = positions[0]._asdict()
        symbol = pos["symbol"]
        volume = pos["volume"]
        pos_type = pos["type"]

        # Determinar tipo de orden de cierre
        order_type = mt5.ORDER_TYPE_SELL if pos_type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return {"ok": False, "message": f"No se obtuvo precio tick para {symbol}."}

        price = tick.bid if order_type == mt5.ORDER_TYPE_SELL else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": symbol,
            "volume": volume,
            "type": order_type,
            "price": price,
            "deviation": 20,
            "magic": 100001,
            "comment": "Close via BotService",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
            err_code = result.retcode if result else "UNKNOWN"
            return {"ok": False, "message": f"Error al cerrar ticket #{ticket} (retcode: {err_code})."}

        return {
            "ok": True,
            "message": f"Posición #{ticket} ({symbol} {volume} lotes) cerrada con éxito a precio {price}.",
            "ticket": ticket,
            "price": price,
        }

    # ── 3. Balance & Métricas de Cuenta ───────────────────────────────────────

    def get_account_equity(self) -> Dict[str, Any]:
        """Obtiene métricas de balance, equity, margen y flotante."""
        if mt5.terminal_info() is None:
            if not mt5.initialize():
                return {"ok": False, "message": "MT5 desconectado"}

        acc = mt5.account_info()
        if acc is None:
            return {"ok": False, "message": "No se pudo obtener información de cuenta MT5."}

        acc_dict = acc._asdict()
        balance = acc_dict.get("balance", 0.0)
        equity = acc_dict.get("equity", 0.0)
        margin = acc_dict.get("margin", 0.0)
        free_margin = acc_dict.get("margin_free", 0.0)
        margin_level = acc_dict.get("margin_level", 0.0)
        floating_pnl = equity - balance

        return {
            "ok": True,
            "account": acc_dict.get("login"),
            "currency": acc_dict.get("currency", "EUR"),
            "balance": balance,
            "equity": equity,
            "margin": margin,
            "free_margin": free_margin,
            "margin_level": margin_level,
            "floating_pnl": floating_pnl,
            "leverage": acc_dict.get("leverage"),
            "server": acc_dict.get("server"),
        }

    # ── 4. Telemetría de Riesgo & Risk Engine v2 ──────────────────────────────

    def get_risk_telemetry(self) -> Dict[str, Any]:
        """Obtiene estado detallado de Risk Engine v2 y Circuit Breaker."""
        acc_info = self.get_account_equity()
        positions = self.get_open_positions()
        
        total_exposure = sum(p["volume"] for p in positions)
        total_floating = sum(p["profit"] for p in positions)
        
        cb_status = {"can_trade": True, "consecutive_losses": 0, "consecutive_wins": 0, "risk_multiplier": 1.0, "reason": ""}
        try:
            from services.mobile_store import get_mobile_store
            cb_data = get_mobile_store().get_circuit_breaker_status()
            if cb_data:
                cb_status.update(cb_data)
        except Exception:
            pass

        return {
            "ok": True,
            "can_trade": cb_status.get("can_trade", True),
            "circuit_breaker": cb_status,
            "open_positions_count": len(positions),
            "total_exposure_lots": round(total_exposure, 2),
            "total_floating_pnl": round(total_floating, 2),
            "account_equity": acc_info.get("equity", 0.0),
            "margin_level_pct": acc_info.get("margin_level", 0.0),
        }

    # ── 5. Journal & Calidad de Ejecución ─────────────────────────────────────

    def get_journal_summary(self, days: int = 30) -> Dict[str, Any]:
        """Obtiene métricas acumuladas del Journal de Ejecución."""
        try:
            from core.journal import get_journal
            journal = get_journal()
            stats = journal.get_execution_quality_summary(days=days)
            return {"ok": True, "stats": stats}
        except Exception as e:
            logger.error(f"Error fetching journal summary in BotService: {e}")
            return {"ok": False, "message": str(e), "stats": {}}

    def get_uptime_formatted(self) -> str:
        """Returns human-readable uptime formatted string."""
        now = datetime.now(timezone.utc)
        uptime_seconds = int((now - self.start_time).total_seconds())
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)
        return f"{days}d {hours}h {minutes}m" if days > 0 else f"{hours}h {minutes}m {seconds}s"

    # ── 6. Research Database & Investigaciones ─────────────────────────────────

    def get_research_summary(self) -> Dict[str, Any]:
        """Obtiene resumen de investigación cuantitativa."""
        try:
            try:
                from services.research_store import get_research_store
                store = get_research_store()
                exps, total = store.list_experiments(limit=5)
                promoted, _ = store.list_experiments(decision_status="PROMOTED")
                candidates, _ = store.list_experiments(decision_status="CANDIDATE")
                rejected, _ = store.list_experiments(decision_status="REJECTED")

                return {
                    "ok": True,
                    "total_experiments": total,
                    "promoted_count": len(promoted),
                    "candidates_count": len(candidates),
                    "rejected_count": len(rejected),
                    "recent_experiments": exps,
                }
            except ImportError:
                return {
                    "ok": True,
                    "source": "strategy_lab_remote",
                    "total_experiments": 0,
                    "promoted_count": 0,
                    "candidates_count": 0,
                    "rejected_count": 0,
                    "recent_experiments": [],
                    "message": "Strategy Lab operates as an independent service."
                }
        except Exception as e:
            logger.error(f"Error fetching research summary in BotService: {e}")
            return {"ok": False, "message": str(e), "total_experiments": 0, "recent_experiments": []}

    # ── 7. Noticias de Alto Impacto ────────────────────────────────────────────

    def get_upcoming_news(self) -> List[Dict[str, Any]]:
        """Obtiene calendario de noticias de alto impacto."""
        try:
            from services.news_filter import NewsFilter
            nf = NewsFilter()
            events = nf.get_upcoming_high_impact_events()
            return events if isinstance(events, list) else []
        except Exception as e:
            logger.error(f"Error fetching news in BotService: {e}")
            return []

    # ── 8. Control de Autosignals & Config ────────────────────────────────────

    def toggle_autosignals(self, mode: str = "status") -> Dict[str, Any]:
        """Activa, desactiva o consulta el estado de generación de autosignals."""
        mode_clean = mode.lower().strip()
        if mode_clean in ("on", "enable", "1", "true"):
            self.autosignals_enabled = True
            os.environ["AUTOSIGNALS_ENABLED"] = "true"
        elif mode_clean in ("off", "disable", "0", "false"):
            self.autosignals_enabled = False
            os.environ["AUTOSIGNALS_ENABLED"] = "false"

        return {
            "ok": True,
            "autosignals_enabled": self.autosignals_enabled,
            "mode": mode_clean,
        }

    # ── 9. Diagnóstico Técnico de Salud (/health) ──────────────────────────────

    def get_health_status(self) -> Dict[str, Any]:
        """Obtiene el diagnóstico técnico completo de la infraestructura y observabilidad P4."""
        try:
            from services.health_monitor import get_health_monitor_service
            monitor = get_health_monitor_service()
            report = monitor.get_full_health_report(mt5_client=self.mt5_client)
            
            # Incorporar métricas de broker quality
            from services.execution_analytics import get_execution_analytics_service
            analytics = get_execution_analytics_service().get_execution_metrics(days=7)

            return {
                "ok": True,
                "overall_status": report.get("status", "HEALTHY"),
                "mt5": report.get("mt5", {}),
                "database": report.get("database", {}),
                "process": report.get("process", {}),
                "autosignals": report.get("autosignals", {}),
                "broker_quality": {
                    "score": analytics.get("broker_quality_score", 100.0),
                    "avg_latency_ms": analytics.get("avg_latency_ms", 0.0),
                    "fill_rate_pct": analytics.get("fill_rate_pct", 100.0),
                    "avg_slippage_pips": analytics.get("avg_slippage_pips", 0.0)
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as e:
            logger.error(f"Error in get_health_status: {e}")
            return {"ok": False, "overall_status": "DEGRADED", "error": str(e)}

    # ── 10. Información de Despliegue (/version) ────────────────────────────────

    def get_version_info(self) -> Dict[str, Any]:
        """Obtiene información sobre la versión y el despliegue actual."""
        commit_sha = "N/A"
        branch_name = "N/A"
        try:
            commit_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()[:7]
            branch_name = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
        except Exception:
            pass

        return {
            "ok": True,
            "platform_name": "LastEdge Quantitative Platform",
            "version": "1.1.0",
            "git_commit": commit_sha,
            "git_branch": branch_name,
            "python_version": sys.version.split()[0],
            "db_schema_version": "v2",
            "environment": "PRODUCTION" if os.getenv("DEMO_MODE", "0") == "0" else "DEMO",
            "build_date": "2026-07-26",
        }

    # ── 11. Registros Recientes (/logs) ─────────────────────────────────────────

    def get_recent_logs(self, count: int = 10) -> List[Dict[str, Any]]:
        """Obtiene los últimos eventos o errores importantes registrados."""
        try:
            from services.logging import get_intelligent_logger
            logger_inst = get_intelligent_logger()
            return logger_inst.get_recent_events(count=count)
        except Exception as e:
            logger.error(f"Error fetching recent logs in BotService: {e}")
            return []

    # ── 12. Observabilidad & Calidad de Ejecución (P4 Observability) ────────────

    def get_execution_analytics(self, days: int = 30, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Obtiene analítica avanzada de ejecución, latencia, slippage y calidad del bróker."""
        try:
            from services.execution_analytics import get_execution_analytics_service
            service = get_execution_analytics_service()
            data = service.get_execution_metrics(days=days, symbol=symbol)
            return {"ok": True, "analytics": data}
        except Exception as e:
            logger.error(f"Error fetching execution analytics in BotService: {e}")
            return {"ok": False, "message": str(e), "analytics": {}}

    def run_go_live_checklist(self) -> Dict[str, Any]:
        """Ejecuta la lista de comprobaciones pre-producción (Go-Live Checklist P5.1)."""
        try:
            from services.go_live_checklist import get_go_live_checklist_service
            service = get_go_live_checklist_service()
            return service.run_checklist(mt5_client=self.mt5_client, bot_service=self)
        except Exception as e:
            logger.error(f"Error running go-live checklist in BotService: {e}")
            return {"ready_to_trade": False, "error": str(e), "checks": []}

    def run_production_verification(self) -> Dict[str, Any]:
        """Ejecuta la verificación automatizada de los 11 subsistemas críticos (P5.2)."""
        try:
            from services.production_verifier import get_production_verifier_service
            service = get_production_verifier_service()
            return service.verify_all_subsystems(bot_service=self)
        except Exception as e:
            logger.error(f"Error running production verification in BotService: {e}")
            return {"verification_passed": False, "error": str(e), "subsystems": []}

    def get_long_forward_status(self) -> Dict[str, Any]:
        """Obtiene la telemetría de estabilidad y salud a largo plazo (P5.3)."""
        try:
            from services.long_forward_validation import get_long_forward_validation_service
            service = get_long_forward_validation_service()
            return service.get_validation_report()
        except Exception as e:
            logger.error(f"Error getting long forward status in BotService: {e}")
            return {"verdict": "UNKNOWN", "error": str(e)}

    def start_long_forward_session(self, profile: str = "24h") -> Dict[str, Any]:
        """Inicia una sesión continua de validación de estabilidad a largo plazo (24h, 72h, 7d)."""
        try:
            from services.long_forward_validation import get_long_forward_validation_service
            service = get_long_forward_validation_service()
            return service.start_session(profile=profile)
        except Exception as e:
            logger.error(f"Error starting long forward session in BotService: {e}")
            return {"ok": False, "error": str(e)}

    def stop_long_forward_session(self) -> Dict[str, Any]:
        """Detiene la sesión activa de validación de estabilidad a largo plazo."""
        try:
            from services.long_forward_validation import get_long_forward_validation_service
            service = get_long_forward_validation_service()
            return service.stop_session()
        except Exception as e:
            logger.error(f"Error stopping long forward session in BotService: {e}")
            return {"ok": False, "error": str(e)}

    def list_long_forward_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Obtiene el historial de sesiones almacenadas en SQLite."""
        try:
            from services.long_forward_validation import get_long_forward_validation_service
            service = get_long_forward_validation_service()
            return service.list_sessions(limit=limit)
        except Exception as e:
            logger.error(f"Error listing long forward sessions in BotService: {e}")
            return []

    def get_long_forward_session(self, session_id: str) -> Dict[str, Any]:
        """Obtiene los detalles completos de una sesión específica por ID."""
        try:
            from services.long_forward_validation import get_long_forward_validation_service
            service = get_long_forward_validation_service()
            return service.get_session(session_id=session_id)
        except Exception as e:
            logger.error(f"Error fetching long forward session {session_id} in BotService: {e}")
            return {"ok": False, "error": str(e)}

    def run_broker_certification(self) -> Dict[str, Any]:
        """Ejecuta la auditoría completa de certificación operativa del bróker (P5.4)."""
        try:
            from services.broker_certification import get_broker_certification_service
            service = get_broker_certification_service()
            return service.run_certification(mt5_client=self.mt5_client, bot_service=self)
        except Exception as e:
            logger.error(f"Error running broker certification in BotService: {e}")
            return {"certification_status": "NOT_CERTIFIED_FOR_LIVE", "error": str(e), "checks": []}

    def run_stability_verification(self) -> Dict[str, Any]:
        """Ejecuta la auditoría automatizada de los 9 factores de estabilidad del sistema (P5.5)."""
        try:
            from services.stability_verification import get_stability_verification_service
            service = get_stability_verification_service()
            return service.run_stability_audit(bot_service=self)
        except Exception as e:
            logger.error(f"Error running stability verification in BotService: {e}")
            return {"stability_status": "CRITICAL_STABILITY_RISK", "error": str(e), "checks": []}

    def run_operational_readiness_audit(self) -> Dict[str, Any]:
        """Ejecuta la auditoría de preparación operativa de producción (P5.6)."""
        try:
            from services.operational_readiness import get_operational_readiness_service
            return get_operational_readiness_service().run_operational_readiness_audit(bot_service=self)
        except Exception as e:
            logger.error(f"Error running operational readiness audit in BotService: {e}")
            return {"readiness_status": "NOT_READY", "error": str(e)}

    def create_backup(self, backup_name: Optional[str] = None) -> Dict[str, Any]:
        """Crea una copia de seguridad online segura de la base de datos."""
        try:
            from services.operational_readiness import get_operational_readiness_service
            return get_operational_readiness_service().create_backup(backup_name=backup_name)
        except Exception as e:
            logger.error(f"Error creating backup in BotService: {e}")
            return {"ok": False, "error": str(e)}

    def list_backups(self) -> List[Dict[str, Any]]:
        """Lista todas las copias de seguridad de base de datos disponibles."""
        try:
            from services.operational_readiness import get_operational_readiness_service
            return get_operational_readiness_service().list_backups()
        except Exception as e:
            logger.error(f"Error listing backups in BotService: {e}")
            return []

    def restore_backup(self, backup_file: str) -> Dict[str, Any]:
        """Restaura la base de datos desde una copia de seguridad verificando integridad."""
        try:
            from services.operational_readiness import get_operational_readiness_service
            return get_operational_readiness_service().restore_backup(backup_file)
        except Exception as e:
            logger.error(f"Error restoring backup in BotService: {e}")
            return {"ok": False, "error": str(e)}

    def rotate_logs(self) -> Dict[str, Any]:
        """Ejecuta la rotación y purga de archivos de log de la plataforma."""
        try:
            from services.operational_readiness import get_operational_readiness_service
            return get_operational_readiness_service().rotate_logs()
        except Exception as e:
            logger.error(f"Error rotating logs in BotService: {e}")
            return {"ok": False, "error": str(e)}

    def run_production_monitoring_audit(self) -> Dict[str, Any]:
        """Ejecuta la auditoría de observabilidad de los 6 canales de producción (P5.7)."""
        try:
            from services.production_monitoring import get_production_monitoring_service
            return get_production_monitoring_service().run_monitoring_audit(bot_service=self)
        except Exception as e:
            logger.error(f"Error running production monitoring audit in BotService: {e}")
            return {"monitoring_status": "CRITICAL_BLIND_SPOTS", "error": str(e)}

# Instancia global por defecto
_bot_service_instance: Optional[BotService] = None

def get_bot_service() -> BotService:
    global _bot_service_instance
    if _bot_service_instance is None:
        _bot_service_instance = BotService()
    return _bot_service_instance
