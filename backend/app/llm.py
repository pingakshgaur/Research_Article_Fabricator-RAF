"""Thin, resilient client for the local Ollama server (no API keys involved)."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import Callable

import httpx

from .config import settings

log = logging.getLogger("raf.llm")


class LLMError(RuntimeError):
    pass


_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def _clean(text: str) -> str:
    text = _THINK_RE.sub("", text)
    return text.strip()


def health() -> dict:
    try:
        r = httpx.get(f"{settings.ollama_url}/api/tags", timeout=5)
        r.raise_for_status()
        names = [m["name"] for m in r.json().get("models", [])]
        return {
            "ollama": True,
            "model": settings.model,
            "model_available": any(n == settings.model or n.startswith(settings.model + ":") for n in names),
            "embed_model_available": any(n.split(":")[0] == settings.embed_model.split(":")[0] for n in names),
            "models": names,
        }
    except Exception as exc:  # noqa: BLE001
        return {"ollama": False, "model": settings.model, "model_available": False, "embed_model_available": False, "error": str(exc)}


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
        self.num_gpu = settings.num_gpu
        self.notify: Callable[[str], None] = lambda message: None
        self.local = threading.local()

    def configure(self, agents: int, notify: Callable[[str], None] | None = None) -> None:
        with self.cond:
            self.capacity = max(1, min(3, agents))
            self.free_slots = list(range(1, self.capacity + 1))
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

    def lower_gpu(self) -> bool:
        ladder = list(self.GPU_LADDER)
        current = self.num_gpu if self.num_gpu in ladder else -1
        idx = ladder.index(current)
        if idx >= len(ladder) - 1:
            return False
        self.num_gpu = ladder[idx + 1]
        self.notify(f"⚠ Model ran out of memory: retrying with {'CPU only' if self.num_gpu == 0 else f'{self.num_gpu} GPU layers'} (RAF_NUM_GPU={self.num_gpu})")
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
        payload = {
            "model": settings.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "options": {
                "temperature": temperature,
                "top_p": top_p,
                "top_k": 64,
                "num_ctx": settings.num_ctx,
                "num_predict": max_tokens,
                "repeat_penalty": 1.08,
            },
        }
        if runtime.num_gpu >= 0:
            payload["options"]["num_gpu"] = runtime.num_gpu
        if json_mode:
            payload["format"] = "json"
        slot = runtime.acquire()
        try:
            with httpx.Client(timeout=settings.llm_timeout) as client:
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
            runtime.notify(f"⚠ Model call timed out after {settings.llm_timeout}s; retrying")
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
