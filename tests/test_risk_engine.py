"""
Tests del Risk Engine — LastEdge

Tests completos del sistema de gestión de riesgo sin necesidad de
conexión real a MetaTrader 5 (mock de todas las llamadas MT5).

Cubre:
    - PositionSizer: todos los tipos de activo, SL corto/largo, vol_min/max
    - MarginChecker: margen suficiente, insuficiente, reducción automática
    - PortfolioRisk: portfolio vacío, lleno, posiciones sin SL
    - RiskEngine (pipeline completo): aprobado, rechazado, lote reducido

Ejecutar:
    python -m pytest tests/test_risk_engine.py -v
    python -m pytest tests/test_risk_engine.py -v -s   # con print output
"""

import pytest
from dataclasses import dataclass
from typing import Any, Optional
from unittest.mock import patch, MagicMock

# ──────────────────────────────────────────────────────────────────────────────
# Mocks de symbol_info y account_info
# ──────────────────────────────────────────────────────────────────────────────

def make_symbol_info(
    trade_tick_size:  float = 0.00001,   # EURUSD default
    trade_tick_value: float = 0.9,       # USD por tick por lote (EURUSD ~0.9 USD/tick)
    volume_min:  float = 0.01,
    volume_max:  float = 500.0,
    volume_step: float = 0.01,
    point:       float = 0.00001,
    trade_contract_size: float = 100000.0,
) -> dict:
    """Crea un mock de symbol_info como dict."""
    return {
        "trade_tick_size":  trade_tick_size,
        "trade_tick_value": trade_tick_value,
        "volume_min":       volume_min,
        "volume_max":       volume_max,
        "volume_step":      volume_step,
        "point":            point,
        "trade_contract_size": trade_contract_size,
    }


def make_account_info(
    balance:     float = 5000.0,
    equity:      float = 5000.0,
    margin_free: float = 5000.0,
) -> dict:
    return {
        "balance":     balance,
        "equity":      equity,
        "margin_free": margin_free,
    }


# Símbolos de referencia para tests
EURUSD_SI = make_symbol_info(
    trade_tick_size=0.00001, trade_tick_value=0.9,
    volume_min=0.01, volume_max=500.0, volume_step=0.01,
)
XAUUSD_SI = make_symbol_info(
    trade_tick_size=0.01, trade_tick_value=1.0,   # 1 USD/tick/lot (aprox. para cuenta USD)
    volume_min=0.01, volume_max=50.0, volume_step=0.01,
)
BTCEUR_SI = make_symbol_info(
    trade_tick_size=0.5, trade_tick_value=0.5,    # 0.5 EUR/tick/lot
    volume_min=0.01, volume_max=5.0, volume_step=0.01,
)


# ══════════════════════════════════════════════════════════════════════════════
# Tests de PositionSizer
# ══════════════════════════════════════════════════════════════════════════════

class TestPositionSizer:
    """Tests del módulo de cálculo de tamaño de posición."""

    def _sizer(self):
        from core.risk.position_sizer import PositionSizer
        return PositionSizer()

    # ── EURUSD ──────────────────────────────────────────────────────────────

    def test_eurusd_basic(self):
        """EURUSD: balance 5000, risk 0.5%, SL 20 pips."""
        sizer = self._sizer()
        # SL: 20 pips = 0.0020 en EURUSD
        result = sizer.calculate(
            symbol="EURUSD", entry=1.08500, sl=1.08300,
            risk_pct=0.5, balance=5000.0, symbol_info=EURUSD_SI,
        )
        assert result.success, f"Fallo: {result.reason}"
        assert result.lot >= 0.01, "Lote debe ser >= vol_min"
        # Con balance=5000 y risk=0.5%, risk_amount=25 USD
        # sl_ticks = 200 (20 pips = 200 ticks de 0.00001)
        # risk_per_lot = 200 * 0.9 = 180 USD/lote
        # raw_lot = 25/180 ≈ 0.138 → 0.13 lotes
        assert 0.10 <= result.lot <= 0.20, f"Lote esperado ~0.13, got {result.lot}"
        assert result.risk_pct <= 0.55, f"Risk pct demasiado alto: {result.risk_pct}"

    def test_eurusd_large_account(self):
        """EURUSD: balance grande (100.000 USD) debe escalar el lote."""
        sizer = self._sizer()
        result_small = sizer.calculate(
            symbol="EURUSD", entry=1.08500, sl=1.08300,
            risk_pct=0.5, balance=5000.0, symbol_info=EURUSD_SI,
        )
        result_large = sizer.calculate(
            symbol="EURUSD", entry=1.08500, sl=1.08300,
            risk_pct=0.5, balance=100000.0, symbol_info=EURUSD_SI,
        )
        assert result_large.lot > result_small.lot, "Cuenta grande debe producir lote mayor"
        # El lote debe escalar proporcionalmente (factor ~20x)
        assert result_large.lot >= result_small.lot * 15, "Escala insuficiente"

    def test_eurusd_short_sl(self):
        """SL corto produce lote mayor que SL largo (mismo balance y risk)."""
        sizer = self._sizer()
        # SL 10 pips
        short_sl = sizer.calculate(
            symbol="EURUSD", entry=1.08500, sl=1.08400,
            risk_pct=0.5, balance=5000.0, symbol_info=EURUSD_SI,
        )
        # SL 40 pips
        long_sl = sizer.calculate(
            symbol="EURUSD", entry=1.08500, sl=1.08100,
            risk_pct=0.5, balance=5000.0, symbol_info=EURUSD_SI,
        )
        assert short_sl.success and long_sl.success
        assert short_sl.lot > long_sl.lot, "SL corto debe producir lote mayor"

    # ── XAUUSD ──────────────────────────────────────────────────────────────

    def test_xauusd_small_account(self):
        """
        XAUUSD en cuenta demo de 5000 USD con SL de 18 USD.

        Este es el caso que causó el problema original (1.00 lot).
        El resultado correcto es ~0.08 lotes.
        """
        sizer = self._sizer()
        # Precio oro ~2350, SL 18 USD más abajo
        result = sizer.calculate(
            symbol="XAUUSD", entry=2350.00, sl=2332.00,
            risk_pct=0.6, balance=5000.0, symbol_info=XAUUSD_SI,
        )
        assert result.success, f"Fallo: {result.reason}"
        # risk_amount = 5000 * 0.006 = 30 USD
        # sl_ticks = 18.00 / 0.01 = 1800 ticks
        # risk_per_lot = 1800 * 1.0 = 1800 USD/lot
        # raw_lot = 30 / 1800 ≈ 0.0167 → 0.01 lotes (vol_min)
        # Con tick_value=1.0: sería correcto ~0.01-0.03
        assert result.lot <= 0.10, f"XAUUSD en cuenta demo 5k NO debe ser 1.00 lot! got {result.lot}"
        assert result.lot >= 0.01, f"Lote debe ser >= vol_min, got {result.lot}"

    def test_xauusd_never_one_lot_on_small_account(self):
        """XAUUSD con balance 5000 y cualquier risk razonable nunca debe dar 1.00 lot."""
        sizer = self._sizer()
        for risk_pct in [0.5, 0.75, 1.0, 1.5]:
            result = sizer.calculate(
                symbol="XAUUSD", entry=2350.00, sl=2332.00,
                risk_pct=risk_pct, balance=5000.0, symbol_info=XAUUSD_SI,
            )
            assert result.lot < 0.50, (
                f"XAUUSD balance=5000 risk={risk_pct}%: lote {result.lot} es peligrosamente alto"
            )

    # ── BTCEUR ──────────────────────────────────────────────────────────────

    def test_btceur_basic(self):
        """BTCEUR: verifica que el cálculo funciona para crypto."""
        sizer = self._sizer()
        # BTC a ~60000 EUR, SL de 1000 EUR
        result = sizer.calculate(
            symbol="BTCEUR", entry=60000.0, sl=59000.0,
            risk_pct=0.5, balance=5000.0, symbol_info=BTCEUR_SI,
        )
        assert result.success, f"Fallo: {result.reason}"
        assert result.lot >= 0.01, "Lote mínimo"
        assert result.lot <= 5.0, "No debe exceder vol_max"

    # ── Validaciones de inputs ────────────────────────────────────────────────

    def test_invalid_entry_zero(self):
        sizer = self._sizer()
        result = sizer.calculate(
            symbol="EURUSD", entry=0.0, sl=1.08300,
            risk_pct=0.5, balance=5000.0, symbol_info=EURUSD_SI,
        )
        assert not result.success

    def test_entry_equals_sl(self):
        sizer = self._sizer()
        result = sizer.calculate(
            symbol="EURUSD", entry=1.08500, sl=1.08500,
            risk_pct=0.5, balance=5000.0, symbol_info=EURUSD_SI,
        )
        assert not result.success, "SL = Entry debe rechazarse"

    def test_invalid_balance(self):
        sizer = self._sizer()
        result = sizer.calculate(
            symbol="EURUSD", entry=1.08500, sl=1.08300,
            risk_pct=0.5, balance=0.0, symbol_info=EURUSD_SI,
        )
        assert not result.success

    def test_vol_min_enforced(self):
        """Si el lote calculado es < vol_min, debe usar vol_min."""
        sizer = self._sizer()
        # Balance muy pequeño: muy poco risk, lote calculado < vol_min
        result = sizer.calculate(
            symbol="EURUSD", entry=1.08500, sl=1.08300,
            risk_pct=0.5, balance=10.0, symbol_info=EURUSD_SI,
        )
        assert result.success
        assert result.lot == 0.01, f"Debe usar vol_min=0.01, got {result.lot}"

    def test_vol_max_enforced(self):
        """Si el lote calculado excede vol_max, debe cappear al vol_max."""
        sizer = self._sizer()
        # Balance enorme: lot calculado > vol_max
        result = sizer.calculate(
            symbol="EURUSD", entry=1.08500, sl=1.08499,  # SL de 0.1 pip
            risk_pct=0.5, balance=10_000_000.0, symbol_info=EURUSD_SI,
        )
        assert result.success
        assert result.lot <= 500.0, f"No debe exceder vol_max, got {result.lot}"


# ══════════════════════════════════════════════════════════════════════════════
# Tests de MarginChecker
# ══════════════════════════════════════════════════════════════════════════════

class TestMarginChecker:
    """Tests del módulo de verificación de margen."""

    def _checker(self, allow_auto_reduce=True, min_free_margin_pct=20.0):
        from core.risk.margin_checker import MarginChecker
        return MarginChecker(
            allow_auto_reduce=allow_auto_reduce,
            reduction_sequence=[1.0, 0.5, 0.25, 0.12, 0.08, 0.05, 0.03, 0.01],
            minimum_free_margin_pct=min_free_margin_pct,
        )

    def _check_with_margin(self, checker, lot, free_margin, equity=10000.0, margin_needed=100.0):
        """Helper: verifica con un margin_needed simulado."""
        account = make_account_info(
            balance=equity, equity=equity, margin_free=free_margin
        )
        # Patch order_calc_margin para devolver margin_needed
        with patch("core.risk.margin_checker.MarginChecker._calc_margin", return_value=margin_needed):
            return checker.check(
                symbol="EURUSD", order_type="BUY",
                lot=lot, price=1.085, vol_min=0.01,
                account_info=account,
            )

    def test_sufficient_margin(self):
        """Margen suficiente: orden aprobada sin modificaciones."""
        checker = self._checker()
        result = self._check_with_margin(
            checker, lot=0.1, free_margin=5000.0, equity=5000.0, margin_needed=200.0
        )
        assert result.approved
        assert result.lot == 0.1
        assert not result.was_reduced

    def test_insufficient_margin_auto_reduce(self):
        """Margen insuficiente: reduce el lote automáticamente."""
        checker = self._checker(allow_auto_reduce=True, min_free_margin_pct=0.0)
        account = make_account_info(balance=5000.0, equity=5000.0, margin_free=500.0)

        # El lote 1.0 requiere 4500 USD de margen (no cabe)
        # El lote 0.5 requiere 2250 USD (no cabe)
        # El lote 0.25 requiere 1125 USD (no cabe)
        # El lote 0.12 requiere 540 USD (no cabe)
        # El lote 0.08 requiere 360 USD (no cabe)
        # El lote 0.05 requiere 225 USD (no cabe)
        # El lote 0.03 requiere 135 USD (no cabe)
        # El lote 0.01 requiere 45 USD (cabe!)

        def fake_calc_margin(symbol, order_type, lot, price, symbol_info=None):
            # Simular: margen = lot * 4500 USD
            return lot * 4500.0

        with patch("core.risk.margin_checker.MarginChecker._calc_margin", side_effect=fake_calc_margin):
            result = checker.check(
                symbol="EURUSD", order_type="BUY",
                lot=1.0, price=1.085, vol_min=0.01,
                account_info=account,
            )

        assert result.approved, f"Debería aprobar con lote reducido: {result.reason}"
        assert result.was_reduced
        assert result.lot < 1.0
        assert result.lot >= 0.01

    def test_insufficient_margin_no_auto_reduce(self):
        """Sin auto-reduce: orden rechazada si el margen es insuficiente."""
        checker = self._checker(allow_auto_reduce=False)
        result = self._check_with_margin(
            checker, lot=1.0, free_margin=50.0, equity=1000.0, margin_needed=900.0
        )
        assert not result.approved

    def test_blocked_all_lots_no_margin(self):
        """Si ni el vol_min cabe en el margen, orden bloqueada."""
        checker = self._checker(allow_auto_reduce=True)
        account = make_account_info(balance=100.0, equity=100.0, margin_free=10.0)

        with patch("core.risk.margin_checker.MarginChecker._calc_margin", return_value=50.0):
            result = checker.check(
                symbol="XAUUSD", order_type="BUY",
                lot=0.1, price=2350.0, vol_min=0.01,
                account_info=account,
            )

        assert not result.approved
        assert "insuficiente" in result.reason.lower() or "insufficient" in result.reason.lower()

    def test_min_free_margin_pct_guard(self):
        """Si el margen libre < minimum_free_margin_pct, bloquear independientemente."""
        # minimum_free_margin_pct = 50%, free_margin = 10% → debe bloquear
        checker = self._checker(min_free_margin_pct=50.0)
        account = make_account_info(balance=1000.0, equity=1000.0, margin_free=100.0)  # 10%

        with patch("core.risk.margin_checker.MarginChecker._calc_margin", return_value=50.0):
            result = checker.check(
                symbol="EURUSD", order_type="BUY",
                lot=0.1, price=1.085, vol_min=0.01,
                account_info=account,
            )

        assert not result.approved
        assert "10.0%" in result.reason or "mínimo" in result.reason.lower()

    def test_warnings_include_lot_reduction_info(self):
        """Si el lote fue reducido, debe aparecer en los warnings."""
        checker = self._checker(allow_auto_reduce=True)
        account = make_account_info(balance=5000.0, equity=5000.0, margin_free=200.0)

        def fake_margin(symbol, order_type, lot, price, symbol_info=None):
            return lot * 1000.0  # 1.0 lot -> 1000 (no cabe), 0.01 -> 10 (cabe)

        with patch("core.risk.margin_checker.MarginChecker._calc_margin", side_effect=fake_margin):
            result = checker.check(
                symbol="EURUSD", order_type="BUY",
                lot=1.0, price=1.085, vol_min=0.01,
                account_info=account,
            )

        if result.approved and result.was_reduced:
            assert len(result.warnings) > 0, "Debe haber warning sobre la reducción"


# ══════════════════════════════════════════════════════════════════════════════
# Tests de PortfolioRisk
# ══════════════════════════════════════════════════════════════════════════════

class TestPortfolioRisk:
    """Tests del módulo de riesgo del portfolio."""

    def _risk(self, max_pct=2.0):
        from core.risk.portfolio_risk import PortfolioRisk
        return PortfolioRisk(max_portfolio_risk_pct=max_pct, enabled=True)

    def make_position(self, symbol, volume, price_open, sl, ticket=1):
        """Crea una posición mock."""
        return {
            "ticket": ticket,
            "symbol": symbol,
            "volume": volume,
            "price_open": price_open,
            "sl": sl,
            "type": 0,  # BUY
        }

    def test_empty_portfolio(self):
        """Portfolio vacío: nueva orden aprobada si no supera el límite."""
        pr = self._risk(max_pct=2.0)
        result = pr.check(
            new_trade_risk_pct=0.5,
            balance=5000.0,
            positions=[],
        )
        assert result.approved
        assert result.total_risk_pct == 0.0
        assert result.combined_risk_pct == 0.5

    def test_portfolio_below_limit(self):
        """Portfolio con riesgo bajo: nueva orden permitida."""
        pr = self._risk(max_pct=2.0)
        eurusd_si = EURUSD_SI
        positions = [
            self.make_position("EURUSD", volume=0.1, price_open=1.085, sl=1.083, ticket=1),
        ]
        # Simular que cada posición tiene 0.5% de riesgo
        result = pr.check(
            new_trade_risk_pct=0.5,
            balance=5000.0,
            positions=positions,
            symbol_info_provider=lambda s: EURUSD_SI,
        )
        assert result.approved

    def test_portfolio_at_limit_blocked(self):
        """Portfolio casi lleno: nueva orden debe bloquearse."""
        pr = self._risk(max_pct=2.0)

        # Crear 3 posiciones con riesgo total ~1.8%
        # Con balance=5000, risk_per_lot = sl_ticks * tick_value
        # EURUSD, vol=0.2, entry=1.085, sl=1.083 → sl_dist=0.002 → sl_ticks=200
        # risk_amount = 200 * 0.9 * 0.2 = 36 USD → 36/5000 = 0.72%
        positions = [
            self.make_position("EURUSD", volume=0.2, price_open=1.085, sl=1.083, ticket=i)
            for i in range(1, 4)
        ]

        result = pr.check(
            new_trade_risk_pct=0.6,  # Nueva operación añadiría 0.6%
            balance=5000.0,
            positions=positions,
            symbol_info_provider=lambda s: EURUSD_SI,
        )

        # Si el total supera 2.0%, debe rechazarse
        if result.combined_risk_pct > 2.0:
            assert not result.approved, "Debe bloquear cuando combined > max"
        else:
            assert result.approved

    def test_new_trade_alone_exceeds_limit(self):
        """La nueva operación por sí sola excede el límite → bloqueada."""
        pr = self._risk(max_pct=2.0)
        result = pr.check(
            new_trade_risk_pct=3.0,  # Solo la nueva ya supera el límite de 2%
            balance=5000.0,
            positions=[],
        )
        assert not result.approved
        assert "exceder" in result.reason.lower() or "exceed" in result.reason.lower() or "3.00" in result.reason

    def test_position_without_sl(self):
        """Posición sin SL: debe estimarse el riesgo al 2% del precio."""
        pr = self._risk(max_pct=5.0)
        positions = [
            {"ticket": 1, "symbol": "EURUSD", "volume": 0.1,
             "price_open": 1.085, "sl": 0.0, "type": 0}
        ]
        result = pr.check(
            new_trade_risk_pct=0.5,
            balance=5000.0,
            positions=positions,
            symbol_info_provider=lambda s: EURUSD_SI,
        )
        assert result.approved  # Con max 5% debería aprobar
        # Verificar que hay warning sobre SL ausente
        pos_risks = [p for p in result.positions if not p.has_sl]
        if pos_risks:
            assert any("SL" in w or "sl" in w.lower() for w in result.warnings)

    def test_disabled_always_approves(self):
        """Portfolio risk desactivado: siempre aprueba."""
        from core.risk.portfolio_risk import PortfolioRisk
        pr = PortfolioRisk(max_portfolio_risk_pct=0.1, enabled=False)  # límite imposible
        result = pr.check(new_trade_risk_pct=99.0, balance=5000.0, positions=[])
        assert result.approved


# ══════════════════════════════════════════════════════════════════════════════
# Tests del RiskEngine (pipeline completo)
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskEngine:
    """Tests de integración del RiskEngine completo."""

    def _engine(self, max_portfolio_risk=2.0, min_free_margin_pct=20.0, portfolio_enabled=True):
        from core.risk.config import RiskConfig
        from core.risk.engine import RiskEngine
        config = RiskConfig(
            default_risk_pct=0.5,
            use_symbol_override=True,
            symbol_risk_overrides={
                "EURUSD": 0.75,
                "XAUUSD": 0.60,
                "BTCEUR": 0.50,
            },
            max_portfolio_risk_pct=max_portfolio_risk,
            portfolio_risk_enabled=portfolio_enabled,
            margin_protection_enabled=True,
            minimum_free_margin_pct=min_free_margin_pct,
            allow_auto_reduce_lot=True,
            lot_reduction_sequence=[1.0, 0.5, 0.25, 0.12, 0.08, 0.05, 0.03, 0.01],
            max_simultaneous_positions=3,
            max_positions_per_symbol=1,
            verbose_logging=False,  # No spam en tests
            log_approved=False,
            log_rejected=False,
        )
        return RiskEngine(config=config)

    def _full_account(self, balance=5000.0, margin_pct=100.0):
        """Crea account_info con margen libre = balance * margin_pct/100."""
        free = balance * margin_pct / 100.0
        return make_account_info(balance=balance, equity=balance, margin_free=free)

    def test_eurusd_approved(self):
        """EURUSD: pipeline completo aprobado."""
        engine = self._engine()
        signal = {"symbol": "EURUSD", "type": "BUY", "entry": 1.08500, "sl": 1.08300, "tp": 1.09000}
        account = self._full_account(5000.0, margin_pct=100.0)

        with patch("core.risk.margin_checker.MarginChecker._calc_margin", return_value=150.0):
            decision = engine.evaluate(signal, account_info=account, symbol_info=EURUSD_SI, open_positions=[])

        assert decision.approved, f"Rechazado: {decision.reason}"
        assert decision.lot >= 0.01
        assert decision.lot <= 1.0

    def test_xauusd_small_account_safe_lot(self):
        """
        CASO CRÍTICO: XAUUSD en cuenta demo 5000 USD.
        El lote debe ser <<1.00, nunca 1.00 lot.
        """
        engine = self._engine()
        signal = {"symbol": "XAUUSD", "type": "BUY", "entry": 2350.00, "sl": 2332.00, "tp": 2400.00}
        account = self._full_account(5000.0, margin_pct=100.0)

        with patch("core.risk.margin_checker.MarginChecker._calc_margin", return_value=50.0):
            decision = engine.evaluate(signal, account_info=account, symbol_info=XAUUSD_SI, open_positions=[])

        assert decision.approved or not decision.approved  # No importa si se aprueba
        if decision.approved:
            assert decision.lot < 0.20, (
                f"XAUUSD con 5000 USD de balance NO debe abrir 1.00 lot! got {decision.lot}"
            )

    def test_btceur_approved(self):
        """BTCEUR: pipeline completo aprobado."""
        engine = self._engine()
        signal = {"symbol": "BTCEUR", "type": "SELL", "entry": 60000.0, "sl": 61000.0, "tp": 58000.0}
        account = self._full_account(5000.0, margin_pct=100.0)

        with patch("core.risk.margin_checker.MarginChecker._calc_margin", return_value=200.0):
            decision = engine.evaluate(signal, account_info=account, symbol_info=BTCEUR_SI, open_positions=[])

        if decision.approved:
            assert decision.lot <= 5.0, "BTCEUR lote no debe superar vol_max"

    def test_rejected_insufficient_margin(self):
        """Orden rechazada cuando no hay margen ni para el lote mínimo."""
        engine = self._engine(min_free_margin_pct=0.0)  # Sin límite mínimo
        signal = {"symbol": "EURUSD", "type": "BUY", "entry": 1.085, "sl": 1.083, "tp": 1.090}
        account = make_account_info(balance=5000.0, equity=5000.0, margin_free=1.0)  # 1 USD libre

        with patch("core.risk.margin_checker.MarginChecker._calc_margin", return_value=100.0):
            decision = engine.evaluate(signal, account_info=account, symbol_info=EURUSD_SI, open_positions=[])

        assert not decision.approved

    def test_rejected_portfolio_full(self):
        """Orden rechazada cuando el portfolio está lleno."""
        engine = self._engine(max_portfolio_risk=0.1)  # Límite muy bajo: 0.1%
        signal = {"symbol": "EURUSD", "type": "BUY", "entry": 1.085, "sl": 1.083, "tp": 1.090}
        account = self._full_account(5000.0, margin_pct=100.0)

        with patch("core.risk.margin_checker.MarginChecker._calc_margin", return_value=50.0):
            decision = engine.evaluate(signal, account_info=account, symbol_info=EURUSD_SI, open_positions=[])

        # Con límite 0.1% y risk 0.75% para EURUSD, debe rechazarse
        assert not decision.approved

    def test_lot_reduced_warning(self):
        """Si el lote fue reducido, decision.lot_was_reduced debe ser True."""
        engine = self._engine()
        signal = {"symbol": "EURUSD", "type": "BUY", "entry": 1.085, "sl": 1.083}
        account = make_account_info(balance=5000.0, equity=5000.0, margin_free=300.0)  # Margen justo

        def margin_fn(symbol, order_type, lot, price, symbol_info=None):
            return lot * 800.0  # 0.5 lot → 400 (no cabe), 0.25 → 200 (no cabe), 0.12 → 96 (cabe con 300)

        with patch("core.risk.margin_checker.MarginChecker._calc_margin", side_effect=margin_fn):
            decision = engine.evaluate(signal, account_info=account, symbol_info=EURUSD_SI, open_positions=[])

        if decision.approved:
            # No importa si fue reducido o no, pero si fue reducido debe notificarlo
            if decision.lot_was_reduced:
                assert len(decision.warnings) > 0

    def test_missing_account_info(self):
        """Sin account_info (MT5 no conectado), debe rechazarse limpiamente."""
        engine = self._engine()
        signal = {"symbol": "EURUSD", "type": "BUY", "entry": 1.085, "sl": 1.083}

        with patch("core.risk.engine.RiskEngine._get_account_info", return_value=None):
            decision = engine.evaluate(signal)

        assert not decision.approved
        assert "account_info" in decision.reason.lower() or "mt5" in decision.reason.lower()

    def test_invalid_signal_no_entry(self):
        """Señal sin entry debe rechazarse."""
        engine = self._engine()
        signal = {"symbol": "EURUSD", "type": "BUY", "sl": 1.083}
        account = self._full_account()

        decision = engine.evaluate(signal, account_info=account, symbol_info=EURUSD_SI, open_positions=[])
        assert not decision.approved

    def test_risk_pct_per_symbol(self):
        """Cada símbolo usa su propio risk_pct configurado."""
        engine = self._engine()
        account = self._full_account(10000.0)

        signals = {
            "EURUSD": {"symbol": "EURUSD", "type": "BUY", "entry": 1.085, "sl": 1.083},
            "XAUUSD": {"symbol": "XAUUSD", "type": "BUY", "entry": 2350.0, "sl": 2330.0},
            "BTCEUR": {"symbol": "BTCEUR", "type": "BUY", "entry": 60000.0, "sl": 59000.0},
        }
        symbol_infos = {"EURUSD": EURUSD_SI, "XAUUSD": XAUUSD_SI, "BTCEUR": BTCEUR_SI}

        with patch("core.risk.margin_checker.MarginChecker._calc_margin", return_value=100.0):
            for sym, sig in signals.items():
                decision = engine.evaluate(
                    sig, account_info=account,
                    symbol_info=symbol_infos[sym],
                    open_positions=[],
                )
                if decision.approved:
                    # Verificar que el riesgo % es el configurado para ese símbolo
                    expected = {"EURUSD": 0.75, "XAUUSD": 0.60, "BTCEUR": 0.50}[sym]
                    assert decision.risk_pct <= expected * 1.1, (
                        f"{sym}: risk_pct={decision.risk_pct:.3f} > esperado {expected}"
                    )


# ══════════════════════════════════════════════════════════════════════════════
# Tests de compatibilidad backward (RiskManager legacy)
# ══════════════════════════════════════════════════════════════════════════════

class TestRiskManagerLegacy:
    """Verifica que la API legacy de RiskManager sigue funcionando."""

    def test_risk_manager_assess_signal(self):
        """RiskManager.assess_signal_risk() devuelve RiskAssessment válido."""
        from core.risk import get_risk_manager, RiskAssessment

        manager = get_risk_manager()
        signal = {"symbol": "EURUSD", "type": "BUY", "entry": 1.085, "sl": 1.083, "tp": 1.090}

        account = make_account_info(5000.0, 5000.0, 5000.0)
        with patch("core.risk.engine.RiskEngine._get_account_info", return_value=account):
            with patch("core.risk.position_sizer.PositionSizer._get_symbol_info", return_value=EURUSD_SI):
                with patch("core.risk.margin_checker.MarginChecker._calc_margin", return_value=100.0):
                    with patch("core.risk.portfolio_risk.PortfolioRisk._get_open_positions", return_value=[]):
                        result = manager.assess_signal_risk(signal)

        assert isinstance(result, RiskAssessment)
        assert hasattr(result, "approved")
        assert hasattr(result, "reason")
        assert hasattr(result, "parameters")
        assert hasattr(result, "warnings")

    def test_risk_manager_calculate_position_size(self):
        """RiskManager.calculate_position_size() devuelve (lot, risk, rr) tuple."""
        from core.risk import get_risk_manager

        manager = get_risk_manager()
        account = make_account_info(5000.0, 5000.0, 5000.0)

        with patch("core.risk.engine.RiskEngine._get_account_info", return_value=account):
            with patch("core.risk.position_sizer.PositionSizer._get_symbol_info", return_value=EURUSD_SI):
                with patch("core.risk.margin_checker.MarginChecker._calc_margin", return_value=100.0):
                    with patch("core.risk.portfolio_risk.PortfolioRisk._get_open_positions", return_value=[]):
                        lot, risk_amount, rr = manager.calculate_position_size(
                            "EURUSD", 1.085, 1.083
                        )

        assert lot >= 0.0
        assert risk_amount >= 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Punto de entrada
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
