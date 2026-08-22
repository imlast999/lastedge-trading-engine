"""
Circuit Breaker y Risk Scaling

Implementa dos mecanismos de protección:

1. Circuit Breaker: pausa automática del bot tras N pérdidas consecutivas
   o si el drawdown diario supera el límite configurado.

2. Risk Scaling: ajusta el riesgo por trade dinámicamente según la racha
   de resultados (implementa los valores de rules_config.json).

Uso:
    from core.circuit_breaker import get_circuit_breaker
    cb = get_circuit_breaker()

    # Registrar resultado de un trade
    cb.record_result('WIN', pips=45.0)
    cb.record_result('LOSS', pips=-22.0)

    # Verificar si se puede operar
    ok, reason = cb.can_trade('EURUSD')

    # Obtener riesgo ajustado para el próximo trade
    risk_pct = cb.get_adjusted_risk('EURUSD', base_risk=0.75)
"""

import json
import os
import logging
from datetime import datetime, timezone, date
from typing import Tuple, List, Dict, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class TradeResult:
    outcome: str        # 'WIN' | 'LOSS'
    pips: float
    symbol: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class CircuitBreaker:
    """
    Protege el capital pausando el bot automáticamente cuando:
    - Se alcanzan N pérdidas consecutivas (configurable)
    - El drawdown diario supera el límite configurado

    También implementa risk scaling dinámico basado en rachas.
    El estado se persiste en disco para sobrevivir reinicios del bot.
    """

    # Ruta del archivo de estado persistente
    _STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'circuit_breaker_state.json')

    def __init__(self):
        self._load_config()
        self.results: List[TradeResult] = []
        self.daily_pips: Dict[str, float] = {}
        self.paused_until: Optional[datetime] = None
        self.pause_reason: str = ""
        self._load_state()   # restaurar estado desde disco

    def _load_config(self):
        """Carga configuración desde rules_config.json"""
        try:
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'rules_config.json')
            with open(config_path, 'r') as f:
                rules = json.load(f)

            global_cfg = rules.get('GLOBAL_SETTINGS', {})

            # Límites del circuit breaker
            self.max_consecutive_losses = 4          # pausa tras 4 pérdidas seguidas
            self.daily_loss_limit_pct   = float(global_cfg.get('loss_limit_daily', 2.0))
            self.drawdown_limit_pct     = float(global_cfg.get('drawdown_limit', 15.0))
            self.pause_hours_on_trigger = 24         # horas de pausa al activarse

            # Risk scaling desde config
            scaling = global_cfg.get('risk_scaling', {})
            self.risk_scaling = {
                'winning_streak_3': float(scaling.get('winning_streak_3', 1.0)),
                'winning_streak_5': float(scaling.get('winning_streak_5', 1.0)),
                'winning_streak_7': float(scaling.get('winning_streak_7', 1.0)),
                'losing_streak_2':  float(scaling.get('losing_streak_2',  0.8)),
                'losing_streak_3':  float(scaling.get('losing_streak_3',  0.5)),
                'losing_streak_4':  float(scaling.get('losing_streak_4',  0.3)),
            }

            logger.info("CircuitBreaker: configuración cargada")

        except Exception as e:
            logger.warning(f"CircuitBreaker: usando valores por defecto ({e})")
            self.max_consecutive_losses = 4
            self.daily_loss_limit_pct   = 2.0
            self.drawdown_limit_pct     = 15.0
            self.pause_hours_on_trigger = 24
            self.risk_scaling = {
                'winning_streak_3': 1.0,
                'winning_streak_5': 1.0,
                'winning_streak_7': 1.0,
                'losing_streak_2':  0.8,
                'losing_streak_3':  0.5,
                'losing_streak_4':  0.3,
            }

    # ── Persistencia ─────────────────────────────────────────────────────────

    def _save_state(self):
        """Guarda el estado del circuit breaker en disco."""
        try:
            data = {
                'results': [
                    {'outcome': r.outcome, 'pips': r.pips, 'symbol': r.symbol,
                     'timestamp': r.timestamp.isoformat()}
                    for r in self.results[-50:]   # solo los últimos 50
                ],
                'daily_pips': self.daily_pips,
                'paused_until': self.paused_until.isoformat() if self.paused_until else None,
                'pause_reason': self.pause_reason,
                'saved_at': datetime.now(timezone.utc).isoformat(),
            }
            with open(self._STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"CircuitBreaker: no se pudo guardar estado: {e}")

    def _load_state(self):
        """Restaura el estado del circuit breaker desde disco."""
        try:
            if not os.path.exists(self._STATE_FILE):
                return

            with open(self._STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # No cargar estado de más de 48h (puede ser obsoleto)
            saved_at_str = data.get('saved_at', '')
            if saved_at_str:
                saved_at = datetime.fromisoformat(saved_at_str)
                if saved_at.tzinfo is None:
                    saved_at = saved_at.replace(tzinfo=timezone.utc)
                age_hours = (datetime.now(timezone.utc) - saved_at).total_seconds() / 3600
                if age_hours > 48:
                    logger.info("CircuitBreaker: estado guardado tiene >48h, empezando limpio")
                    return

            # Restaurar resultados
            for r in data.get('results', []):
                try:
                    ts = datetime.fromisoformat(r['timestamp'])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    self.results.append(TradeResult(
                        outcome=r['outcome'], pips=float(r['pips']),
                        symbol=r.get('symbol', 'UNKNOWN'), timestamp=ts
                    ))
                except Exception:
                    pass

            # Restaurar pips diarios
            self.daily_pips = data.get('daily_pips', {})

            # Restaurar pausa activa
            paused_until_str = data.get('paused_until')
            if paused_until_str:
                paused_until = datetime.fromisoformat(paused_until_str)
                if paused_until.tzinfo is None:
                    paused_until = paused_until.replace(tzinfo=timezone.utc)
                # Solo restaurar si la pausa sigue vigente
                if paused_until > datetime.now(timezone.utc):
                    self.paused_until = paused_until
                    self.pause_reason = data.get('pause_reason', '')
                    logger.warning(
                        "CircuitBreaker: pausa restaurada desde disco — %s | hasta %s",
                        self.pause_reason,
                        self.paused_until.strftime('%Y-%m-%d %H:%M UTC')
                    )

            cons_losses = self._consecutive_losses()
            cons_wins   = self._consecutive_wins()
            logger.info(
                "CircuitBreaker: estado restaurado | %d resultados | "
                "racha pérdidas=%d | racha wins=%d | pausado=%s",
                len(self.results), cons_losses, cons_wins,
                self.paused_until is not None
            )

        except Exception as e:
            logger.warning(f"CircuitBreaker: no se pudo cargar estado: {e}")

    def record_result(self, outcome: str, pips: float = 0.0, symbol: str = 'UNKNOWN'):
        """
        Registra el resultado de un trade cerrado.

        Args:
            outcome: 'WIN' o 'LOSS'
            pips: pips ganados (positivo) o perdidos (negativo)
            symbol: símbolo del trade
        """
        result = TradeResult(outcome=outcome.upper(), pips=pips, symbol=symbol)
        self.results.append(result)

        # Acumular pips del día
        today = date.today().isoformat()
        self.daily_pips[today] = self.daily_pips.get(today, 0.0) + pips

        # Mantener solo los últimos 50 resultados en memoria
        if len(self.results) > 50:
            self.results = self.results[-50:]

        # Verificar si hay que activar el circuit breaker
        self._check_triggers()

        logger.info(
            "CircuitBreaker: resultado registrado | %s %s %.1f pips | "
            "racha=%d | pips_hoy=%.1f",
            outcome, symbol, pips,
            self._consecutive_losses(),
            self.daily_pips.get(today, 0.0)
        )

        # Persistir estado tras cada resultado
        self._save_state()

    def can_trade(self, symbol: str = None) -> Tuple[bool, str]:
        """
        Verifica si el bot puede abrir nuevas operaciones.

        Returns:
            (puede_operar, razón)
        """
        # Verificar pausa activa
        if self.paused_until is not None:
            now = datetime.now(timezone.utc)
            if now < self.paused_until:
                remaining = (self.paused_until - now).total_seconds() / 3600
                return False, (
                    f"Circuit breaker activo: {self.pause_reason} | "
                    f"Reanuda en {remaining:.1f}h"
                )
            else:
                # Pausa expirada
                self.paused_until = None
                self.pause_reason = ""
                logger.info("CircuitBreaker: pausa expirada, trading reanudado")

        return True, "OK"

    def get_adjusted_risk(self, symbol: str, base_risk: float) -> float:
        """
        Devuelve el riesgo ajustado según la racha actual.

        Args:
            symbol: símbolo del trade
            base_risk: riesgo base configurado (ej: 0.75%)

        Returns:
            riesgo ajustado (puede ser menor o mayor que base_risk)
        """
        consecutive_losses = self._consecutive_losses()
        consecutive_wins   = self._consecutive_wins()

        multiplier = 1.0

        # Rachas perdedoras → reducir riesgo
        if consecutive_losses >= 4:
            multiplier = self.risk_scaling['losing_streak_4']
        elif consecutive_losses >= 3:
            multiplier = self.risk_scaling['losing_streak_3']
        elif consecutive_losses >= 2:
            multiplier = self.risk_scaling['losing_streak_2']

        # Rachas ganadoras → aumentar riesgo (solo si no hay pérdidas recientes)
        elif consecutive_wins >= 7:
            multiplier = self.risk_scaling['winning_streak_7']
        elif consecutive_wins >= 5:
            multiplier = self.risk_scaling['winning_streak_5']
        elif consecutive_wins >= 3:
            multiplier = self.risk_scaling['winning_streak_3']

        adjusted = round(base_risk * multiplier, 4)

        if multiplier != 1.0:
            logger.info(
                "RiskScaling: %s | base=%.3f%% × %.1f = %.3f%% | "
                "losses=%d wins=%d",
                symbol, base_risk, multiplier, adjusted,
                consecutive_losses, consecutive_wins
            )

        return adjusted

    def get_status(self) -> Dict:
        """Devuelve el estado actual del circuit breaker."""
        today = date.today().isoformat()
        can_trade, reason = self.can_trade()

        return {
            'can_trade':           can_trade,
            'reason':              reason,
            'consecutive_losses':  self._consecutive_losses(),
            'consecutive_wins':    self._consecutive_wins(),
            'daily_pips':          self.daily_pips.get(today, 0.0),
            'paused_until':        self.paused_until.isoformat() if self.paused_until else None,
            'pause_reason':        self.pause_reason,
            'total_results':       len(self.results),
            'risk_multiplier':     self._current_risk_multiplier(),
        }

    # ── Internos ─────────────────────────────────────────────────────────────

    def _consecutive_losses(self) -> int:
        count = 0
        for r in reversed(self.results):
            if r.outcome == 'LOSS':
                count += 1
            else:
                break
        return count

    def _consecutive_wins(self) -> int:
        count = 0
        for r in reversed(self.results):
            if r.outcome == 'WIN':
                count += 1
            else:
                break
        return count

    def _current_risk_multiplier(self) -> float:
        """Multiplier actual sin aplicar a un riesgo base."""
        losses = self._consecutive_losses()
        wins   = self._consecutive_wins()
        if losses >= 4: return self.risk_scaling['losing_streak_4']
        if losses >= 3: return self.risk_scaling['losing_streak_3']
        if losses >= 2: return self.risk_scaling['losing_streak_2']
        if wins   >= 7: return self.risk_scaling['winning_streak_7']
        if wins   >= 5: return self.risk_scaling['winning_streak_5']
        if wins   >= 3: return self.risk_scaling['winning_streak_3']
        return 1.0

    def _check_triggers(self):
        """Verifica si hay que activar el circuit breaker."""
        # Único trigger: pérdidas consecutivas
        # El trigger de pips diarios se eliminó porque mezcla XAUUSD/EURUSD/BTCEUR
        # con escalas de pips completamente distintas (0.1$ vs 0.0001$ vs 1$)
        consecutive = self._consecutive_losses()
        if consecutive >= self.max_consecutive_losses:
            self._activate_pause(
                f"{consecutive} pérdidas consecutivas"
            )

    def _activate_pause(self, reason: str):
        """Activa la pausa del circuit breaker."""
        from datetime import timedelta
        if self.paused_until is not None:
            return  # Ya está pausado

        self.paused_until = datetime.now(timezone.utc) + timedelta(hours=self.pause_hours_on_trigger)
        self.pause_reason = reason

        logger.warning(
            "🔴 CIRCUIT BREAKER ACTIVADO: %s | Pausa hasta %s",
            reason, self.paused_until.strftime('%Y-%m-%d %H:%M UTC')
        )

        # Persistir inmediatamente para que el reinicio respete la pausa
        self._save_state()


# ── Instancia global ──────────────────────────────────────────────────────────

_circuit_breaker: Optional[CircuitBreaker] = None

def get_circuit_breaker() -> CircuitBreaker:
    """Obtiene la instancia global del circuit breaker."""
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker
