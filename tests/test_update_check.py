from update_check import parse_version, is_newer


def test_parse_version_plain():
    assert parse_version("1.2.3") == (1, 2, 3)


def test_parse_version_with_v_prefix():
    assert parse_version("v1.2.3") == (1, 2, 3)


def test_parse_version_uppercase_v_prefix():
    assert parse_version("V2.0.0") == (2, 0, 0)


def test_parse_version_strips_non_numeric_suffix():
    assert parse_version("1.2.3-beta") == (1, 2, 3)


def test_parse_version_missing_segment_defaults_to_zero():
    assert parse_version("1.2") == (1, 2)


def test_is_newer_true_for_higher_version():
    assert is_newer("1.1.0", "1.0.0") is True


def test_is_newer_false_for_same_version():
    assert is_newer("1.0.0", "1.0.0") is False


def test_is_newer_false_for_lower_version():
    assert is_newer("0.9.0", "1.0.0") is False


def test_is_newer_handles_v_prefix_on_either_side():
    assert is_newer("v1.2.0", "1.1.0") is True
    assert is_newer("1.2.0", "v1.1.0") is True


def test_is_newer_compares_patch_versions():
    assert is_newer("1.0.10", "1.0.9") is True
    assert is_newer("1.0.9", "1.0.10") is False
