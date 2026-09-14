"""
Discord Command Parser & Adapter — services/commands_refactored.py
===================================================================
Provee parseo y resolución de comandos Discord para verificación de producción
y telemetría de monitoreo operativo.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class DiscordCommandParser:
    """Parser de comandos para interacciones y comandos de Discord."""

    def __init__(self):
        self.supported_commands = {
            "status",
            "positions",
            "close_position",
            "equity",
            "risk",
            "journal",
            "research",
            "autosignals",
            "health",
            "version",
            "logs",
            "discord",
        }

    def parse(self, text: str) -> Dict[str, Any]:
        """
        Parsea un string de comando (ej. '/status' o '!risk EURUSD').
        Retorna diccionario con 'command', 'args' y metadatos de validación.
        """
        clean_text = (text or "").strip()
        if not clean_text:
            return {"command": "", "args": [], "valid": False, "raw": clean_text}

        tokens = clean_text.split()
        cmd_token = tokens[0].lstrip("/").lstrip("!").lower()
        args = tokens[1:]

        is_valid = cmd_token in self.supported_commands
        return {
            "command": cmd_token,
            "args": args,
            "valid": is_valid,
            "raw": clean_text,
        }


__all__ = ["DiscordCommandParser"]
