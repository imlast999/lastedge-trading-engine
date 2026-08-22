import importlib


def test_partial_strategies_are_registered_and_loadable():
    signals = importlib.import_module('services.signals')
    strategies_pkg = importlib.import_module('strategies')

    xauusd_strategy = signals.STRATEGY_REGISTRY['xauusd_partial']()
    btceur_strategy = signals.STRATEGY_REGISTRY['btceur_partial']()

    assert xauusd_strategy.__class__.__name__ == 'XAUUSDPartialStrategy'
    assert btceur_strategy.__class__.__name__ == 'BTCEURPartialStrategy'

    assert strategies_pkg.STRATEGY_REGISTRY['XAUUSD'] is strategies_pkg.XAUUSDPartialStrategy
    assert strategies_pkg.STRATEGY_REGISTRY['BTCEUR'] is strategies_pkg.BTCEURPartialStrategy
