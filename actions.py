from trade_logic import pip_size, breakeven_price, half_close_volume, validate_sltp


def _direction(mt5, position) -> str:
    return "BUY" if position.type == mt5.POSITION_TYPE_BUY else "SELL"


def _closing_price(mt5, position, direction: str) -> float:
    tick = mt5.symbol_info_tick(position.symbol)
    return tick.bid if direction == "BUY" else tick.ask


def apply_breakeven(mt5, position, pips: float = 0.0):
    """Moves SL to breakeven (pips=0) or breakeven+pips in the profitable
    direction. TP is left untouched. Always sends -- there is no invalid
    state for a breakeven move computed from the position's own entry price."""
    symbol_info = mt5.symbol_info(position.symbol)
    direction = _direction(mt5, position)
    new_sl = breakeven_price(direction, position.price_open, pip_size(symbol_info), pips)
    return mt5.order_send({
        "action": mt5.TRADE_ACTION_SLTP,
        "position": position.ticket,
        "symbol": position.symbol,
        "sl": round(new_sl, symbol_info.digits),
        "tp": position.tp,
    })


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
        "type_filling": mt5.ORDER_FILLING_IOC,
    })


def full_close(mt5, position):
    """Closes the entire position at market. The caller (GUI) is
    responsible for confirming with the user before calling this."""
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
        "type_filling": mt5.ORDER_FILLING_IOC,
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
    result = mt5.order_send({
        "action": mt5.TRADE_ACTION_SLTP,
        "position": position.ticket,
        "symbol": position.symbol,
        "sl": round(sl, symbol_info.digits) if sl is not None else position.sl,
        "tp": round(tp, symbol_info.digits) if tp is not None else position.tp,
    })
    return result, None
