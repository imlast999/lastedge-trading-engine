"""
LastEdge Trading Engine — Main Entry Point
Inicia el servidor REST API del Trading Engine (puerto 8081)
y los servicios del núcleo operativo.
"""

from __future__ import annotations

import os
import sys
import time
from dotenv import load_dotenv

load_dotenv()

from services.api_server import start_trading_api_server


def main():
    print("=" * 65)
    print("🚀 LastEdge Trading Engine — Core Service Runner")
    print("=" * 65)
    port = int(os.getenv("TRADING_API_PORT", "8081"))
    srv = start_trading_api_server(port=port)
    print(f"📡 Trading API Server escuchando en http://localhost:{port}")
    print("   Endpoints disponibles:")
    print(f"   • http://localhost:{port}/api/health")
    print(f"   • http://localhost:{port}/api/trading/status")
    print(f"   • http://localhost:{port}/api/trading/positions")
    print(f"   • http://localhost:{port}/api/trading/risk")
    print("=" * 65)
    print("Presiona Ctrl+C para detener el servicio.\n")
    sys.stdout.flush()

    try:
        from datetime import datetime
        counter = 0
        while True:
            time.sleep(1)
            counter += 1
            if counter % 15 == 0:
                now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # Intento de telemetría MT5 segura
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

                print(f"[{now_str}] [Trading Engine] 💓 Heartbeat OK | API :8081 activa | {mt5_info}")
                sys.stdout.flush()
    except KeyboardInterrupt:
        print("\n🛑 Deteniendo Trading Engine...")
        sys.stdout.flush()
        srv.stop()


if __name__ == "__main__":
    main()
