import pytest
from unittest.mock import MagicMock
from actions import apply_breakeven, half_close, full_close, apply_custom_sltp


@pytest.fixture
def mock_mt5():
    mt5 = MagicMock()
    mt5.POSITION_TYPE_BUY = 0
    mt5.POSITION_TYPE_SELL = 1
    mt5.ORDER_TYPE_BUY = 0
    mt5.ORDER_TYPE_SELL = 1
    mt5.TRADE_ACTION_DEAL = 1
    mt5.TRADE_ACTION_SLTP = 6
    mt5.ORDER_TIME_GTC = 1
    mt5.ORDER_FILLING_IOC = 1
    mt5.TRADE_RETCODE_DONE = 10009

    symbol_info = MagicMock()
    symbol_info.digits = 2
    symbol_info.point = 0.01
    symbol_info.volume_step = 0.01
    symbol_info.volume_min = 0.01
    mt5.symbol_info.return_value = symbol_info

    tick = MagicMock()
    tick.bid = 2299.8
    tick.ask = 2300.2
    mt5.symbol_info_tick.return_value = tick

    result = MagicMock()
    result.retcode = 10009
    mt5.order_send.return_value = result

    return mt5


@pytest.fixture
def buy_position():
    position = MagicMock()
    position.ticket = 12345
    position.symbol = "XAUUSD"
    position.type = 0  # BUY
    position.price_open = 2280.0
    position.volume = 0.10
    position.sl = 2270.0
    position.tp = 2300.0
    return position


@pytest.fixture
def sell_position():
    position = MagicMock()
    position.ticket = 54321
    position.symbol = "XAUUSD"
    position.type = 1  # SELL
    position.price_open = 2300.0
    position.volume = 0.10
    position.sl = 2310.0
    position.tp = 2280.0
    return position


def test_apply_breakeven_exact_buy_sets_sl_to_entry(mock_mt5, buy_position):
    apply_breakeven(mock_mt5, buy_position, pips=0.0)

    sent = mock_mt5.order_send.call_args[0][0]
    assert sent["action"] == mock_mt5.TRADE_ACTION_SLTP
    assert sent["position"] == 12345
    assert sent["sl"] == pytest.approx(2280.0)
    assert sent["tp"] == 2300.0  # existing TP preserved


def test_apply_breakeven_with_pips_buy_adds_offset(mock_mt5, buy_position):
    apply_breakeven(mock_mt5, buy_position, pips=3)

    sent = mock_mt5.order_send.call_args[0][0]
    # 2-digit symbol -> pip_size = point = 0.01 -> offset = 0.03
    assert sent["sl"] == pytest.approx(2280.03)


def test_apply_breakeven_with_pips_sell_subtracts_offset(mock_mt5, sell_position):
    apply_breakeven(mock_mt5, sell_position, pips=3)

    sent = mock_mt5.order_send.call_args[0][0]
    assert sent["sl"] == pytest.approx(2299.97)


def test_half_close_sends_half_volume_at_market(mock_mt5, buy_position):
    result = half_close(mock_mt5, buy_position)

    sent = mock_mt5.order_send.call_args[0][0]
    assert sent["action"] == mock_mt5.TRADE_ACTION_DEAL
    assert sent["volume"] == pytest.approx(0.05)
    assert sent["type"] == mock_mt5.ORDER_TYPE_SELL  # closing a BUY = SELL order
    assert sent["price"] == 2299.8  # bid, since closing a BUY
    assert result.retcode == 10009


def test_half_close_returns_none_when_below_minimum(mock_mt5, buy_position):
    buy_position.volume = 0.01  # half=0.005, rounds to 0.00, below volume_min 0.01
    result = half_close(mock_mt5, buy_position)

    assert result is None
    mock_mt5.order_send.assert_not_called()


def test_full_close_sends_full_volume_at_market(mock_mt5, buy_position):
    full_close(mock_mt5, buy_position)

    sent = mock_mt5.order_send.call_args[0][0]
    assert sent["volume"] == pytest.approx(0.10)
    assert sent["type"] == mock_mt5.ORDER_TYPE_SELL


def test_full_close_sell_position_uses_buy_order_and_ask_price(mock_mt5, sell_position):
    full_close(mock_mt5, sell_position)

    sent = mock_mt5.order_send.call_args[0][0]
    assert sent["type"] == mock_mt5.ORDER_TYPE_BUY
    assert sent["price"] == 2300.2  # ask, since closing a SELL


def test_apply_custom_sltp_valid_values_sends_order(mock_mt5, buy_position):
    result, error = apply_custom_sltp(mock_mt5, buy_position, sl=2285.0, tp=2310.0)

    assert error is None
    sent = mock_mt5.order_send.call_args[0][0]
    assert sent["sl"] == pytest.approx(2285.0)
    assert sent["tp"] == pytest.approx(2310.0)
    assert result.retcode == 10009


def test_apply_custom_sltp_invalid_sl_rejected_before_sending(mock_mt5, buy_position):
    # current price for a BUY close = bid = 2299.8; an SL above that is invalid for a BUY
    result, error = apply_custom_sltp(mock_mt5, buy_position, sl=2305.0, tp=None)

    assert result is None
    assert error is not None
    mock_mt5.order_send.assert_not_called()


def test_apply_custom_sltp_none_values_keep_existing(mock_mt5, buy_position):
    result, error = apply_custom_sltp(mock_mt5, buy_position, sl=None, tp=None)

    assert error is None
    sent = mock_mt5.order_send.call_args[0][0]
    assert sent["sl"] == buy_position.sl
    assert sent["tp"] == buy_position.tp
