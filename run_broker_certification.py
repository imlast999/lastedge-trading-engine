"""
LastEdge — Broker Certification CLI Runner (P5.4)
=================================================
Ejecuta la auditoría completa de certificación operativa del bróker y de la cadena de ejecución.
"""

from __future__ import annotations

import sys
import json
from services.bot_service import get_bot_service


def main():
    print("=" * 80)
    print("🏆 LastEdge — Operational Broker Certification Engine (P5.4)")
    print("=" * 80)

    bot_svc = get_bot_service()
    report = bot_svc.run_broker_certification()

    cert_status = report.get("certification_status", "NOT_CERTIFIED_FOR_LIVE")
    score = report.get("certification_score", 0.0)
    msg = report.get("verdict_message", "")
    summary = report.get("summary", {})
    checks = report.get("checks", [])

    print(f"\nFecha/Hora: {report.get('timestamp')}")
    print(f"Duración de Auditoría: {report.get('total_duration_ms', 0)} ms")
    print(f"Puntuación Global (Score): {score} / 100")
    print(f"Dictamen Oficial: {msg}")
    print(f"Resumen: PASS: {summary.get('passed', 0)} | WARN: {summary.get('warnings', 0)} | FAIL: {summary.get('failed', 0)}\n")

    print("-" * 80)
    for c in checks:
        st = c["status"]
        icon = "✅ PASS" if st == "PASS" else ("⚠️ WARN" if st == "WARN" else "❌ FAIL")
        lat = f"{c['latency_ms']} ms"
        crit = "[CRITICAL]" if c.get("critical", True) else "[OPTIONAL]"
        print(f"[{icon}] {c['name']:<42} ({lat:>8}) {crit:<10} ↳ {c['message']}")
    print("-" * 80)

    if "--json" in sys.argv:
        print("\n--- JSON OUTPUT ---")
        print(json.dumps(report, indent=2))

    sys.exit(0 if cert_status != "NOT_CERTIFIED_FOR_LIVE" else 1)


if __name__ == "__main__":
    main()
