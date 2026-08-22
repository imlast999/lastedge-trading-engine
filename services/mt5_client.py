import MetaTrader5 as mt5
import logging
import pandas as pd
import time

logger = logging.getLogger(__name__)

def initialize(path=None, retries: int = 3, backoff_factor: float = 2.0, initial_delay: float = 1.0):
    """Initialize MT5 with simple retry/backoff.
    Attempts to initialize MT5 up to `retries` times with exponential backoff.
    Returns True on success, raises RuntimeError on failure.
    """
    import os
    from dotenv import load_dotenv
    load_dotenv()

    login_id_str = os.getenv('MT5_LOGIN')
    password = os.getenv('MT5_PASSWORD')
    server = os.getenv('MT5_SERVER')

    # Strip quotes if they were included literally in the .env file
    if password and password.startswith('"') and password.endswith('"'):
        password = password[1:-1]
    if server and server.startswith('"') and server.endswith('"'):
        server = server[1:-1]

    kwargs = {}
    if path:
        kwargs['path'] = path
    if login_id_str and password and server:
        try:
            kwargs['login'] = int(login_id_str)
            kwargs['password'] = password
            kwargs['server'] = server
        except ValueError:
            pass

    attempt = 0
    while True:
        try:
            ok = mt5.initialize(**kwargs)
            if ok:
                logger.info("MT5 initialized")
                return True
            else:
                err = mt5.last_error()
                msg = f"MT5 initialize failed: {err}"
                logger.error(msg)
                # fall through to retry logic
        except Exception:
            logger.exception("Exception while initializing MT5")

        attempt += 1
        if attempt >= retries:
            raise RuntimeError(f"MT5 initialize failed after {retries} attempts. Last error: {mt5.last_error()}")
        # sleep with exponential backoff before retrying
        delay = initial_delay * (backoff_factor ** (attempt - 1))
        logger.info("Retrying MT5 initialize in %.1f seconds (attempt %d/%d)", delay, attempt + 1, retries)
        time.sleep(delay)

def shutdown():
    try:
        mt5.shutdown()
        logger.info("MT5 shutdown")
    except Exception:
        logger.exception("Error shutting down MT5")

def get_candles(symbol, timeframe, n):
    """Return a pandas.DataFrame with the last `n` candles for `symbol`.

    Raises RuntimeError if data cannot be retrieved.
    """
    # ensure MT5 is initialized
    try:
        if not initialize():
            # if initialize returns False, log and continue
            logger.debug('initialize() returned False (may already be initialized)')
    except Exception:
        logger.exception('Exception calling mt5.initialize')

    # validate symbol
    si = mt5.symbol_info(symbol)
    if si is None:
        # try to find a close match in available symbols
        try:
            syms = mt5.symbols_get()
            if syms is None:
                # MT5 desconectado — no intentar iterar sobre None
                msg = f"MT5 disconnected, cannot get symbols for {symbol}"
                logger.error(msg)
                raise RuntimeError(msg)
            matches = [s.name for s in syms if symbol.lower() in s.name.lower()]
            if matches:
                new_sym = matches[0]
                logger.warning('Symbol %s not found; using close match %s', symbol, new_sym)
                symbol = new_sym
                si = mt5.symbol_info(symbol)
            else:
                msg = f"Symbol not available in MT5 terminal: {symbol}"
                logger.error(msg)
                raise RuntimeError(msg)
        except Exception:
            msg = f"Symbol not available in MT5 terminal: {symbol}"
            logger.exception(msg)
            raise RuntimeError(msg)

    # ensure symbol is selected/visible
    if not si.visible:
        try:
            ok = mt5.symbol_select(symbol, True)
            logger.info('symbol_select(%s) -> %s', symbol, ok)
        except Exception:
            logger.exception('symbol_select failed for %s', symbol)

    # support timeframe passed as string (e.g. 'H1')
    if isinstance(timeframe, str):
        tf = timeframe.upper()
        tf_map = {
            'M1': mt5.TIMEFRAME_M1,
            'M5': mt5.TIMEFRAME_M5,
            'M15': mt5.TIMEFRAME_M15,
            'M30': mt5.TIMEFRAME_M30,
            'H1': mt5.TIMEFRAME_H1,
            'H4': mt5.TIMEFRAME_H4,
            'D1': mt5.TIMEFRAME_D1,
        }
        timeframe = tf_map.get(tf, timeframe)

    # try copying rates with a couple of attempts to avoid transient terminal errors
    attempts = 0
    while attempts < 3:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
        if rates is None:
            err = mt5.last_error()
            logger.warning('copy_rates_from_pos returned None for %s (attempt %d): %s', symbol, attempts + 1, err)
            attempts += 1
            time.sleep(0.5 * attempts)
            continue

        if len(rates) == 0:
            msg = f'No candle data returned from MT5 for {symbol} (timeframe={timeframe})'
            logger.error(msg)
            raise RuntimeError(msg)

        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        # attach symbol name for convenience
        df.attrs['symbol'] = symbol
        df['symbol'] = symbol
        return df

    # if we exhausted attempts
    err = mt5.last_error()
    msg = f"Failed to copy rates after retries for {symbol}: {err}"
    logger.error(msg)
    raise RuntimeError(msg)


def login(login_id, password, server=None):
    """Login to account after initializing MT5. Returns True on success else False.

    Raises RuntimeError on initialization failure.
    """
    initialize()
    try:
        if server:
            ok = mt5.login(login_id, password, server=server)
        else:
            ok = mt5.login(login_id, password)

        if not ok:
            err = mt5.last_error()
            logger.error(f"MT5 login failed: {err}")
        return ok
    except Exception:
        logger.exception("Exception while calling mt5.login")
        raise


def place_order(symbol: str, order_type: str, volume: float, price: float = None, sl: float = None, tp: float = None, deviation: int = 20):
    """Place a market or pending order.

    order_type: 'BUY' | 'SELL' (market orders). Returns order result dict.
    """
    initialize()
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        raise RuntimeError(f"Symbol not found: {symbol}")

    # ensure symbol is selected
    if not symbol_info.visible:
        try:
            mt5.symbol_select(symbol, True)
        except Exception:
            pass

    if order_type.upper() == 'BUY':
        mt_type = mt5.ORDER_TYPE_BUY
        price_ = mt5.symbol_info_tick(symbol).ask if price is None else price
    elif order_type.upper() == 'SELL':
        mt_type = mt5.ORDER_TYPE_SELL
        price_ = mt5.symbol_info_tick(symbol).bid if price is None else price
    else:
        raise ValueError('order_type must be BUY or SELL')
    # normalize and validate volume according to symbol info
    vol_min = getattr(symbol_info := mt5.symbol_info(symbol), 'volume_min', None)
    vol_max = getattr(symbol_info, 'volume_max', None)
    vol_step = getattr(symbol_info, 'volume_step', None)

    try:
        raw_vol = float(volume)
    except Exception:
        raise ValueError('Invalid volume')

    if vol_step and vol_step > 0:
        # floor to nearest step
        steps = int(raw_vol / vol_step)
        vol = max(vol_min or vol_step, min(vol_max or raw_vol, steps * vol_step)) if steps > 0 else (vol_min or vol_step)
    else:
        vol = raw_vol

    if vol_min and vol < vol_min:
        raise ValueError(f'Volume {vol} is less than symbol minimum {vol_min}')

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(vol),
        "type": mt_type,
        "price": float(price_),
        "sl": float(sl) if sl is not None else 0.0,
        "tp": float(tp) if tp is not None else 0.0,
        "deviation": deviation,
        "magic": 234000,
        "comment": "bot-exec",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result is None:
        err = mt5.last_error()
        logger.error(f"order_send returned None: {err}")
        raise RuntimeError(f"order_send failed: {err}")
    # If MT5 returned a result object, check common error codes
    res = result._asdict() if hasattr(result, '_asdict') else result
    try:
        retcode = res.get('retcode', None) if isinstance(res, dict) else getattr(result, 'retcode', None)
    except Exception:
        retcode = None

    # retcode 10027 == TRADE_RETCODE_CLIENT_DISABLE_AUTOTRADE (AutoTrading disabled)
    if retcode == 10027 or (isinstance(res, dict) and 'AutoTrading disabled' in str(res)):
        last = mt5.last_error()
        raise RuntimeError('AutoTrading appears disabled in the MT5 terminal (retcode=10027). Enable AutoTrading in the MT5 toolbar (green) and allow automated trading.')

    return res
