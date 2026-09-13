"""
LastEdge Trading Engine — REST API Server
services/api_server.py

Provides clean, decoupled REST endpoints for external UI applications (LastEdge App,
Web Dashboard, Mobile App, Telegram/Discord bots) to query trading engine status,
metrics, positions, and execution analytics without importing internal Python modules.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


class TradingAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for LastEdge Trading Engine REST API."""

    def _send_json(self, status_code: int, data: Any):
        try:
            body = json.dumps(data, indent=2, default=str).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionAbortedError, BrokenPipeError, OSError):
            pass
        except Exception as e:
            logger.error("Error sending JSON response: %s", e)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")

        try:
            # ── Root Index & Discovery ─────────────────────────────────────────
            if path in ("", "/", "/api"):
                from services.bot_service import get_bot_service
                health = get_bot_service().get_health_status()
                self._send_json(200, {
                    "ok": True,
                    "service": "LastEdge Trading Engine",
                    "version": "1.0.0",
                    "status": "ONLINE",
                    "mt5_connected": health.get("mt5_connected", False),
                    "endpoints": {
                        "health": "/api/health",
                        "status": "/api/trading/status",
                        "positions": "/api/trading/positions",
                        "risk": "/api/trading/risk",
                        "equity": "/api/trading/equity",
                        "signals": "/api/trading/signals",
                        "news": "/api/trading/news",
                        "journal": "/api/trading/journal",
                        "checklist": "/api/trading/checklist"
                    },
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

            # ── Health & Status ───────────────────────────────────────────────
            elif path in ("/api/trading/health", "/api/health", "/health"):
                from services.bot_service import get_bot_service
                health = get_bot_service().get_health_status()
                self._send_json(200, {"ok": True, "service": "LastEdge Trading Engine", "health": health})

            elif path in ("/api/trading/status", "/api/status"):
                from services.bot_service import get_bot_service
                bot_svc = get_bot_service()
                health = bot_svc.get_health_status()
                uptime = bot_svc.get_uptime_formatted()
                self._send_json(200, {
                    "ok": True,
                    "service": "LastEdge Trading Engine",
                    "status": "ONLINE",
                    "uptime": uptime,
                    "mt5_connected": health.get("mt5_connected", False),
                    "health": health,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

            # ── Real-Time Metrics & Signals ──────────────────────────────────
            elif path in ("/api/trading/metrics", "/api/metrics"):
                from services.bot_service import get_bot_service
                bot_svc = get_bot_service()
                metrics = bot_svc.get_system_status()
                self._send_json(200, {"ok": True, "metrics": metrics})

            elif path in ("/api/trading/positions", "/api/positions"):
                from services.bot_service import get_bot_service
                positions = get_bot_service().get_open_positions()
                self._send_json(200, {"ok": True, "positions": positions, "count": len(positions)})

            elif path in ("/api/trading/risk", "/api/risk"):
                from services.bot_service import get_bot_service
                risk = get_bot_service().get_risk_telemetry()
                self._send_json(200, risk)

            elif path in ("/api/trading/equity", "/api/equity"):
                from services.bot_service import get_bot_service
                eq = get_bot_service().get_account_equity()
                self._send_json(200, {"ok": True, "equity": eq})

            elif path in ("/api/trading/signals", "/api/signals"):
                from services.bot_service import get_bot_service
                history = get_bot_service().get_signal_history(limit=100)
                self._send_json(200, {"ok": True, "signals": history})

            elif path in ("/api/trading/execution-analytics", "/api/analytics/execution"):
                from services.bot_service import get_bot_service
                analytics = get_bot_service().get_execution_analytics()
                self._send_json(200, {"ok": True, "analytics": analytics})

            elif path in ("/api/trading/checklist", "/api/system/go-live-checklist"):
                from services.bot_service import get_bot_service
                result = get_bot_service().run_go_live_checklist()
                self._send_json(200, {"ok": True, "checklist": result})

            elif path in ("/api/trading/news", "/api/news"):
                from services.bot_service import get_bot_service
                news = get_bot_service().get_upcoming_news()
                self._send_json(200, {"ok": True, "news": news})

            elif path in ("/api/trading/journal", "/api/journal"):
                from services.bot_service import get_bot_service
                journal = get_bot_service().get_journal_summary()
                self._send_json(200, journal)

            elif path in ("/api/trading/research", "/api/research"):
                from services.bot_service import get_bot_service
                research = get_bot_service().get_research_summary()
                self._send_json(200, research)

            else:
                self._send_json(404, {"ok": False, "error": f"Endpoint '{self.path}' not found on Trading Engine API."})

        except Exception as e:
            logger.error("API error handling GET %s: %s", self.path, e)
            self._send_json(500, {"ok": False, "error": str(e)})

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body_bytes = self.rfile.read(content_length) if content_length > 0 else b"{}"
            payload = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}

            if path in ("/api/trading/positions/close", "/api/positions/close"):
                ticket = payload.get("ticket")
                if not ticket:
                    self._send_json(400, {"ok": False, "error": "Missing 'ticket' in request body."})
                    return
                from services.position_manager import close_position
                closed = close_position(int(ticket))
                self._send_json(200, {"ok": closed, "ticket": ticket})
            else:
                self._send_json(404, {"ok": False, "error": f"POST endpoint '{self.path}' not found."})
        except Exception as e:
            logger.error("API error handling POST %s: %s", self.path, e)
            self._send_json(500, {"ok": False, "error": str(e)})

    def log_message(self, format, *args):
        # Suppress standard HTTP request logging spam
        pass


class TradingAPIServer:
    """Manages the background HTTP server for the Trading Engine REST API."""

    def __init__(self, host: str = "0.0.0.0", port: Optional[int] = None):
        self.host = host or os.getenv("TRADING_API_HOST", "0.0.0.0")
        self.port = port or int(os.getenv("TRADING_API_PORT", "8081"))
        self.server: Optional[ReusableThreadingHTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.is_running = False
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.is_running:
                return
            try:
                self.server = ReusableThreadingHTTPServer((self.host, self.port), TradingAPIHandler)
                self.is_running = True
                self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="TradingAPIServer")
                self.thread.start()
                logger.info("[Trading API] Server listening on http://%s:%d", self.host, self.port)
            except Exception as e:
                logger.error("[Trading API] Failed to start server on port %d: %s", self.port, e)

    def stop(self):
        with self.lock:
            if not self.is_running or not self.server:
                return
            self.is_running = False
            try:
                self.server.shutdown()
                self.server.server_close()
                logger.info("[Trading API] Server stopped.")
            except Exception as e:
                logger.debug("[Trading API] Error during shutdown: %s", e)


_api_server_instance: Optional[TradingAPIServer] = None


def get_trading_api_server(port: Optional[int] = None) -> TradingAPIServer:
    global _api_server_instance
    if _api_server_instance is None:
        _api_server_instance = TradingAPIServer(port=port)
    return _api_server_instance


def start_trading_api_server(port: Optional[int] = None) -> TradingAPIServer:
    srv = get_trading_api_server(port=port)
    srv.start()
    return srv


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.getenv("TRADING_API_PORT", "8081"))
    srv = start_trading_api_server(port=port)
    print(f"Trading API Server running on port {port}. Press Ctrl+C to stop.")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()
