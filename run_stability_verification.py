"""
LastEdge — Stability Verification CLI Runner (P5.5)
====================================================
Ejecuta la auditoría completa de estabilidad de tiempo de ejecución de 9 factores.
"""

from __future__ import annotations

import sys
import json
from services.bot_service import get_bot_service


def main():
    print("=" * 80)
    print("🛡️ LastEdge — Runtime & System Stability Verification Engine (P5.5)")
    print("=" * 80)

    bot_svc = get_bot_service()
    report = bot_svc.run_stability_verification()

    status = report.get("stability_status", "CRITICAL_STABILITY_RISK")
    score = report.get("stability_index_score", 0.0)
    msg = report.get("verdict_message", "")
    summary = report.get("summary", {})
    checks = report.get("checks", [])

    print(f"\nFecha/Hora: {report.get('timestamp')}")
    print(f"Duración de Auditoría: {report.get('total_duration_ms', 0)} ms")
    print(f"Índice de Estabilidad (Score): {score} / 100")
    print(f"Dictamen Global: {msg}")
    print(f"Resumen: PASS: {summary.get('passed', 0)} | WARN: {summary.get('warnings', 0)} | FAIL: {summary.get('failed', 0)}\n")

    print("-" * 80)
    for c in checks:
        st = c["status"]
        icon = "✅ PASS" if st == "PASS" else ("⚠️ WARN" if st == "WARN" else "❌ FAIL")
        lat = f"{c['latency_ms']} ms"
        print(f"[{icon}] {c['name']:<46} ({lat:>8}) ↳ {c['message']}")
    print("-" * 80)

    if "--json" in sys.argv:
        print("\n--- JSON OUTPUT ---")
        print(json.dumps(report, indent=2))

    sys.exit(0 if status != "CRITICAL_STABILITY_RISK" else 1)


if __name__ == "__main__":
    main()
