"""Starting and following a fabrication run, and the whole-article review."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from .. import jobs, live, llm, store, structure, writer
from ..config import settings
from ..models import GenerateRequest
from .common import busy, engine_ready, get, view

router = APIRouter(prefix="/api")


@router.post("/projects/{pid}/generate")
def generate(pid: str, body: GenerateRequest):
    p = get(pid)
    busy(pid)
    if not body.segments or any(not structure.exists(p, s) for s in body.segments):
        raise HTTPException(422, "Select at least one valid segment.")
    need = {"references": settings.min_references, "mixed": 1, "research": 0}[p.source_mode]
    if len(p.references) < need:
        raise HTTPException(422, f"Upload at least {need} reference article{'s' if need != 1 else ''} (currently {len(p.references)}), or choose another source mode on the References page.")
    if p.source_mode == "research" and not body.web_research:
        raise HTTPException(422, "A Research-only article needs Online research switched on: it has no other sources.")
    engine_ready()
    store.mutate(pid, lambda proj: setattr(proj, "stage", "processing"))
    jobs.start(pid, "Article generation", lambda: writer.generate_article(pid, body))
    return view(get(pid))


@router.get("/projects/{pid}/events")
async def events(pid: str):
    get(pid)
    q = jobs.subscribe(pid)

    async def stream():
        try:
            yield jobs.sse({"kind": "hello", "busy": jobs.running(pid), "sheets": live.snapshot(pid)})   # the Window as it is right now
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield jobs.sse(event)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            jobs.unsubscribe(pid, q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/projects/{pid}/review")
def run_review(pid: str):
    """Re-run the article-level consistency review on demand (issues are reported, not auto-applied)."""
    p = get(pid)
    busy(pid)
    keys = [k for k, s in p.segments.items() if s.content]

    def job():
        ws = writer.Workspace(pid)
        llm.runtime.notify = ws.log
        store.mutate(pid, lambda proj: setattr(proj, "review", {}))
        writer.review_and_fix(ws, keys, apply_fixes=False)
    jobs.start(pid, "Article review", job)
    return view(get(pid))
