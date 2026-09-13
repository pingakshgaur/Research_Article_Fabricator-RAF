"""Thin, resilient client for the local Ollama server (no API keys involved)."""
from __future__ import annotations

import json
import logging
import re
import time

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


def chat(
    messages: list[dict],
    *,
    temperature: float = 0.7,
    top_p: float = 0.92,
    max_tokens: int = 2048,
    json_mode: bool = False,
    retries: int = 2,
) -> str:
    payload = {
        "model": settings.model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
            "top_p": top_p,
            "top_k": 64,
            "num_ctx": settings.num_ctx,
            "num_predict": max_tokens,
            "repeat_penalty": 1.08,
        },
    }
    if settings.num_gpu >= 0:
        payload["options"]["num_gpu"] = settings.num_gpu
    if json_mode:
        payload["format"] = "json"
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=settings.llm_timeout) as client:
                r = client.post(f"{settings.ollama_url}/api/chat", json=payload)
                if r.status_code == 400 and "think" in r.text:
                    payload.pop("think", None)  # older Ollama builds reject the flag
                    r = client.post(f"{settings.ollama_url}/api/chat", json=payload)
                r.raise_for_status()
                return _clean(r.json()["message"]["content"])
        except Exception as exc:  # noqa: BLE001
            last = exc
            log.warning("LLM call failed (attempt %s): %s", attempt + 1, exc)
            time.sleep(2 * (attempt + 1))
    raise LLMError(f"Ollama request failed: {last}")


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
