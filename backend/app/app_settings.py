"""Settings of RAF itself (stored in <data_dir>/app_settings.json): appearance, the defaults new articles start with,
and the optional admin lock.

The admin lock is a passcode that must be entered before settings can be changed in the app. It keeps someone who shares
the computer from changing them by accident or in passing. It is not protection against a person who can open the data
folder: deleting the "admin" entry of the file removes the lock (which is also how a forgotten passcode is recovered).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import threading
import time

from .blueprints import ARTICLE_PROFILES, TONES
from .config import settings

PATH = settings.data_dir / "app_settings.json"
PALETTES = {   # key -> name shown in Settings; the colours themselves live in frontend/src/styles.css
    "violet": "Violet & Lime", "rosewood": "Rosewood", "aurora": "Aurora", "solar": "Solar", "ember": "Ember",
    "custom": "Custom",             # every shade is worked out from one colour the user picks (frontend/src/customTheme.js)
}
DEFAULTS: dict = {
    "palette": "violet",
    "custom_color": "#2f7df6",      # the colour the Custom theme is built from
    "effects": True,                # ambient light, grain and cursor glow
    "workspace": "",                # optional line shown under the RAF mark, e.g. a lab or team name
    "article": {"authors": [], "affiliation": "", "discipline": "", "article_type": "Empirical research article", "citation_style": "APA", "target_words": 6000},
    "run": {"web_research": settings.web_research, "data_analysis": True, "depth": "thorough", "agents": 1, "hallucination_filter": True, "style_pass": True},
    "tone": {"name": "academic", "intensity": 50},
}
TOKEN_HOURS = 12
MAX_FAILS, FAIL_WAIT = 5, 30

_lock = threading.Lock()
_tokens: dict[str, float] = {}      # admin session token -> expiry; kept in memory, so a restart locks again
_fails = {"count": 0, "until": 0.0}


def _read() -> dict:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write(data: dict) -> None:
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PATH)


def get() -> dict:
    """Current settings: the defaults with whatever was saved laid over them. Never contains the passcode."""
    stored = _read()
    out = {}
    for key, default in DEFAULTS.items():
        value = stored.get(key, default)
        out[key] = {**default, **{k: v for k, v in value.items() if k in default}} if isinstance(default, dict) and isinstance(value, dict) else value
    return out


def _text(value, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def validate(patch: dict) -> dict:
    """Keep only known settings with valid values; raise ValueError with a message for the user otherwise."""
    clean: dict = {}
    if "palette" in patch:
        if patch["palette"] not in PALETTES:
            raise ValueError("Unknown theme.")
        clean["palette"] = patch["palette"]
    if "custom_color" in patch:
        color = str(patch["custom_color"]).strip().lower()
        if not re.fullmatch(r"#[0-9a-f]{6}", color):
            raise ValueError("The colour must look like #2f7df6.")
        clean["custom_color"] = color
    if "effects" in patch:
        clean["effects"] = bool(patch["effects"])
    if "workspace" in patch:
        clean["workspace"] = _text(patch["workspace"], 60)
    if isinstance(patch.get("article"), dict):
        a, out = patch["article"], {}
        if "authors" in a:
            names = a["authors"] if isinstance(a["authors"], list) else str(a["authors"]).split(",")
            out["authors"] = [_text(n, 80) for n in names if _text(n, 80)][:12]
        for key, limit in (("affiliation", 160), ("discipline", 80)):
            if key in a:
                out[key] = _text(a[key], limit)
        if "article_type" in a:
            if a["article_type"] not in ARTICLE_PROFILES:
                raise ValueError("Unknown article type.")
            out["article_type"] = a["article_type"]
        if "citation_style" in a:
            if a["citation_style"] not in {"APA", "Harvard", "IEEE", "Chicago"}:
                raise ValueError("Unknown citation style.")
            out["citation_style"] = a["citation_style"]
        if "target_words" in a:
            try:
                out["target_words"] = max(2500, min(12000, int(a["target_words"]) // 500 * 500))
            except (TypeError, ValueError):
                raise ValueError("The target length must be a number of words.") from None
        clean["article"] = out
    if isinstance(patch.get("run"), dict):
        r, out = patch["run"], {}
        for key in ("web_research", "data_analysis", "hallucination_filter", "style_pass"):
            if key in r:
                out[key] = bool(r[key])
        if "depth" in r:
            if r["depth"] not in {"quick", "thorough"}:
                raise ValueError("Writing depth must be quick or thorough.")
            out["depth"] = r["depth"]
        if "agents" in r:
            if r["agents"] not in (1, 2, 3):
                raise ValueError("Agents must be 1, 2 or 3.")
            out["agents"] = r["agents"]
        clean["run"] = out
    if isinstance(patch.get("tone"), dict):
        t = patch["tone"]
        if t.get("name") not in TONES:
            raise ValueError("Unknown tone.")
        try:
            clean["tone"] = {"name": t["name"], "intensity": max(0, min(100, int(t.get("intensity", 50))))}
        except (TypeError, ValueError):
            raise ValueError("Tone intensity must be a number from 0 to 100.") from None
    return clean


def update(patch: dict) -> dict:
    clean = validate(patch)
    with _lock:
        stored, current = _read(), get()
        for key, value in clean.items():
            stored[key] = {**current[key], **value} if isinstance(value, dict) else value
        _write(stored)
    return get()


def reset() -> dict:
    """Back to the defaults. The admin lock stays as it is."""
    with _lock:
        stored = _read()
        _write({"admin": stored["admin"]} if "admin" in stored else {})
    return get()


# ---------------------------------------------------------------------------- admin lock
def _digest(passcode: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), salt, 200_000).hex()


def locked() -> bool:
    """True when a passcode has been set."""
    return bool(_read().get("admin", {}).get("hash"))


def _matches(passcode: str) -> bool:
    admin = _read().get("admin", {})
    if not admin.get("hash"):
        return True
    return hmac.compare_digest(_digest(passcode, bytes.fromhex(admin["salt"])), admin["hash"])


def unlock(passcode: str) -> str:
    """Check the passcode and return a session token. Raises PermissionError (wrong) or TimeoutError (too many tries)."""
    with _lock:
        now = time.time()
        if now < _fails["until"]:
            raise TimeoutError(f"Too many wrong attempts. Try again in {int(_fails['until'] - now) + 1} seconds.")
        if not _matches(passcode):
            _fails["count"] += 1
            if _fails["count"] >= MAX_FAILS:
                _fails["count"], _fails["until"] = 0, now + FAIL_WAIT
            raise PermissionError("That passcode is not correct.")
        _fails["count"] = 0
        token = secrets.token_urlsafe(24)
        _tokens[token] = now + TOKEN_HOURS * 3600
        for old in [t for t, exp in _tokens.items() if exp < now]:
            del _tokens[old]
        return token


def relock(token: str | None) -> None:
    _tokens.pop(token or "", None)


def allowed(token: str | None) -> bool:
    """May this request change settings? Always when no passcode is set; otherwise only with a live session token."""
    return not locked() or _tokens.get(token or "", 0) > time.time()


def set_passcode(new: str) -> None:
    """Set, change or (with an empty string) remove the passcode. The caller has already checked `allowed`."""
    if new and len(new) < 4:
        raise ValueError("Use at least 4 characters.")
    if len(new) > 128:
        raise ValueError("Use at most 128 characters.")
    with _lock:
        stored = _read()
        if new:
            salt = secrets.token_bytes(16)
            stored["admin"] = {"salt": salt.hex(), "hash": _digest(new, salt), "set": time.time()}
        else:
            stored.pop("admin", None)
        _write(stored)
        _tokens.clear()     # every open session has to unlock again with the new passcode
