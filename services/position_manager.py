import MetaTrader5 as mt5
import logging

logger = logging.getLogger(__name__)


def list_positions():
    """Return a list of open positions as dicts."""
    try:
        pos = mt5.positions_get()
        if not pos:
            return []
        out = []
        for p in pos:
            d = {
                'ticket': int(getattr(p, 'ticket', 0)),
                'symbol': getattr(p, 'symbol', ''),
                'type': 'BUY' if getattr(p, 'type', 0) == mt5.POSITION_TYPE_BUY else 'SELL',
                'volume': float(getattr(p, 'volume', 0.0)),
                'price_open': float(getattr(p, 'price_open', 0.0)),
                'profit': float(getattr(p, 'profit', 0.0)),
            }
            out.append(d)
        return out
    except Exception:
        logger.exception('Failed to list positions')
        return []


def close_position(ticket: int):
    """Close a position by ticket. Returns MT5 result dict or raises.

    This function issues a market opposite order for the full volume of the position
    and sets the `position` field so MT5 treats it as a close request.
    """
    try:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            raise RuntimeError(f'Position {ticket} not found')
        p = positions[0]
        symbol = p.symbol
        vol = float(p.volume)
        pos_type = p.type

        # choose opposite order type to close
        if pos_type == mt5.POSITION_TYPE_BUY:
            close_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(symbol).bid
        else:
            close_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(symbol).ask

        request = {
            'action': mt5.TRADE_ACTION_DEAL,
            'symbol': symbol,
            'volume': vol,
            'type': close_type,
            'price': float(price),
            'position': int(ticket),
            'deviation': 20,
            'magic': 234000,
            'comment': 'bot-close',
            'type_time': mt5.ORDER_TIME_GTC,
            'type_filling': mt5.ORDER_FILLING_IOC,
        }

        res = mt5.order_send(request)
        if res is None:
            err = mt5.last_error()
            raise RuntimeError(f'order_send returned None: {err}')
        r = res._asdict() if hasattr(res, '_asdict') else res
        return r
    except Exception:
        logger.exception('Failed to close position %s', ticket)
        raise
