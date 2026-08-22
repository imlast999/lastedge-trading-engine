"""
Sistema de Reconexión Automática para Bot MT5
Maneja reconexiones automáticas de MT5 y Discord con retry logic
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Callable, Any
import MetaTrader5 as mt5
from services.mt5_client import initialize as mt5_initialize, login as mt5_login

logger = logging.getLogger(__name__)

class ReconnectionSystem:
    """Sistema de reconexión automática con watchdog"""
    
    def __init__(self):
        self.mt5_connected = False
        self.discord_connected = False
        self.last_mt5_check = time.time()
        self.last_discord_check = time.time()
        self.mt5_retry_count = 0
        self.discord_retry_count = 0
        self.max_retries = 5
        self.retry_delay = 30  # segundos
        self.watchdog_interval = 60  # verificar cada minuto
        self.is_running = False
        
        # Callbacks para notificaciones
        self.on_mt5_reconnect: Optional[Callable] = None
        self.on_discord_reconnect: Optional[Callable] = None
        self.on_connection_lost: Optional[Callable] = None
        
    def set_callbacks(self, 
                     mt5_reconnect: Optional[Callable] = None,
                     discord_reconnect: Optional[Callable] = None,
                     connection_lost: Optional[Callable] = None):
        """Configurar callbacks para eventos de reconexión"""
        self.on_mt5_reconnect = mt5_reconnect
        self.on_discord_reconnect = discord_reconnect
        self.on_connection_lost = connection_lost
    
    def log_reconnection_event(self, message: str, level: str = "INFO"):
        """Log personalizado para eventos de reconexión"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        console_msg = f"[{timestamp}] 🔄 RECONNECTION: {message}"
        print(console_msg)
        
        if level.upper() == "ERROR":
            logger.error(f"RECONNECTION: {message}")
        elif level.upper() == "WARNING":
            logger.warning(f"RECONNECTION: {message}")
        else:
            logger.info(f"RECONNECTION: {message}")
    
    async def check_mt5_connection(self) -> bool:
        """Verificar estado de conexión MT5"""
        try:
            # Verificar si MT5 está inicializado
            if not mt5.initialize():
                return False
            
            # Verificar si podemos obtener información de cuenta
            account_info = mt5.account_info()
            if account_info is None:
                return False
            
            # Verificar si podemos obtener datos de mercado
            symbol_info = mt5.symbol_info("EURUSD")
            if symbol_info is None:
                return False
            
            self.last_mt5_check = time.time()
            return True
            
        except Exception as e:
            try:
                from services.long_forward_validation import get_long_forward_validation_service
                get_long_forward_validation_service().notify_mt5_disconnect()
            except Exception:
                pass
            self.log_reconnection_event(f"MT5 connection check failed: {e}", "ERROR")
            return False
    
    async def check_discord_connection(self, bot) -> bool:
        """Verificar estado de conexión Discord"""
        try:
            if bot is None:
                return False
            
            # Verificar si el bot está conectado
            if not bot.is_ready():
                return False
            
            # Verificar si podemos acceder a guilds
            if not bot.guilds:
                return False
            
            self.last_discord_check = time.time()
            return True
            
        except Exception as e:
            self.log_reconnection_event(f"Discord connection check failed: {e}", "ERROR")
            return False
    
    async def reconnect_mt5(self, credentials: dict = None) -> bool:
        """Intentar reconectar MT5"""
        try:
            self.log_reconnection_event(f"Attempting MT5 reconnection (attempt {self.mt5_retry_count + 1}/{self.max_retries})")
            
            # Cerrar conexión existente
            try:
                mt5.shutdown()
                await asyncio.sleep(2)
            except:
                pass
            
            # Intentar reconectar
            if not mt5_initialize():
                raise Exception("MT5 initialization failed")
            
            # Si tenemos credenciales, intentar login
            if credentials:
                login_result = mt5_login(
                    credentials.get('login'),
                    credentials.get('password'),
                    credentials.get('server')
                )
                if not login_result:
                    raise Exception("MT5 login failed")
            
            # Verificar conexión
            if await self.check_mt5_connection():
                self.mt5_connected = True
                self.mt5_retry_count = 0
                self.log_reconnection_event("✅ MT5 reconnection successful")
                
                try:
                    from services.long_forward_validation import get_long_forward_validation_service
                    get_long_forward_validation_service().notify_mt5_reconnect()
                except Exception:
                    pass

                if self.on_mt5_reconnect:
                    await self.on_mt5_reconnect()
                
                return True
            else:
                raise Exception("MT5 connection verification failed")
                
        except Exception as e:
            self.mt5_retry_count += 1
            self.log_reconnection_event(f"❌ MT5 reconnection failed: {e}", "ERROR")
            return False
    
    async def reconnect_discord(self, bot) -> bool:
        """Intentar reconectar Discord"""
        try:
            self.log_reconnection_event(f"Attempting Discord reconnection (attempt {self.discord_retry_count + 1}/{self.max_retries})")
            
            # Discord se reconecta automáticamente, solo verificamos
            await asyncio.sleep(5)  # Dar tiempo para reconexión automática
            
            if await self.check_discord_connection(bot):
                self.discord_connected = True
                self.discord_retry_count = 0
                self.log_reconnection_event("✅ Discord reconnection successful")
                
                if self.on_discord_reconnect:
                    await self.on_discord_reconnect()
                
                return True
            else:
                raise Exception("Discord connection verification failed")
                
        except Exception as e:
            self.discord_retry_count += 1
            self.log_reconnection_event(f"❌ Discord reconnection failed: {e}", "ERROR")
            return False
    
    async def watchdog_loop(self, bot, mt5_credentials: dict = None):
        """Loop principal del watchdog"""
        self.is_running = True
        self.log_reconnection_event("🐕 Watchdog started - Monitoring connections every 60s")
        
        while self.is_running:
            try:
                # Verificar MT5
                mt5_ok = await self.check_mt5_connection()
                if not mt5_ok and self.mt5_connected:
                    self.mt5_connected = False
                    self.log_reconnection_event("⚠️ MT5 connection lost", "WARNING")
                    
                    if self.on_connection_lost:
                        await self.on_connection_lost("MT5")
                
                # Verificar Discord
                discord_ok = await self.check_discord_connection(bot)
                if not discord_ok and self.discord_connected:
                    self.discord_connected = False
                    self.log_reconnection_event("⚠️ Discord connection lost", "WARNING")
                    
                    if self.on_connection_lost:
                        await self.on_connection_lost("Discord")
                
                # Intentar reconexiones si es necesario
                if not mt5_ok and self.mt5_retry_count < self.max_retries:
                    await self.reconnect_mt5(mt5_credentials)
                    await asyncio.sleep(self.retry_delay)
                
                if not discord_ok and self.discord_retry_count < self.max_retries:
                    await self.reconnect_discord(bot)
                    await asyncio.sleep(self.retry_delay)
                
                # Actualizar estados
                self.mt5_connected = mt5_ok
                self.discord_connected = discord_ok
                
                # Log estado cada 10 minutos
                if int(time.time()) % 600 == 0:  # Cada 10 minutos
                    status = f"MT5: {'✅' if self.mt5_connected else '❌'}, Discord: {'✅' if self.discord_connected else '❌'}"
                    self.log_reconnection_event(f"Connection status - {status}")
                
                await asyncio.sleep(self.watchdog_interval)
                
            except Exception as e:
                self.log_reconnection_event(f"Watchdog error: {e}", "ERROR")
                await asyncio.sleep(self.watchdog_interval)
    
    def stop_watchdog(self):
        """Detener el watchdog"""
        self.is_running = False
        self.log_reconnection_event("🐕 Watchdog stopped")
    
    def get_connection_status(self) -> dict:
        """Obtener estado actual de las conexiones"""
        return {
            'mt5_connected': self.mt5_connected,
            'discord_connected': self.discord_connected,
            'mt5_retry_count': self.mt5_retry_count,
            'discord_retry_count': self.discord_retry_count,
            'last_mt5_check': self.last_mt5_check,
            'last_discord_check': self.last_discord_check,
            'watchdog_running': self.is_running
        }

# Instancia global
reconnection_system = ReconnectionSystem()