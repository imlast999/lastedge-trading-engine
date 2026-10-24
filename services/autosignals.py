"""
Servicio de Auto-Señales

Maneja el loop automático de detección y envío de señales.
Consolidado desde bot.py para reducir el tamaño del archivo principal.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Any, Dict, List
import discord

logger = logging.getLogger(__name__)

class AutoSignalsService:
    """Servicio para manejo de señales automáticas"""
    
    def __init__(self, bot=None, state=None, config=None):
        self.bot = bot
        if state is None:
            from core import BotState
            state = BotState(autosignals=True)
        self.state = state

        if config is None:
            symbols_str = os.getenv("AUTOSIGNAL_SYMBOLS", "EURUSD,XAUUSD,BTCEUR")
            symbols = [s.strip() for s in symbols_str.split(",") if s.strip()]
            config = {
                'AUTOSIGNAL_SYMBOLS': symbols,
                'AUTOSIGNAL_INTERVAL': int(os.getenv("AUTOSIGNAL_INTERVAL", "60")),
                'SIGNALS_CHANNEL_NAME': os.getenv("DISCORD_CHANNEL_ID") or os.getenv("SIGNALS_CHANNEL_NAME", "signals"),
                'MAX_TRADES_PER_DAY': int(os.getenv("MAX_DAILY_TRADES_ALL", "12")),
                'MAX_TRADES_PER_PERIOD': 6,
                'KILL_SWITCH': False,
                'AUTO_EXECUTE_SIGNALS': os.getenv("AUTO_EXECUTE_SIGNALS", "1") == "1",
            }
        self.config = config
        self.scan_count = 0
        # Cooldown por símbolo: guarda el timestamp de la última señal enviada
        self._last_signal_time: dict = {}   # {symbol: datetime}
        # Cooldown per-symbol (minutes)
        self._cooldown_minutes = {
            'EURUSD': 60,
            'XAUUSD': 240,
            'BTCEUR': 60,
        }
        # Límite de señales en la misma dirección por par por día
        # Evita spam de señales correlacionadas durante tendencias fuertes
        self._daily_direction_count: dict = {}  # {symbol: {'BUY': n, 'SELL': n, 'date': str}}
        self._max_same_direction_per_day = 3

        # Watchdog: track last successful scan time
        self.last_scan_time: Optional[datetime] = None

        # Cooldown de arranque: no enviar señales durante los primeros N segundos
        # Evita señales falsas generadas justo al iniciar el bot
        self._startup_cooldown_seconds = 120   # 2 minutos
        self._startup_time: Optional[datetime] = None   # se fija en start_auto_signal_loop

        # Persistir cooldowns entre reinicios
        self._cooldown_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'autosignals_state.json'
        )
        self._load_cooldown_state()
        
    def _load_cooldown_state(self):
        """Restaura los cooldowns desde disco para sobrevivir reinicios."""
        try:
            if not os.path.exists(self._cooldown_file):
                return
            with open(self._cooldown_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Solo restaurar si el archivo tiene menos de 24h
            saved_at = datetime.fromisoformat(data.get('saved_at', '2000-01-01T00:00:00+00:00'))
            if saved_at.tzinfo is None:
                saved_at = saved_at.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - saved_at).total_seconds() > 86400:
                return
            for sym, ts_str in data.get('last_signal_time', {}).items():
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    self._last_signal_time[sym] = ts
                except Exception:
                    pass
            self._daily_direction_count = data.get('daily_direction_count', {})
            logger.info("AutoSignals: cooldowns restaurados desde disco")
        except Exception as e:
            logger.debug(f"AutoSignals: no se pudo cargar estado de cooldown: {e}")

    def _save_cooldown_state(self):
        """Guarda los cooldowns en disco."""
        try:
            import json as _json
            data = {
                'last_signal_time': {
                    sym: ts.isoformat()
                    for sym, ts in self._last_signal_time.items()
                },
                'daily_direction_count': self._daily_direction_count,
                'saved_at': datetime.now(timezone.utc).isoformat(),
            }
            with open(self._cooldown_file, 'w', encoding='utf-8') as f:
                _json.dump(data, f, indent=2)
        except Exception as e:
            logger.debug(f"AutoSignals: no se pudo guardar estado de cooldown: {e}")

    def _check_direction_limit(self, symbol: str, direction: str) -> bool:
        """
        Devuelve True si se puede enviar la señal (no se ha superado el límite
        de señales en la misma dirección para este par hoy).
        """
        today = datetime.now(timezone.utc).date().isoformat()
        entry = self._daily_direction_count.get(symbol, {})
        # Resetear si es un día nuevo
        if entry.get('date') != today:
            entry = {'date': today, 'BUY': 0, 'SELL': 0}
            self._daily_direction_count[symbol] = entry
        return entry.get(direction, 0) < self._max_same_direction_per_day

    def _register_direction(self, symbol: str, direction: str):
        """Incrementa el contador de señales en esta dirección para hoy."""
        today = datetime.now(timezone.utc).date().isoformat()
        entry = self._daily_direction_count.setdefault(symbol, {'date': today, 'BUY': 0, 'SELL': 0})
        if entry.get('date') != today:
            entry.update({'date': today, 'BUY': 0, 'SELL': 0})
        entry[direction] = entry.get(direction, 0) + 1

    async def find_signals_channel(self) -> Optional[discord.TextChannel]:
        """Encuentra el canal de señales por ID o nombre si bot está disponible"""
        if not self.bot:
            return None
        target = str(self.config.get('SIGNALS_CHANNEL_NAME', 'signals')).strip()
        try:
            if target.isdigit():
                ch = self.bot.get_channel(int(target))
                if ch:
                    return ch
            guilds = getattr(self.bot, 'guilds', []) or []
            for guild in guilds:
                for channel in getattr(guild, 'text_channels', []):
                    if str(channel.id) == target or channel.name == target:
                        return channel
        except Exception as e:
            logger.debug(f"find_signals_channel exception: {e}")
        return None
    
    async def start_auto_signal_loop(self):
        """Inicia el loop principal de auto-señales"""
        if self.bot and hasattr(self.bot, 'wait_until_ready'):
            try:
                await self.bot.wait_until_ready()
            except Exception:
                pass

        from services.logging import log_event
        from core.circuit_breaker import get_circuit_breaker

        self._circuit_breaker = get_circuit_breaker()
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5
        self._startup_time = datetime.now(timezone.utc)   # marcar arranque

        log_event(
            f'Auto-signal loop iniciado '
            f'(AUTOSIGNALS={self.state.autosignals}, '
            f'AUTO_EXECUTE={self.config["AUTO_EXECUTE_SIGNALS"]}) '
            f'| Cooldown arranque: {self._startup_cooldown_seconds}s'
        )

        while True:
            try:
                if self.state.autosignals and not self.config['KILL_SWITCH']:
                    # ── Cooldown de arranque ──────────────────────────────────
                    if self._startup_time is not None:
                        elapsed_startup = (datetime.now(timezone.utc) - self._startup_time).total_seconds()
                        if elapsed_startup < self._startup_cooldown_seconds:
                            remaining = int(self._startup_cooldown_seconds - elapsed_startup)
                            if self.scan_count % 6 == 0:   # log cada ~2 min
                                log_event(
                                    f"⏳ Cooldown de arranque: {remaining}s restantes — "
                                    f"señales pausadas para evitar falsas al inicio",
                                    "INFO", "AUTOSIGNAL"
                                )
                            self._consecutive_errors = 0
                            await asyncio.sleep(self.config['AUTOSIGNAL_INTERVAL'])
                            continue

                    # Verificar circuit breaker antes de escanear
                    can_trade, cb_reason = self._circuit_breaker.can_trade()
                    if not can_trade:
                        if self.scan_count % 30 == 0:
                            log_event(f"⏸️ Circuit breaker activo: {cb_reason}", "WARNING", "AUTOSIGNAL")
                    else:
                        await self._scan_symbols()

                    # Second-level watchdog: check if scan is stuck (>30 min without scanning)
                    # Solo alertar si el CB NO está activo — durante pausa es comportamiento normal
                    cb_active = not self._circuit_breaker.can_trade()[0]
                    if self.last_scan_time is not None and not cb_active:
                        elapsed_since_scan = (datetime.now(timezone.utc) - self.last_scan_time).total_seconds() / 60
                        if elapsed_since_scan > 30:
                            logger.critical(
                                "AUTOSIGNAL WATCHDOG: No scan in %.1f minutes! Bot may be stuck.",
                                elapsed_since_scan
                            )
                            log_event(
                                f"🚨 WATCHDOG: Sin escaneo en {elapsed_since_scan:.0f} minutos. "
                                f"El bot puede estar bloqueado.",
                                "CRITICAL", "AUTOSIGNAL"
                            )
                            try:
                                channel = await self.find_signals_channel()
                                if channel:
                                    await channel.send(
                                        f"🚨 **ALERTA WATCHDOG**: El bot no ha escaneado señales en "
                                        f"**{elapsed_since_scan:.0f} minutos**. "
                                        f"Puede estar bloqueado. Revisa los logs."
                                    )
                            except Exception as wde:
                                logger.error(f"Watchdog Discord notification error: {wde}")
                            # Reset to avoid repeated alerts
                            self.last_scan_time = datetime.now(timezone.utc)

                self._consecutive_errors = 0  # reset en cada iteración exitosa
                await asyncio.sleep(self.config['AUTOSIGNAL_INTERVAL'])

            except asyncio.CancelledError:
                log_event("Auto-signal loop cancelado", "WARNING", "AUTOSIGNAL")
                break
            except Exception as e:
                self._consecutive_errors += 1
                logger.error(f"Error en auto-signal loop (intento {self._consecutive_errors}): {e}")

                if self._consecutive_errors >= self._max_consecutive_errors:
                    log_event(
                        f"❌ Auto-signal loop: {self._consecutive_errors} errores consecutivos. "
                        f"Pausando 5 minutos.",
                        "ERROR", "AUTOSIGNAL"
                    )
                    await asyncio.sleep(300)
                    self._consecutive_errors = 0
                else:
                    await asyncio.sleep(30)
    
    def _check_expired_signals(self) -> int:
        """
        Comprueba señales en enhanced_signals con estado 'PROPOSED'.
        Si (now - created_at) > 10 minutos (600s), marca automáticamente su estado como 'EXPIRED'.
        Registra evento informativo: [AutoSignals] Señal #{id} ({symbol}) expirada tras 10 min sin confirmación.
        """
        try:
            from services.database import get_database_manager
            from services.logging import log_event
            db_mgr = get_database_manager()
            now_utc = datetime.now(timezone.utc)
            expired_count = 0
            with db_mgr.get_connection() as conn:
                rows = conn.execute(
                    """SELECT id, symbol, created_at, timestamp, status
                       FROM enhanced_signals
                       WHERE status = 'PROPOSED'"""
                ).fetchall()

                for row in rows:
                    sig_id = row["id"]
                    symbol = row["symbol"]
                    raw_time = row["created_at"] or row["timestamp"]
                    if not raw_time:
                        continue
                    try:
                        clean_time = str(raw_time).strip().replace("Z", "+00:00")
                        created_dt = datetime.fromisoformat(clean_time)
                        if created_dt.tzinfo is None:
                            created_dt = created_dt.replace(tzinfo=timezone.utc)
                        age_seconds = (now_utc - created_dt).total_seconds()
                    except Exception:
                        continue

                    if age_seconds > 600:
                        conn.execute(
                            "UPDATE enhanced_signals SET status = 'EXPIRED' WHERE id = ?",
                            (sig_id,)
                        )
                        expired_count += 1
                        msg = f"[AutoSignals] Señal #{sig_id} ({symbol}) expirada tras 10 min sin confirmación"
                        logger.info(f"⏳ {msg}")
                        log_event(msg, "INFO", "AUTOSIGNAL")

            return expired_count
        except Exception as e:
            logger.debug(f"[AutoSignals] Error comprobando señales expiradas: {e}")
            return 0

    async def _scan_symbols(self):
        """Escanea todos los símbolos configurados"""
        from services.logging import log_event

        # Comprobar y expirar automáticamente señales pendientes con TTL > 10 min
        self._check_expired_signals()

        # Update last scan time for watchdog
        self.last_scan_time = datetime.now(timezone.utc)

        self.scan_count += 1
        symbols_str = ", ".join(self.config['AUTOSIGNAL_SYMBOLS'])
        if self.scan_count == 1 or self.scan_count % 3 == 0:
            log_event(
                f"🔍 AUTOSIGNAL SCAN #{self.scan_count}: Escaneando {len(self.config['AUTOSIGNAL_SYMBOLS'])} pares ({symbols_str}) | Conexión MT5: OK",
                "INFO",
                "AUTOSIGNAL"
            )

        channel = await self.find_signals_channel() if self.bot else None
        if channel is None and self.scan_count % 50 == 1:
            log_event(
                f"ℹ️ Canal de Discord no conectado o en modo headless. "
                f"Las señales se registrarán en base de datos, dashboard y Telegram.",
                "INFO", "AUTOSIGNAL"
            )

        signals_found = 0
        for symbol in self.config['AUTOSIGNAL_SYMBOLS']:
            try:
                signal_sent = await self._process_symbol(symbol, channel)
                if signal_sent:
                    signals_found += 1
            except Exception as e:
                logger.error(f"Error procesando símbolo {symbol}: {e}", exc_info=True)

        if self.scan_count % 30 == 0:
            await self._log_periodic_stats()
    
    async def _process_symbol(self, symbol: str, channel: Optional[Any] = None) -> bool:
        """Procesa un símbolo individual"""
        try:
            from services.logging import log_event
            from core import get_trading_engine
            
            # Obtener engine de trading
            engine = get_trading_engine()
            if not engine:
                if self.scan_count % 100 == 1:
                    log_event("Trading engine not available", "WARNING", "AUTOSIGNAL")
                return False
            
            # Obtener datos de mercado
            # Garantizar historial suficiente para estrategias macro H4/H1 (BTCEUR requiere >= 850)
            try:
                required_count = 1000 if symbol.upper() == 'BTCEUR' else 300
                min_candles = 850 if symbol.upper() == 'BTCEUR' else 210
                df = await engine.get_market_data(symbol, timeframe='H1', count=required_count)
                if df is None or len(df) == 0:
                    return False
                if len(df) < min_candles:
                    if self.scan_count % 20 == 1:
                        log_event(f"⚠️ {symbol}: solo {len(df)} velas disponibles (mínimo {min_candles})", "WARNING", "AUTOSIGNAL")
                    return False
            except Exception as e:
                if self.scan_count % 50 == 1:
                    log_event(f"Error getting market data for {symbol}: {e}", "WARNING", "AUTOSIGNAL")
                return False
            
            # Evaluar señal usando el ENGINE COMPLETO (no directamente la estrategia)
            try:
                # Obtener configuración del símbolo
                import json
                import os
                rules_config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules_config.json')
                
                try:
                    with open(rules_config_path, 'r') as f:
                        rules = json.load(f)
                    symbol_config = rules.get(symbol, {})
                    strategy_name = symbol_config.get('strategy', 'ema50_200')
                except Exception:
                    strategy_name = 'ema50_200'
                
                # Usar el engine completo (mismo pipeline que replay)
                result = engine.evaluate_signal(
                    df, 
                    symbol, 
                    strategy_name,
                    symbol_config,
                    skip_duplicate_filter=False  # En producción SÍ usar filtro de duplicados
                )
                
                # Si no hay señal o no debe mostrarse, salir
                if not result.signal or not result.should_show:
                    return False
                
                signal = result.signal
                confidence = result.confidence
                score = result.score
                
                # FILTRO DE CONFIANZA: Rechazar señales LOW
                if confidence in ['LOW', 'VERY_LOW']:
                    if self.scan_count % 20 == 1:
                        log_event(f"{symbol} signal rejected: LOW confidence", "INFO", "AUTOSIGNAL")
                    return False

                # NEWS FILTER: pause during high-impact news blackout windows
                try:
                    from services.news_filter import NewsFilter
                    news_filter = NewsFilter()
                    is_blackout, blackout_reason = news_filter.is_news_blackout(symbol)
                    if is_blackout:
                        logger.debug(f"[{symbol}] News blackout: {blackout_reason}")
                        return False
                except Exception as nfe:
                    logger.debug(f"News filter error for {symbol}: {nfe}")

                # COOLDOWN POR SÍMBOLO: evitar spam del mismo par
                now = datetime.now(timezone.utc)
                last_sent = self._last_signal_time.get(symbol)
                cooldown_min = self._cooldown_minutes.get(symbol, 60)
                if last_sent is not None:
                    elapsed_min = (now - last_sent).total_seconds() / 60
                    if elapsed_min < cooldown_min:
                        remaining = int(cooldown_min - elapsed_min)
                        if self.scan_count % 20 == 1:
                            log_event(
                                f"⏳ {symbol}: cooldown activo, {remaining} min restantes",
                                "INFO", "AUTOSIGNAL"
                            )
                        return False

                # LÍMITE DE DIRECCIÓN: máximo 3 señales en la misma dirección por par por día
                signal_direction = result.signal.get('type', 'BUY').upper()
                if not self._check_direction_limit(symbol, signal_direction):
                    if self.scan_count % 20 == 1:
                        log_event(
                            f"🚫 {symbol}: límite de {self._max_same_direction_per_day} señales "
                            f"{signal_direction} alcanzado hoy",
                            "INFO", "AUTOSIGNAL"
                        )
                    return False

            except Exception as e:
                if self.scan_count % 50 == 1:
                    log_event(f"Error evaluating signal for {symbol}: {e}", "WARNING", "AUTOSIGNAL")
                return False
            
            # Señal aprobada - enviar al canal
            try:
                # Formatear mensaje de señal
                signal_type = signal.get('type', 'BUY').upper()
                entry = signal.get('entry', 0)
                sl = signal.get('sl', 0)
                tp = signal.get('tp', 0)
                # Determinar si es auto-aprobada (HIGH o VERY_HIGH)
                auto_approved = confidence in ['HIGH', 'VERY_HIGH']
                
                # Calcular R:R ratio
                risk = abs(entry - sl)
                reward = abs(tp - entry)
                rr_ratio = reward / risk if risk > 0 else 0

                # Crear embed de señal
                if auto_approved:
                    embed_color = 0xFFD700  # Dorado para señales auto-aprobadas
                    embed = discord.Embed(
                        title=f"⭐ 🎯 {signal_type} {symbol}",
                        description="✅ AUTO-APROBADA",
                        color=embed_color,
                        timestamp=datetime.now(timezone.utc)
                    )
                else:
                    embed_color = 0xFFA500  # Ámbar/dorado para señales pendientes de confirmación
                    embed = discord.Embed(
                        title=f"⏸️ SEÑAL PENDIENTE DE CONFIRMACIÓN | {signal_type} {symbol}",
                        description="👉 Pulsa \"Aprobar\" en tu Web Dashboard para ejecutarla en MT5.",
                        color=embed_color,
                        timestamp=datetime.now(timezone.utc)
                    )
                
                embed.add_field(name="📈 Entry", value=f"{entry:.5f}", inline=True)
                embed.add_field(name="🛡️ Stop Loss", value=f"{sl:.5f}", inline=True)
                embed.add_field(name="🎯 Take Profit", value=f"{tp:.5f}", inline=True)
                embed.add_field(name="⚖️ R:R Ratio", value=f"1:{rr_ratio:.2f}", inline=True)
                embed.add_field(name="⭐ Confidence", value=confidence, inline=True)
                embed.add_field(name="⚙️ Strategy", value=strategy_name, inline=True)
                
                if auto_approved:
                    embed.set_footer(text="Auto-Signal System | AUTO-APROBADA ✅")
                else:
                    embed.set_footer(text="Aprobación requerida vía Dashboard")
                
                # Generar gráfico con la señal si Discord está conectado
                if channel:
                    chart_file = None
                    try:
                        from charts import generate_chart
                        chart_filename = generate_chart(df, symbol=symbol, signal=signal)
                        if chart_filename:
                            chart_file = discord.File(chart_filename, filename=f"{symbol}_signal.png")
                            embed.set_image(url=f"attachment://{symbol}_signal.png")
                    except Exception as chart_error:
                        logger.warning(f"Error generando gráfico para {symbol}: {chart_error}")
                    
                    if chart_file:
                        await channel.send(embed=embed, file=chart_file)
                        try:
                            import os
                            os.remove(chart_filename)
                        except Exception:
                            pass
                    else:
                        await channel.send(embed=embed)
                
                # Log señal enviada
                approval_status = "AUTO-APROBADA ✅" if auto_approved else "MANUAL ⏳"
                log_event(
                    f"🎯 AUTO-SIGNAL: {signal_type} {symbol} @ {entry:.5f} "
                    f"(SL: {sl:.5f}, TP: {tp:.5f}, Conf: {confidence}) [{approval_status}]",
                    "INFO", "AUTOSIGNAL"
                )
                
                # Registro de actividad por símbolo (métricas dashboard)
                try:
                    from core import record_signal
                    record_signal(symbol.upper())
                except Exception:
                    pass

                # ── Guardar señal en Base de Datos (enhanced_signals) para Dashboard y Mobile ──
                saved_signal_id = None
                try:
                    from services.mobile_store import get_mobile_store
                    m_store = get_mobile_store()
                    saved_signal_id = m_store.insert_signal(
                        symbol=symbol.upper(),
                        direction=signal_type,
                        price=float(entry),
                        tp_price=float(tp),
                        sl_price=float(sl),
                        lot_size=float(signal.get('lot_size', 0.01)),
                        confidence_score=float(score) if isinstance(score, (int, float)) else 0.8,
                        confidence=confidence,
                        strategy=strategy_name,
                        status='OPEN' if auto_approved else 'PROPOSED'
                    )
                except Exception as db_err:
                    logger.error(f"[AutoSignals] Error guardando señal en enhanced_signals: {db_err}")

                # Actualizar cooldown — evitar spam del mismo par
                self._last_signal_time[symbol] = datetime.now(timezone.utc)
                # Registrar dirección para el límite diario
                self._register_direction(symbol, signal_type)
                # Persistir cooldowns en disco
                self._save_cooldown_state()

                # ── MODO REAL: ejecutar orden en MT5 si está activo ───────────
                auto_execute = os.getenv('AUTO_EXECUTE_SIGNALS', '1') == '1'
                min_confidence = os.getenv('AUTO_EXECUTE_CONFIDENCE', 'HIGH')
                confidence_rank = {'LOW': 0, 'MEDIUM': 1, 'MEDIUM-HIGH': 2, 'HIGH': 3, 'VERY_HIGH': 4}
                signal_rank = confidence_rank.get(confidence, 0)
                required_rank = confidence_rank.get(min_confidence, 3)
                exec_success = False

                if auto_execute and signal_rank >= required_rank:
                    try:
                        from services.execution import get_execution_service
                        exec_svc = get_execution_service()
                        exec_result = exec_svc.execute_signal(signal)
                        if exec_result.success:
                            exec_success = True
                            log_event(
                                f"✅ ORDEN REAL ejecutada: {signal_type} {symbol} @ {entry:.5f} "
                                f"| Ticket: {exec_result.order_id}",
                                "INFO", "AUTOSIGNAL"
                            )
                            # Actualizar estado en DB si se guardó la señal
                            if saved_signal_id:
                                try:
                                    from services.mobile_store import get_mobile_store
                                    get_mobile_store().update_signal_status(saved_signal_id, 'EXECUTED')
                                except Exception:
                                    pass

                            # ── Slippage tracking ─────────────────────────────
                            try:
                                exec_price = exec_result.details.get('mt5_result', {}).get('price', entry) if hasattr(exec_result, 'details') and exec_result.details else entry
                                if exec_price and entry:
                                    pip_size = 0.01 if symbol == 'XAUUSD' else (1.0 if symbol == 'BTCEUR' else 0.0001)
                                    slippage_pips = abs(float(exec_price) - float(entry)) / pip_size
                                    log_event(
                                        f"📊 SLIPPAGE {symbol}: entry={entry:.5f} exec={exec_price:.5f} "
                                        f"slippage={slippage_pips:.1f} pips",
                                        "INFO", "AUTOSIGNAL"
                                    )
                            except Exception as slip_err:
                                logger.debug(f"Slippage tracking error: {slip_err}")

                            # ── Trailing stop integration (desacoplado) ────────
                            try:
                                from services.trailing_stops import get_trailing_manager
                                trailing_mgr = get_trailing_manager()
                                if trailing_mgr and exec_result.order_id:
                                    trailing_mgr.add_position_to_trail(
                                        ticket=exec_result.order_id,
                                        symbol=symbol,
                                        entry_price=float(entry),
                                        original_sl=float(sl),
                                        original_tp=float(tp),
                                        trade_type=signal_type
                                    )
                                    log_event(
                                        f"🔄 Trailing stop activado para ticket {exec_result.order_id}",
                                        "INFO", "AUTOSIGNAL"
                                    )
                            except Exception as trail_err:
                                logger.debug(f"Trailing stop integration error: {trail_err}")
                        else:
                            log_event(
                                f"❌ Error ejecutando orden real: {exec_result.message}",
                                "ERROR", "AUTOSIGNAL"
                            )
                    except Exception as exec_err:
                        log_event(f"❌ Error en ejecución real: {exec_err}", "ERROR", "AUTOSIGNAL")

                # ── Notificación Proactiva a Telegram ─────────────────────────
                try:
                    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
                    tg_chat_id = os.getenv("TELEGRAM_CHAT_ID")
                    if tg_token and tg_chat_id:
                        from services.telegram_adapter import TelegramAdapter
                        tg_adapter = TelegramAdapter(token=tg_token, chat_id=tg_chat_id)
                        if not auto_approved:
                            tg_text = (
                                "⏸️ *SEÑAL PENDIENTE DE CONFIRMACIÓN*\n"
                                "━━━━━━━━━━━━━━━━━━\n"
                                f"Par: {symbol} | Dirección: {signal_type}\n"
                                f"Precio: {entry:.5f}\n"
                                f"SL: {sl:.5f} | TP: {tp:.5f} | R:R: 1:{rr_ratio:.2f}\n"
                                f"Confianza: {confidence} | Estrategia: {strategy_name}\n"
                                "━━━━━━━━━━━━━━━━━━\n"
                                "👉 Pulsa \"Aprobar\" en tu Web Dashboard para ejecutarla en MT5."
                            )
                        else:
                            status_label = "✅ EJECUTADA EN MT5" if exec_success else "🟢 AUTO-APROBADA"
                            tg_text = (
                                f"🎯 *SEÑAL {signal_type} {symbol}*\n"
                                f"━━━━━━━━━━━━━━━━━━\n"
                                f"📈 *Entrada:* `{entry:.5f}`\n"
                                f"🛡️ *Stop Loss:* `{sl:.5f}`\n"
                                f"🎯 *Take Profit:* `{tp:.5f}`\n"
                                f"⚖️ *R:R Ratio:* `1:{rr_ratio:.2f}`\n"
                                f"⭐ *Confianza:* *{confidence}* ({score:.2f})\n"
                                f"⚙️ *Estrategia:* `{strategy_name}`\n"
                                f"🚀 *Estado:* *{status_label}*\n"
                                f"⏰ `{datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}`"
                            )
                        await tg_adapter.send_message(tg_text)
                except Exception as tg_err:
                    logger.debug(f"[AutoSignals] Error enviando alerta Telegram: {tg_err}")
                
                return True
                
            except Exception as e:
                log_event(f"Error sending signal for {symbol}: {e}", "ERROR", "AUTOSIGNAL")
                return False
                
        except Exception as e:
            log_event(f"Unexpected error processing {symbol}: {e}", "ERROR", "AUTOSIGNAL")
            return False
    
    async def _log_periodic_stats(self):
        """Log de estadísticas periódicas"""
        from services.logging import log_event
        from core import get_filters_system
        
        try:
            # Obtener estadísticas del filtro de duplicados
            filters_system = get_filters_system()
            filter_stats = filters_system.get_stats()
            
            # Calcular tiempo de sesión (evitar naive vs aware)
            from services.logging import get_intelligent_logger
            logger_instance = get_intelligent_logger()
            session_start = getattr(logger_instance, 'last_dump', None) or datetime.now(timezone.utc)
            if session_start.tzinfo is None:
                session_start = session_start.replace(tzinfo=timezone.utc)
            now_utc = datetime.now(timezone.utc)
            session_duration = (now_utc - session_start).total_seconds() / 3600
            
            log_event(
                f"📊 STATS: {filter_stats.get('total_signals', 0)} señales evaluadas, "
                f"{filter_stats.get('shown_signals', 0)} mostradas, "
                f"sesión: {session_duration:.1f}h",
                "INFO", "AUTOSIGNAL"
            )
            
        except Exception as e:
            logger.error(f"Error en estadísticas periódicas: {e}")

def create_autosignals_service(bot=None, state=None, config=None):
    """Factory para crear el servicio de auto-señales, soporta modo headless"""
    return AutoSignalsService(bot, state, config)


# Alias para compatibilidad con verificadores
AutoSignalsEngine = AutoSignalsService

__all__ = ["AutoSignalsService", "AutoSignalsEngine", "create_autosignals_service"]