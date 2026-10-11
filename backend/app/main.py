"""RAF — Research Article Fabricator API. The routes live in app/api/, one module per area."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import llm, writer
from .config import settings

# Bump whenever the backend changes in a way the UI depends on; the UI warns when the running server is older.
API_VERSION = "1.7.0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = FastAPI(title="RAF — Research Article Fabricator", version=API_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _recover() -> None:
    writer.recover_interrupted_runs()


@app.get("/api/health")
def health():
    return {"status": "ok", "api_version": API_VERSION, **llm.health(),
            "limits": {"min_references": settings.min_references, "max_references": settings.max_references}}


from .api import ROUTERS  # noqa: E402 - the route modules import this module's siblings, so they load after the app exists

for _router in ROUTERS:
    app.include_router(_router)

# ------------------------------------------------------------------ static frontend (Docker single-image mode)
_static = Path(__file__).resolve().parents[1] / "static"
if _static.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_static, html=True), name="ui")
