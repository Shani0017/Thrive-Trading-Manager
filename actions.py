from trade_logic import (pip_size, breakeven_price, half_close_volume, validate_sltp,
                          min_stop_distance, validate_stop_distance)


def _direction(mt5, position) -> str:
    return "BUY" if position.type == mt5.POSITION_TYPE_BUY else "SELL"


def _closing_price(mt5, position, direction: str) -> float:
    tick = mt5.symbol_info_tick(position.symbol)
    return tick.bid if direction == "BUY" else tick.ask


def _filling_type(mt5, symbol_info):
    """MT5 rejects an order (retcode 10030, "Unsupported filling mode") if
    its type_filling isn't one the broker/symbol actually accepts --
    symbol_info.filling_mode is a bitmask of what's allowed. Hardcoding
    IOC broke on brokers/symbols that don't support it; this picks FOK or
    IOC if the symbol allows it, falling back to Return (the safe default
    for symbols/brokers that support neither, e.g. many market-execution
    setups) -- the same fallback order MT5's own documentation recommends.

    The bitmask flags themselves (1=FOK, 2=IOC, per MQL5's
    ENUM_SYMBOL_TRADE_EXECUTION) are used as raw integers rather than
    mt5.SYMBOL_FILLING_FOK/IOC -- the MetaTrader5 Python package doesn't
    expose those as named constants, so referencing them raised
    AttributeError (caught by the GUI's broad except and surfaced as the
    unhelpful "Action failed (MT5 error)" on every Half/Full Close)."""
    SYMBOL_FILLING_FOK = 1
    SYMBOL_FILLING_IOC = 2
    mode = getattr(symbol_info, "filling_mode", 0) or 0
    if mode & SYMBOL_FILLING_FOK:
        return mt5.ORDER_FILLING_FOK
    if mode & SYMBOL_FILLING_IOC:
        return mt5.ORDER_FILLING_IOC
    return mt5.ORDER_FILLING_RETURN


def apply_breakeven(mt5, position, pips: float = 0.0):
    """Moves SL to breakeven (pips=0) or breakeven+pips in the profitable
    direction. TP is left untouched. Returns (result, None) on success, or
    (None, error_message) if the computed SL is too close to the current
    market price per the broker's own minimum stop distance for this
    symbol -- order_send is never called in that case. Without this check,
    a too-small breakeven+pips offset (or a fast-moving market) got
    rejected by the broker with retcode 10016 ("Invalid stops") instead of
    a clear message (confirmed by a user screenshot of exactly this)."""
    symbol_info = mt5.symbol_info(position.symbol)
    direction = _direction(mt5, position)
    new_sl = breakeven_price(direction, position.price_open, pip_size(symbol_info), pips)
    current_price = _closing_price(mt5, position, direction)
    error = validate_stop_distance(current_price, new_sl, None, min_stop_distance(symbol_info))
    if error:
        return None, error
    result = mt5.order_send({
        "action": mt5.TRADE_ACTION_SLTP,
        "position": position.ticket,
        "symbol": position.symbol,
        "sl": round(new_sl, symbol_info.digits),
        "tp": position.tp,
    })
    return result, None


def half_close(mt5, position):
    """Closes half the position's volume at market, rounded down to the
    broker's lot step. Returns None (and never calls order_send) if half
    the volume would round below the broker's minimum lot -- the caller
    is responsible for disabling the button in that case."""
    symbol_info = mt5.symbol_info(position.symbol)
    close_vol = half_close_volume(position.volume, symbol_info.volume_step, symbol_info.volume_min)
    if close_vol is None:
        return None
    direction = _direction(mt5, position)
    close_type = mt5.ORDER_TYPE_SELL if direction == "BUY" else mt5.ORDER_TYPE_BUY
    return mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": close_vol,
        "type": close_type,
        "position": position.ticket,
        "price": _closing_price(mt5, position, direction),
        "deviation": 20,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _filling_type(mt5, symbol_info),
    })


def full_close(mt5, position):
    """Closes the entire position at market. The caller (GUI) is
    responsible for confirming with the user before calling this."""
    symbol_info = mt5.symbol_info(position.symbol)
    direction = _direction(mt5, position)
    close_type = mt5.ORDER_TYPE_SELL if direction == "BUY" else mt5.ORDER_TYPE_BUY
    return mt5.order_send({
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": close_type,
        "position": position.ticket,
        "price": _closing_price(mt5, position, direction),
        "deviation": 20,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": _filling_type(mt5, symbol_info),
    })


def apply_custom_sltp(mt5, position, sl: float | None, tp: float | None):
    """Validates the given SL/TP against the position's direction and
    current price before sending. Returns (result, None) on success, or
    (None, error_message) if validation failed -- order_send is never
    called in the failure case."""
    direction = _direction(mt5, position)
    current_price = _closing_price(mt5, position, direction)
    error = validate_sltp(direction, current_price, sl, tp)
    if error:
        return None, error
    symbol_info = mt5.symbol_info(position.symbol)
    error = validate_stop_distance(current_price, sl, tp, min_stop_distance(symbol_info))
    if error:
        return None, error
    result = mt5.order_send({
        "action": mt5.TRADE_ACTION_SLTP,
        "position": position.ticket,
        "symbol": position.symbol,
        "sl": round(sl, symbol_info.digits) if sl is not None else position.sl,
        "tp": round(tp, symbol_info.digits) if tp is not None else position.tp,
    })
    return result, None
