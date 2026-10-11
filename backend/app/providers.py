"""Cloud language models: the API keys the user adds in Settings, and how RAF talks to each provider.

A key turns a provider's model into extra agents that work beside (or instead of) the local Ollama model. Keys are
stored encrypted in <data_dir>/llm_keys.json (see vault.py) and never leave this module in clear text: the rest of RAF,
the API and the browser only ever see the last four characters.

Every provider has a rule profile — how RAF has to drive it to get the best out of it:

* protocol        Claude through Anthropic's own SDK; everything else through the OpenAI-compatible chat API that
                  OpenAI, Google Gemini, NVIDIA, Groq, Mistral, DeepSeek and OpenRouter all offer.
* contract        the same short output contract for every cloud model (text only, citation markers untouched).
* headroom        models that reason before answering need room for it inside the token limit.
* negotiation     when a model rejects a parameter (temperature, max_tokens, JSON mode, effort), RAF drops or renames
                  it, repeats the call and remembers the rule for that model.
* failure rules   a rejected key is switched off, a rate limit makes the key rest, a refusal is handed to another model.

When a cloud model is used, the prompts — which contain passages of the reference files and the draft — are sent to that
provider. Nothing is sent while the mode is "local" or no key is enabled.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time

import httpx

from . import vault
from .config import settings

PATH = settings.data_dir / "llm_keys.json"
MODES = {"local": "This PC only", "hybrid": "This PC and cloud models together", "cloud": "Cloud models only"}
ROLES = {"all": "Everything", "writing": "Writing only", "checks": "Checks only"}
MAX_KEYS, MAX_PARALLEL = 12, 4

CONTRACT = ("Output contract: return only the text that was asked for. No preamble, no closing remark, no notes about what you did, "
            "and no Markdown headings, bold or code fences unless the task asks for them. Keep citation markers such as [R3] or [W2] "
            "exactly as they are given and never invent one.")
JSON_RULE = "Reply with one valid JSON value and nothing else: no words before or after it and no code fence."

# name · protocol · API address · the model a new key starts with · what a key looks like · tokens kept free for reasoning · rules shown in Settings
CATALOG: dict[str, dict] = {
    "anthropic": {
        "name": "Claude", "company": "Anthropic", "protocol": "anthropic", "base_url": "", "model": "claude-opus-5-5", "prefix": "sk-ant-", "headroom": 6000,
        "models": ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"],
        "rules": ["Called through Anthropic's own SDK, with the system prompt kept apart from the conversation.",
                  "Sampling is left to the model (current Claude models reject temperature); depth is set by effort instead: medium for writing, low for checks.",
                  "Thinking stays on, so 6,000 tokens are kept free for it on top of the text RAF asks for.",
                  "If Claude declines a request, Anthropic's own fallback model answers; if that declines too, your next model does."],
    },
    "openai": {
        "name": "GPT", "company": "OpenAI", "protocol": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-5", "prefix": "sk-", "headroom": 4000,
        "models": [],
        "rules": ["Reasoning models take max_completion_tokens and no temperature: RAF switches on the first rejection and remembers it.",
                  "Checks are requested in JSON mode.", "4,000 tokens are kept free for reasoning."],
    },
    "gemini": {
        "name": "Gemini", "company": "Google", "protocol": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "model": "gemini-2.5-pro",
        "prefix": "AIza", "headroom": 4000, "models": [],
        "rules": ["Called through Google's OpenAI-compatible address.", "4,000 tokens are kept free for thinking.", "Checks are requested in JSON mode."],
    },
    "nvidia": {
        "name": "NVIDIA NIM", "company": "NVIDIA", "protocol": "openai", "base_url": "https://integrate.api.nvidia.com/v1", "model": "meta/llama-3.3-70b-instruct",
        "prefix": "nvapi-", "headroom": 0, "models": [],
        "rules": ["Hosts many open models: choose the one to use from the list RAF loads with your key.",
                  "Free keys are limited to a few requests a minute, so a limited key rests and the other agents carry on."],
    },
    "groq": {
        "name": "Groq", "company": "Groq", "protocol": "openai", "base_url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile", "prefix": "gsk_",
        "headroom": 0, "models": [],
        "rules": ["Very fast, with tight per-minute limits: a good key for the Checks role."],
    },
    "mistral": {
        "name": "Mistral", "company": "Mistral AI", "protocol": "openai", "base_url": "https://api.mistral.ai/v1", "model": "mistral-large-latest", "prefix": "",
        "headroom": 0, "models": [], "rules": ["Checks are requested in JSON mode."],
    },
    "deepseek": {
        "name": "DeepSeek", "company": "DeepSeek", "protocol": "openai", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "prefix": "",
        "headroom": 0, "models": [], "rules": ["Checks are requested in JSON mode."],
    },
    "openrouter": {
        "name": "OpenRouter", "company": "OpenRouter", "protocol": "openai", "base_url": "https://openrouter.ai/api/v1", "model": "openrouter/auto", "prefix": "sk-or-",
        "headroom": 2000, "models": [], "rules": ["One key for the models of many providers: choose the model from the list RAF loads with your key."],
    },
    "custom": {
        "name": "Other", "company": "OpenAI-compatible server", "protocol": "openai", "base_url": "", "model": "", "prefix": "", "headroom": 0, "models": [],
        "rules": ["Any server that speaks the OpenAI chat API (LM Studio, vLLM, Together, Fireworks, xAI, Azure-style gateways …): give its address and the model name."],
    },
}
_FALLBACK_MODELS = re.compile(r"claude-(fable-5-1|opus-5-5|opus-5|sonnet-5-5)$")   # the models Anthropic's server-side refusal fallback covers

_lock = threading.RLock()
_secrets: dict[str, str] = {}                 # key id -> decrypted key, for the life of the process
_learned: dict[tuple[str, str], set[str]] = {}   # (provider, model) -> parameters this model rejected
_stats: dict[str, dict] = {}                  # key id -> calls and errors since RAF started


class ProviderError(RuntimeError):
    """A cloud call that failed. `kind` tells the router what to do: auth and quota switch the key off, rate and busy make
    it rest, bad means this model or address cannot do the job, refused sends the request to another model."""

    def __init__(self, kind: str, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.kind, self.retry_after = kind, retry_after


# ---------------------------------------------------------------------------- the key store
def _read() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    return {"mode": data.get("mode", "hybrid") if data.get("mode") in MODES else "hybrid", "keys": [k for k in data.get("keys", []) if k.get("provider") in CATALOG]}


def _write(data: dict) -> None:
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PATH)


def _public(k: dict) -> dict:
    """A key as the browser may see it: everything but the secret."""
    spec = CATALOG[k["provider"]]
    return {**{f: k[f] for f in ("id", "provider", "label", "model", "base_url", "enabled", "parallel", "role", "tail", "status", "note", "added")},
            "name": spec["name"], "company": spec["company"], "usage": _stats.get(k["id"], {"calls": 0, "errors": 0, "last_error": ""})}


def version() -> float:
    """Changes whenever the key store is written."""
    try:
        return PATH.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def mode() -> str:
    return _read()["mode"]


def set_mode(value: str) -> str:
    if value not in MODES:
        raise ValueError("Unknown mode.")
    with _lock:
        data = _read()
        data["mode"] = value
        _write(data)
    return value


def list_keys() -> list[dict]:
    return [_public(k) for k in _read()["keys"]]


def detect(key: str) -> str:
    """Which provider a key belongs to, judged by how it starts ('' when it cannot be told)."""
    known = sorted(((spec["prefix"], name) for name, spec in CATALOG.items() if spec["prefix"]), key=lambda x: -len(x[0]))
    return next((name for prefix, name in known if key.startswith(prefix)), "")


def _address(url: str, provider: str) -> str:
    url = str(url or "").strip().rstrip("/")
    if not url:
        if provider == "custom":
            raise ValueError("Give the address of the server, for example https://api.example.com/v1.")
        return ""
    m = re.fullmatch(r"(https?)://([^/\s:@]+)(:\d+)?(/\S*)?", url)
    if not m:
        raise ValueError("The address must look like https://api.example.com/v1.")
    if m.group(1) == "http" and m.group(2) not in {"localhost", "127.0.0.1", "[::1]"}:
        raise ValueError("Use an https:// address: a key must not travel unencrypted. (http:// is accepted for localhost only.)")
    return url


def _clean(patch: dict, provider: str) -> dict:
    out: dict = {}
    if "label" in patch:
        out["label"] = " ".join(str(patch["label"]).split())[:40]
    if "base_url" in patch:
        out["base_url"] = _address(patch["base_url"], provider)
    if "model" in patch:
        model = str(patch["model"]).strip()
        if not model or len(model) > 120 or re.search(r"\s", model):
            raise ValueError("Give the name of the model, for example " + (CATALOG[provider]["model"] or "llama-3.3-70b") + ".")
        out["model"] = model
    if "enabled" in patch:
        out["enabled"] = bool(patch["enabled"])
    if "parallel" in patch:
        try:
            out["parallel"] = max(1, min(MAX_PARALLEL, int(patch["parallel"])))
        except (TypeError, ValueError):
            raise ValueError(f"Agents on a key must be a number from 1 to {MAX_PARALLEL}.") from None
    if "role" in patch:
        if patch["role"] not in ROLES:
            raise ValueError("Unknown role.")
        out["role"] = patch["role"]
    return out


def _secret_of(patch: dict) -> str:
    key = str(patch.get("key", "")).strip()
    if not 8 <= len(key) <= 400 or re.search(r"\s", key):
        raise ValueError("That does not look like an API key.")
    return key


def add_key(body: dict, check: bool = True) -> dict:
    """Store a new key (encrypted). With `check`, the provider is asked for its model list first, which costs nothing and
    proves the key works; a key the provider rejects is not stored."""
    secret = _secret_of(body)
    provider = body.get("provider") or detect(secret)
    if provider not in CATALOG:
        raise ValueError("Choose which provider this key belongs to.")
    spec = CATALOG[provider]
    fields = _clean({"label": body.get("label", ""), "model": body.get("model") or spec["model"] or "", "base_url": body.get("base_url", ""),
                     "parallel": body.get("parallel", 2), "role": body.get("role", "all"), "enabled": True}, provider)
    fp = hashlib.sha256(secret.encode()).hexdigest()[:16]
    with _lock:
        data = _read()
        if len(data["keys"]) >= MAX_KEYS:
            raise ValueError(f"RAF keeps at most {MAX_KEYS} keys. Remove one first.")
        if any(k["fp"] == fp and k["model"] == fields["model"] for k in data["keys"]):
            raise ValueError("This key is already saved for this model.")
    record = {"id": secrets.token_hex(4), "provider": provider, **fields, "secret": vault.seal(secret), "tail": secret[-4:], "fp": fp,
              "added": time.time(), "status": "unchecked", "note": ""}
    if check:
        try:
            offered = _models(record, secret)
            record["status"] = "ok"
            if offered and record["model"] not in offered:
                record["note"] = f"The provider does not list {record['model']}. Choose a model from its list."
        except ProviderError as exc:
            if exc.kind in {"auth", "quota"}:
                raise ValueError(f"{spec['name']} did not accept this key: {exc}") from None
            record["note"] = f"Could not reach {spec['name']} to check the key ({exc}). It is saved; use Test once you are online."
    with _lock:
        data = _read()
        data["keys"].append(record)
        _write(data)
        _secrets[record["id"]] = secret
    return _public(record)


def update_key(kid: str, patch: dict) -> dict:
    with _lock:
        data = _read()
        record = next((k for k in data["keys"] if k["id"] == kid), None)
        if record is None:
            raise KeyError(kid)
        record.update(_clean(patch, record["provider"]))
        if patch.get("key"):
            secret = _secret_of(patch)
            record.update(secret=vault.seal(secret), tail=secret[-4:], fp=hashlib.sha256(secret.encode()).hexdigest()[:16], status="unchecked", note="")
            _secrets[kid] = secret
        if {"model", "base_url"} & set(patch):
            record["note"] = ""
            record["status"] = "unchecked" if record["status"] == "rejected" else record["status"]
        _write(data)
        return _public(record)


def remove_key(kid: str) -> None:
    with _lock:
        data = _read()
        if not any(k["id"] == kid for k in data["keys"]):
            raise KeyError(kid)
        data["keys"] = [k for k in data["keys"] if k["id"] != kid]
        _write(data)
        _secrets.pop(kid, None)
        _stats.pop(kid, None)


def reorder(ids: list[str]) -> list[dict]:
    """The order of the keys is their priority: the first free one takes the next request."""
    with _lock:
        data = _read()
        by_id = {k["id"]: k for k in data["keys"]}
        data["keys"] = [by_id[i] for i in dict.fromkeys(ids) if i in by_id] + [k for k in data["keys"] if k["id"] not in ids]
        _write(data)
    return list_keys()


def mark(kid: str, status: str, note: str = "") -> None:
    with _lock:
        data = _read()
        for k in data["keys"]:
            if k["id"] == kid:
                k["status"], k["note"] = status, note[:240]
                _write(data)


def _record(kid: str) -> dict:
    record = next((k for k in _read()["keys"] if k["id"] == kid), None)
    if record is None:
        raise KeyError(kid)
    return record


def _secret(record: dict) -> str:
    with _lock:
        if record["id"] not in _secrets:
            try:
                _secrets[record["id"]] = vault.unseal(record["secret"])
            except ValueError as exc:
                raise ProviderError("auth", str(exc)) from None
        return _secrets[record["id"]]


def engines() -> list[dict]:
    """The keys that can work right now, in priority order (empty in local mode). No secrets."""
    data = _read()
    if data["mode"] == "local":
        return []
    return [_public(k) for k in data["keys"] if k["enabled"] and k["status"] != "rejected" and k["model"]]


def summary() -> dict:
    """What the rest of the app may know about the cloud team: shown on the Segments page and in the status line."""
    team = engines()
    return {"mode": mode(), "engines": [{f: e[f] for f in ("id", "provider", "name", "label", "model", "parallel", "role")} for e in team],
            "agents": sum(e["parallel"] for e in team)}


def catalog() -> list[dict]:
    return [{"key": name, **{f: spec[f] for f in ("name", "company", "model", "models", "prefix", "rules")}, "needs_address": name == "custom",
             "address": spec["base_url"]} for name, spec in CATALOG.items()]


# ---------------------------------------------------------------------------- talking to a provider
def _scrub(text: str, secret: str) -> str:
    """An error message that is safe to show and to log: some providers repeat part of the key in theirs."""
    text = text.replace(secret, "•••") if secret else text
    return re.sub(r"\b(sk-|nvapi-|gsk_|AIza)[\w\-*.]{6,}", r"\1•••", " ".join(text.split()))[:300]


def _count(kid: str, error: str = "") -> None:
    with _lock:
        s = _stats.setdefault(kid, {"calls": 0, "errors": 0, "last_error": ""})
        s["errors" if error else "calls"] += 1
        if error:
            s["last_error"] = error


def _split(messages: list[dict], json_mode: bool) -> tuple[str, list[dict]]:
    """RAF's messages as (system prompt with the output rules, conversation)."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    system = "\n\n".join(part for part in (system, JSON_RULE if json_mode else CONTRACT) if part)
    return system, [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]


def call(kid: str, messages: list[dict], *, temperature: float, max_tokens: int, json_mode: bool = False, sink=None, timeout: float = 900) -> str:
    """One request to the model behind a key. Returns the text; raises ProviderError."""
    try:
        record = _record(kid)
    except KeyError:
        raise ProviderError("auth", "This key was removed.") from None
    secret = _secret(record)
    system, turns = _split(messages, json_mode)
    try:
        send = _claude if CATALOG[record["provider"]]["protocol"] == "anthropic" else _openai
        text = send(record, secret, system, turns, temperature=temperature, max_tokens=max_tokens, json_mode=json_mode, sink=sink, timeout=timeout)
    except ProviderError as exc:
        clean = ProviderError(exc.kind, _scrub(str(exc), secret), exc.retry_after)
        _count(kid, str(clean))
        raise clean from None
    if not text.strip():
        _count(kid, "empty answer")
        raise ProviderError("busy", "The model returned no text (it may have spent its whole token limit on reasoning).")
    _count(kid)
    return text


def _retry_after(headers) -> float | None:
    try:
        return float(headers.get("retry-after", ""))
    except (TypeError, ValueError):
        return None


# ---- Claude, through the Anthropic SDK
def _claude(record: dict, secret: str, system: str, turns: list[dict], *, temperature: float, max_tokens: int, json_mode: bool, sink, timeout: float) -> str:
    try:
        import anthropic
    except ImportError:
        raise ProviderError("setup", "The Anthropic SDK is not installed. Run: pip install anthropic") from None
    model = record["model"]
    learned = _learned.setdefault(("anthropic", model), set())
    client = anthropic.Anthropic(api_key=secret, base_url=record["base_url"] or None, timeout=float(timeout), max_retries=1)
    for _ in range(3):      # at most two rules to learn: effort and the refusal fallback
        params: dict = {"model": model, "max_tokens": max_tokens + CATALOG["anthropic"]["headroom"], "messages": turns}
        if system:
            params["system"] = system
        if "effort" not in learned:
            params["output_config"] = {"effort": "low" if json_mode else "medium"}
        fallback = "fallbacks" not in learned and not record["base_url"] and _FALLBACK_MODELS.search(model)
        parts: list[str] = []
        try:
            stream = (client.beta.messages.stream(**params, betas=["server-side-fallback-2026-07-01"], fallbacks="default") if fallback
                      else client.messages.stream(**params))
            with stream as s:
                for piece in s.text_stream:
                    parts.append(piece)
                    if sink:
                        sink(piece)
                final = s.get_final_message()
        except anthropic.BadRequestError as exc:
            said = str(exc).lower()
            rule = "fallbacks" if fallback and ("fallback" in said or "beta" in said) else "effort" if "output_config" in params and ("effort" in said or "output_config" in said) else ""
            if not rule or parts:
                raise ProviderError("bad", exc.message) from None
            learned.add(rule)
            continue
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise ProviderError("auth", exc.message) from None
        except anthropic.NotFoundError as exc:
            raise ProviderError("bad", f"{model} is not available to this key ({exc.message})") from None
        except anthropic.RateLimitError as exc:
            raise ProviderError("rate", exc.message, _retry_after(exc.response.headers)) from None
        except anthropic.APIStatusError as exc:
            raise ProviderError("busy" if exc.status_code >= 500 else "bad", exc.message) from None
        except anthropic.APIConnectionError as exc:     # includes timeouts
            raise ProviderError("busy", f"could not reach Anthropic ({type(exc).__name__})") from None
        if final.stop_reason == "refusal":
            raise ProviderError("refused", "Claude declined this request.")
        return "".join(block.text for block in final.content if block.type == "text")
    raise ProviderError("bad", "The request was rejected twice.")


def _claude_models(record: dict, secret: str) -> list[str]:
    try:
        import anthropic
    except ImportError:
        raise ProviderError("setup", "The Anthropic SDK is not installed. Run: pip install anthropic") from None
    client = anthropic.Anthropic(api_key=secret, base_url=record["base_url"] or None, timeout=20.0, max_retries=1)
    try:
        names = []
        for m in client.models.list():
            names.append(m.id)
            if len(names) >= 80:
                break
        return names
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
        raise ProviderError("auth", exc.message) from None
    except anthropic.RateLimitError as exc:
        raise ProviderError("rate", exc.message) from None
    except anthropic.APIStatusError as exc:
        raise ProviderError("busy" if exc.status_code >= 500 else "bad", exc.message) from None
    except anthropic.APIConnectionError as exc:
        raise ProviderError("busy", f"could not reach Anthropic ({type(exc).__name__})") from None


# ---- every provider with an OpenAI-compatible chat API
def _base(record: dict) -> str:
    return (record["base_url"] or CATALOG[record["provider"]]["base_url"]).rstrip("/")


def _problem(status: int, body: str, headers) -> ProviderError:
    try:
        err = json.loads(body)
        err = err[0] if isinstance(err, list) and err else err
        detail = err.get("error", err) if isinstance(err, dict) else err
        message = detail.get("message") or detail.get("detail") or json.dumps(detail) if isinstance(detail, dict) else str(detail)
    except (json.JSONDecodeError, AttributeError):
        message = body
    message = f"HTTP {status}: {message}"
    low = message.lower()
    if status in {401, 403}:
        return ProviderError("auth", message)
    if status == 402 or (status == 429 and any(w in low for w in ("quota", "billing", "credit", "balance"))):
        return ProviderError("quota", message)
    if status == 429:
        return ProviderError("rate", message, _retry_after(headers))
    return ProviderError("busy" if status >= 500 or status == 408 else "bad", message)


def _adapt(body: dict, said: str, learned: set[str]) -> bool:
    """Change the request after a 400 that names a parameter the model does not take. True when something was changed."""
    said = said.lower()
    if "max_completion_tokens" in said and "max_tokens" in body:
        learned.add("max_completion_tokens")
    elif "temperature" in said and "temperature" in body:
        learned.add("no_temperature")
    elif "response_format" in said and "response_format" in body:
        learned.add("no_json_mode")
    else:
        return False
    _apply(body, learned)
    return True


def _apply(body: dict, learned: set[str]) -> None:
    if "max_completion_tokens" in learned and "max_tokens" in body:
        body["max_completion_tokens"] = body.pop("max_tokens")
    if "no_temperature" in learned:
        body.pop("temperature", None)
    if "no_json_mode" in learned:
        body.pop("response_format", None)


def _openai(record: dict, secret: str, system: str, turns: list[dict], *, temperature: float, max_tokens: int, json_mode: bool, sink, timeout: float) -> str:
    spec = CATALOG[record["provider"]]
    learned = _learned.setdefault((record["provider"], record["model"]), set())
    body: dict = {"model": record["model"], "messages": ([{"role": "system", "content": system}] if system else []) + turns,
                  "max_tokens": max_tokens + spec["headroom"], "temperature": round(max(0.0, min(1.0, temperature)), 3)}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    _apply(body, learned)
    url, headers = _base(record) + "/chat/completions", {"Authorization": f"Bearer {secret}"}
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=15.0)) as client:
            for _ in range(4):      # at most three rules to learn
                if sink is None:
                    r = client.post(url, headers=headers, json=body)
                    if r.status_code == 200:
                        content = (r.json().get("choices") or [{}])[0].get("message", {}).get("content")
                        return content if isinstance(content, str) else "".join(p.get("text", "") for p in content or [] if isinstance(p, dict))
                    status, text, got = r.status_code, r.text, r.headers
                else:
                    parts: list[str] = []
                    with client.stream("POST", url, headers=headers, json={**body, "stream": True}) as r:
                        status, got = r.status_code, r.headers
                        if status == 200:
                            for line in r.iter_lines():
                                if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                                    continue
                                d = json.loads(line[5:])
                                if d.get("error"):
                                    raise ProviderError("busy", json.dumps(d["error"])[:300])
                                piece = ((d.get("choices") or [{}])[0].get("delta") or {}).get("content") or ""
                                if piece:
                                    parts.append(piece)
                                    sink(piece)
                            return "".join(parts)
                        text = r.read().decode("utf-8", "replace")
                if status not in {400, 422} or not _adapt(body, text, learned):
                    raise _problem(status, text, got)
    except httpx.TimeoutException:
        raise ProviderError("busy", f"{spec['name']} did not answer within {int(timeout)} s") from None
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        raise ProviderError("busy", f"could not reach {spec['name']} ({type(exc).__name__})") from None
    raise ProviderError("bad", "The request was rejected after three adjustments.")


def _openai_models(record: dict, secret: str) -> list[str]:
    spec = CATALOG[record["provider"]]
    try:
        r = httpx.get(_base(record) + "/models", headers={"Authorization": f"Bearer {secret}"}, timeout=20)
    except httpx.HTTPError as exc:
        raise ProviderError("busy", f"could not reach {spec['name']} ({type(exc).__name__})") from None
    if r.status_code != 200:
        raise _problem(r.status_code, r.text, r.headers)
    try:
        rows = r.json()
        rows = rows.get("data", rows.get("models", [])) if isinstance(rows, dict) else rows
        return sorted({str(m.get("id") or m.get("name") or "").removeprefix("models/") for m in rows if isinstance(m, dict)} - {""})[:400]
    except (json.JSONDecodeError, AttributeError):
        return []


def _models(record: dict, secret: str) -> list[str]:
    try:
        return (_claude_models if CATALOG[record["provider"]]["protocol"] == "anthropic" else _openai_models)(record, secret)
    except ProviderError as exc:
        raise ProviderError(exc.kind, _scrub(str(exc), secret), exc.retry_after) from None


def models(kid: str) -> list[str]:
    """The models this key can use, asked from the provider."""
    record = _record(kid)
    return _models(record, _secret(record))


def test(kid: str) -> dict:
    """One very small real request, to prove the key, the model and the address work together. Costs a few tokens."""
    record = _record(kid)
    started = time.monotonic()
    try:
        text = call(kid, [{"role": "user", "content": "Reply with the single word: ready"}], temperature=0.0, max_tokens=24, timeout=60)
    except ProviderError as exc:
        if exc.kind in {"auth", "quota"}:
            mark(kid, "rejected", str(exc))
        return {"ok": False, "kind": exc.kind, "error": str(exc), "seconds": round(time.monotonic() - started, 1), "model": record["model"]}
    mark(kid, "ok")
    return {"ok": True, "seconds": round(time.monotonic() - started, 1), "model": record["model"], "sample": text.strip()[:80]}
