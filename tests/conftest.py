import sys
from unittest.mock import MagicMock

# Mock MetaTrader5 if not installed in python environment (e.g. Linux CI runners)
if 'MetaTrader5' not in sys.modules:
    try:
        import MetaTrader5
    except ImportError:
        mt5_mock = MagicMock()

        # MT5 Trade Retcodes
        mt5_mock.TRADE_RETCODE_DONE = 10009
        mt5_mock.TRADE_RETCODE_PLACED = 10008
        mt5_mock.TRADE_RETCODE_INVALID = 10013
        mt5_mock.TRADE_RETCODE_NO_MONEY = 10019

        # MT5 Trade Actions
        mt5_mock.TRADE_ACTION_DEAL = 1
        mt5_mock.TRADE_ACTION_PENDING = 5
        mt5_mock.TRADE_ACTION_SLTP = 6
        mt5_mock.TRADE_ACTION_MODIFY = 7
        mt5_mock.TRADE_ACTION_REMOVE = 8

        # MT5 Order & Position Types
        mt5_mock.ORDER_TYPE_BUY = 0
        mt5_mock.ORDER_TYPE_SELL = 1
        mt5_mock.POSITION_TYPE_BUY = 0
        mt5_mock.POSITION_TYPE_SELL = 1

        # MT5 Filling Modes
        mt5_mock.ORDER_FILLING_FOK = 0
        mt5_mock.ORDER_FILLING_IOC = 1
        mt5_mock.ORDER_FILLING_RETURN = 2

        # MT5 Time in Force
        mt5_mock.ORDER_TIME_GTC = 0
        mt5_mock.ORDER_TIME_DAY = 1
        mt5_mock.ORDER_TIME_SPECIFIED = 2

        # MT5 Timeframes
        mt5_mock.TIMEFRAME_M1 = 1
        mt5_mock.TIMEFRAME_M5 = 5
        mt5_mock.TIMEFRAME_M15 = 15
        mt5_mock.TIMEFRAME_H1 = 16385
        mt5_mock.TIMEFRAME_H4 = 16388
        mt5_mock.TIMEFRAME_D1 = 16408

        # Default method mocks
        mt5_mock.initialize.return_value = True
        mt5_mock.shutdown.return_value = True
        mt5_mock.terminal_info.return_value = MagicMock()
        mt5_mock.positions_get.return_value = []
        mt5_mock.account_info.return_value = None
        mt5_mock.symbol_info_tick.return_value = None
        mt5_mock.symbol_info.return_value = None
        mt5_mock.order_calc_margin.return_value = 100.0

        sys.modules['MetaTrader5'] = mt5_mock

# Mock discord if not installed in python environment
if 'discord' not in sys.modules:
    try:
        import discord
    except ImportError:
        discord_mock = MagicMock()
        sys.modules['discord'] = discord_mock
        sys.modules['discord.ext'] = MagicMock()
        sys.modules['discord.ext.commands'] = MagicMock()

# Mock private strategy vault if absent (e.g. public repository CI)
if 'strategies.vault' not in sys.modules:
    try:
        import strategies.vault
    except (ImportError, ModuleNotFoundError):
        import types
        from strategies.base import BaseStrategy, StrategyMetadata

        vault_mod = types.ModuleType("strategies.vault")
        sys.modules["strategies.vault"] = vault_mod

        class _StubBTCEURTrendSurge(BaseStrategy):
            def __init__(self):
                super().__init__("BTCEUR_Trend_Surge")
                self.strategy_name = "btceur_trend_surge"

            @property
            def metadata(self) -> StrategyMetadata:
                return StrategyMetadata(
                    required_history=850,
                    symbol="BTCEUR",
                    timeframe="H1",
                    strategy_name="btceur_trend_surge",
                    version="1.0",
                )

            def _add_specific_indicators(self, df):
                return df

            def _get_default_config(self):
                return {}

            def detect_setup(self, df):
                if len(df) < self.metadata.required_history:
                    return None
                return None

        class _StubXAUUSDSurge(BaseStrategy):
            def __init__(self):
                super().__init__("XAUUSD_Surge")
                self.strategy_name = "xauusd_surge"

            @property
            def metadata(self) -> StrategyMetadata:
                return StrategyMetadata(
                    required_history=200,
                    symbol="XAUUSD",
                    timeframe="H1",
                    strategy_name="xauusd_surge",
                    version="1.0",
                )

            def _add_specific_indicators(self, df):
                return df

            def _get_default_config(self):
                return {}

            def detect_setup(self, df):
                return None

        class _StubEURUSDFlow(BaseStrategy):
            def __init__(self):
                super().__init__("EURUSD_Flow")
                self.strategy_name = "eurusd_flow"

            @property
            def metadata(self) -> StrategyMetadata:
                return StrategyMetadata(
                    required_history=200,
                    symbol="EURUSD",
                    timeframe="H1",
                    strategy_name="eurusd_flow",
                    version="1.0",
                )

            def _add_specific_indicators(self, df):
                return df

            def _get_default_config(self):
                return {}

            def detect_setup(self, df):
                return None

        m1 = types.ModuleType("strategies.vault.btceur_trend_surge")
        m1.BTCEURTrendSurgeStrategy = _StubBTCEURTrendSurge
        sys.modules["strategies.vault.btceur_trend_surge"] = m1

        m2 = types.ModuleType("strategies.vault.xauusd_surge")
        m2.XAUUSDSurgeStrategy = _StubXAUUSDSurge
        sys.modules["strategies.vault.xauusd_surge"] = m2

        m3 = types.ModuleType("strategies.vault.eurusd_flow")
        m3.EURUSDFlowStrategy = _StubEURUSDFlow
        sys.modules["strategies.vault.eurusd_flow"] = m3
