"""Checks GitHub Releases for a version of the app newer than the one
currently running. A lightweight, best-effort background check -- no
internet, no releases published yet, or a slow/rate-limited API call
should never interrupt or error out the app itself, so every failure
path here returns None rather than raising."""
import json
import urllib.request

APP_VERSION = "1.0.5"
GITHUB_REPO = "Shani0017/Thrive-Trading-Manager"


def parse_version(v: str) -> tuple:
    """'v1.2.3' or '1.2.3' -> (1, 2, 3), for simple tuple comparison. Any
    non-numeric trailing text on a segment (e.g. the 'beta' in '1.2.3-beta')
    is stripped rather than rejected."""
    v = v.strip()
    if v[:1].lower() == "v":
        v = v[1:]
    parts = []
    for segment in v.split("."):
        digits = "".join(ch for ch in segment if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    """True if candidate's version is strictly newer than current's."""
    return parse_version(candidate) > parse_version(current)


def fetch_latest_release(repo: str = GITHUB_REPO, timeout: float = 4.0):
    """Returns (tag_name, html_url) for the repo's latest published GitHub
    release, or None on any failure (no internet, no releases published
    yet, rate limiting, etc.). Uses GitHub's public REST API -- works
    without authentication as long as the repo itself is public, which
    matters here: embedding a personal access token in an .exe handed to
    many people would leak that token to every one of them."""
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
        tag = data.get("tag_name")
        html_url = data.get("html_url")
        if not tag or not html_url:
            return None
        return tag, html_url
    except Exception:
        return None
