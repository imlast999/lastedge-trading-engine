"""
LastEdge — Go-Live Pre-Production Checklist Runner (P5.1)
=========================================================
Ejecuta las 17 comprobaciones de infraestructura, MT5, riesgo,
base de datos, red y entorno pre-producción.
"""

from __future__ import annotations

import sys
import json
from services.bot_service import get_bot_service


def main():
    print("=" * 70)
    print("🚀 LastEdge — Pre-Production Go-Live Checklist Audit (P5.1)")
    print("=" * 70)

    bot_svc = get_bot_service()
    report = bot_svc.run_go_live_checklist()

    ready = report.get("ready_to_trade", False)
    summary = report.get("summary", {})
    checks = report.get("checks", [])

    print(f"\nFecha/Hora Audit: {report.get('timestamp')}")
    print(f"Resultado General: {'✅ READY TO TRADE (Aprobado)' if ready else '❌ NOT READY (Fallos Detectados)'}")
    print(f"Resumen: PASS: {summary.get('passed', 0)} | WARN: {summary.get('warnings', 0)} | FAIL: {summary.get('failed', 0)}\n")

    print("-" * 70)
    for c in checks:
        status_icon = "✅ PASS" if c["status"] == "PASS" else ("⚠️ WARN" if c["status"] == "WARN" else "❌ FAIL")
        print(f"[{status_icon}] {c['name']} ({c['id']})")
        print(f"         ↳ {c['message']}")
    print("-" * 70)

    if "--json" in sys.argv:
        print("\n--- JSON OUTPUT ---")
        print(json.dumps(report, indent=2))

    sys.exit(0 if ready else 1)


if __name__ == "__main__":
    main()
