#!/usr/bin/env python3
"""
LastEdge Multi-Channel CI/CD Notification Dispatcher
scripts/notify_bots.py

Dispatches institutional release announcements and CI failure/success alerts
simultaneously to both Telegram and Discord bots.
Uses only the Python standard library (urllib.request) for zero-dependency execution
in any GitHub Actions runner or local environment.
"""

from __future__ import annotations

import os
import sys
import json
import argparse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def send_telegram_message(token: str, chat_id: str, html_text: str) -> bool:
    """Sends an HTML formatted message via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "LastEdge-CI/1.0"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 201):
                print("  [Telegram] Message delivered successfully.")
                return True
            print(f"  [Telegram] HTTP {resp.status}: {resp.read().decode('utf-8')}")
            return False
    except Exception as e:
        print(f"  [Telegram] Error sending message: {e}")
        return False


def send_discord_message(token: str, channel_id: str, content: str, embed: Optional[Dict[str, Any]] = None) -> bool:
    """Sends an announcement or embed via Discord REST API."""
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload: Dict[str, Any] = {"content": content}
    if embed:
        payload["embeds"] = [embed]
        
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "LastEdge-CI/1.0"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 201):
                print("  [Discord] Message delivered successfully.")
                return True
            print(f"  [Discord] HTTP {resp.status}: {resp.read().decode('utf-8')}")
            return False
    except Exception as e:
        print(f"  [Discord] Error sending message: {e}")
        return False


def build_release_messages(args: argparse.Namespace) -> tuple[str, str, dict]:
    """Builds Telegram HTML text and Discord Embed for a new APK release."""
    version = args.version or "1.0.0"
    apk_name = args.apk_name or f"LastEdge-v{version}.apk"
    download_url = args.download_url or f"https://github.com/{args.repo}/releases/download/v{version}/{apk_name}"
    release_url = args.release_url or f"https://github.com/{args.repo}/releases/tag/v{version}"
    commit_sha = (args.commit or "")[:7]
    
    # Changelog snippet
    changelog_snippet = ""
    if args.changelog:
        cl_path = Path(args.changelog)
        if cl_path.exists():
            changelog_snippet = cl_path.read_text(encoding="utf-8").strip()
        else:
            changelog_snippet = args.changelog.strip()

    # Truncate changelog for bot limits if needed
    if len(changelog_snippet) > 800:
        changelog_snippet = changelog_snippet[:800] + "\n... (ver release completa para ms detalles)"

    # Telegram HTML
    tg_lines = [
        f"<b>🚀 NUEVA VERSIN DISPONIBLE  LastEdge Mobile v{version}</b>",
        "",
        f"• <b>Archivo:</b> <code>{apk_name}</code>",
        f"• <b>Commit:</b> <code>{commit_sha}</code>" if commit_sha else "",
        f"• <b>Firma:</b> Keystore de Produccin (Actualizacin directa)",
        f"• <b>Tipografa:</b> Nexa Display + Plus Jakarta Sans",
        "",
        "<b>📥 Descarga directa:</b>",
        f"<a href=\"{download_url}\">Descargar {apk_name}</a>",
        "",
        f"<b>🔗 Notas de la versin:</b> <a href=\"{release_url}\">GitHub Release</a>"
    ]
    if changelog_snippet:
        tg_lines.extend([
            "",
            "<b>📋 Novedades destacadas:</b>",
            f"<blockquote>{changelog_snippet}</blockquote>"
        ])
    tg_text = "\n".join([line for line in tg_lines if line is not None])

    # Discord Embed
    discord_content = f"📱 **Nueva Versin Publicada: LastEdge Mobile v{version}**"
    discord_embed = {
        "title": f"LastEdge Mobile v{version} ya est disponible",
        "description": (
            f"El nuevo paquete Android firmado en produccin est listo para instalacin directa.\n\n"
            f"**[⬇️ Descargar APK ({apk_name})]({download_url})**\n"
            f"**[🔗 Ver Release en GitHub]({release_url})**"
        ),
        "url": release_url,
        "color": 2278750,  # #22c55e (Green)
        "fields": [
            {"name": "📦 Versin", "value": f"`v{version}`", "inline": True},
            {"name": "🔏 Firma", "value": "Produccin (In-place update)", "inline": True},
            {"name": "🎨 Diseo", "value": "Nexa + Jakarta Sans", "inline": True},
        ],
        "footer": {"text": f"LastEdge CI/CD  Commit {commit_sha}" if commit_sha else "LastEdge CI/CD"}
    }
    if changelog_snippet:
        discord_embed["fields"].append({
            "name": "📋 Registro de Cambios",
            "value": changelog_snippet[:1024],
            "inline": False
        })

    return tg_text, discord_content, discord_embed


def build_ci_failure_messages(args: argparse.Namespace) -> tuple[str, str, dict]:
    """Builds Telegram HTML text and Discord Embed for a CI failure."""
    repo = args.repo or "LastEdge"
    workflow = args.workflow or "CI Pipeline"
    branch = args.branch or "main"
    commit_sha = (args.commit or "")[:7]
    actor = args.actor or "CI"
    run_url = args.run_url or f"https://github.com/{repo}/actions"

    # Telegram HTML
    tg_lines = [
        "<b>🚨 ALERTA CRTICA  FALLO EN CI</b>",
        "",
        f"• <b>Repositorio:</b> <code>{repo}</code>",
        f"• <b>Workflow:</b> <code>{workflow}</code>",
        f"• <b>Rama:</b> <code>{branch}</code>",
        f"• <b>Commit:</b> <code>{commit_sha}</code> ({actor})",
        "",
        f"<b>🔍 Ver Registro y Diagnstico:</b> <a href=\"{run_url}\">GitHub Actions Run</a>"
    ]
    tg_text = "\n".join(tg_lines)

    # Discord Embed
    discord_content = f"🚨 **Fallo en Pipeline CI: `{repo}`**"
    discord_embed = {
        "title": f"Fallo en CI  {workflow}",
        "description": f"Se ha detectado un fallo en la ejecucin de pruebas continuas en la rama `{branch}`.\n\n**[🔍 Ver detalles de la ejecucin en GitHub]({run_url})**",
        "url": run_url,
        "color": 15680580,  # #ef4444 (Red)
        "fields": [
            {"name": "📁 Repositorio", "value": f"`{repo}`", "inline": True},
            {"name": "🌿 Rama", "value": f"`{branch}`", "inline": True},
            {"name": "👤 Autor", "value": f"`{actor}`", "inline": True},
            {"name": "🔖 Commit", "value": f"`{commit_sha}`", "inline": True},
        ],
        "footer": {"text": "LastEdge Observability & Risk Monitor"}
    }

    return tg_text, discord_content, discord_embed


def main():
    parser = argparse.ArgumentParser(description="LastEdge Multi-Channel CI/CD Notifier")
    parser.add_argument("--event", choices=["release", "ci-failure", "ci-success"], required=True)
    parser.add_argument("--repo", default=os.getenv("GITHUB_REPOSITORY", "imlast999/lastedge-app"))
    parser.add_argument("--workflow", default=os.getenv("GITHUB_WORKFLOW", "CI"))
    parser.add_argument("--branch", default=os.getenv("GITHUB_REF_NAME", "main"))
    parser.add_argument("--commit", default=os.getenv("GITHUB_SHA", ""))
    parser.add_argument("--actor", default=os.getenv("GITHUB_ACTOR", ""))
    parser.add_argument("--run-url", default="")
    parser.add_argument("--version", default="")
    parser.add_argument("--apk-name", default="")
    parser.add_argument("--download-url", default="")
    parser.add_argument("--release-url", default="")
    parser.add_argument("--changelog", default="")
    parser.add_argument("--dry-run", action="store_true", help="Print messages without sending")

    args = parser.parse_args()

    # Fallback run URL
    if not args.run_url and os.getenv("GITHUB_RUN_ID"):
        server_url = os.getenv("GITHUB_SERVER_URL", "https://github.com")
        args.run_url = f"{server_url}/{args.repo}/actions/runs/{os.getenv('GITHUB_RUN_ID')}"

    # Build messages
    if args.event == "release":
        tg_text, discord_content, discord_embed = build_release_messages(args)
    elif args.event == "ci-failure":
        tg_text, discord_content, discord_embed = build_ci_failure_messages(args)
    else:
        print(f"Event {args.event} not configured for broadcast.")
        return 0

    if args.dry_run:
        print("=== TELEGRAM MESSAGE ===")
        print(tg_text)
        print("\n=== DISCORD MESSAGE ===")
        print(discord_content)
        print(json.dumps(discord_embed, indent=2))
        return 0

    # Retrieve credentials from environment
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    dc_token = os.getenv("DISCORD_BOT_TOKEN")
    dc_channel_id = os.getenv("DISCORD_CHANNEL_ID")

    print(f"[*] Dispatching multi-channel alert for event '{args.event}'...")

    if tg_token and tg_chat_id:
        send_telegram_message(tg_token, tg_chat_id, tg_text)
    else:
        print("  [Telegram] Credentials not found in environment (skipping).")

    if dc_token and dc_channel_id:
        send_discord_message(dc_token, dc_channel_id, discord_content, discord_embed)
    else:
        print("  [Discord] Credentials not found in environment (skipping).")

    print("[*] Dispatch finished.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
