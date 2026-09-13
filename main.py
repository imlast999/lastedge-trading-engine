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
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Deteniendo Trading Engine...")
        srv.stop()


if __name__ == "__main__":
    main()
