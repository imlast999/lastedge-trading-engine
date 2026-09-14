"""
NotificationDispatcher — Despachador de Alertas Multi-Canal (Discord + Telegram)
================================================================================
Permite transmitir señales de trading, alertas de riesgo, eventos de Circuit Breaker
y resúmenes en tiempo real simultáneamente a Discord y Telegram sin duplicar código.
Utiliza una sesión aiohttp.ClientSession persistente para evitar fugas de sockets.
"""

from __future__ import annotations

import os
import logging
import asyncio
from typing import Optional, Callable, Awaitable, List, Dict, Any
import aiohttp

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Despachador centralizado de notificaciones multi-plataforma."""

    def __init__(self):
        self.discord_send_func: Optional[Callable[[str], Awaitable[None]]] = None
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self._session: Optional[aiohttp.ClientSession] = None

    def register_discord_handler(self, send_func: Callable[[str], Awaitable[None]]):
        """Registra la función de envío de mensajes de Discord."""
        self.discord_send_func = send_func

    def set_telegram_credentials(self, token: str, chat_id: str):
        """Configura credenciales de Telegram si no estaban en el entorno."""
        self.telegram_token = token
        self.telegram_chat_id = chat_id

    async def _get_session(self) -> aiohttp.ClientSession:
        """Obtiene o crea una sesión aiohttp persistente."""
        if self._session is None or self._session.closed:
            import ssl
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE
            connector = aiohttp.TCPConnector(ssl=ssl_ctx)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    async def close(self) -> None:
        """Cierra la sesión HTTP persistente."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def broadcast_message(self, text: str, title: Optional[str] = None, level: str = "INFO") -> Dict[str, bool]:
        """Transmite una notificación a Discord y Telegram simultáneamente."""
        prefix = "⚡" if level == "INFO" else ("⚠️" if level == "WARNING" else "🚨")
        full_text = f"{prefix} **{title}**\n{text}" if title else f"{prefix} {text}"

        results = {"discord": False, "telegram": False}
        tasks = []

        # 1. Enviar a Discord si está registrado
        if self.discord_send_func:
            async def _send_discord():
                try:
                    await self.discord_send_func(full_text)
                    results["discord"] = True
                except Exception as e:
                    logger.error(f"Error despachando notificación a Discord: {e}")
            tasks.append(_send_discord())

        # 2. Enviar a Telegram si están configuradas las credenciales
        if self.telegram_token and self.telegram_chat_id:
            async def _send_telegram():
                try:
                    url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
                    clean_text = full_text.replace("**", "*")  # Telegram Markdown style
                    payload = {
                        "chat_id": self.telegram_chat_id,
                        "text": clean_text,
                        "parse_mode": "Markdown",
                    }
                    session = await self._get_session()
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            results["telegram"] = True
                        else:
                            err_body = await resp.text()
                            logger.error(f"Error Telegram Bot API HTTP {resp.status}: {err_body}")
                except Exception as e:
                    logger.error(f"Error despachando notificación a Telegram: {e}")
            tasks.append(_send_telegram())

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        return results


# Instancia global por defecto
_dispatcher_instance: Optional[NotificationDispatcher] = None


def get_notification_dispatcher() -> NotificationDispatcher:
    global _dispatcher_instance
    if _dispatcher_instance is None:
        _dispatcher_instance = NotificationDispatcher()
    return _dispatcher_instance
