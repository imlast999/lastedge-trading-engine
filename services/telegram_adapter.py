"""
TelegramAdapter — Adaptador de Telegram para LastEdge Trading Engine
===================================================================
Adaptador liviano para Telegram que permite enviar notificaciones
y procesar comandos operativos sobre la infraestructura del Trading Engine.
"""

from __future__ import annotations

import os
import logging
import asyncio
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class TelegramAdapter:
    """Adaptador asíncrono para notificaciones y comandos de Telegram."""

    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
        bot_service: Optional[Any] = None,
        **kwargs
    ):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.authorized_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.authorized_user_id = os.getenv("TELEGRAM_AUTHORIZED_USER_ID")
        self.bot_service = bot_service
        self.last_update_id = 0
        self.is_running = False

    def is_configured(self) -> bool:
        """Indica si las credenciales de Telegram están configuradas."""
        return bool(self.token)

    async def send_message(self, text: str, chat_id: Optional[str] = None) -> bool:
        """Envía un mensaje a través de la API HTTP de Telegram."""
        dest_chat = chat_id or self.authorized_chat_id
        if not self.token or not dest_chat:
            return False

        try:
            import aiohttp
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {"chat_id": dest_chat, "text": text, "parse_mode": "Markdown"}
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.debug(f"[TelegramAdapter] Error enviando mensaje: {e}")
            return False


__all__ = ["TelegramAdapter"]
