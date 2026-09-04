"""Checks the feedback Google Form's response sheet for submissions not
seen on a previous run, classifying each by its own "What's this about?"
answer (bug / suggestion / other). Used by a scheduled task -- this
script only ever reports; it never fixes anything or ships a release by
itself. State (which responses have already been seen) is a local JSON
file, not shipped app data."""
import csv
import io
import json
import os
import urllib.request

SHEET_ID = "1N7fbmhD25RMdoaYDQaqMRb-ohhy5aJSQVKpYjDrfLfM"
EXPORT_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".feedback_state.json")


def fetch_rows(url: str = EXPORT_URL, timeout: float = 10.0) -> list[dict]:
    """Returns one dict per response row, with column names stripped of
    whitespace -- Google Forms sometimes pads question titles with extra
    spaces in the exported CSV header depending on how they were typed,
    which would otherwise make exact-match lookups fragile."""
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        text = resp.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return [{(k or "").strip(): v for k, v in row.items()} for row in reader]


def classify(row: dict) -> str:
    """Returns 'bug', 'suggestion', or 'other', based on the form's own
    "What's this about?" multiple-choice answer -- the form already asks
    this directly, so no text-guessing is needed for the common case."""
    answer = (row.get("What's this about?") or "").strip().lower()
    if "not working" in answer or "bug" in answer:
        return "bug"
    if "idea" in answer or "suggestion" in answer:
        return "suggestion"
    return "other"


def _load_seen(state_file: str = STATE_FILE) -> set:
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()


def _save_seen(seen: set, state_file: str = STATE_FILE) -> None:
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(sorted(seen), f, indent=2)
    except Exception:
        pass


def new_submissions(rows: list[dict], state_file: str = STATE_FILE) -> list[dict]:
    """Returns the rows not seen on a previous run, keyed by their
    Timestamp column (Google Forms always includes one, unique per
    submission). Marks them seen as a side effect, so calling this again
    with the same rows returns []."""
    seen = _load_seen(state_file)
    fresh = [r for r in rows if r.get("Timestamp") and r["Timestamp"] not in seen]
    if fresh:
        seen.update(r["Timestamp"] for r in fresh)
        _save_seen(seen, state_file)
    return fresh


if __name__ == "__main__":
    fresh = new_submissions(fetch_rows())
    if not fresh:
        print("No new feedback.")
    for row in fresh:
        print(f"[{classify(row).upper()}] {row}")
