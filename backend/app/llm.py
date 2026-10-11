"""Every model call of RAF goes through here: the local Ollama server and, when the user added API keys, cloud models
(providers.py). The runtime decides which of them takes a call and what happens when one fails."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from contextlib import contextmanager
from typing import Callable

import httpx

from . import llm_settings, providers
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
        local = {
            "ollama": True,
            "model": model,
            "model_available": any(n == model or n.startswith(model + ":") for n in names),
            "embed_model_available": any(n.split(":")[0] == settings.embed_model.split(":")[0] for n in names),
            "models": names,
        }
    except Exception as exc:  # noqa: BLE001
        local = {"ollama": False, "model": model, "model_available": False, "embed_model_available": False, "error": str(exc)}
    cloud = providers.summary()
    # "ready": something can write — the local model, or at least one cloud model the user added a key for
    return {**local, "cloud": cloud, "ready": local["model_available"] or bool(cloud["engines"])}


def ready() -> bool:
    h = health()
    return bool(h.get("ready", h.get("model_available")))


# ---------------------------------------------------------------------------- agents, engines & fallbacks
MAX_AGENTS = 8


class Engine:
    """One model that can take calls: the local one ("local") or the model behind an API key (the key's id)."""

    def __init__(self, id: str, name: str, model: str, slots: int, role: str = "all", provider: str = "ollama") -> None:
        self.id, self.name, self.model, self.slots, self.role, self.provider = id, name, model, slots, role, provider
        self.busy = 0            # calls running on it now
        self.rest_until = 0.0    # resting after a rate limit or an error (time.monotonic)
        self.fails = 0           # failures in a row
        self.off = ""            # why it is out for the rest of the run ("" = working)

    @property
    def local(self) -> bool:
        return self.id == "local"


class _Runtime:
    """Process-wide state shared by every model call.

    * engines   — the local model (1 solo, 2 duo, 3 trio agents) and, when the user added API keys, one engine per key
                  with as many agents as the key allows. Every call occupies one agent of one engine.
    * routing   — a call goes to the engine its thread used last when that is free (one voice per segment), otherwise
                  to the first free engine: cloud keys in the order of the list in Settings, then the local model.
                  In "cloud" mode the local model only steps in when no cloud model is left.
    * fallbacks — out-of-memory errors lower local concurrency, then GPU offload; a crashed/restarting Ollama is waited
                  for; a rejected key is switched off, a rate-limited one rests, and their work moves to the others.
    """

    GPU_LADDER = (-1, 24, 12, 0)   # auto → partial offload → CPU only

    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.pc = Engine("local", "This PC", "", 1)
        self.cloud: list[Engine] = []
        self.mode = "local"
        self.want_cloud = True                  # the last run's choice; a run can leave the cloud models out
        self.version: float | None = None       # the key store this team was built from
        self.numbers: set[int] = set()          # agent numbers in use (only for labelling)
        self.gpu_override: int | None = None   # set by the out-of-memory fallback; otherwise Developer Tools decide
        self.notify: Callable[[str], None] = lambda message: None
        self.local = threading.local()

    # ---- the team
    def _load(self, fresh: bool = False) -> None:
        """Build the list of cloud engines from the key store. `fresh` forgets which keys were switched off."""
        known = {} if fresh else {e.id: e for e in self.cloud}
        self.version = providers.version()
        self.mode = providers.mode() if self.want_cloud else "local"
        self.cloud = []
        for k in providers.engines() if self.want_cloud else []:
            e = known.get(k["id"]) or Engine(k["id"], k["label"] or k["name"], k["model"], k["parallel"], k["role"], k["provider"])
            e.name, e.model, e.slots, e.role = k["label"] or k["name"], k["model"], k["parallel"], k["role"]
            self.cloud.append(e)

    def _alive(self) -> list[Engine]:
        return [e for e in self.cloud if not e.off]

    def _pc_works(self) -> bool:
        return not self.pc.off and (self.mode != "cloud" or not self._alive())

    def _capacity(self) -> int:
        return max(1, min(MAX_AGENTS, sum(e.slots for e in self._alive()) + (self.pc.slots if self._pc_works() else 0)))

    @property
    def capacity(self) -> int:
        """How many model calls can run at the same time: the number of agents."""
        with self.cond:
            return self._capacity()

    def configure(self, agents: int, notify: Callable[[str], None] | None = None, cloud: bool = True) -> None:
        """Set up the team for a run: `agents` local agents plus, unless `cloud` is False, the cloud models."""
        with self.cond:
            self.pc = Engine("local", "This PC", llm_settings.get()["model"], max(1, min(3, agents)))
            self.want_cloud = cloud
            self._load(fresh=True)
            self.numbers = set()
            self.cond.notify_all()
        if notify:
            self.notify = notify

    def ensure(self, agents: int, notify: Callable[[str], None] | None = None, cloud: bool = True) -> None:
        """Like configure(), but safe while other jobs are working: agents in use stay taken."""
        with self.cond:
            self.pc.slots, self.pc.model = max(1, min(3, agents)), llm_settings.get()["model"]
            self.want_cloud = cloud
            self._load()
            self.cond.notify_all()
        if notify:
            self.notify = notify

    def team(self) -> list[dict]:
        """Who is working, for the log and the record of the run."""
        with self.cond:
            if self.version != providers.version():
                self._load()
            pc = [self.pc] if self._pc_works() else []
            return [{"id": e.id, "provider": e.provider, "name": e.name, "model": e.model or llm_settings.get()["model"], "agents": e.slots, "local": e.local}
                    for e in [*self._alive(), *pc]]

    # ---- taking and returning an agent
    def _pick(self, prose: bool, avoid: set[str]) -> Engine | None:
        now = time.monotonic()
        alive = [e for e in self._alive() if e.id not in avoid]
        pc_ok = not self.pc.off and "local" not in avoid and (self.mode != "cloud" or not alive)
        fitting = [e for e in alive if e.role == "all" or e.role == ("writing" if prose else "checks")]
        if not fitting and not pc_ok:
            fitting = alive                      # a role never leaves a request without a model
        candidates = fitting + ([self.pc] if pc_ok else [])
        if not candidates:
            raise LLMError("No language model is available: " + ("; ".join(f"{e.name}: {e.off}" for e in [*self.cloud, self.pc] if e.off) or "every model declined the request"))
        if len(self.numbers) >= self._capacity():
            return None
        free = [e for e in candidates if e.busy < e.slots and e.rest_until <= now]
        last = getattr(self.local, "engine", None)
        return last if last in free else free[0] if free else None

    def acquire(self, prose: bool = True, avoid: set[str] | None = None) -> tuple[int, Engine]:
        with self.cond:
            if self.version != providers.version():      # a key was added, changed or removed in Settings
                self._load()
            if not self.pc.model:
                self.pc.model = llm_settings.get()["model"]
            while True:
                engine = self._pick(prose, avoid or set())
                if engine:
                    break
                self.cond.wait(timeout=1.0)              # an engine that rests becomes free with time, not with a release
            engine.busy += 1
            slot = next(n for n in range(1, MAX_AGENTS + 2) if n not in self.numbers)
            self.numbers.add(slot)
        self.local.agent, self.local.engine = slot, engine
        return slot, engine

    def release(self, slot: int, engine: Engine) -> None:
        with self.cond:
            engine.busy = max(0, engine.busy - 1)
            self.numbers.discard(slot)
            self.cond.notify_all()

    # ---- fallbacks: the local model
    def reduce_capacity(self) -> bool:
        with self.cond:
            if self.pc.slots <= 1:
                return False
            self.pc.slots -= 1
            left = self.pc.slots
        self.notify(f"⚠ Memory pressure: reducing to {left} parallel local agent(s)")
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

    def pc_down(self, why: str) -> bool:
        """The local model cannot be reached. True when cloud models can carry on without it (it is then left out)."""
        with self.cond:
            if not self._alive():
                return False
            first, self.pc.off = not self.pc.off, why
            self.cond.notify_all()
        if first:
            self.notify("⚠ The local model is not reachable — the cloud models carry on without it")
        return True

    # ---- fallbacks: cloud models
    def setback(self, engine: Engine, exc: "providers.ProviderError") -> None:
        """A cloud call failed: decide whether the key rests, is switched off, or just loses this one request."""
        now, message = time.monotonic(), ""
        with self.cond:
            if exc.kind in {"auth", "quota", "setup"}:
                engine.off = str(exc)
                message = f"⚠ {engine.name}: the key was not accepted and is switched off ({exc})"
            elif exc.kind == "rate":
                if engine.rest_until <= now:
                    message = f"⏳ {engine.name} reached its rate limit — it rests for {int(min(120, exc.retry_after or 20))} s while the other agents carry on"
                engine.rest_until = now + min(120, exc.retry_after or 20)
            elif exc.kind == "refused":
                message = f"↪ {engine.name} declined a request — passing it to another model"
            else:                                        # busy (server or network trouble) · bad (this model cannot take the request)
                engine.fails += 2 if exc.kind == "bad" else 1
                if engine.fails >= 4:
                    engine.off = str(exc)
                    message = f"⚠ {engine.name} keeps failing and is left out for the rest of this run ({exc})"
                else:
                    engine.rest_until = now + min(60, 4 * 2 ** engine.fails)
                    message = f"⚠ {engine.name}: {exc} — retrying"
            alone = bool(engine.off) and not self._alive() and not self.pc.off
            self.cond.notify_all()
        if exc.kind in {"auth", "quota"}:
            providers.mark(engine.id, "rejected", str(exc))
        if message:
            self.notify(message)
        if alone:
            self.notify("⚠ No cloud model is left — the local model continues the work")


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


_stream = threading.local()


@contextmanager
def streaming(sink: Callable[[str | None], None]):
    """While this is open, prose calls made by this thread stream: `sink` gets each piece of text as the model produces it,
    and `None` whenever a call starts (again), so a retry does not leave half a passage behind. JSON calls never stream."""
    previous = getattr(_stream, "sink", None)
    _stream.sink = sink
    try:
        yield
    finally:
        _stream.sink = previous


def _post(client: httpx.Client, payload: dict, sink) -> tuple[int, str]:
    """One request to Ollama. Returns (status, text): the answer on 200, the error body otherwise."""
    if sink is None:
        r = client.post(f"{settings.ollama_url}/api/chat", json=payload)
        return r.status_code, (r.json()["message"]["content"] if r.status_code == 200 else r.text)
    sink(None)
    parts: list[str] = []
    with client.stream("POST", f"{settings.ollama_url}/api/chat", json={**payload, "stream": True}) as r:
        if r.status_code != 200:
            return r.status_code, r.read().decode("utf-8", "replace")
        for line in r.iter_lines():
            if not line:
                continue
            d = json.loads(line)
            if d.get("error"):
                return 500, str(d["error"])
            piece = (d.get("message") or {}).get("content", "")
            if piece:
                parts.append(piece)
                sink(piece)
            if d.get("done"):
                break
    return 200, "".join(parts)


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
    avoid: set[str] = set()      # engines that declined or could not take this particular request
    for attempt in range(retries + 1):
        s = llm_settings.get()   # Developer Tools settings, re-read on every call
        sink = None if json_mode else getattr(_stream, "sink", None)
        slot, engine = runtime.acquire(prose=not json_mode, avoid=avoid)
        try:
            if not engine.local:                         # a cloud model, through the key the user added
                if sink:
                    sink(None)
                text = providers.call(engine.id, messages, temperature=llm_settings.scaled_temperature(temperature),
                                      max_tokens=min(max_tokens, s["max_output_tokens"]), json_mode=json_mode, sink=sink, timeout=s["request_timeout"])
                engine.fails = 0
                return _clean(text)
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
            with httpx.Client(timeout=s["request_timeout"]) as client:
                status, text = _post(client, payload, sink)
                if status == 400 and "think" in text:
                    payload.pop("think", None)  # older Ollama builds reject the flag
                    status, text = _post(client, payload, sink)
            if status == 200:
                return _clean(text)
            body = text.lower()
            last = LLMError(f"HTTP {status}: {text[:300]}")
            if status >= 500 and any(k in body for k in _MEMORY_ERRORS):
                # Fallback ladder: fewer parallel agents first, then less GPU offload.
                if not runtime.reduce_capacity() and not runtime.lower_gpu():
                    time.sleep(10)
            elif status in {400, 404}:
                if runtime.pc_down(f"Ollama rejected the request: {text[:160]}"):
                    continue
                raise LLMError(f"Ollama rejected the request: {text[:300]}")
            else:
                time.sleep(3 * (attempt + 1))
        except providers.ProviderError as exc:
            last = exc
            if exc.kind in {"refused", "bad"}:
                avoid.add(engine.id)
            runtime.setback(engine, exc)
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError) as exc:
            last = exc
            log.warning("Ollama connection problem (attempt %s): %s", attempt + 1, exc)
            runtime.release(slot, engine)
            slot = 0
            if isinstance(exc, httpx.ConnectError) and runtime.pc_down("Ollama is not running"):
                continue
            if not wait_for_ollama(settings.ollama_wait):
                break
        except httpx.TimeoutException as exc:
            last = exc
            runtime.notify(f"⚠ Model call timed out after {s['request_timeout']}s; retrying")
        finally:
            if slot:
                runtime.release(slot, engine)
    raise LLMError(f"The model request failed after retries: {last}")


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
