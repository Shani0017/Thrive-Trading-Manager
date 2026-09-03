import pytest
from unittest.mock import MagicMock
from trade_records import build_trade_records


def _deal(position_id, entry, type_, time, volume, price, profit, symbol="XAUUSD"):
    d = MagicMock()
    d.position_id = position_id
    d.entry = entry
    d.type = type_
    d.time = time
    d.volume = volume
    d.price = price
    d.profit = profit
    d.symbol = symbol
    return d


def test_pairs_entry_and_exit_into_one_completed_trade():
    deals = [
        _deal(position_id=1, entry=0, type_=0, time=1000, volume=0.10, price=2280.0, profit=0.0),
        _deal(position_id=1, entry=1, type_=1, time=2000, volume=0.10, price=2300.0, profit=20.0),
    ]
    records = build_trade_records(deals)

    assert len(records) == 1
    r = records[0]
    assert r["position_id"] == 1
    assert r["symbol"] == "XAUUSD"
    assert r["direction"] == "BUY"
    assert r["volume"] == pytest.approx(0.10)
    assert r["entry_price"] == pytest.approx(2280.0)
    assert r["exit_price"] == pytest.approx(2300.0)
    assert r["pnl"] == pytest.approx(20.0)
    assert r["close_time"] == 2000


def test_sell_direction_detected_from_entry_deal_type():
    deals = [
        _deal(position_id=2, entry=0, type_=1, time=1000, volume=0.05, price=2300.0, profit=0.0),
        _deal(position_id=2, entry=1, type_=0, time=2000, volume=0.05, price=2280.0, profit=10.0),
    ]
    records = build_trade_records(deals)
    assert records[0]["direction"] == "SELL"


def test_position_with_no_exit_yet_is_skipped():
    deals = [_deal(position_id=3, entry=0, type_=0, time=1000, volume=0.10, price=2280.0, profit=0.0)]
    assert build_trade_records(deals) == []


def test_position_with_no_entry_deal_is_skipped():
    deals = [_deal(position_id=4, entry=1, type_=0, time=1000, volume=0.10, price=2280.0, profit=5.0)]
    assert build_trade_records(deals) == []


def test_hedging_close_by_opposite_position_counts_as_exit():
    deals = [
        _deal(position_id=5, entry=0, type_=0, time=1000, volume=0.10, price=2280.0, profit=0.0),
        _deal(position_id=5, entry=3, type_=1, time=2000, volume=0.10, price=2290.0, profit=10.0),
    ]
    records = build_trade_records(deals)
    assert len(records) == 1
    assert records[0]["exit_price"] == pytest.approx(2290.0)


def test_partial_close_sums_exit_pnl_across_multiple_exit_deals():
    deals = [
        _deal(position_id=6, entry=0, type_=0, time=1000, volume=0.10, price=2280.0, profit=0.0),
        _deal(position_id=6, entry=1, type_=1, time=1500, volume=0.05, price=2290.0, profit=5.0),
        _deal(position_id=6, entry=1, type_=1, time=2000, volume=0.05, price=2300.0, profit=10.0),
    ]
    records = build_trade_records(deals)
    assert len(records) == 1
    assert records[0]["pnl"] == pytest.approx(15.0)
    # exit_price reflects the LAST exit deal (final close), not the first partial
    assert records[0]["exit_price"] == pytest.approx(2300.0)
    assert records[0]["close_time"] == 2000


def test_non_trade_deal_types_are_ignored():
    # type 2 = BALANCE, e.g. a deposit -- has no meaningful position pairing
    deals = [_deal(position_id=0, entry=0, type_=2, time=1000, volume=0.0, price=0.0, profit=100.0)]
    assert build_trade_records(deals) == []


def test_multiple_positions_sorted_newest_first():
    deals = [
        _deal(position_id=10, entry=0, type_=0, time=1000, volume=0.10, price=2280.0, profit=0.0),
        _deal(position_id=10, entry=1, type_=1, time=2000, volume=0.10, price=2290.0, profit=10.0),
        _deal(position_id=11, entry=0, type_=0, time=3000, volume=0.10, price=2290.0, profit=0.0),
        _deal(position_id=11, entry=1, type_=1, time=4000, volume=0.10, price=2310.0, profit=20.0),
    ]
    records = build_trade_records(deals)
    assert [r["position_id"] for r in records] == [11, 10]


def test_empty_deals_returns_empty_list():
    assert build_trade_records([]) == []
