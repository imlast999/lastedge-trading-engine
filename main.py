"""
LastEdge Trading Engine — Main Entry Point
Inicia el motor de trading en tiempo real:
1. Conexión e inicialización de MetaTrader 5 y Market Watch.
2. Servidor REST API del Trading Engine (puerto 8081).
3. Bucle continuo de escaneo de mercado y evaluación de estrategias (AutoSignals).
4. Monitor dinámico de Trailing Stops y gestión de posiciones.
"""

from __future__ import annotations

import os
import sys
import time
import signal
import asyncio
import threading
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

from services.api_server import start_trading_api_server
from services.mt5_client import initialize as mt5_initialize, shutdown as mt5_shutdown, ensure_symbols_selected
from services.autosignals import create_autosignals_service, AutoSignalsService

logger = logging.getLogger(__name__)


class BackgroundTradingRunner:
    """Orquestador de hilos y bucles en segundo plano para el motor de trading."""

    def __init__(self):
        self.autosignals_svc: AutoSignalsService = create_autosignals_service()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.thread: threading.Thread | None = None
        self.is_running = False

    def start(self):
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True, name="LastEdgeMarketScanner")
        self.thread.start()

    def _run_event_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        async def _trailing_stops_loop():
            try:
                from services.trailing_stops import get_trailing_manager
                trailing_mgr = get_trailing_manager()
            except Exception as e:
                logger.debug(f"Trailing manager no disponible: {e}")
                trailing_mgr = None

            while self.is_running:
                try:
                    if trailing_mgr:
                        trailing_mgr.update_all_trailing_stops()
                except Exception as ex:
                    logger.debug(f"Error en bucle de trailing stops: {ex}")
                await asyncio.sleep(15)

        tasks = [
            self.autosignals_svc.start_auto_signal_loop(),
            _trailing_stops_loop(),
        ]

        try:
            self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        except Exception as e:
            logger.error(f"[BackgroundTradingRunner] Excepción en bucle de escaneo: {e}")
        finally:
            self.loop.close()

    def stop(self):
        self.is_running = False
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)


def main():
    print("=" * 70)
    print("🚀 LastEdge Trading Engine — Core Service Runner (Autonomous Engine)")
    print("=" * 70)

    # 1. Inicialización MT5 y suscripción a Market Watch
    print("🔌 Conectando con MetaTrader 5...")
    mt5_ok = False
    try:
        mt5_ok = mt5_initialize()
        if mt5_ok:
            sel_results = ensure_symbols_selected()
            selected_str = ", ".join(f"{s}: {'OK' if ok else 'FAIL'}" for s, ok in sel_results.items())
            print(f"✅ Conexión MT5 establecida | Market Watch: {selected_str}")
        else:
            print("⚠️ MT5 no pudo inicializarse de inmediato. El motor reintentará automáticamente.")
    except Exception as e:
        print(f"⚠️ Aviso MT5 al inicio: {e}")

    # 2. Servidor REST API
    port = int(os.getenv("TRADING_API_PORT", "8081"))
    srv = start_trading_api_server(port=port)
    print(f"📡 Trading API Server escuchando en http://localhost:{port}")
    print("   Endpoints disponibles:")
    print(f"   • http://localhost:{port}/api/health")
    print(f"   • http://localhost:{port}/api/trading/status")
    print(f"   • http://localhost:{port}/api/trading/positions")
    print(f"   • http://localhost:{port}/api/trading/signals")
    print(f"   • http://localhost:{port}/api/trading/risk")

    # 3. Iniciar bucle de escaneo de mercado y trailing stops
    runner = BackgroundTradingRunner()
    runner.start()
    symbols_str = ", ".join(runner.autosignals_svc.config.get('AUTOSIGNAL_SYMBOLS', []))
    interval_s = runner.autosignals_svc.config.get('AUTOSIGNAL_INTERVAL', 60)
    auto_exec = "ACTIVADA ✅" if runner.autosignals_svc.config.get('AUTO_EXECUTE_SIGNALS') else "SOLO ALERTAS ⚠️"
    print(f"🔍 Escáner de Mercado: ACTIVO (Pares: {symbols_str} | Intervalo: {interval_s}s)")
    print(f"⚡ Auto-Ejecución MT5: {auto_exec}")
    print("=" * 70)
    print("Presiona Ctrl+C para detener el servicio.\n")
    sys.stdout.flush()

    # Manejadores de señal para parada elegante
    def _graceful_exit(signum, frame):
        print("\n🛑 Señal recibida. Deteniendo Trading Engine...")
        sys.stdout.flush()
        runner.stop()
        srv.stop()
        try:
            mt5_shutdown()
        except Exception:
            pass
        sys.exit(0)

    signal.signal(signal.SIGINT, _graceful_exit)
    signal.signal(signal.SIGTERM, _graceful_exit)

    try:
        counter = 0
        while True:
            time.sleep(1)
            counter += 1
            if counter % 15 == 0:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # Telemetría MT5
                mt5_info = "Standby"
                try:
                    import MetaTrader5 as mt5
                    if mt5.terminal_info() is not None:
                        pos_count = len(mt5.positions_get() or [])
                        acc = mt5.account_info()
                        bal = acc.balance if acc else 0.0
                        mt5_info = f"MT5 Online (Cuenta #{acc.login if acc else '—'} | Bal: ${bal:.2f} | Pos: {pos_count})"
                    else:
                        mt5_info = "MT5 Standby / Offline"
                except Exception:
                    mt5_info = "MT5 Driver Initialized"

                scans = runner.autosignals_svc.scan_count
                last_scan = runner.autosignals_svc.last_scan_time.strftime("%H:%M:%S") if runner.autosignals_svc.last_scan_time else "Iniciando..."
                print(f"[{now_str}] [Trading Engine] 💓 Heartbeat OK | API :8081 | {mt5_info} | Escaneos: #{scans} (Último: {last_scan})")
                sys.stdout.flush()
    except KeyboardInterrupt:
        _graceful_exit(None, None)


if __name__ == "__main__":
    main()
