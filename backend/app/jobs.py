"""Background job runner with a live event stream (Server-Sent Events) per project.

Two kinds of job:
  * project jobs  — fabrication, article review, imports. Exclusive: nothing else runs on the project meanwhile.
  * segment jobs  — Studio regenerate / revise / text tools. Up to MAX_SEGMENT_JOBS run side by side, one per segment.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import traceback
from typing import Callable

from . import store

log = logging.getLogger("raf.jobs")

MAX_SEGMENT_JOBS = 3

_subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
_running: dict[str, str] = {}
_segment_jobs: dict[str, dict[str, str]] = {}
_lock = threading.Lock()


def emit(pid: str, kind: str, message: str = "", **data) -> None:
    event = {"t": time.time(), "kind": kind, "message": message, **data}
    if kind in {"log", "stage", "segment", "error", "done", "job", "checkpoint"}:
        try:
            def add(p):
                p.log.append(event)
                p.log[:] = p.log[-400:]
            store.mutate(pid, add)
        except KeyError:
            pass
    for loop, q in list(_subscribers.get(pid, [])):
        loop.call_soon_threadsafe(q.put_nowait, event)


def subscribe(pid: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(pid, []).append((asyncio.get_running_loop(), q))
    return q


def unsubscribe(pid: str, q: asyncio.Queue) -> None:
    _subscribers[pid] = [(l, x) for l, x in _subscribers.get(pid, []) if x is not q]


def running(pid: str) -> str | None:
    """Name of the exclusive project job, if one is running."""
    return _running.get(pid)


def segment_jobs(pid: str) -> dict[str, str]:
    """Segment key -> job name for every Studio job running on the project."""
    with _lock:
        return dict(_segment_jobs.get(pid, {}))


def any_running(pid: str) -> str | None:
    with _lock:
        return _running.get(pid) or next(iter(_segment_jobs.get(pid, {}).values()), None)


def _spawn(pid: str, name: str, fn: Callable[[], None], release: Callable[[], None], **tags) -> None:
    def wrapper():
        emit(pid, "job", f"{name} started", job=name, state="started", **tags)
        try:
            fn()
            emit(pid, "job", f"{name} finished", job=name, state="finished", **tags)
        except Exception as exc:  # noqa: BLE001
            log.error("job %s failed: %s", name, traceback.format_exc())
            emit(pid, "error", f"{name} failed: {exc}", job=name, **tags)
            emit(pid, "job", f"{name} failed", job=name, state="failed", **tags)
        finally:
            with _lock:
                release()

    threading.Thread(target=wrapper, name=f"raf-{pid}-{name}", daemon=True).start()


def start(pid: str, name: str, fn: Callable[[], None]) -> bool:
    """Start an exclusive project job. Fails while any other job (project or segment) is running."""
    with _lock:
        if pid in _running or _segment_jobs.get(pid):
            return False
        _running[pid] = name
    _spawn(pid, name, fn, lambda: _running.pop(pid, None))
    return True


def _block_reason(pid: str, key: str, limit: bool = True) -> str | None:   # caller holds _lock
    if pid in _running:
        return f"RAF is busy with “{_running[pid]}” for this project. Please wait for it to finish."
    jobs = _segment_jobs.get(pid, {})
    if key in jobs:
        return f"RAF is already working on this segment ({jobs[key]})."
    if limit and len(jobs) >= MAX_SEGMENT_JOBS:
        return f"RAF is already working on {MAX_SEGMENT_JOBS} segments. Wait for one to finish, then try again."
    return None


def segment_block_reason(pid: str, key: str, limit: bool = True) -> str | None:
    """Why this segment cannot be changed right now (None when it can). `limit=False` ignores the parallel-job cap."""
    with _lock:
        return _block_reason(pid, key, limit)


def start_segment(pid: str, key: str, name: str, fn: Callable[[], None]) -> str | None:
    """Start a Studio job on one segment. Returns None on success, otherwise the reason it could not start."""
    with _lock:
        reason = _block_reason(pid, key)
        if reason:
            return reason
        _segment_jobs.setdefault(pid, {})[key] = name

    def release():
        jobs = _segment_jobs.get(pid, {})
        jobs.pop(key, None)
        if not jobs:
            _segment_jobs.pop(pid, None)
    _spawn(pid, name, fn, release, key=key)
    return None


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"
