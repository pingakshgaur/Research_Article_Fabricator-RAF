"""Thin, resilient client for the local Ollama server (no API keys involved)."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Callable

import httpx

from . import llm_settings
from .config import settings

log = logging.getLogger("raf.llm")


class LLMError(RuntimeError):
    pass


_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def _clean(text: str) -> str:
    text = _THINK_RE.sub("", text)
    return text.strip()


def health() -> dict:
    model = llm_settings.get()["model"]
    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=5)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
        return {
            "ollama": True,
            "model": model,
            "model_available": any(n == model or n.startswith(model + ":") for n in names),
            "embed_model_available": any(n.split(":")[0] == settings.embed_model.split(":")[0] for n in names),
            "models": names,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ollama": False, "model": model, "model_available": False, "embed_model_available": False, "error": str(exc)}


# ---------------------------------------------------------------------------- agents & fallbacks
class _Runtime:
    """Process-wide state shared by every model call.

    * agent slots — at most N concurrent requests (1 solo, 2 duo, 3 trio); each call occupies one numbered slot.
    * fallbacks   — out-of-memory errors lower concurrency, then GPU offload; a crashed/restarting Ollama is waited for.
    """

    GPU_LADDER = (-1, 24, 12, 0)   # auto → partial offload → CPU only

    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.capacity = 1
        self.free_slots = [1]
        self.gpu_override: int | None = None   # set by the out-of-memory fallback; otherwise Developer Tools decide
        self.notify: Callable[[str], None] = lambda message: None
        self.local = threading.local()

    def configure(self, agents: int, notify: Callable[[str], None] | None = None) -> None:
        with self.cond:
            self.capacity = max(1, min(3, agents))
            self.free_slots = list(range(1, self.capacity + 1))
            self.cond.notify_all()
        if notify:
            self.notify = notify

    def ensure(self, agents: int, notify: Callable[[str], None] | None = None) -> None:
        """Like configure(), but safe while other jobs hold slots: slots in use stay taken."""
        with self.cond:
            target = max(1, min(3, agents))
            if target != self.capacity:
                in_use = set(range(1, self.capacity + 1)) - set(self.free_slots)
                self.capacity = target
                self.free_slots = [s for s in range(1, target + 1) if s not in in_use]
                self.cond.notify_all()
        if notify:
            self.notify = notify

    def acquire(self) -> int:
        with self.cond:
            while not self.free_slots:
                self.cond.wait()
            slot = self.free_slots.pop(0)
        self.local.agent = slot
        return slot

    def release(self, slot: int) -> None:
        with self.cond:
            if slot <= self.capacity and slot not in self.free_slots:
                self.free_slots.append(slot)
                self.free_slots.sort()
            self.cond.notify_all()

    def reduce_capacity(self) -> bool:
        with self.cond:
            if self.capacity <= 1:
                return False
            self.capacity -= 1
            self.free_slots = [s for s in self.free_slots if s <= self.capacity]
        self.notify(f"⚠ Memory pressure: reducing to {self.capacity} parallel agent(s)")
        return True

    def effective_gpu(self, s: dict) -> int:
        return s["num_gpu"] if self.gpu_override is None else self.gpu_override

    def lower_gpu(self) -> bool:
        current = self.effective_gpu(llm_settings.get())
        lower = [g for g in self.GPU_LADDER if g >= 0 and (current < 0 or g < current)]
        if not lower:
            return False
        self.gpu_override = lower[0]
        self.notify(f"⚠ Model ran out of memory: retrying with {'CPU only' if self.gpu_override == 0 else f'{self.gpu_override} GPU layers'}"
                    " (change GPU layers in Developer Tools to make this permanent)")
        return True


runtime = _Runtime()
_MEMORY_ERRORS = ("out of memory", "cuda", "llama-server", "unable to allocate", "failed to allocate", "no longer running", "exit status")


def current_agent() -> int:
    return getattr(runtime.local, "agent", 1)


def wait_for_ollama(max_wait: int) -> bool:
    """Block until Ollama answers again (e.g. after a crash and automatic restart)."""
    deadline = time.monotonic() + max_wait
    announced = False
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{settings.ollama_url}/api/tags", timeout=5).status_code == 200:
                if announced:
                    runtime.notify("✓ Ollama is responding again — continuing")
                return True
        except Exception:  # noqa: BLE001
            pass
        if not announced:
            runtime.notify(f"⚠ Ollama is not responding; waiting up to {max_wait // 60} min for it to come back (start `ollama serve` if it closed)")
            announced = True
        time.sleep(5)
    return False


def chat(
    messages: list[dict],
    *,
    temperature: float = 0.7,
    top_p: float = 0.92,
    max_tokens: int = 2048,
    json_mode: bool = False,
    retries: int = 6,
) -> str:
    last: Exception | None = None
    for attempt in range(retries + 1):
        s = llm_settings.get()   # Developer Tools settings, re-read on every call
        payload = {
            "model": s["model"],
            "messages": messages,
            "stream": False,
            "think": bool(s["think"]) and not json_mode,
            "keep_alive": s["keep_alive"],
            "options": llm_settings.build_options(
                s, temperature=llm_settings.scaled_temperature(temperature), max_tokens=max_tokens,
                num_gpu=runtime.effective_gpu(s),
            ),
        }
        if json_mode:
            payload["format"] = "json"
        slot = runtime.acquire()
        try:
            with httpx.Client(timeout=s["request_timeout"]) as client:
                r = client.post(f"{settings.ollama_url}/api/chat", json=payload)
                if r.status_code == 400 and "think" in r.text:
                    payload.pop("think", None)  # older Ollama builds reject the flag
                    r = client.post(f"{settings.ollama_url}/api/chat", json=payload)
            if r.status_code == 200:
                return _clean(r.json()["message"]["content"])
            body = r.text.lower()
            last = LLMError(f"HTTP {r.status_code}: {r.text[:300]}")
            if r.status_code >= 500 and any(k in body for k in _MEMORY_ERRORS):
                # Fallback ladder: fewer parallel agents first, then less GPU offload.
                if not runtime.reduce_capacity() and not runtime.lower_gpu():
                    time.sleep(10)
            elif r.status_code in {400, 404}:
                raise LLMError(f"Ollama rejected the request: {r.text[:300]}")
            else:
                time.sleep(3 * (attempt + 1))
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError) as exc:
            last = exc
            log.warning("Ollama connection problem (attempt %s): %s", attempt + 1, exc)
            runtime.release(slot)
            slot = 0
            if not wait_for_ollama(settings.ollama_wait):
                break
        except httpx.TimeoutException as exc:
            last = exc
            runtime.notify(f"⚠ Model call timed out after {s['request_timeout']}s; retrying")
        finally:
            if slot:
                runtime.release(slot)
    raise LLMError(f"Ollama request failed after retries: {last}")


def generate(system: str, prompt: str, **kw) -> str:
    return chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}], **kw)


def generate_json(system: str, prompt: str, default, **kw):
    """Ask for JSON and parse defensively; returns `default` if the model misbehaves."""
    kw.setdefault("temperature", 0.3)
    try:
        raw = generate(system, prompt, json_mode=True, **kw)
    except LLMError:
        return default
    for candidate in (raw, _extract_json(raw)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return default


def _extract_json(text: str) -> str | None:
    m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
    return m.group(1) if m else None


def embed(texts: list[str]) -> list[list[float]] | None:
    """Neural sentence embeddings from Ollama. Returns None when no embedding model is installed."""
    if not texts:
        return []
    try:
        vectors: list[list[float]] = []
        with httpx.Client(timeout=120) as client:
            for i in range(0, len(texts), 32):
                r = client.post(
                    f"{settings.ollama_url}/api/embed",
                    json={"model": settings.embed_model, "input": [t[:2000] for t in texts[i : i + 32]]},
                )
                if r.status_code != 200:
                    return None
                vectors.extend(r.json()["embeddings"])
        return vectors
    except Exception:  # noqa: BLE001
        return None
