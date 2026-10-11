"""The Window: what each segment looks like right now, while RAF is writing it.

A "sheet" per segment holds the text settled so far plus the passage the model is producing at this moment. The model's
output arrives word by word (llm.streaming); pieces are gathered and sent to the browser a few times a second as
`delta` events. Corrections made by the integrity filters are sent as `edit` events, and a finished passage as a
`sheet` event carrying the whole text. None of these are stored: they exist while a job runs, and a browser that opens
the page in the middle gets the current sheets with the stream's first message.
"""
from __future__ import annotations

import threading
import time

from . import jobs

FLUSH_SECONDS = 0.12        # at most ~8 updates a second per segment
FLUSH_CHARS = 160
KEEP_EDITS = 6

_lock = threading.Lock()
_sheets: dict[str, dict[str, dict]] = {}      # project id -> segment key -> sheet


def _sheet(pid: str, key: str) -> dict:
    return _sheets.setdefault(pid, {}).setdefault(key, {"text": "", "live": "", "pending": "", "sent": 0.0, "edits": []})


def begin(pid: str, key: str, base: str = "") -> None:
    """A new passage starts. `base` is the segment's text before it (empty when the passage replaces the whole segment)."""
    with _lock:
        s = _sheet(pid, key)
        s.update(text=base, live="", pending="", sent=0.0)
    jobs.emit(pid, "sheet", key=key, text=base, live="")


def feed(pid: str, key: str, piece: str | None) -> None:
    """One piece of model output. `None` means the model call is starting over (a retry): what was streamed is dropped."""
    with _lock:
        s = _sheet(pid, key)
        if piece is None:
            restart = bool(s["live"] or s["pending"])
            s.update(live="", pending="")
            out = None
        else:
            restart = False
            s["pending"] += piece
            now = time.monotonic()
            if now - s["sent"] < FLUSH_SECONDS and len(s["pending"]) < FLUSH_CHARS:
                return
            out, s["pending"], s["sent"] = s["pending"], "", now
            s["live"] += out
        text = s["text"]
    if out:
        jobs.emit(pid, "delta", key=key, text=out)
    elif restart:
        jobs.emit(pid, "sheet", key=key, text=text, live="")


def commit(pid: str, key: str, text: str) -> None:
    """The passage is finished (or a filter changed the segment): this is the segment's text now."""
    with _lock:
        s = _sheet(pid, key)
        s.update(text=text, live="", pending="")
    jobs.emit(pid, "sheet", key=key, text=text, live="")


def edit(pid: str, key: str, kind: str, before: str, after: str = "") -> None:
    """A filter changed a sentence. kind: corrected | removed | cited | rewritten | re-expressed | polished."""
    item = {"change": kind, "before": before[:400], "after": after[:400], "t": time.time()}
    with _lock:
        s = _sheet(pid, key)
        s["edits"] = [*s["edits"], item][-KEEP_EDITS:]
    jobs.emit(pid, "edit", key=key, **item)


def close(pid: str, key: str) -> None:
    """The segment is done; its final text is in the project from here on."""
    with _lock:
        _sheets.get(pid, {}).pop(key, None)
    jobs.emit(pid, "sheet", key=key, closed=True)


def snapshot(pid: str) -> dict:
    with _lock:
        return {k: {"text": s["text"], "live": s["live"] + s["pending"], "edits": list(s["edits"])} for k, s in _sheets.get(pid, {}).items()}
