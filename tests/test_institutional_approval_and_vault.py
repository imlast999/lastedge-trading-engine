"""
Tests para Aprobación Institucional, Slippage Guard, Auto-Expiración y Vault
=============================================================================
1. Slippage Guard con MT5 tick en vivo y bypass con force=True.
2. Endpoints REST POST /api/trading/signals/approve y POST /api/trading/signals/reject.
3. Auto-expiración de señales pendientes tras 10 minutos (TTL) a estado EXPIRED.
4. Inicialización y lógica de entrada de estrategias institucionales del Vault:
   - BTCEURTrendSurgeStrategy (required_history=850)
   - XAUUSDSurgeStrategy
   - EURUSDFlowStrategy
"""

from __future__ import annotations

import json
import time
import unittest
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import numpy as np

from services.database import get_database_manager
from services.bot_service import BotService
from services.autosignals import AutoSignalsService
from services.api_server import TradingAPIServer

from strategies.vault.btceur_trend_surge import BTCEURTrendSurgeStrategy
from strategies.vault.xauusd_surge import XAUUSDSurgeStrategy
from strategies.vault.eurusd_flow import EURUSDFlowStrategy


class TestInstitutionalApprovalAndVault(unittest.TestCase):

    def setUp(self):
        self.db_mgr = get_database_manager()
        with self.db_mgr.get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS enhanced_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    symbol TEXT,
                    direction TEXT,
                    signal_type TEXT,
                    strategy TEXT,
                    price REAL,
                    entry_price REAL,
                    sl_price REAL,
                    tp_price REAL,
                    score REAL,
                    confidence TEXT,
                    confidence_level TEXT,
                    confidence_score INTEGER,
                    lot_size REAL,
                    status TEXT,
                    executed INTEGER DEFAULT 0,
                    rejected INTEGER DEFAULT 0,
                    created_at TEXT,
                    timestamp TEXT,
                    mobile_processed INTEGER DEFAULT 0,
                    mt5_ticket INTEGER
                )
            """)
        self.bot_service = BotService()

    def test_slippage_guard_detection_and_force(self):
        now_iso = datetime.now(timezone.utc).isoformat()
        with self.db_mgr.get_connection() as conn:
            cur = conn.execute("""
                INSERT INTO enhanced_signals (
                    symbol, direction, signal_type, strategy, price, entry_price,
                    sl_price, tp_price, score, confidence_level, lot_size, status,
                    created_at, timestamp
                ) VALUES (
                    'XAUUSD', 'BUY', 'BUY', 'XAUUSD_Surge', 3998.00, 3998.00,
                    3985.00, 4030.00, 90.0, 'HIGH', 0.10, 'PROPOSED',
                    ?, ?
                )
            """, (now_iso, now_iso))
            sig_id = cur.lastrowid

        # Simular tick en 4005.00 (desviación de $7.00 USD > umbral de $1.20 USD)
        mock_tick = MagicMock()
        mock_tick.ask = 4005.00
        mock_tick.bid = 4004.50

        with patch("MetaTrader5.symbol_info_tick", return_value=mock_tick):
            with patch("services.execution.get_execution_service") as mock_exec_getter:
                mock_exec_svc = MagicMock()
                mock_exec_getter.return_value = mock_exec_svc

                # 1. Sin forzar: debe detectar PRICE_DRIFT y NO ejecutar orden
                res = self.bot_service.approve_signal(sig_id, force=False)
                self.assertFalse(res["ok"])
                self.assertEqual(res["error"], "PRICE_DRIFT")
                self.assertEqual(res["signal_price"], 3998.00)
                self.assertEqual(res["current_price"], 4005.00)
                self.assertIn("$7.00", res["drift_pips"])
                mock_exec_svc.execute_signal.assert_not_called()

                # Comprobar que en la base de datos la señal sigue PROPOSED
                with self.db_mgr.get_connection() as conn:
                    row = conn.execute("SELECT status FROM enhanced_signals WHERE id=?", (sig_id,)).fetchone()
                    self.assertEqual(row["status"], "PROPOSED")

                # 2. Con force=True: debe ignorar la desviación y ejecutar la orden
                mock_exec_svc.execute_signal.return_value = MagicMock(success=True, order_id=554433)
                res_force = self.bot_service.approve_signal(sig_id, force=True)
                self.assertTrue(res_force["ok"])
                self.assertEqual(res_force["ticket"], 554433)
                self.assertEqual(res_force["executed_price"], 4005.00)
                mock_exec_svc.execute_signal.assert_called_once()

                # Comprobar que en la base de datos la señal pasa a EXECUTED con su ticket
                with self.db_mgr.get_connection() as conn:
                    row = conn.execute("SELECT status, mt5_ticket, executed FROM enhanced_signals WHERE id=?", (sig_id,)).fetchone()
                    self.assertEqual(row["status"], "EXECUTED")
                    self.assertEqual(row["mt5_ticket"], 554433)
                    self.assertEqual(row["executed"], 1)

    def test_api_server_approve_and_reject_endpoints(self):
        port = 8896
        server = TradingAPIServer(port=port)
        server.start()
        time.sleep(0.3)

        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            with self.db_mgr.get_connection() as conn:
                # Señal 1: para rechazo
                cur = conn.execute("""
                    INSERT INTO enhanced_signals (
                        symbol, direction, signal_type, strategy, price, entry_price,
                        status, created_at, timestamp
                    ) VALUES ('EURUSD', 'SELL', 'SELL', 'EURUSD_Flow', 1.0850, 1.0850, 'PROPOSED', ?, ?)
                """, (now_iso, now_iso))
                sig_reject_id = cur.lastrowid

                # Señal 2: para aprobación
                cur = conn.execute("""
                    INSERT INTO enhanced_signals (
                        symbol, direction, signal_type, strategy, price, entry_price,
                        sl_price, tp_price, status, created_at, timestamp
                    ) VALUES ('EURUSD', 'BUY', 'BUY', 'EURUSD_Flow', 1.0820, 1.0820, 1.0800, 1.0880, 'PROPOSED', ?, ?)
                """, (now_iso, now_iso))
                sig_approve_id = cur.lastrowid

            # 1. Probar POST /api/trading/signals/reject
            reject_url = f"http://localhost:{port}/api/trading/signals/reject"
            req_data = json.dumps({"signal_id": sig_reject_id}).encode("utf-8")
            req = urllib.request.Request(reject_url, data=req_data, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.status, 200)
                data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(data.get("ok"))
                self.assertEqual(data.get("status"), "REJECTED_MANUAL")

            with self.db_mgr.get_connection() as conn:
                row = conn.execute("SELECT status, rejected FROM enhanced_signals WHERE id=?", (sig_reject_id,)).fetchone()
                self.assertEqual(row["status"], "REJECTED_MANUAL")
                self.assertEqual(row["rejected"], 1)

            # 2. Probar POST /api/trading/signals/approve con force=True
            with patch("MetaTrader5.symbol_info_tick", return_value=None):
                with patch("services.execution.get_execution_service") as mock_exec_getter:
                    mock_exec = MagicMock()
                    mock_exec.execute_signal.return_value = MagicMock(success=True, order_id=778899)
                    mock_exec_getter.return_value = mock_exec

                    approve_url = f"http://localhost:{port}/api/trading/signals/approve"
                    req_data = json.dumps({"signal_id": sig_approve_id, "force": True}).encode("utf-8")
                    req = urllib.request.Request(approve_url, data=req_data, headers={"Content-Type": "application/json"}, method="POST")
                    with urllib.request.urlopen(req) as resp:
                        self.assertEqual(resp.status, 200)
                        data = json.loads(resp.read().decode("utf-8"))
                        self.assertTrue(data.get("ok"))
                        self.assertEqual(data.get("ticket"), 778899)

            with self.db_mgr.get_connection() as conn:
                row = conn.execute("SELECT status, mt5_ticket FROM enhanced_signals WHERE id=?", (sig_approve_id,)).fetchone()
                self.assertEqual(row["status"], "EXECUTED")
                self.assertEqual(row["mt5_ticket"], 778899)

        finally:
            server.stop()

    def test_auto_expiration_ttl_10min(self):
        # Insertar señal de hace 12 minutos
        old_time = (datetime.now(timezone.utc) - timedelta(minutes=12)).isoformat()
        fresh_time = datetime.now(timezone.utc).isoformat()

        with self.db_mgr.get_connection() as conn:
            cur1 = conn.execute("""
                INSERT INTO enhanced_signals (
                    symbol, direction, signal_type, strategy, price, entry_price, status, created_at, timestamp
                ) VALUES ('BTCEUR', 'BUY', 'BUY', 'BTCEUR_Trend_Surge', 65000, 65000, 'PROPOSED', ?, ?)
            """, (old_time, old_time))
            sig_old_id = cur1.lastrowid

            cur2 = conn.execute("""
                INSERT INTO enhanced_signals (
                    symbol, direction, signal_type, strategy, price, entry_price, status, created_at, timestamp
                ) VALUES ('BTCEUR', 'BUY', 'BUY', 'BTCEUR_Trend_Surge', 65000, 65000, 'PROPOSED', ?, ?)
            """, (fresh_time, fresh_time))
            sig_fresh_id = cur2.lastrowid

        autosignals_svc = AutoSignalsService(config={
            "AUTOSIGNAL_SYMBOLS": ["BTCEUR"],
            "AUTOSIGNAL_INTERVAL": 10
        })

        expired_count = autosignals_svc._check_expired_signals()
        self.assertGreaterEqual(expired_count, 1)

        with self.db_mgr.get_connection() as conn:
            row_old = conn.execute("SELECT status FROM enhanced_signals WHERE id=?", (sig_old_id,)).fetchone()
            self.assertEqual(row_old["status"], "EXPIRED")

            row_fresh = conn.execute("SELECT status FROM enhanced_signals WHERE id=?", (sig_fresh_id,)).fetchone()
            self.assertEqual(row_fresh["status"], "PROPOSED")

    def test_vault_strategies_instantiation_and_rules(self):
        btc_strat = BTCEURTrendSurgeStrategy()
        xau_strat = XAUUSDSurgeStrategy()
        eur_strat = EURUSDFlowStrategy()

        # Comprobar metadatos institucionales
        self.assertEqual(btc_strat.metadata.symbol, "BTCEUR")
        self.assertEqual(btc_strat.metadata.required_history, 850)

        self.assertEqual(xau_strat.metadata.symbol, "XAUUSD")
        self.assertGreaterEqual(xau_strat.metadata.required_history, 200)

        self.assertEqual(eur_strat.metadata.symbol, "EURUSD")
        self.assertGreaterEqual(eur_strat.metadata.required_history, 200)

        # Comprobar que detect_setup en BTCEURTrendSurgeStrategy rechaza con len(df) < 850
        dates_short = pd.date_range("2026-01-01", periods=300, freq="1h")
        df_short = pd.DataFrame({
            "time": dates_short,
            "open": np.linspace(60000, 65000, 300),
            "high": np.linspace(60100, 65100, 300),
            "low": np.linspace(59900, 64900, 300),
            "close": np.linspace(60050, 65050, 300),
            "volume": np.random.uniform(50, 200, 300),
        })
        setup_short = btc_strat.detect_setup(df_short)
        self.assertIsNone(setup_short)

        # Probar que con len(df) >= 850 procesa la estrategia
        dates_long = pd.date_range("2026-01-01", periods=900, freq="1h")
        df_long = pd.DataFrame({
            "time": dates_long,
            "open": np.linspace(50000, 65000, 900),
            "high": np.linspace(50100, 65200, 900),
            "low": np.linspace(49900, 64800, 900),
            "close": np.linspace(50050, 65150, 900),
            "volume": np.random.uniform(50, 200, 900),
        })
        # Ejecuta sin excepción
        setup_long = btc_strat.detect_setup(df_long)
        # El resultado es un dict o None según condiciones técnicas de indicadores
        self.assertTrue(setup_long is None or isinstance(setup_long, dict))


if __name__ == "__main__":
    unittest.main()
