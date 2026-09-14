"""Developer Tools: persisted settings for the local language model (stored in <data_dir>/llm_settings.json).

Every model call reads these, so changes apply from the next call — no restart needed. Changing the context window,
batch size or GPU layers makes Ollama reload the model once.
"""
from __future__ import annotations

import json
import threading
import time

import httpx

from .config import settings

PATH = settings.data_dir / "llm_settings.json"

# Base drafting temperature. Each call type keeps its own tuned temperature; the user's value scales all of them.
BASE_TEMPERATURE = 0.7

DEFAULTS: dict = {
    "model": settings.model,
    "temperature": BASE_TEMPERATURE,
    "top_p": 0.92,
    "top_k": 64,
    "min_p": 0.0,
    "repeat_penalty": 1.08,
    "repeat_last_n": 128,
    "presence_penalty": 0.0,
    "frequency_penalty": 0.0,
    "seed": -1,
    "num_ctx": settings.num_ctx,
    "num_batch": 512,
    "max_output_tokens": 4096,
    "num_gpu": settings.num_gpu,
    "num_thread": 0,
    "keep_alive": "30m",
    "think": False,
    "request_timeout": settings.llm_timeout,
}

# (type, min, max) — used for validation and to build the UI.
SPEC: dict = {
    "model": ("str", None, None),
    "temperature": ("float", 0.0, 2.0),
    "top_p": ("float", 0.05, 1.0),
    "top_k": ("int", 1, 200),
    "min_p": ("float", 0.0, 0.5),
    "repeat_penalty": ("float", 0.8, 2.0),
    "repeat_last_n": ("int", 0, 4096),
    "presence_penalty": ("float", -2.0, 2.0),
    "frequency_penalty": ("float", -2.0, 2.0),
    "seed": ("int", -1, 2**31 - 1),
    "num_ctx": ("int", 2048, 262144),
    "num_batch": ("int", 32, 4096),
    "max_output_tokens": ("int", 256, 16384),
    "num_gpu": ("int", -1, 99),
    "num_thread": ("int", 0, 128),
    "keep_alive": ("str", None, None),
    "think": ("bool", None, None),
    "request_timeout": ("int", 60, 7200),
}

PRESETS: dict = {
    "precise": {"temperature": 0.45, "top_p": 0.85, "top_k": 40, "min_p": 0.05, "repeat_penalty": 1.1},
    "balanced": {"temperature": 0.7, "top_p": 0.92, "top_k": 64, "min_p": 0.0, "repeat_penalty": 1.08},
    "expressive": {"temperature": 0.9, "top_p": 0.95, "top_k": 80, "min_p": 0.02, "repeat_penalty": 1.05},
}

_lock = threading.Lock()
_cache: dict | None = None
_mtime = 0.0


def get() -> dict:
    global _cache, _mtime
    with _lock:
        try:
            mtime = PATH.stat().st_mtime
        except FileNotFoundError:
            mtime = 0.0
        if _cache is None or mtime != _mtime:
            stored = {}
            if mtime:
                try:
                    stored = json.loads(PATH.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    stored = {}
            _cache = {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}
            _mtime = mtime
        return dict(_cache)


def validate(patch: dict) -> dict:
    clean = {}
    for key, value in patch.items():
        if key not in SPEC:
            continue
        kind, lo, hi = SPEC[key]
        try:
            if kind == "int":
                value = int(value)
            elif kind == "float":
                value = float(value)
            elif kind == "bool":
                value = bool(value)
            else:
                value = str(value).strip()
        except (TypeError, ValueError):
            raise ValueError(f"{key}: invalid value {value!r}") from None
        if lo is not None and not (lo <= value <= hi):
            raise ValueError(f"{key} must be between {lo} and {hi}")
        if key == "model" and not value:
            raise ValueError("model cannot be empty")
        clean[key] = value
    return clean


def update(patch: dict) -> dict:
    global _cache
    merged = {**get(), **validate(patch)}
    with _lock:
        PATH.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        _cache = None
    return get()


def reset() -> dict:
    global _cache
    with _lock:
        PATH.unlink(missing_ok=True)
        _cache = None
    return get()


def ollama_state() -> dict:
    """Installed models and what is currently loaded (with its memory split between GPU and RAM)."""
    out = {"installed": [], "loaded": []}
    try:
        tags = httpx.get(f"{settings.ollama_url}/api/tags", timeout=2.5).json().get("models", [])
        out["installed"] = [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 2),
                             "parameters": m.get("details", {}).get("parameter_size", ""),
                             "quantization": m.get("details", {}).get("quantization_level", "")} for m in tags]
        ps = httpx.get(f"{settings.ollama_url}/api/ps", timeout=2.5).json().get("models", [])
        out["loaded"] = [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 2), "vram_gb": round(m.get("size_vram", 0) / 1e9, 2),
                          "context": m.get("context_length"), "expires": m.get("expires_at", "")} for m in ps]
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


def benchmark(prompt: str = "In three sentences, explain why crowd density matters for event safety.") -> dict:
    """Run one short generation with the current settings and report real speeds."""
    s = get()
    payload = {
        "model": s["model"], "prompt": prompt, "stream": False, "think": bool(s["think"]), "keep_alive": s["keep_alive"],
        "options": build_options(s, temperature=s["temperature"], max_tokens=160),
    }
    started = time.time()
    r = httpx.post(f"{settings.ollama_url}/api/generate", json=payload, timeout=s["request_timeout"])
    r.raise_for_status()
    d = r.json()
    ns = 1e9
    eval_rate = d.get("eval_count", 0) / (d.get("eval_duration", 0) / ns) if d.get("eval_duration") else 0
    prompt_rate = d.get("prompt_eval_count", 0) / (d.get("prompt_eval_duration", 0) / ns) if d.get("prompt_eval_duration") else 0
    return {
        "model": s["model"], "wall_seconds": round(time.time() - started, 1),
        "load_seconds": round(d.get("load_duration", 0) / ns, 1),
        "prompt_tokens": d.get("prompt_eval_count", 0), "prompt_tokens_per_sec": round(prompt_rate, 1),
        "output_tokens": d.get("eval_count", 0), "output_tokens_per_sec": round(eval_rate, 1),
        "sample": d.get("response", "").strip()[:400],
    }


def build_options(s: dict, *, temperature: float, max_tokens: int, top_p: float | None = None, num_gpu: int | None = None) -> dict:
    opts = {
        "temperature": round(max(0.0, min(2.0, temperature)), 3),
        "top_p": top_p if top_p is not None else s["top_p"],
        "top_k": s["top_k"],
        "min_p": s["min_p"],
        "repeat_penalty": s["repeat_penalty"],
        "repeat_last_n": s["repeat_last_n"],
        "num_ctx": s["num_ctx"],
        "num_batch": s["num_batch"],
        "num_predict": min(max_tokens, s["max_output_tokens"]),
    }
    if s["presence_penalty"]:
        opts["presence_penalty"] = s["presence_penalty"]
    if s["frequency_penalty"]:
        opts["frequency_penalty"] = s["frequency_penalty"]
    if s["seed"] >= 0:
        opts["seed"] = s["seed"]
    gpu = s["num_gpu"] if num_gpu is None else num_gpu
    if gpu >= 0:
        opts["num_gpu"] = gpu
    if s["num_thread"] > 0:
        opts["num_thread"] = s["num_thread"]
    return opts


def scaled_temperature(call_temperature: float) -> float:
    return call_temperature * get()["temperature"] / BASE_TEMPERATURE
