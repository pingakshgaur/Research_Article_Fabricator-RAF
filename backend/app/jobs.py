"""Background job runner with a live event stream (Server-Sent Events) per project."""
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

_subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}
_running: dict[str, str] = {}
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
    return _running.get(pid)


def start(pid: str, name: str, fn: Callable[[], None]) -> bool:
    with _lock:
        if pid in _running:
            return False
        _running[pid] = name

    def wrapper():
        emit(pid, "job", f"{name} started", job=name, state="started")
        try:
            fn()
            emit(pid, "job", f"{name} finished", job=name, state="finished")
        except Exception as exc:  # noqa: BLE001
            log.error("job %s failed: %s", name, traceback.format_exc())
            emit(pid, "error", f"{name} failed: {exc}", job=name)
            emit(pid, "job", f"{name} failed", job=name, state="failed")
        finally:
            with _lock:
                _running.pop(pid, None)

    threading.Thread(target=wrapper, name=f"raf-{pid}-{name}", daemon=True).start()
    return True


def sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"
