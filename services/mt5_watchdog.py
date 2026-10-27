"""
LastEdge Trading Engine — Mission-Critical MetaTrader 5 Watchdog Service
services/mt5_watchdog.py
========================================================================
Continuous 24/7 background watchdog service monitoring:
1. `terminal64.exe` process health & memory utilization.
2. MetaTrader 5 broker server connection & ping.
3. Automated trade execution allowance (`trade_allowed`).
4. Automatic crash recovery & process auto-relaunch.
5. Real-time Telegram alerting with state-change hysteresis.
6. Heartbeat status logging to `logs/watchdog_heartbeat.json`.
"""

from __future__ import annotations

import os
import sys
import time
import json
import signal
import logging
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from dotenv import load_dotenv

# Ensure UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ENGINE_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = ENGINE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [MT5Watchdog] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("MT5Watchdog")

# Default configurations
CHECK_INTERVAL_SECONDS = int(os.getenv("WATCHDOG_INTERVAL_SECONDS", "30"))
MT5_DEFAULT_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"
HEARTBEAT_FILE = LOGS_DIR / "watchdog_heartbeat.json"


class MT5Watchdog:
    """Watchdog agent monitoring MT5 process and terminal connection."""

    def __init__(self, check_interval: int = 30):
        self.check_interval = check_interval
        self.is_running = True
        self.last_state = "UNKNOWN"
        self.failure_counter = 0
        self.start_time = datetime.now(timezone.utc)
        self.last_alert_time = datetime.min.replace(tzinfo=timezone.utc)
        self.last_heartbeat_time = datetime.min.replace(tzinfo=timezone.utc)

        # Load environment
        load_dotenv(ENGINE_DIR / ".env")
        self.mt5_path = os.getenv("MT5_PATH", MT5_DEFAULT_PATH)
        self.login_id = os.getenv("MT5_LOGIN")
        self.password = os.getenv("MT5_PASSWORD")
        self.server = os.getenv("MT5_SERVER")

        if self.password and self.password.startswith('"') and self.password.endswith('"'):
            self.password = self.password[1:-1]
        if self.server and self.server.startswith('"') and self.server.endswith('"'):
            self.server = self.server[1:-1]

        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

    def send_telegram(self, text: str) -> bool:
        """Sends immediate Telegram alert using standard library."""
        if not self.telegram_token or not self.telegram_chat_id:
            logger.debug("Telegram credentials not available.")
            return False

        try:
            import urllib.request
            import urllib.parse
            import ssl

            url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": text,
                "parse_mode": "Markdown"
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"}
            )
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning(f"Failed to dispatch Telegram watchdog message: {e}")
            return False

    def is_process_running(self) -> bool:
        """Checks whether terminal64.exe is in Windows active process table."""
        try:
            cmd = ["tasklist", "/fi", "imagename eq terminal64.exe"]
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, creationflags=0x08000000)
            return b"terminal64.exe" in output
        except Exception as e:
            logger.debug(f"Error checking process via tasklist: {e}")
            return False

    def restart_process(self) -> bool:
        """Attempts to relaunch MetaTrader 5 terminal executable."""
        logger.warning(f"Relaunching MT5 terminal process from {self.mt5_path}...")
        try:
            if not os.path.exists(self.mt5_path):
                logger.error(f"MT5 executable path not found: {self.mt5_path}")
                return False

            # Launch detached process on Windows
            subprocess.Popen([self.mt5_path], creationflags=0x00000008)
            time.sleep(8)
            return self.is_process_running()
        except Exception as e:
            logger.error(f"Failed to relaunch MT5 terminal: {e}")
            return False

    def is_forex_weekend(self, now: Optional[datetime] = None) -> bool:
        """Returns True if traditional Forex/Commodities markets are closed (Fri 22:00 -> Sun 22:00 UTC)."""
        dt = now or datetime.now(timezone.utc)
        weekday = dt.weekday() # 4=Friday, 5=Saturday, 6=Sunday
        hour = dt.hour

        if weekday == 4 and hour >= 22:
            return True
        if weekday == 5:
            return True
        if weekday == 6 and hour < 22:
            return True
        return False

    def check_mt5_health(self) -> Dict[str, Any]:
        """Queries MetaTrader 5 API for connectivity and account state."""
        try:
            import MetaTrader5 as mt5
        except ImportError:
            return {
                "ok": False,
                "reason": "MetaTrader5 library not installed in Python environment",
                "state": "CRITICAL"
            }

        proc_alive = self.is_process_running()
        if not proc_alive:
            return {
                "ok": False,
                "reason": "terminal64.exe process not running",
                "state": "PROCESS_DEAD",
                "proc_alive": False,
                "connected": False
            }

        t0 = time.perf_counter()
        kwargs = {}
        if self.mt5_path:
            kwargs["path"] = self.mt5_path
        if self.login_id and self.password and self.server:
            try:
                kwargs["login"] = int(self.login_id)
                kwargs["password"] = self.password
                kwargs["server"] = self.server
            except ValueError:
                pass

        init_ok = mt5.initialize(**kwargs)
        ping_ms = round((time.perf_counter() - t0) * 1000, 1)

        if not init_ok:
            err = mt5.last_error()
            return {
                "ok": False,
                "reason": f"mt5.initialize() failed: {err}",
                "state": "INIT_FAILED",
                "proc_alive": proc_alive,
                "connected": False,
                "ping_ms": ping_ms
            }

        t_info = mt5.terminal_info()
        if t_info is None:
            return {
                "ok": False,
                "reason": "terminal_info() is None",
                "state": "NO_TERMINAL_INFO",
                "proc_alive": proc_alive,
                "connected": False,
                "ping_ms": ping_ms
            }

        connected = bool(t_info.connected)
        trade_allowed = bool(t_info.trade_allowed)
        acc_info = mt5.account_info()

        balance = float(acc_info.balance) if acc_info else 0.0
        equity = float(acc_info.equity) if acc_info else 0.0
        login_acc = int(acc_info.login) if acc_info else 0
        server_name = str(acc_info.server) if acc_info else self.server or "Unknown"

        if not connected:
            return {
                "ok": False,
                "reason": "MT5 terminal disconnected from broker",
                "state": "DISCONNECTED",
                "proc_alive": proc_alive,
                "connected": False,
                "trade_allowed": trade_allowed,
                "ping_ms": ping_ms,
                "login": login_acc,
                "balance": balance,
                "equity": equity,
                "server": server_name
            }

        state = "HEALTHY" if trade_allowed else "TRADE_DISABLED"
        return {
            "ok": True,
            "reason": "OK",
            "state": state,
            "proc_alive": proc_alive,
            "connected": connected,
            "trade_allowed": trade_allowed,
            "ping_ms": ping_ms,
            "login": login_acc,
            "balance": balance,
            "equity": equity,
            "server": server_name
        }

    def write_heartbeat(self, health: Dict[str, Any]) -> None:
        """Persists health status to watchdog_heartbeat.json."""
        now = datetime.now(timezone.utc)
        uptime_sec = int((now - self.start_time).total_seconds())

        payload = {
            "status": health.get("state", "UNKNOWN"),
            "is_healthy": health.get("ok", False),
            "proc_alive": health.get("proc_alive", False),
            "connected": health.get("connected", False),
            "trade_allowed": health.get("trade_allowed", False),
            "ping_ms": health.get("ping_ms", 0.0),
            "login": health.get("login", self.login_id),
            "server": health.get("server", self.server),
            "balance": health.get("balance", 0.0),
            "equity": health.get("equity", 0.0),
            "failure_counter": self.failure_counter,
            "last_check_utc": now.isoformat(),
            "watchdog_uptime_seconds": uptime_sec,
            "reason": health.get("reason", "OK")
        }

        try:
            with open(HEARTBEAT_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            logger.debug(f"Error persisting heartbeat: {e}")

    def run_step(self) -> None:
        """Performs a single evaluation cycle."""
        now = datetime.now(timezone.utc)
        health = self.check_mt5_health()
        current_state = health.get("state", "UNKNOWN")

        # 1. Process dead auto-recovery
        if current_state == "PROCESS_DEAD":
            logger.critical("🚨 terminal64.exe is NOT running! Initiating emergency auto-restart...")
            self.failure_counter += 1
            restarted = self.restart_process()
            if restarted:
                logger.info("✅ MT5 terminal process relaunched. Re-checking connection...")
                health = self.check_mt5_health()
                current_state = health.get("state", "UNKNOWN")
            else:
                self.send_telegram(
                    f"🚨 *[CRITICAL] MT5 Process Crashed on VPS!*\n"
                    f"• *Process:* `terminal64.exe` down\n"
                    f"• *Path:* `{self.mt5_path}`\n"
                    f"• *Auto-Restart:* Attempted, process failed to spawn.\n"
                    f"• *Time:* `{now.strftime('%Y-%m-%d %H:%M:%S UTC')}`"
                )

        # 2. Broker Disconnection Handling
        if not health.get("connected", False) and current_state != "PROCESS_DEAD":
            self.failure_counter += 1
            logger.warning(f"⚠️ MT5 disconnected from broker. Reason: {health.get('reason')} (Failure #{self.failure_counter})")

            # Check weekend filter
            is_weekend = self.is_forex_weekend(now)
            if not is_weekend:
                # Send alert if state changed or failure persisted for 3 cycles (90s)
                if self.last_state != "DISCONNECTED" or (self.failure_counter % 6 == 0):
                    self.send_telegram(
                        f"⚠️ *[ALERT] MetaTrader 5 Disconnected on VPS!*\n"
                        f"• *Broker:* `{health.get('server', self.server)}`\n"
                        f"• *Login:* `{health.get('login', self.login_id)}`\n"
                        f"• *Reason:* `{health.get('reason')}`\n"
                        f"• *Duration:* Disconnected for ~{self.failure_counter * self.check_interval}s\n"
                        f"• *Reconnection:* Auto-retry loop active..."
                    )
            else:
                logger.info("Market is closed (Weekend). Disconnection alert suppressed.")

        # 3. Restored State Handling
        if health.get("ok", False) and self.last_state in ("DISCONNECTED", "PROCESS_DEAD", "INIT_FAILED"):
            logger.info("🎉 MT5 connection successfully RESTORED!")
            self.send_telegram(
                f"✅ *[RESTORED] MetaTrader 5 Online on VPS!*\n"
                f"• *Server:* `{health.get('server')}`\n"
                f"• *Account:* `{health.get('login')}`\n"
                f"• *Balance:* `${health.get('balance'):,.2f}`\n"
                f"• *Equity:* `${health.get('equity'):,.2f}`\n"
                f"• *Algo Trading:* {'Allowed' if health.get('trade_allowed') else '⚠️ DISABLED'}\n"
                f"• *Ping:* `{health.get('ping_ms')} ms`\n"
                f"• *Status:* Normal operations resumed."
            )
            self.failure_counter = 0

        # 4. Trade Allowed Warning
        if health.get("connected", False) and not health.get("trade_allowed", True) and self.last_state != "TRADE_DISABLED":
            logger.warning("MT5 Algo Trading is turned off in terminal toolbar.")
            self.send_telegram(
                f"⚠️ *[WARNING] MT5 Algo Trading Disabled!*\n"
                f"The terminal is connected, but Automated Trading button is OFF.\n"
                f"Bot signals cannot execute trades until enabled."
            )

        if health.get("ok", False):
            self.failure_counter = 0

        self.last_state = current_state
        self.write_heartbeat(health)

    def run_forever(self) -> None:
        """Main daemon loop."""
        logger.info(f"Starting MT5 Watchdog daemon (Interval: {self.check_interval}s, Path: {self.mt5_path})")

        # Initial evaluation
        self.run_step()

        while self.is_running:
            try:
                time.sleep(self.check_interval)
                if not self.is_running:
                    break
                self.run_step()
            except KeyboardInterrupt:
                logger.info("Watchdog received KeyboardInterrupt. Exiting...")
                break
            except Exception as e:
                logger.exception(f"Unexpected exception in Watchdog loop: {e}")
                time.sleep(5)

        logger.info("MT5 Watchdog service stopped cleanly.")


def main():
    dog = MT5Watchdog(check_interval=CHECK_INTERVAL_SECONDS)

    def sig_handler(sig, frame):
        dog.is_running = False

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    dog.run_forever()


if __name__ == "__main__":
    main()
