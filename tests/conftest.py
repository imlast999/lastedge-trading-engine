import sys
from unittest.mock import MagicMock

# Mock MetaTrader5 if not installed in python environment
if 'MetaTrader5' not in sys.modules:
    try:
        import MetaTrader5
    except ImportError:
        mt5_mock = MagicMock()
        mt5_mock.positions_get.return_value = []
        mt5_mock.account_info.return_value = None
        mt5_mock.symbol_info_tick.return_value = None
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
