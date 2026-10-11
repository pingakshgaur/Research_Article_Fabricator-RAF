"""Settings: RAF itself (appearance, defaults for new articles, admin lock) and the local language model."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from .. import app_settings, llm, llm_settings, providers, store, vault
from ..config import settings

router = APIRouter(prefix="/api")


def admin(x_raf_admin: str | None = Header(default=None)) -> str | None:
    """Dependency for every route that changes settings: passes when no passcode is set or the session is unlocked."""
    if not app_settings.allowed(x_raf_admin):
        raise HTTPException(401, "Settings are locked. Enter the admin passcode in Settings to change them.")
    return x_raf_admin


# ------------------------------------------------------------------ RAF settings
@router.get("/settings/app")
def get_app_settings(x_raf_admin: str | None = Header(default=None)):
    from ..main import API_VERSION   # imported here: main imports this module

    return {"settings": app_settings.get(), "defaults": app_settings.DEFAULTS,
            "palettes": [{"key": k, "name": v} for k, v in app_settings.PALETTES.items()],
            "locked": app_settings.locked(), "unlocked": app_settings.allowed(x_raf_admin),
            "info": {"version": API_VERSION, "data_dir": str(settings.data_dir), "projects": len(store.summaries()), "model": llm_settings.get()["model"]}}


@router.put("/settings/app", dependencies=[Depends(admin)])
def put_app_settings(patch: dict):
    try:
        return {"settings": app_settings.update(patch)}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/settings/app", dependencies=[Depends(admin)])
def reset_app_settings():
    return {"settings": app_settings.reset()}


# ------------------------------------------------------------------ admin lock
class Passcode(BaseModel):
    passcode: str = ""


@router.post("/settings/admin/unlock")
def unlock(body: Passcode):
    try:
        return {"token": app_settings.unlock(body.passcode)}
    except TimeoutError as exc:
        raise HTTPException(429, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(401, str(exc)) from exc


@router.post("/settings/admin/lock")
def relock(x_raf_admin: str | None = Header(default=None)):
    app_settings.relock(x_raf_admin)
    return {"ok": True}


@router.put("/settings/admin/passcode", dependencies=[Depends(admin)])
def set_passcode(body: Passcode):
    """Set or change the passcode; an empty one removes the lock. Returns a fresh session token when a passcode is set."""
    try:
        app_settings.set_passcode(body.passcode)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"locked": bool(body.passcode), "token": app_settings.unlock(body.passcode) if body.passcode else ""}


# ------------------------------------------------------------------ language model (formerly "Developer Tools")
@router.get("/settings/llm")
def get_llm_settings():
    return {"settings": llm_settings.get(), "defaults": llm_settings.DEFAULTS, "presets": llm_settings.PRESETS,
            "spec": {k: {"type": t, "min": lo, "max": hi} for k, (t, lo, hi) in llm_settings.SPEC.items()},
            "ollama": llm_settings.ollama_state(), "gpu_fallback": llm.runtime.gpu_override}


@router.put("/settings/llm", dependencies=[Depends(admin)])
def put_llm_settings(patch: dict):
    try:
        saved = llm_settings.update(patch)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if "num_gpu" in patch:
        llm.runtime.gpu_override = None      # an explicit choice replaces any automatic out-of-memory fallback
    return {"settings": saved}


@router.delete("/settings/llm", dependencies=[Depends(admin)])
def reset_llm_settings():
    llm.runtime.gpu_override = None
    return {"settings": llm_settings.reset()}


@router.post("/settings/llm/benchmark")
def benchmark_llm():
    try:
        return llm_settings.benchmark()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(503, f"Benchmark failed: {exc}") from exc


# ------------------------------------------------------------------ cloud models: the user's own API keys
class NewKey(BaseModel):
    key: str
    provider: str = ""          # empty: told from how the key starts
    label: str = ""
    model: str = ""
    base_url: str = ""
    parallel: int = 2
    role: str = "all"


def _keys() -> dict:
    return {"keys": providers.list_keys(), "mode": providers.mode(), "modes": providers.MODES, "roles": providers.ROLES, "providers": providers.catalog(),
            "protection": vault.METHOD, "max_parallel": providers.MAX_PARALLEL, "max_agents": llm.MAX_AGENTS}


def _key_call(fn, *args):
    try:
        return fn(*args)
    except KeyError:
        raise HTTPException(404, "Key not found") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except providers.ProviderError as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get("/settings/llm/keys")
def get_keys():
    """The saved keys without their secrets (only the last four characters), and what RAF knows about each provider."""
    return _keys()


@router.post("/settings/llm/keys", dependencies=[Depends(admin)])
def add_key(body: NewKey):
    _key_call(providers.add_key, body.model_dump())
    return _keys()


@router.patch("/settings/llm/keys/{kid}", dependencies=[Depends(admin)])
def change_key(kid: str, patch: dict):
    _key_call(providers.update_key, kid, patch)
    return _keys()


@router.delete("/settings/llm/keys/{kid}", dependencies=[Depends(admin)])
def delete_key(kid: str):
    _key_call(providers.remove_key, kid)
    return _keys()


@router.put("/settings/llm/keys-order", dependencies=[Depends(admin)])
def order_keys(body: dict):
    providers.reorder([str(i) for i in body.get("order", [])])
    return _keys()


@router.put("/settings/llm/mode", dependencies=[Depends(admin)])
def set_mode(mode: str):
    _key_call(providers.set_mode, mode)
    return _keys()


@router.post("/settings/llm/keys/{kid}/test", dependencies=[Depends(admin)])
def test_key(kid: str):
    """One very small real request through the key (a few tokens)."""
    return {"result": _key_call(providers.test, kid), **_keys()}


@router.get("/settings/llm/keys/{kid}/models", dependencies=[Depends(admin)])
def key_models(kid: str):
    return {"models": _key_call(providers.models, kid)}
