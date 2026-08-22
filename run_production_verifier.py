"""
LastEdge — Automated Production Verification Runner (P5.2)
==========================================================
Verifica de forma 100% automatizada los 11 subsistemas críticos.
"""

from __future__ import annotations

import sys
import json
from services.bot_service import get_bot_service


def main():
    print("=" * 75)
    print("🛡️ LastEdge — Automated Production Verification Engine (P5.2)")
    print("=" * 75)

    bot_svc = get_bot_service()
    report = bot_svc.run_production_verification()

    passed = report.get("verification_passed", False)
    summary = report.get("summary", {})
    subsystems = report.get("subsystems", [])

    print(f"\nFecha/Hora: {report.get('timestamp')}")
    print(f"Duración Total: {report.get('total_duration_ms', 0)} ms")
    print(f"Dictamen Global: {'✅ ALL SUBSYSTEMS VERIFIED' if passed else '❌ SUBSYSTEM FAILURE DETECTED'}")
    print(f"Resumen: VERIFIED: {summary.get('verified', 0)} | DEGRADED: {summary.get('degraded', 0)} | FAILED: {summary.get('failed', 0)}\n")

    print("-" * 75)
    for s in subsystems:
        st = s["status"]
        icon = "✅ VERIFIED" if st == "VERIFIED" else ("⚠️ DEGRADED" if st == "DEGRADED" else "❌ FAILED")
        lat = f"{s['latency_ms']} ms"
        print(f"[{icon}] {s['subsystem']:<22} ({lat:>8}) ↳ {s['details']}")
    print("-" * 75)

    if "--json" in sys.argv:
        print("\n--- JSON OUTPUT ---")
        print(json.dumps(report, indent=2))

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
