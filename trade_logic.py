def pip_size(symbol_info) -> float:
    """symbol_info: an MT5 SymbolInfo-like object with .point and .digits.
    A 'pip' is the 2nd-to-last decimal for 3-digit (JPY pairs) and 5-digit
    (standard forex) quoted symbols, so those use point*10. Everything else
    (2-digit Gold, 4-digit legacy forex quoting) uses point as-is."""
    if symbol_info.digits in (3, 5):
        return symbol_info.point * 10
    return symbol_info.point


def breakeven_price(direction: str, entry_price: float, pip_size: float, pips: float = 0.0) -> float:
    """direction: 'BUY' or 'SELL'. Returns the SL price for breakeven (pips=0)
    or breakeven+pips, offset in the position's profitable direction."""
    offset = pip_size * pips
    if direction == "BUY":
        return entry_price + offset
    return entry_price - offset


def half_close_volume(volume: float, volume_step: float, volume_min: float) -> float | None:
    """Returns the volume to close for a 'half close', rounded DOWN to the
    broker's volume_step. Returns None if half the volume rounds to less
    than volume_min (the caller should disable the Half Close button in
    that case). Note: since this always rounds DOWN from exactly half, the
    remaining volume (volume - rounded) is always >= rounded, so there is
    no separate "remainder too small" case to check once rounded itself
    clears volume_min."""
    half = volume / 2
    steps = int(half / volume_step)
    rounded = round(steps * volume_step, 8)
    if rounded < volume_min:
        return None
    return rounded


def validate_sltp(direction: str, current_price: float, sl: float | None, tp: float | None) -> str | None:
    """Returns an error message if the given SL/TP would be invalid for the
    position's direction relative to current_price, or None if valid. A
    None sl/tp value means 'leave unchanged' and is never itself invalid."""
    if direction == "BUY":
        if sl is not None and sl >= current_price:
            return "For a BUY, SL must be below the current price."
        if tp is not None and tp <= current_price:
            return "For a BUY, TP must be above the current price."
    else:
        if sl is not None and sl <= current_price:
            return "For a SELL, SL must be above the current price."
        if tp is not None and tp >= current_price:
            return "For a SELL, TP must be below the current price."
    return None
