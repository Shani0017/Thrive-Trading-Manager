import json
import pytest
import trade_sources


@pytest.fixture(autouse=True)
def isolated_paths(tmp_path, monkeypatch):
    # Every test gets its own writable/legacy locations under tmp_path so
    # a real trade_sources.json sitting next to this script (e.g. left
    # over from manual dev-mode testing) can never leak into a test and
    # make it flaky -- confirmed this was a real risk: the migration
    # logic in load_sources() checks _legacy_path() too, not just
    # _writable_path().
    (tmp_path / "new").mkdir()
    monkeypatch.setattr(trade_sources, "_writable_path", lambda name: str(tmp_path / "new" / name))
    monkeypatch.setattr(trade_sources, "_legacy_path", lambda name: str(tmp_path / "legacy" / name))


def test_load_sources_returns_empty_dict_when_file_missing():
    assert trade_sources.load_sources() == {}


def test_save_then_load_round_trips():
    trade_sources.save_sources({"123": "My Analysis", "456": "XYZ Trader"})
    assert trade_sources.load_sources() == {"123": "My Analysis", "456": "XYZ Trader"}


def test_load_sources_returns_empty_dict_on_corrupt_file(tmp_path):
    (tmp_path / "new" / trade_sources.SOURCES_FILENAME).write_text("not valid json{{{", encoding="utf-8")
    assert trade_sources.load_sources() == {}


def test_load_sources_returns_empty_dict_when_file_is_not_a_json_object(tmp_path):
    (tmp_path / "new" / trade_sources.SOURCES_FILENAME).write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert trade_sources.load_sources() == {}


def test_load_sources_migrates_from_legacy_path_next_to_exe(tmp_path):
    # Simulates someone upgrading from the old "next to the .exe" version:
    # a file already exists at the legacy location but not the new
    # AppData one -- load_sources() should pick it up transparently and
    # carry it forward to the new location so nothing is lost.
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / trade_sources.SOURCES_FILENAME).write_text(
        json.dumps({"789": "Thrive"}), encoding="utf-8")

    result = trade_sources.load_sources()

    assert result == {"789": "Thrive"}
    new_path = tmp_path / "new" / trade_sources.SOURCES_FILENAME
    assert new_path.exists()
    assert json.loads(new_path.read_text(encoding="utf-8")) == {"789": "Thrive"}


def test_load_sources_prefers_new_path_over_legacy_when_both_exist(tmp_path):
    legacy_dir = tmp_path / "legacy"
    legacy_dir.mkdir()
    (legacy_dir / trade_sources.SOURCES_FILENAME).write_text(
        json.dumps({"old": "should not be used"}), encoding="utf-8")
    trade_sources.save_sources({"new": "current data"})

    assert trade_sources.load_sources() == {"new": "current data"}
