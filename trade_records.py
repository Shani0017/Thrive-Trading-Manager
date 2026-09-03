"""Pure logic for turning raw MT5 history deals into completed-trade
records, kept separate from MT5/GUI code so it's unit-testable without a
real terminal (same pattern as trade_logic.py/actions.py)."""

DEAL_ENTRY_IN = 0
DEAL_ENTRY_OUT = 1
DEAL_ENTRY_OUT_BY = 3  # a hedging-mode close by an opposite position
DEAL_TYPE_BUY = 0
DEAL_TYPE_SELL = 1


def build_trade_records(deals) -> list[dict]:
    """deals: an iterable of MT5 history-deal objects (or anything with the
    same attributes: position_id, entry, type, time, volume, price, profit,
    symbol). Only real BUY/SELL deals are considered -- balance/commission/
    correction entries etc. share no meaningful position pairing and are
    dropped. Returns one dict per completed trade (a position that has both
    an entry and an exit deal), newest first:
    {position_id, symbol, direction, volume, entry_price, exit_price, pnl,
     close_time}. A position with no matching entry+exit pair yet (e.g.
     still open) is silently skipped -- this module only reconstructs
     CLOSED trades."""
    by_position: dict = {}
    for d in deals:
        if d.type not in (DEAL_TYPE_BUY, DEAL_TYPE_SELL):
            continue
        by_position.setdefault(d.position_id, []).append(d)

    records = []
    for position_id, group in by_position.items():
        group.sort(key=lambda d: d.time)
        entries = [d for d in group if d.entry == DEAL_ENTRY_IN]
        exits = [d for d in group if d.entry in (DEAL_ENTRY_OUT, DEAL_ENTRY_OUT_BY)]
        if not entries or not exits:
            continue
        entry = entries[0]
        exit_ = exits[-1]
        direction = "BUY" if entry.type == DEAL_TYPE_BUY else "SELL"
        records.append({
            "position_id": position_id,
            "symbol": entry.symbol,
            "direction": direction,
            "volume": sum(d.volume for d in entries),
            "entry_price": entry.price,
            "exit_price": exit_.price,
            "pnl": sum(d.profit for d in exits),
            "close_time": exit_.time,
        })

    records.sort(key=lambda r: r["close_time"], reverse=True)
    return records
