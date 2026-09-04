"""Local persistence for user-entered trade 'source' tags (e.g. "My
Analysis", "XYZ Trader", "XYZ YouTube", "Thrive"). MT5 has no concept of
this -- it's a note the user attaches to a trade -- so it's stored in a
small JSON file, kept in the OS's own per-user app-data folder rather
than next to the .exe."""
import json
import os
import sys

SOURCES_FILENAME = "trade_sources.json"
APP_FOLDER_NAME = "THRIVE Trade Manager"


def _writable_path(filename: str) -> str:
    """Where trade_sources.json actually lives: %APPDATA%\\THRIVE Trade
    Manager\\ (e.g. C:\\Users\\<name>\\AppData\\Roaming\\THRIVE Trade
    Manager), Windows' standard place for a per-user data file. Keeping
    it next to the .exe worked, but meant shipping the app to someone
    else was really shipping two files (the .exe and this JSON) if you
    wanted their saved sources to survive between runs -- AppData lets
    the .exe stay a single, self-contained file with no visible sidecar;
    this file gets created there automatically on first save.

    Falls back to next to the .exe/script (the old behavior) only if
    APPDATA isn't set, which shouldn't happen on a real Windows install."""
    appdata = os.getenv("APPDATA")
    if appdata:
        base = os.path.join(appdata, APP_FOLDER_NAME)
    elif getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, filename)


def _legacy_path(filename: str) -> str:
    """Where trade_sources.json used to live (next to the .exe/script),
    kept only so a one-time migration in load_sources() can carry
    forward anyone's already-saved tags from before this change."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)


def load_sources() -> dict:
    """Returns {position_id (str): source label (str)}. Missing/corrupt
    file -> empty dict, never raises -- a bad journal file must never stop
    the app from starting."""
    path = _writable_path(SOURCES_FILENAME)
    if not os.path.exists(path):
        legacy = _legacy_path(SOURCES_FILENAME)
        if os.path.exists(legacy):
            try:
                with open(legacy, "r", encoding="utf-8") as f:
                    legacy_data = json.load(f)
                if isinstance(legacy_data, dict):
                    save_sources(legacy_data)
                    return legacy_data
            except Exception:
                pass
    try:
        with open(path, "r", encoding="utf-8") as f:
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
