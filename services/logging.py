"""
Sistema de Logging Inteligente Consolidado

Consolida toda la lógica de logging que estaba fragmentada en:
- intelligent_logging.py
- bot.py (IntelligentBotLogger)
- Otros archivos con logging duplicado
"""

import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from collections import defaultdict
from dataclasses import dataclass, field
import json

logger = logging.getLogger(__name__)

@dataclass
class LoggingStats:
    """Estadísticas de logging consolidadas"""
    signals_evaluated: int = 0
    signals_shown: int = 0
    signals_rejected: int = 0
    signals_executed: int = 0
    rejection_reasons: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    symbol_activity: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    strategy_usage: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    confidence_distribution: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

class IntelligentLogger:
    """
    Sistema de logging inteligente que consolida toda la funcionalidad
    de logging fragmentada anteriormente.
    
    Características:
    - Logging agregado para reducir ruido
    - Estadísticas automáticas
    - Rotación de archivos por sesión
    - Captura completa de stdout/stderr
    - Formateo inteligente por tipo de evento
    """
    
    def __init__(self, dump_interval_minutes: int = 15):
        self.dump_interval = dump_interval_minutes * 60
        self.last_dump = datetime.now()
        
        # Estadísticas consolidadas
        self.stats = LoggingStats()
        
        # Buffer de eventos recientes para debugging
        self.recent_events = []
        self.max_recent_events = 100
        
        # Configuración de archivos
        self.current_log_file = None
        self.logs_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs')
        
        # Emojis para diferentes tipos de eventos
        self.emoji_map = {
            'SIGNAL_HIGH': '🎯',
            'SIGNAL_MEDIUM': '🔍', 
            'SIGNAL_EXECUTED': '✅',
            'SIGNAL_REJECTED': '❌',
            'ERROR': '❌',
            'WARNING': '⚠️',
            'COOLDOWN': '🔄',
            'SYSTEM': '🤖',
            'AUTOSIGNAL': '🔍',
            'TRADING': '💹',
            'RISK': '🛡️',
            'FILTER': '🔧',
            'COMMAND': '🎮',
            'SUCCESS': '✅',
            'INFO': '📝'
        }
        
        # Inicializar sistema de archivos
        self._setup_logging_system()
    
    def _setup_logging_system(self):
        """Configura el sistema completo de logging"""
        try:
            # Crear directorio de logs
            os.makedirs(self.logs_dir, exist_ok=True)
            
            # Crear archivo de log único por sesión
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            log_filename = f'logs_{timestamp}.txt'
            self.current_log_file = os.path.join(self.logs_dir, log_filename)
            
            # Crear archivo con header
            with open(self.current_log_file, 'w', encoding='utf-8') as f:
                startup_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"=== LastEdge STARTED: {startup_time} ===\n")
                f.write(f"=== LOG FILE: {log_filename} ===\n")
                f.write("=" * 60 + "\n\n")
            
            # Configurar captura de stdout/stderr
            self._setup_output_capture()
            
            # Configurar handler de logging estándar
            self._setup_standard_logging()
            
            self.log_important_event(
                f"Sistema de logging iniciado: {log_filename}", "INFO", "SYSTEM"
            )
            
        except Exception as e:
            print(f"❌ Error configurando sistema de logging: {e}")
            logger.exception('Failed to setup logging system')
    
    def _setup_output_capture(self):
        """Configura captura automática de stdout y stderr"""
        try:
            log_file_path = self.current_log_file

            class TeeOutput:
                """
                Duplica stdout/stderr al archivo de log con saltos de línea garantizados.
                """
                def __init__(self, file_path, original_stream):
                    self.file_path = file_path
                    self.original_stream = original_stream
                    self.terminal = original_stream

                def write(self, message):
                    # 1. Escribir a la terminal original
                    try:
                        self.terminal.write(message)
                        self.terminal.flush()
                    except BaseException:
                        pass

                    # 2. Escribir al archivo de log línea por línea con salto de línea garantizado
                    try:
                        if not message or not message.strip():
                            return

                        # Evitar guardar la traza de KeyboardInterrupt al pulsar Ctrl+C
                        if "KeyboardInterrupt" in message or "Loop thread traceback" in message:
                            return

                        lines = message.splitlines()
                        now_str = datetime.now().strftime('%H:%M:%S')
                        with open(self.file_path, 'a', encoding='utf-8') as f:
                            for line in lines:
                                clean_line = line.strip('\r')
                                if not clean_line.strip():
                                    continue
                                # Si ya empieza por timestamp '[', escribir tal cual
                                if clean_line.startswith('['):
                                    f.write(f"{clean_line}\n")
                                else:
                                    f.write(f"[{now_str}] {clean_line}\n")
                    except BaseException:
                        pass

                def flush(self):
                    try:
                        self.terminal.flush()
                    except BaseException:
                        pass

            # Redirigir stdout y stderr
            sys.stdout = TeeOutput(log_file_path, sys.stdout)
            sys.stderr = TeeOutput(log_file_path, sys.stderr)

        except Exception as e:
            logger.error(f"Error configurando captura de salida: {e}")
    
    def _setup_standard_logging(self):
        """Configura handler estándar de logging"""
        try:
            # Verificar si ya existe handler para este archivo
            root_logger = logging.getLogger()
            existing_handlers = [
                h for h in root_logger.handlers 
                if isinstance(h, logging.FileHandler) and 
                getattr(h, 'baseFilename', None) == os.path.abspath(self.current_log_file)
            ]
            
            if not existing_handlers:
                fh = logging.FileHandler(self.current_log_file, encoding='utf-8')
                fh.setLevel(logging.INFO)
                formatter = logging.Formatter(
                    '[%(asctime)s] %(levelname)s - %(name)s: %(message)s', 
                    datefmt='%H:%M:%S'
                )
                fh.setFormatter(formatter)
                root_logger.addHandler(fh)
                
        except Exception as e:
            logger.error(f"Error configurando handler estándar: {e}")
    
    def log_signal_evaluation(self, symbol: str, strategy: str, shown: bool, 
                            confidence: str = "MEDIUM", score: float = 0.0,
                            rejection_reason: str = None, executed: bool = False):
        """
        Registra evaluación de señal (logging agregado, no individual)
        
        Args:
            symbol: Símbolo del instrumento
            strategy: Estrategia utilizada
            shown: Si la señal fue mostrada
            confidence: Nivel de confianza
            score: Score numérico
            rejection_reason: Razón de rechazo si aplica
            executed: Si la señal fue ejecutada
        """
        # Actualizar estadísticas
        self.stats.signals_evaluated += 1
        self.stats.symbol_activity[symbol] += 1
        self.stats.strategy_usage[strategy] += 1
        self.stats.confidence_distribution[confidence] += 1
        
        if shown:
            self.stats.signals_shown += 1
        else:
            self.stats.signals_rejected += 1
            if rejection_reason:
                self.stats.rejection_reasons[rejection_reason] += 1
        
        if executed:
            self.stats.signals_executed += 1
        
        # Agregar a eventos recientes para debugging
        event = {
            'timestamp': datetime.now().isoformat(),
            'type': 'signal_evaluation',
            'symbol': symbol,
            'strategy': strategy,
            'shown': shown,
            'executed': executed,
            'confidence': confidence,
            'score': score,
            'rejection_reason': rejection_reason
        }
        
        self._add_recent_event(event)
        
        # Verificar si es hora de volcar estadísticas
        if datetime.now().timestamp() - self.last_dump.timestamp() > self.dump_interval:
            self._dump_periodic_stats()
    
    def log_important_event(self, message: str, level: str = "INFO", component: str = "BOT"):
        """
        Log para eventos importantes (estos SÍ aparecen inmediatamente en texto)
        
        Args:
            message: Mensaje del evento
            level: Nivel de logging (INFO, WARNING, ERROR)
            component: Componente que genera el evento
        """
        timestamp = datetime.now().strftime('%H:%M:%S')
        
        # Obtener emoji apropiado
        emoji = self.emoji_map.get(component, self.emoji_map.get(level, '📝'))
        
        # Formatear mensaje para consola
        console_msg = f"[{timestamp}] {emoji} {component}: {message}"
        
        # Imprimir (se capturará automáticamente en archivo)
        try:
            print(console_msg)
        except Exception:
            pass  # Si print bloquea (terminal congelada), continuar sin crashear
        
        # También usar logger estándar para compatibilidad
        log_level = getattr(logging, level.upper(), logging.INFO)
        logger.log(log_level, f"{component}: {message}")
        
        # Agregar a eventos recientes
        event = {
            'timestamp': datetime.now().isoformat(),
            'type': 'important_event',
            'level': level,
            'component': component,
            'message': message
        }
        
        self._add_recent_event(event)
    
    def log_command_execution(self, command_name: str, user_id: int, 
                            args: str = "", success: bool = True, 
                            error_msg: str = None):
        """Log específico para comandos Discord"""
        if success:
            self.log_important_event(
                f"Command /{command_name} {args} executed by {user_id}",
                "INFO", "COMMAND"
            )
        else:
            self.log_important_event(
                f"Command /{command_name} {args} failed for {user_id}: {error_msg}",
                "ERROR", "COMMAND"
            )
    
    def command_used(self, user_id: int, command_details: str, success: bool = True):
        """
        Método de compatibilidad para logging de comandos
        
        Args:
            user_id: ID del usuario que ejecutó el comando
            command_details: Detalles del comando ejecutado
            success: Si el comando fue exitoso
        """
        if success:
            self.log_important_event(
                f"🎮 COMMAND: {command_details} | User: {user_id}",
                "INFO", "COMMAND"
            )
        else:
            self.log_important_event(
                f"❌ COMMAND FAILED: {command_details} | User: {user_id}",
                "ERROR", "COMMAND"
            )
    
    def log_trading_action(self, action: str, symbol: str, details: Dict = None):
        """Log específico para acciones de trading"""
        details_str = ""
        if details:
            key_details = []
            for key in ['type', 'entry', 'sl', 'tp', 'lot_size']:
                if key in details:
                    key_details.append(f"{key}={details[key]}")
            details_str = f" ({', '.join(key_details)})" if key_details else ""
        
        self.log_important_event(
            f"{action} {symbol}{details_str}",
            "INFO", "TRADING"
        )
    
    def _add_recent_event(self, event: Dict):
        """Añade evento al buffer de eventos recientes"""
        self.recent_events.append(event)
        
        # Mantener solo los más recientes
        if len(self.recent_events) > self.max_recent_events:
            self.recent_events = self.recent_events[-self.max_recent_events:]
    
    def _dump_periodic_stats(self):
        """Volcado periódico de estadísticas agregadas"""
        try:
            duration = (datetime.now() - self.last_dump).total_seconds() / 60
            
            if self.stats.signals_evaluated > 0:
                show_rate = (self.stats.signals_shown / self.stats.signals_evaluated) * 100
                exec_rate = (self.stats.signals_executed / self.stats.signals_shown) * 100 if self.stats.signals_shown > 0 else 0
                
                self.log_important_event(
                    f"📊 RESUMEN {duration:.0f}min: {self.stats.signals_evaluated} evaluadas, "
                    f"{self.stats.signals_shown} mostradas ({show_rate:.1f}%), "
                    f"{self.stats.signals_executed} ejecutadas ({exec_rate:.1f}%)",
                    "INFO", "SYSTEM"
                )
                
                # Top 3 razones de rechazo
                if self.stats.rejection_reasons:
                    top_rejections = sorted(
                        self.stats.rejection_reasons.items(), 
                        key=lambda x: x[1], reverse=True
                    )[:3]
                    rejection_summary = ", ".join([f"{reason}({count})" for reason, count in top_rejections])
                    self.log_important_event(f"Top rechazos: {rejection_summary}", "INFO", "SYSTEM")
                
                # Actividad por símbolo
                if self.stats.symbol_activity:
                    symbol_summary = ", ".join([
                        f"{symbol}({count})" 
                        for symbol, count in sorted(self.stats.symbol_activity.items(), key=lambda x: x[1], reverse=True)[:3]
                    ])
                    self.log_important_event(f"Actividad: {symbol_summary}", "INFO", "SYSTEM")
                
                # Distribución de confianza
                if self.stats.confidence_distribution:
                    conf_summary = ", ".join([
                        f"{conf}({count})" 
                        for conf, count in sorted(self.stats.confidence_distribution.items(), key=lambda x: x[1], reverse=True)
                    ])
                    self.log_important_event(f"Confianza: {conf_summary}", "INFO", "SYSTEM")
            
            # Reset estadísticas
            self._reset_stats()
            
        except Exception as e:
            logger.error(f"Error volcando estadísticas: {e}")
    
    def _reset_stats(self):
        """Resetea las estadísticas para el próximo período"""
        self.stats = LoggingStats()
        self.last_dump = datetime.now()
    
    def get_current_stats(self) -> Dict:
        """Obtiene estadísticas actuales sin resetear"""
        return {
            'period_start': self.last_dump.isoformat(),
            'signals_evaluated': self.stats.signals_evaluated,
            'signals_shown': self.stats.signals_shown,
            'signals_rejected': self.stats.signals_rejected,
            'signals_executed': self.stats.signals_executed,
            'show_rate': (self.stats.signals_shown / self.stats.signals_evaluated * 100) if self.stats.signals_evaluated > 0 else 0,
            'execution_rate': (self.stats.signals_executed / self.stats.signals_shown * 100) if self.stats.signals_shown > 0 else 0,
            'rejection_reasons': dict(self.stats.rejection_reasons),
            'symbol_activity': dict(self.stats.symbol_activity),
            'strategy_usage': dict(self.stats.strategy_usage),
            'confidence_distribution': dict(self.stats.confidence_distribution),
            'current_log_file': os.path.basename(self.current_log_file) if self.current_log_file else None
        }
    
    def get_recent_events(self, count: int = 20) -> list:
        """Obtiene eventos recientes para debugging"""
        return self.recent_events[-count:] if count > 0 else self.recent_events
    
    def export_session_log(self, format: str = 'json') -> str:
        """
        Exporta log de la sesión actual
        
        Args:
            format: 'json' o 'text'
            
        Returns:
            Contenido del log en el formato especificado
        """
        try:
            if format.lower() == 'json':
                session_data = {
                    'session_start': self.last_dump.isoformat(),
                    'current_stats': self.get_current_stats(),
                    'recent_events': self.recent_events,
                    'log_file': self.current_log_file
                }
                return json.dumps(session_data, indent=2, ensure_ascii=False)
            
            else:  # text format
                if self.current_log_file and os.path.exists(self.current_log_file):
                    with open(self.current_log_file, 'r', encoding='utf-8') as f:
                        return f.read()
                else:
                    return "Log file not available"
                    
        except Exception as e:
            logger.error(f"Error exportando log de sesión: {e}")
            return f"Error: {str(e)}"

# Instancia global del logger inteligente
intelligent_logger = IntelligentLogger()

def get_intelligent_logger() -> IntelligentLogger:
    """Obtiene la instancia global del logger inteligente"""
    return intelligent_logger

def log_event(message: str, level: str = "INFO", component: str = "BOT"):
    """Función de conveniencia para logging de eventos importantes"""
    intelligent_logger.log_important_event(message, level, component)

def log_signal_evaluation(symbol: str, strategy: str, shown: bool, **kwargs):
    """Función de conveniencia para logging de evaluación de señales"""
    intelligent_logger.log_signal_evaluation(symbol, strategy, shown, **kwargs)

def log_command(command_name: str, user_id: int, success: bool = True, **kwargs):
    """Función de conveniencia para logging de comandos"""
    intelligent_logger.log_command_execution(command_name, user_id, success=success, **kwargs)

def log_trading(action: str, symbol: str, details: Dict = None):
    """Función de conveniencia para logging de trading"""
    intelligent_logger.log_trading_action(action, symbol, details)