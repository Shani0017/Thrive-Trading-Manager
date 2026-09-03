import pytest
from unittest.mock import MagicMock
from trade_logic import pip_size, breakeven_price, half_close_volume, validate_sltp


def _symbol_info(digits, point):
    info = MagicMock()
    info.digits = digits
    info.point = point
    return info


def test_pip_size_5_digit_forex():
    info = _symbol_info(digits=5, point=0.00001)
    assert pip_size(info) == pytest.approx(0.0001)


def test_pip_size_3_digit_jpy():
    info = _symbol_info(digits=3, point=0.001)
    assert pip_size(info) == pytest.approx(0.01)


def test_pip_size_2_digit_gold():
    # 1 pip = $0.10 for Gold, per explicit user correction (point * 10,
    # same 2nd-to-last-decimal convention as 3/5-digit symbols).
    info = _symbol_info(digits=2, point=0.01)
    assert pip_size(info) == pytest.approx(0.10)


def test_breakeven_price_exact_buy():
    assert breakeven_price("BUY", 2280.0, pip_size=0.01, pips=0.0) == pytest.approx(2280.0)


def test_breakeven_price_exact_sell():
    assert breakeven_price("SELL", 2280.0, pip_size=0.01, pips=0.0) == pytest.approx(2280.0)


def test_breakeven_price_with_pips_buy_adds():
    assert breakeven_price("BUY", 2280.0, pip_size=0.1, pips=3) == pytest.approx(2280.3)


def test_breakeven_price_with_pips_sell_subtracts():
    assert breakeven_price("SELL", 2280.0, pip_size=0.1, pips=3) == pytest.approx(2279.7)


def test_half_close_volume_normal_case():
    assert half_close_volume(volume=0.10, volume_step=0.01, volume_min=0.01) == pytest.approx(0.05)


def test_half_close_volume_rounds_down_to_step():
    # 0.03 / 2 = 0.015 -> rounds down to 0.01 (volume_step=0.01)
    assert half_close_volume(volume=0.03, volume_step=0.01, volume_min=0.01) == pytest.approx(0.01)


def test_half_close_volume_returns_none_when_half_below_minimum():
    # 0.01 / 2 = 0.005 -> rounds down to 0.00, below volume_min
    assert half_close_volume(volume=0.01, volume_step=0.01, volume_min=0.01) is None


def test_half_close_volume_exact_multiple_not_undershot():
    # Regression: 0.3 / 0.1 == 2.9999999999999996 in float arithmetic, which
    # used to floor to 2 steps (0.2) instead of the correct 3 steps (0.3).
    assert half_close_volume(volume=0.6, volume_step=0.1, volume_min=0.01) == pytest.approx(0.3)


def test_half_close_volume_exact_multiple_not_undershot_small_step():
    assert half_close_volume(volume=0.58, volume_step=0.01, volume_min=0.01) == pytest.approx(0.29)


def test_half_close_volume_exact_multiple_not_undershot_larger_volume():
    assert half_close_volume(volume=2.8, volume_step=0.1, volume_min=0.01) == pytest.approx(1.4)


def test_validate_sltp_buy_sl_too_high_rejected():
    error = validate_sltp("BUY", current_price=2300.0, sl=2305.0, tp=None)
    assert error is not None
    assert "SL" in error


def test_validate_sltp_buy_tp_too_low_rejected():
    error = validate_sltp("BUY", current_price=2300.0, sl=None, tp=2295.0)
    assert error is not None
    assert "TP" in error


def test_validate_sltp_buy_valid_values_accepted():
    assert validate_sltp("BUY", current_price=2300.0, sl=2290.0, tp=2320.0) is None


def test_validate_sltp_sell_sl_too_low_rejected():
    error = validate_sltp("SELL", current_price=2300.0, sl=2295.0, tp=None)
    assert error is not None
    assert "SL" in error


def test_validate_sltp_sell_tp_too_high_rejected():
    error = validate_sltp("SELL", current_price=2300.0, sl=None, tp=2305.0)
    assert error is not None
    assert "TP" in error


def test_validate_sltp_sell_valid_values_accepted():
    assert validate_sltp("SELL", current_price=2300.0, sl=2310.0, tp=2280.0) is None


def test_validate_sltp_none_values_always_valid():
    assert validate_sltp("BUY", current_price=2300.0, sl=None, tp=None) is None
