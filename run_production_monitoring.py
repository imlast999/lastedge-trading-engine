"""
LastEdge — Production Monitoring CLI Runner (P5.7)
===================================================
Ejecuta la auditoría de observabilidad de los 6 canales principales para garantizar ZERO PUNTOS CIEGOS.
"""

from __future__ import annotations

import sys
import json
from services.bot_service import get_bot_service


def main():
    print("=" * 80)
    print("📡 LastEdge — Production Observability & Monitoring Engine (P5.7)")
    print("=" * 80)

    bot_svc = get_bot_service()
    report = bot_svc.run_production_monitoring_audit()

    status = report.get("monitoring_status", "CRITICAL_BLIND_SPOTS")
    score = report.get("observability_coverage_score", 0.0)
    msg = report.get("verdict_message", "")
    summary = report.get("summary", {})
    channels = report.get("channels", [])
    blind_spots = report.get("blind_spots", [])

    print(f"\nFecha/Hora: {report.get('timestamp')}")
    print(f"Duración de Auditoría: {report.get('total_duration_ms', 0)} ms")
    print(f"Cobertura Global de Observabilidad (Score): {score} / 100")
    print(f"Dictamen Oficial: {msg}")
    print(f"Resumen: PASS: {summary.get('passed', 0)} | WARN: {summary.get('warnings', 0)} | FAIL: {summary.get('failed', 0)}\n")

    print("-" * 80)
    for c in channels:
        st = c["status"]
        icon = "✅ PASS" if st == "PASS" else ("⚠️ WARN" if st == "WARN" else "❌ FAIL")
        lat = f"{c['latency_ms']} ms"
        cov = f"{c['coverage_pct']}%"
        print(f"[{icon}] {c['name']:<38} Cobertura: {cov:>5} ({lat:>8}) ↳ {c['message']}")
    print("-" * 80)

    if blind_spots:
        print("\n⚠️ PUNTOS CIEGOS REGISTRADOS:")
        for bs in blind_spots:
            print(f"  • {bs}")

    if "--json" in sys.argv:
        print("\n--- JSON OUTPUT ---")
        print(json.dumps(report, indent=2))

    sys.exit(0 if status != "CRITICAL_BLIND_SPOTS" else 1)


if __name__ == "__main__":
    main()
