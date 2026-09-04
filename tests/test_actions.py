import pytest
from unittest.mock import MagicMock
from actions import apply_breakeven, half_close, full_close, apply_custom_sltp, _filling_type


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
    mt5.ORDER_FILLING_FOK = 0
    mt5.ORDER_FILLING_IOC = 1
    mt5.ORDER_FILLING_RETURN = 2
    mt5.SYMBOL_FILLING_FOK = 1
    mt5.SYMBOL_FILLING_IOC = 2
    mt5.TRADE_RETCODE_DONE = 10009

    symbol_info = MagicMock()
    symbol_info.digits = 2
    symbol_info.point = 0.01
    symbol_info.volume_step = 0.01
    symbol_info.volume_min = 0.01
    symbol_info.filling_mode = 2  # broker supports IOC only, not FOK
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
    # 2-digit (Gold) symbol -> pip_size = point * 10 = 0.10 -> offset = 0.30
    assert sent["sl"] == pytest.approx(2280.30)


def test_apply_breakeven_with_pips_sell_subtracts_offset(mock_mt5, sell_position):
    apply_breakeven(mock_mt5, sell_position, pips=3)

    sent = mock_mt5.order_send.call_args[0][0]
    assert sent["sl"] == pytest.approx(2299.70)


def test_half_close_sends_half_volume_at_market(mock_mt5, buy_position):
    result = half_close(mock_mt5, buy_position)

    sent = mock_mt5.order_send.call_args[0][0]
    assert sent["action"] == mock_mt5.TRADE_ACTION_DEAL
    assert sent["volume"] == pytest.approx(0.05)
    assert sent["type"] == mock_mt5.ORDER_TYPE_SELL  # closing a BUY = SELL order
    assert sent["price"] == 2299.8  # bid, since closing a BUY
    assert sent["position"] == 12345
    assert sent["symbol"] == "XAUUSD"
    assert sent["type_filling"] == mock_mt5.ORDER_FILLING_IOC  # symbol supports IOC (fixture: filling_mode=2)
    assert result.retcode == 10009


def test_filling_type_prefers_fok_when_supported(mock_mt5):
    symbol_info = MagicMock()
    symbol_info.filling_mode = 1  # SYMBOL_FILLING_FOK only
    assert _filling_type(mock_mt5, symbol_info) == mock_mt5.ORDER_FILLING_FOK


def test_filling_type_uses_ioc_when_fok_unsupported(mock_mt5):
    symbol_info = MagicMock()
    symbol_info.filling_mode = 2  # SYMBOL_FILLING_IOC only
    assert _filling_type(mock_mt5, symbol_info) == mock_mt5.ORDER_FILLING_IOC


def test_filling_type_falls_back_to_return_when_neither_supported(mock_mt5):
    symbol_info = MagicMock()
    symbol_info.filling_mode = 0  # neither bit set -- e.g. some market-execution brokers
    assert _filling_type(mock_mt5, symbol_info) == mock_mt5.ORDER_FILLING_RETURN


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
    assert sent["position"] == 12345
    assert sent["symbol"] == "XAUUSD"
    assert sent["type_filling"] == mock_mt5.ORDER_FILLING_IOC  # symbol supports IOC (fixture: filling_mode=2)


def test_full_close_sell_position_uses_buy_order_and_ask_price(mock_mt5, sell_position):
    full_close(mock_mt5, sell_position)

    sent = mock_mt5.order_send.call_args[0][0]
    assert sent["type"] == mock_mt5.ORDER_TYPE_BUY
    assert sent["price"] == 2300.2  # ask, since closing a SELL


def test_half_close_sell_position_uses_buy_order_and_ask_price(mock_mt5, sell_position):
    result = half_close(mock_mt5, sell_position)

    sent = mock_mt5.order_send.call_args[0][0]
    assert sent["type"] == mock_mt5.ORDER_TYPE_BUY
    assert sent["price"] == 2300.2  # ask, since closing a SELL
    assert sent["volume"] == pytest.approx(0.05)
    assert sent["position"] == 54321
    assert result.retcode == 10009


def test_apply_custom_sltp_valid_values_sends_order(mock_mt5, buy_position):
    result, error = apply_custom_sltp(mock_mt5, buy_position, sl=2285.0, tp=2310.0)

    assert error is None
    sent = mock_mt5.order_send.call_args[0][0]
    assert sent["sl"] == pytest.approx(2285.0)
    assert sent["tp"] == pytest.approx(2310.0)
    assert sent["position"] == 12345
    assert sent["symbol"] == "XAUUSD"
    assert result.retcode == 10009


def test_apply_custom_sltp_partial_update_keeps_other_field(mock_mt5, buy_position):
    result, error = apply_custom_sltp(mock_mt5, buy_position, sl=2285.0, tp=None)

    assert error is None
    sent = mock_mt5.order_send.call_args[0][0]
    assert sent["sl"] == pytest.approx(2285.0)
    assert sent["tp"] == buy_position.tp  # unchanged since tp=None means "leave as-is"


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
