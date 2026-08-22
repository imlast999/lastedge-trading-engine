"""
LastEdge — Operational Readiness & Production Operations CLI Runner (P5.6)
============================================================================
Ejecuta la auditoría de preparación operativa y gestiona copias de seguridad,
restauraciones y rotación de logs.
"""

from __future__ import annotations

import sys
import json
from services.bot_service import get_bot_service


def main():
    print("=" * 80)
    print("⚙️ LastEdge — Production Operational Readiness Engine (P5.6)")
    print("=" * 80)

    bot_svc = get_bot_service()

    if "--backup" in sys.argv:
        res = bot_svc.create_backup()
        print(f"\n📦 {res.get('message')}")
        sys.exit(0 if res.get("ok") else 1)

    if "--list-backups" in sys.argv:
        backups = bot_svc.list_backups()
        print("\n📜 COPIAS DE SEGURIDAD DISPONIBLES (BACKUPS):")
        print("-" * 80)
        if not backups:
            print("Sin backups creados aún.")
        else:
            for b in backups:
                print(f"Archivo: {b['filename']:<42} | Tamaño: {b['size_mb']:>5.2f} MB | Creado: {b['created_at'][:19]}")
        print("-" * 80)
        sys.exit(0)

    if "--restore" in sys.argv:
        try:
            idx = sys.argv.index("--restore")
            backup_file = sys.argv[idx + 1]
            res = bot_svc.restore_backup(backup_file)
            print(f"\n♻️ {res.get('message')}")
            sys.exit(0 if res.get("ok") else 1)
        except Exception as e:
            print(f"Error en comando restore: {e}")
            sys.exit(1)

    if "--rotate-logs" in sys.argv:
        res = bot_svc.rotate_logs()
        print(f"\n🔄 {res.get('message')}")
        sys.exit(0)

    # Auditoría por defecto
    report = bot_svc.run_operational_readiness_audit()
    status = report.get("readiness_status", "NOT_READY")
    icon = "✅ OPERATIONAL_READY" if status == "OPERATIONAL_READY" else "❌ NOT_READY"
    procs = report.get("procedures", {})

    print(f"\nFecha/Hora: {report.get('timestamp')}")
    print(f"Estado de Preparación Operativa: {icon} (Score: {report.get('readiness_score', 0)}/100)\n")

    print("📋 PROCEDIMIENTOS OPERATIVOS:")
    print("-" * 80)
    for p_id, p_info in procs.items():
        st = p_info["status"]
        st_icon = "✅ READY" if st == "READY" else "❌ PENDING"
        name_fmt = p_id.replace('_', ' ').title()
        print(f"[{st_icon}] {name_fmt:<28} ↳ {p_info['details']}")
    print("-" * 80)

    if "--json" in sys.argv:
        print("\n--- JSON OUTPUT ---")
        print(json.dumps(report, indent=2))

    sys.exit(0)


if __name__ == "__main__":
    main()
