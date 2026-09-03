"""Local persistence for user-entered trade 'source' tags (e.g. "My
Analysis", "XYZ Trader", "XYZ YouTube", "Thrive"). MT5 has no concept of
this -- it's a note the user attaches to a trade -- so it's stored in a
small JSON file keyed by position_id, next to the running .exe/script."""
import json
import os
import sys

SOURCES_FILENAME = "trade_sources.json"


def _writable_path(filename: str) -> str:
    """Where trade_sources.json actually lives. Deliberately NOT the same
    helper as gui.py's _resource_path: that one resolves to PyInstaller's
    temporary _MEIPASS extraction directory when frozen, which is wiped on
    every run and can't hold anything meant to persist across launches.
    This resolves to the folder the real .exe/script lives in instead."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)


def load_sources() -> dict:
    """Returns {position_id (str): source label (str)}. Missing/corrupt
    file -> empty dict, never raises -- a bad journal file must never stop
    the app from starting."""
    try:
        with open(_writable_path(SOURCES_FILENAME), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_sources(sources: dict) -> None:
    try:
        with open(_writable_path(SOURCES_FILENAME), "w", encoding="utf-8") as f:
            json.dump(sources, f, indent=2)
    except Exception:
        pass
