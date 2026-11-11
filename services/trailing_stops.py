"""
Sistema de Trailing Stops automático y robusto para el motor LastEdge MT5
========================================================================
Protege ganancias con:
1. Breakeven temprano y dinámico (por R-múltiplo o % de TP) con colchón de spread.
2. Trailing Stop en unidades reales de precio (independiente de dígitos del bróker).
3. Cierre Parcial con validación estricta de brokers ECN (precio, filling mode y lotes mínimos).
4. Persistencia en base de datos SQLite (sobrevive a reinicios de PM2 / VPS).
5. Tolerancia a fallos: NUNCA borra estado en micro-cortes de red ni desconexiones temporales.
6. Auto-adopción automática de posiciones abiertas/huérfanas al reiniciar el motor.
"""

from __future__ import annotations

import os
import json
import logging
import asyncio
import threading
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional, Any
import MetaTrader5 as mt5

logger = logging.getLogger(__name__)


def _load_default_config() -> dict:
    """Carga configuración desde rules_config.json si existe."""
    try:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'rules_config.json'
        )
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('trailing_stops', {})
    except Exception as e:
        logger.debug(f"No se pudo cargar rules_config.json para trailing stops: {e}")
    return {}


class TrailingStopManager:
    """Gestor de trailing stops automático con persistencia y tolerancia a fallos."""

    def __init__(self, config: Optional[dict] = None, db_service: Optional[Any] = None):
        cfg = config if config is not None else _load_default_config()
        self.config = cfg
        
        # Parámetros operativos
        self.enabled: bool = cfg.get('enabled', True)
        self.breakeven_r: float = float(cfg.get('breakeven_r_multiple', 0.8))
        self.breakeven_tp_pct: float = float(cfg.get('breakeven_at_profit_pct', 30)) / 100.0
        self.trailing_start_r: float = float(cfg.get('trailing_start_r_multiple', 1.2))
        self.trailing_start_tp_pct: float = float(cfg.get('trailing_start_pct', 50)) / 100.0
        self.partial_close_r: float = float(cfg.get('partial_close_r_multiple', 1.5))
        self.partial_close_tp_pct: float = float(cfg.get('partial_close_pct', 70)) / 100.0
        self.partial_close_amount: float = float(cfg.get('partial_close_amount', 50)) / 100.0
        
        # Distancias reales de trailing en unidades de precio
        # (Ej: 5.0 en XAUUSD = $5.00 USD, 0.0015 en EURUSD = 15 pips)
        self.price_distances: Dict[str, float] = cfg.get('price_distances', {
            'EURUSD': 0.0015,
            'GBPUSD': 0.0020,
            'XAUUSD': 5.0,
            'BTCEUR': 500.0,
            'BTCUSD': 500.0
        })

        # Servicio de base de datos para persistencia
        self.db_service = db_service
        if self.db_service is None:
            try:
                from services.database import get_database_service
                self.db_service = get_database_service()
            except Exception as e:
                logger.debug(f"DatabaseService no disponible directamente: {e}")
                self.db_service = None

        # Cargar trails persistidos en BD para sobrevivir a reinicios
        self.active_trails: Dict[int, dict] = {}
        if self.db_service and hasattr(self.db_service, 'load_all_trailing_stops'):
            try:
                self.active_trails = self.db_service.load_all_trailing_stops()
                if self.active_trails:
                    logger.info(f"🔄 TrailingStopManager: {len(self.active_trails)} trails restaurados desde BD.")
            except Exception as e:
                logger.warning(f"Error cargando trailing stops desde BD: {e}")

    def add_position_to_trail(self, ticket: int, symbol: str, entry_price: float,
                             original_sl: float, original_tp: float, trade_type: str):
        """Añade una posición al sistema de trailing stops y la persiste."""
        try:
            trail_data = {
                'symbol': symbol,
                'entry_price': float(entry_price),
                'original_sl': float(original_sl),
                'original_tp': float(original_tp),
                'trade_type': trade_type.upper(),
                'current_sl': float(original_sl),
                'highest_profit': 0.0,
                'breakeven_moved': False,
                'trailing_active': False,
                'partial_closed': False,
                'last_r_locked_notified': 0.0,
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            self.active_trails[ticket] = trail_data

            if self.db_service and hasattr(self.db_service, 'save_trailing_stop'):
                self.db_service.save_trailing_stop(ticket, trail_data)

            logger.info(
                f"🛡️ TrailingStop: Posición {ticket} registrada ({symbol} {trade_type} "
                f"Entry={entry_price:.5f}, SL={original_sl:.5f}, TP={original_tp:.5f})"
            )
        except Exception as e:
            logger.exception(f"Error registrando posición {ticket} en trailing stops: {e}")

    def update_all_trailing_stops(self):
        """
        Escanea todas las posiciones abiertas en MT5, auto-adopta huérfanas
        y actualiza los trailing stops con protección contra micro-cortes.
        """
        if not self.enabled:
            return

        try:
            positions = mt5.positions_get()

            # ── PROTECCIÓN CRÍTICA #1: Micro-cortes y lags de red ──────────
            # mt5.positions_get() devuelve None si hay un micro-corte de conexión.
            # NUNCA debemos borrar la memoria si positions es None.
            if positions is None:
                err = mt5.last_error()
                logger.warning(
                    f"⚠️ mt5.positions_get() retornó None (posible micro-corte o timeout: {err}). "
                    f"Se conservan los {len(self.active_trails)} trails activos en memoria."
                )
                return

            # Si devuelve lista vacía (), verificamos salud antes de limpiar
            if len(positions) == 0:
                if self.active_trails:
                    term_info = mt5.terminal_info()
                    if term_info is None or not getattr(term_info, 'connected', True):
                        logger.warning("Terminal MT5 desconectada; conservando trails activos.")
                        return

                    # Limpieza segura si verdaderamente no hay posiciones
                    for t in list(self.active_trails.keys()):
                        self._delete_trail(t)
                    self.active_trails.clear()
                return

            open_tickets = {pos.ticket for pos in positions}

            # ── PROTECCIÓN CRÍTICA #2: Auto-adopción de posiciones huérfanas ─
            # Si el proceso se reinició con órdenes abiertas, las adoptamos al vuelo.
            for pos in positions:
                if pos.ticket not in self.active_trails:
                    self._adopt_orphan_position(pos)

            # Limpiar trails de posiciones que verdaderamente ya se cerraron
            closed_tickets = set(self.active_trails.keys()) - open_tickets
            for ticket in closed_tickets:
                self.remove_position(ticket)

            # Actualizar trails activos
            for pos in positions:
                if pos.ticket in self.active_trails:
                    self.update_single_trailing_stop(pos)

        except Exception as e:
            logger.exception(f"Error en ciclo de trailing stops: {e}")

    def _adopt_orphan_position(self, pos):
        """Adopta una posición abierta en MT5 no registrada previamente en RAM."""
        try:
            ticket = pos.ticket
            symbol = pos.symbol
            entry_price = float(pos.price_open)
            current_sl = float(pos.sl)
            tp = float(pos.tp)
            trade_type = 'BUY' if pos.type == mt5.ORDER_TYPE_BUY else 'SELL'

            # Determinar si ya estaba en breakeven
            breakeven_moved = False
            if trade_type == 'BUY' and current_sl >= entry_price > 0:
                breakeven_moved = True
            elif trade_type == 'SELL' and (0 < current_sl <= entry_price):
                breakeven_moved = True

            # Salvaguarda: si la orden huérfana no tiene SL (naked), calcular e inyectar SL sintético
            if current_sl == 0.0:
                default_dist = self._get_default_sl_distance(symbol)
                if default_dist > 0.0:
                    synth_sl = (entry_price - default_dist) if trade_type == 'BUY' else (entry_price + default_dist)
                    logger.warning(
                        f"🛡️ [Cold Orphan Shield] Posición huérfana #{ticket} ({symbol} {trade_type}) detectada SIN SL. "
                        f"Inyectando SL sintético de protección @ {synth_sl:.5f}"
                    )
                    if self.modify_stop_loss(ticket, synth_sl):
                        current_sl = synth_sl

            trail_data = {
                'symbol': symbol,
                'entry_price': entry_price,
                'original_sl': current_sl,
                'original_tp': tp,
                'trade_type': trade_type,
                'current_sl': current_sl,
                'highest_profit': 0.0,
                'breakeven_moved': breakeven_moved,
                'trailing_active': False,
                'partial_closed': False,
                'last_r_locked_notified': 0.0,
                'created_at': datetime.now(timezone.utc).isoformat()
            }
            self.active_trails[ticket] = trail_data

            if self.db_service and hasattr(self.db_service, 'save_trailing_stop'):
                self.db_service.save_trailing_stop(ticket, trail_data)

            logger.info(
                f"📥 Posición huérfana {ticket} adoptada por TrailingStopManager "
                f"({symbol} {trade_type} @ {entry_price:.5f}, SL={current_sl:.5f})"
            )
        except Exception as e:
            logger.debug(f"Error auto-adoptando posición {getattr(pos, 'ticket', '?')}: {e}")

    def update_single_trailing_stop(self, position):
        """Actualiza el trailing stop de una posición específica."""
        try:
            ticket = position.ticket
            trail_info = self.active_trails[ticket]

            current_price = float(position.price_current)
            entry_price = float(trail_info['entry_price'])
            original_sl = float(trail_info['original_sl'])
            original_tp = float(trail_info['original_tp'])
            trade_type = trail_info['trade_type']
            symbol = trail_info['symbol']

            # Calcular distancia de beneficio actual en precio
            if trade_type == 'BUY':
                profit_distance = current_price - entry_price
            else:  # SELL
                profit_distance = entry_price - current_price

            # ── ENFORCEMENT DEL RATCHET: Restaurar SL si fue aflojado durante downtime ──
            stored_sl = float(trail_info.get('current_sl', 0.0) or 0.0)
            live_sl = float(getattr(position, 'sl', 0.0) or 0.0)
            if stored_sl > 0.0:
                is_loosened = False
                if trade_type == 'BUY' and live_sl < (stored_sl - 1e-5):
                    is_loosened = True
                elif trade_type == 'SELL' and (live_sl == 0.0 or live_sl > (stored_sl + 1e-5)):
                    is_loosened = True

                if is_loosened:
                    logger.warning(
                        f"🛡️ [Ratchet Enforcement] Ticket #{ticket} ({symbol} {trade_type}): "
                        f"SL en terminal ({live_sl:.5f}) más laxo que el SL algorítmico persistido ({stored_sl:.5f}). "
                        f"Restaurando suelo de riesgo..."
                    )
                    if self.modify_stop_loss(ticket, stored_sl):
                        logger.info(f"✅ [Ratchet Enforcement] Ticket #{ticket} restaurado a SL={stored_sl:.5f}")

            # Calcular R-múltiplo (beneficio relativo al riesgo inicial)
            initial_risk = abs(entry_price - original_sl) if original_sl > 0 else 0.0
            r_profit = (profit_distance / initial_risk) if initial_risk > 0 else 0.0

            # Calcular porcentaje recorrido hacia el TP
            tp_distance = abs(original_tp - entry_price) if original_tp > 0 else 0.0
            tp_ratio = (profit_distance / tp_distance) if tp_distance > 0 else 0.0

            # Actualizar métrica de beneficio máximo alcanzado
            metric = max(tp_ratio, r_profit)
            trail_info['highest_profit'] = max(trail_info.get('highest_profit', 0.0), metric)

            # ── PROTECCIÓN CRÍTICA #5: Breakeven Temprano y Ágil ───────────
            # Si se conoce el riesgo inicial (R), se evalúa por R-múltiplo (0.8R) o % TP (30%).
            # Si no hay SL/TP, se recurre a la distancia mínima en precio.
            if initial_risk > 0:
                should_move_be = (r_profit >= self.breakeven_r) or (tp_ratio >= self.breakeven_tp_pct if tp_distance > 0 else False)
                should_start_trail = (r_profit >= self.trailing_start_r) or (tp_ratio >= self.trailing_start_tp_pct if tp_distance > 0 else False)
            elif tp_distance > 0:
                should_move_be = (tp_ratio >= self.breakeven_tp_pct)
                should_start_trail = (tp_ratio >= self.trailing_start_tp_pct)
            else:
                should_move_be = (profit_distance >= self._get_min_be_price_distance(symbol))
                should_start_trail = (profit_distance >= self._get_min_trail_start_distance(symbol))

            if not trail_info['breakeven_moved'] and should_move_be:
                self._execute_breakeven(position, trail_info)

            # ── ACTIVE TRADE GUARD (Pre-News Position Shield) ───────────────
            # Proactively shifts SL to Break-Even if Tier-1 news is approaching within 15 minutes and position is profitable
            if not trail_info.get('breakeven_moved', False):
                try:
                    from services.news_filter import get_news_filter
                    news_filter = get_news_filter()
                    prot = news_filter.get_position_news_protection(
                        symbol=symbol,
                        open_price=entry_price,
                        current_price=current_price,
                        current_sl=float(getattr(position, 'sl', 0.0) or 0.0),
                        pos_type=trade_type,
                        window_minutes=15
                    )
                    if prot.get('action') == 'LOCK_BREAKEVEN':
                        logger.warning(
                            f"🛡️ [Active Trade Guard] Ticket #{ticket} ({symbol}): {prot['reason']}"
                        )
                        self._execute_breakeven(position, trail_info)
                except Exception as npe:
                    logger.debug(f"Active trade guard check error for ticket {ticket}: {npe}")

            # ── Trailing Stop Activación Temprana ───────────────────────────
            if not trail_info['trailing_active'] and should_start_trail:
                trail_info['trailing_active'] = True
                self._persist_trail(ticket)
                logger.info(
                    f"🚀 Trailing stop activado para ticket {ticket} ({symbol} {trade_type}) "
                    f"[R={r_profit:.2f}R, TP%={tp_ratio:.1%}, Profit={profit_distance:.4f}]"
                )

            # ── PROTECCIÓN CRÍTICA #3: Cierre Parcial Robusto ───────────────
            should_partial_close = (
                (r_profit >= self.partial_close_r if initial_risk > 0 else False) or
                (tp_ratio >= self.partial_close_tp_pct if tp_distance > 0 else False)
            )

            if not trail_info['partial_closed'] and should_partial_close:
                closed_ok = self.partial_close_position(ticket, self.partial_close_amount)
                if closed_ok:
                    trail_info['partial_closed'] = True
                    self._persist_trail(ticket)
                else:
                    # Si el volumen es indivisible (e.g. 0.01 lotes), marcamos para no spamear
                    sym_info = mt5.symbol_info(symbol)
                    if sym_info and position.volume <= sym_info.volume_min:
                        trail_info['partial_closed'] = True
                        self._persist_trail(ticket)

            # ── PROTECCIÓN CRÍTICA #4: Aplicar Trailing Stop en Precio Real ─
            if trail_info['trailing_active']:
                self.apply_trailing_logic(position, trail_info)

        except Exception as e:
            logger.exception(f"Error actualizando trailing stop para {getattr(position, 'ticket', '?')}: {e}")

    def _execute_breakeven(self, position, trail_info):
        """Mueve el Stop Loss a breakeven con un pequeño colchón para cubrir comisiones/spread."""
        try:
            ticket = position.ticket
            symbol = position.symbol
            entry_price = float(trail_info['entry_price'])
            sym_info = mt5.symbol_info(symbol)

            point = sym_info.point if sym_info else 0.0001
            spread_points = sym_info.spread if sym_info and sym_info.spread else 10
            # Buffer de 1 spread o mínimo 2 puntos en dirección de la ganancia
            spread_buffer = max(spread_points * point, 2 * point)

            if trail_info['trade_type'] == 'BUY':
                target_sl = entry_price + spread_buffer
                # Solo mover si mejora el SL actual
                if target_sl > position.sl:
                    if self.modify_stop_loss(ticket, target_sl):
                        trail_info['breakeven_moved'] = True
                        trail_info['current_sl'] = target_sl
                        self._persist_trail(ticket)
                        logger.info(f"✅ Breakeven ejecutado para BUY {ticket} -> SL={target_sl:.5f}")
                        self._notify_breakeven(ticket, symbol, 'BUY', entry_price, target_sl)
            else:  # SELL
                target_sl = entry_price - spread_buffer
                # Solo mover si mejora el SL actual (o si no tenía SL)
                if position.sl == 0.0 or target_sl < position.sl:
                    if self.modify_stop_loss(ticket, target_sl):
                        trail_info['breakeven_moved'] = True
                        trail_info['current_sl'] = target_sl
                        self._persist_trail(ticket)
                        logger.info(f"✅ Breakeven ejecutado para SELL {ticket} -> SL={target_sl:.5f}")
                        self._notify_breakeven(ticket, symbol, 'SELL', entry_price, target_sl)

        except Exception as e:
            logger.exception(f"Error ejecutando breakeven para {getattr(position, 'ticket', '?')}: {e}")

    def apply_trailing_logic(self, position, trail_info):
        """
        Aplica la lógica de trailing stop calculando la distancia en unidades reales
        de precio (resistente a si el bróker usa 2 o 3 decimales en XAUUSD).
        """
        try:
            ticket = position.ticket
            symbol = trail_info['symbol']
            trade_type = trail_info['trade_type']
            current_price = float(position.price_current)
            current_sl = float(position.sl)

            sym_info = mt5.symbol_info(symbol)
            if not sym_info:
                return

            point = sym_info.point

            # ── CÁLCULO DE DISTANCIA ROBUSTO ───────────────────────────────
            # Si conocemos el riesgo inicial (R), podemos dar un margen de 0.6 R
            initial_risk = abs(trail_info['entry_price'] - trail_info['original_sl']) if trail_info['original_sl'] > 0 else 0.0
            dist_by_risk = initial_risk * 0.6 if initial_risk > 0 else 0.0

            # Distancia configurada por activo
            configured_dist = self.price_distances.get(symbol)
            if configured_dist is None:
                if 'XAU' in symbol or 'GOLD' in symbol:
                    configured_dist = 5.0   # $5.00 USD (en vez de 50 centavos)
                elif 'BTC' in symbol:
                    configured_dist = 500.0 # 500 EUR/USD (en vez de 5 euros)
                else:
                    pip_multiplier = 10 * point if sym_info.digits in (3, 5) else point
                    configured_dist = 20 * pip_multiplier  # 20 pips estándar

            trailing_distance = max(dist_by_risk, configured_dist)

            # Umbral mínimo de modificación (2 puntos) para evitar spam innecesario al broker
            min_step = 2 * point

            if trade_type == 'BUY':
                new_sl = current_price - trailing_distance
                if new_sl > current_sl + min_step:
                    if self.modify_stop_loss(ticket, new_sl):
                        trail_info['current_sl'] = new_sl
                        self._persist_trail(ticket)
                        logger.info(f"📈 Trailing SL avanzado para BUY {ticket}: {new_sl:.5f} (Dist: {trailing_distance:.4f})")
                        self._check_and_notify_r_milestone(ticket, symbol, trade_type, trail_info, new_sl)
            else:  # SELL
                new_sl = current_price + trailing_distance
                if current_sl == 0.0 or (new_sl < current_sl - min_step):
                    if self.modify_stop_loss(ticket, new_sl):
                        trail_info['current_sl'] = new_sl
                        self._persist_trail(ticket)
                        logger.info(f"📉 Trailing SL avanzado para SELL {ticket}: {new_sl:.5f} (Dist: {trailing_distance:.4f})")
                        self._check_and_notify_r_milestone(ticket, symbol, trade_type, trail_info, new_sl)

        except Exception as e:
            logger.exception(f"Error aplicando trailing logic para {getattr(position, 'ticket', '?')}: {e}")

    def modify_stop_loss(self, ticket: int, new_sl: float) -> bool:
        """Modifica el Stop Loss en MT5 respetando el stops_level del bróker."""
        try:
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                return False

            position = positions[0]
            symbol = position.symbol
            sym_info = mt5.symbol_info(symbol)
            if not sym_info:
                return False

            point = sym_info.point
            stops_level = getattr(sym_info, 'stops_level', 0) or 0
            min_dist = stops_level * point
            current_price = float(position.price_current)

            # Validar que no infrinja la distancia mínima obligatoria del bróker
            if position.type == mt5.ORDER_TYPE_BUY:
                if current_price - new_sl < min_dist:
                    new_sl = current_price - min_dist
            else:
                if new_sl - current_price < min_dist:
                    new_sl = current_price + min_dist

            new_sl = round(new_sl, sym_info.digits)

            # Si el SL es idéntico al actual, no reenviar
            if abs(new_sl - position.sl) < (0.5 * point):
                return True

            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": ticket,
                "symbol": symbol,
                "sl": new_sl,
                "tp": position.tp,
            }

            result = mt5.order_send(request)
            if result is None:
                err = mt5.last_error()
                logger.warning(f"mt5.order_send para SL retornó None en {ticket}: {err}")
                return False

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                return True
            else:
                logger.warning(f"Error modificando SL para {ticket}: {result.comment} (retcode: {result.retcode})")
                return False

        except Exception as e:
            logger.exception(f"Excepción modificando SL para {ticket}: {e}")
            return False

    def partial_close_position(self, ticket: int, close_percentage: float) -> bool:
        """
        Cierra parcialmente una posición en MT5 con validación completa:
        - Incluye 'price' explícito (tick.bid para BUY, tick.ask para SELL).
        - Incluye 'type_filling' compatible con brokers ECN.
        - Protege contra cierre accidental del 100% cuando el volumen es 0.01.
        """
        try:
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                return False

            position = positions[0]
            symbol = position.symbol
            sym_info = mt5.symbol_info(symbol)
            if not sym_info:
                return False

            # Validar lotaje mínimo: si ya está en el mínimo permitido (ej: 0.01), no se puede partir
            if position.volume <= sym_info.volume_min:
                logger.info(
                    f"ℹ️ Posición {ticket} ({symbol}) tiene volumen {position.volume} <= mínimo "
                    f"{sym_info.volume_min}. Omitiendo cierre parcial para preservar la posición."
                )
                return False

            # Calcular volumen a cerrar respetando volume_step
            volume_step = sym_info.volume_step if sym_info.volume_step > 0 else 0.01
            raw_close = position.volume * close_percentage
            close_volume = round(raw_close / volume_step) * volume_step
            close_volume = max(sym_info.volume_min, close_volume)

            # Asegurar que no cerramos el 100%
            if close_volume >= position.volume:
                close_volume = position.volume - volume_step

            if close_volume < sym_info.volume_min:
                return False

            close_volume = round(close_volume, 2)

            # Obtener precio actual de salida
            tick = mt5.symbol_info_tick(symbol)
            if not tick:
                logger.warning(f"No se pudo obtener tick de mercado para cierre parcial de {symbol}")
                return False

            if position.type == mt5.ORDER_TYPE_BUY:
                order_type = mt5.ORDER_TYPE_SELL
                exec_price = float(tick.bid)
            else:
                order_type = mt5.ORDER_TYPE_BUY
                exec_price = float(tick.ask)

            # Resolver modo de ejecución (type_filling) del bróker
            filling_mode = mt5.ORDER_FILLING_IOC
            if hasattr(sym_info, 'filling_mode'):
                if sym_info.filling_mode & 2:
                    filling_mode = mt5.ORDER_FILLING_IOC
                elif sym_info.filling_mode & 1:
                    filling_mode = mt5.ORDER_FILLING_FOK

            from services.order_tagger import OrderTagger
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": ticket,
                "symbol": symbol,
                "volume": close_volume,
                "type": order_type,
                "price": exec_price,
                "deviation": 20,
                "magic": getattr(position, 'magic', 234000) or 234000,
                "comment": OrderTagger.generate_partial_close_comment(50),
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }

            result = mt5.order_send(request)
            if result is None:
                err = mt5.last_error()
                logger.error(f"mt5.order_send retornó None en cierre parcial {ticket}: {err}")
                return False

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(
                    f"✂️ Cierre parcial exitoso para {ticket} ({symbol}): "
                    f"{close_volume} lotes a {exec_price:.5f}"
                )
                remaining_vol = max(0.0, position.volume - close_volume)
                pct_label = int(close_percentage * 100) if close_percentage <= 1.0 else int(close_percentage)
                trade_dir = "BUY" if position.type == mt5.ORDER_TYPE_BUY else "SELL"
                self._notify_partial_close(ticket, symbol, trade_dir, close_volume, remaining_vol, exec_price, pct_label)
                return True
            else:
                logger.warning(
                    f"Error en cierre parcial para {ticket}: {result.comment} (retcode: {result.retcode})"
                )
                return False

        except Exception as e:
            logger.exception(f"Excepción en cierre parcial para {ticket}: {e}")
            return False

    def remove_position(self, ticket: int):
        """Remueve una posición cerrada del sistema y de la base de datos."""
        if ticket in self.active_trails:
            del self.active_trails[ticket]
            self._delete_trail(ticket)
            logger.info(f"Trailing stop removido para posición cerrada {ticket}")

    def get_trailing_status(self) -> Dict:
        """Obtiene el estado de todos los trailing stops para la API / Dashboard."""
        try:
            status = {
                'active_trails': len(self.active_trails),
                'positions': []
            }
            for ticket, trail_info in self.active_trails.items():
                status['positions'].append({
                    'ticket': ticket,
                    'symbol': trail_info['symbol'],
                    'breakeven_moved': trail_info.get('breakeven_moved', False),
                    'trailing_active': trail_info.get('trailing_active', False),
                    'partial_closed': trail_info.get('partial_closed', False),
                    'highest_profit': trail_info.get('highest_profit', 0.0),
                    'current_sl': trail_info.get('current_sl', 0.0)
                })
            return status
        except Exception as e:
            logger.exception(f"Error obteniendo trailing status: {e}")
            return {'active_trails': 0, 'positions': []}

    def _persist_trail(self, ticket: int):
        """Helper para guardar estado en SQLite."""
        if self.db_service and hasattr(self.db_service, 'save_trailing_stop'):
            try:
                if ticket in self.active_trails:
                    self.db_service.save_trailing_stop(ticket, self.active_trails[ticket])
            except Exception as e:
                logger.debug(f"Error persistiendo trail {ticket}: {e}")

    def _delete_trail(self, ticket: int):
        """Helper para eliminar estado de SQLite."""
        if self.db_service and hasattr(self.db_service, 'delete_trailing_stop'):
            try:
                self.db_service.delete_trailing_stop(ticket)
            except Exception as e:
                logger.debug(f"Error eliminando trail {ticket} de BD: {e}")

    def _broadcast_telegram(self, text: str):
        """Envía notificación institucional a Telegram (Privado + Canal VIP)."""
        try:
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            if not token:
                return

            chat_id = os.getenv("TELEGRAM_CHAT_ID")
            vip_channel = os.getenv("TELEGRAM_VIP_CHANNEL_ID", "-1004414507559")
            dest_chats = []
            if chat_id:
                dest_chats.append(str(chat_id).strip())
            if vip_channel and str(vip_channel).strip() not in dest_chats:
                dest_chats.append(str(vip_channel).strip())

            if not dest_chats:
                return

            async def _send():
                try:
                    from services.telegram_adapter import TelegramAdapter
                    adapter = TelegramAdapter(token=token, chat_id=chat_id)
                    for cid in dest_chats:
                        try:
                            await adapter.send_message(text, chat_id=cid)
                        except Exception as ex:
                            logger.debug(f"[TrailingStop Telegram] Error enviando a {cid}: {ex}")
                except Exception as ex_adapter:
                    logger.debug(f"[TrailingStop Telegram] Error cargando adapter: {ex_adapter}")

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_send())
            except RuntimeError:
                threading.Thread(target=lambda: asyncio.run(_send()), daemon=True).start()

        except Exception as e:
            logger.debug(f"[TrailingStop Telegram] Excepción en broadcast: {e}")

    def _notify_breakeven(self, ticket: int, symbol: str, trade_type: str, entry_price: float, new_sl: float):
        time_str = datetime.now(timezone.utc).strftime('%H:%M:%S UTC')
        icon_dir = "📈" if trade_type == "BUY" else "📉"
        msg = (
            f"🛡️ *STOP LOSS MOVED TO BREAK-EVEN*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{icon_dir} *Position:* `{trade_type} {symbol}`\n"
            f"🎫 *Ticket:* `#{ticket}`\n"
            f"🟩 *Secured SL:* `{new_sl:.5f}`\n"
            f"🟦 *Entry Price:* `{entry_price:.5f}`\n"
            f"🔒 *Protection:* `Risk-Free (0.00% Risk)`\n"
            f"⏰ `{time_str}`"
        )
        self._broadcast_telegram(msg)

    def _notify_partial_close(self, ticket: int, symbol: str, trade_type: str, close_vol: float, remaining_vol: float, exec_price: float, pct: int):
        time_str = datetime.now(timezone.utc).strftime('%H:%M:%S UTC')
        icon_dir = "📈" if trade_type == "BUY" else "📉"
        msg = (
            f"✂️ *PARTIAL PROFIT SECURED ({pct}%)*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{icon_dir} *Position:* `{trade_type} {symbol}`\n"
            f"🎫 *Ticket:* `#{ticket}`\n"
            f"💰 *Closed Volume:* `{close_vol:.2f} Lots @ {exec_price:.5f}`\n"
            f"🚀 *Runner Remaining:* `{remaining_vol:.2f} Lots (to TP)`\n"
            f"🛡️ *Protection:* `Stop Loss locked at Break-Even / Profit`\n"
            f"⏰ `{time_str}`"
        )
        self._broadcast_telegram(msg)

    def _check_and_notify_r_milestone(self, ticket: int, symbol: str, trade_type: str, trail_info: dict, new_sl: float):
        initial_risk = abs(trail_info['entry_price'] - trail_info['original_sl']) if trail_info.get('original_sl', 0) > 0 else 0.0
        if initial_risk <= 0:
            return

        entry_p = float(trail_info['entry_price'])
        locked_r = ((new_sl - entry_p) if trade_type == 'BUY' else (entry_p - new_sl)) / initial_risk
        last_r = trail_info.get('last_r_locked_notified', 0.0)

        for r_milestone in (1.0, 2.0, 3.0):
            if locked_r >= r_milestone > last_r:
                trail_info['last_r_locked_notified'] = r_milestone
                self._persist_trail(ticket)
                time_str = datetime.now(timezone.utc).strftime('%H:%M:%S UTC')
                icon_dir = "📈" if trade_type == "BUY" else "📉"
                target_tp = float(trail_info.get('original_tp', 0.0))
                tp_text = f"🎯 *Target TP:* `{target_tp:.5f}`\n" if target_tp > 0 else ""
                msg = (
                    f"🔒 *STOP LOSS TRAILED (+{r_milestone:.1f}R PROFIT LOCKED)*\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"{icon_dir} *Position:* `{trade_type} {symbol}`\n"
                    f"🎫 *Ticket:* `#{ticket}`\n"
                    f"📈 *New Protected SL:* `{new_sl:.5f}`\n"
                    f"💰 *Guaranteed Gain:* `+{r_milestone:.1f}R locked`\n"
                    f"{tp_text}"
                    f"⏰ `{time_str}`"
                )
                self._broadcast_telegram(msg)
                break

    def _get_min_be_price_distance(self, symbol: str) -> float:
        """Distancia mínima de precio para activar Breakeven si no hay SL/TP definidos."""
        if 'XAU' in symbol or 'GOLD' in symbol:
            return 3.0  # $3.00 USD
        elif 'BTC' in symbol:
            return 250.0  # 250 EUR/USD
        return 0.0010  # 10 pips

    def _get_min_trail_start_distance(self, symbol: str) -> float:
        """Distancia mínima de precio para activar Trailing si no hay SL/TP definidos."""
        if 'XAU' in symbol or 'GOLD' in symbol:
            return 5.0  # $5.00 USD
        elif 'BTC' in symbol:
            return 400.0  # 400 EUR/USD
        return 0.0015  # 15 pips

    def _get_default_sl_distance(self, symbol: str) -> float:
        """Distancia de Stop Loss sintético inicial para huérfanas sin protección previa."""
        configured_dist = self.price_distances.get(symbol)
        if configured_dist is not None:
            return configured_dist * 1.5

        if 'XAU' in symbol or 'GOLD' in symbol:
            return 8.0  # $8.00 USD en oro
        elif 'BTC' in symbol:
            return 800.0  # $800 USD en BTC

        sym_info = mt5.symbol_info(symbol)
        point = sym_info.point if sym_info else 0.0001
        pip_multiplier = 10 * point if (sym_info and sym_info.digits in (3, 5)) else point
        return 30 * pip_multiplier  # 30 pips en Forex


# Instancia global del trailing stop manager
_trailing_manager: Optional[TrailingStopManager] = None

def get_trailing_manager() -> TrailingStopManager:
    """Obtiene la instancia singleton del trailing manager."""
    global _trailing_manager
    if _trailing_manager is None:
        _trailing_manager = TrailingStopManager()
    return _trailing_manager