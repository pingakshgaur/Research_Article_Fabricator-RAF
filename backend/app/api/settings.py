"""Settings: RAF itself (appearance, defaults for new articles, admin lock) and the local language model."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from .. import app_settings, llm, llm_settings, store
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
