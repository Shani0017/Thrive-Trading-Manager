import json
import trade_sources


def test_load_sources_returns_empty_dict_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_sources, "_writable_path", lambda name: str(tmp_path / name))
    assert trade_sources.load_sources() == {}


def test_save_then_load_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_sources, "_writable_path", lambda name: str(tmp_path / name))
    trade_sources.save_sources({"123": "My Analysis", "456": "XYZ Trader"})
    assert trade_sources.load_sources() == {"123": "My Analysis", "456": "XYZ Trader"}


def test_load_sources_returns_empty_dict_on_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_sources, "_writable_path", lambda name: str(tmp_path / name))
    (tmp_path / trade_sources.SOURCES_FILENAME).write_text("not valid json{{{", encoding="utf-8")
    assert trade_sources.load_sources() == {}


def test_load_sources_returns_empty_dict_when_file_is_not_a_json_object(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_sources, "_writable_path", lambda name: str(tmp_path / name))
    (tmp_path / trade_sources.SOURCES_FILENAME).write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert trade_sources.load_sources() == {}
