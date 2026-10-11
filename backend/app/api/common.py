"""Helpers shared by the route modules."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

from .. import jobs, llm, store, structure
from ..models import Project


def get(pid: str) -> Project:
    p = store.load(pid) if re.fullmatch(r"[a-z0-9]{6,32}", pid) else None
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def busy(pid: str) -> None:
    """Project-wide operations wait for every job, including Studio segment jobs."""
    name = jobs.any_running(pid)
    if name:
        raise HTTPException(409, f"RAF is busy with “{name}” for this project. Please wait for it to finish.")


def segment_free(pid: str, key: str) -> None:
    """Manual changes to one segment only wait for jobs on that segment (or a project-wide job)."""
    reason = jobs.segment_block_reason(pid, key, limit=False)
    if reason:
        raise HTTPException(409, reason)


def start_segment_job(pid: str, key: str, name: str, fn) -> None:
    reason = jobs.start_segment(pid, key, name, fn)
    if reason:
        raise HTTPException(409, reason)


def segment_or_404(p: Project, key: str):
    if key not in p.segments:
        raise HTTPException(404, "Segment not found")
    return p.segments[key]


def engine_ready() -> dict:
    """Raise 503 unless Ollama is running and the chosen model is installed."""
    health = llm.health()
    if not health["ollama"]:
        raise HTTPException(503, "Ollama is not reachable. Start it with `ollama serve`.")
    if not health["model_available"]:
        raise HTTPException(503, f"Model {health['model']} is not installed. Run `ollama pull {health['model']}`.")
    return health


def safe_name(name: str) -> str:
    stem, suffix = Path(name).stem, Path(name).suffix.lower()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:80] + suffix


def slug(text: str, fallback: str = "article") -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text)[:60].strip("_") or fallback


def view(p: Project) -> dict:
    data = p.model_dump()
    data["busy"] = jobs.running(p.id)
    data["busy_segments"] = jobs.segment_jobs(p.id)
    data["max_segment_jobs"] = jobs.MAX_SEGMENT_JOBS
    full = sum(w.fulltext for w in p.web_sources)      # how far the reading went: shown wherever integrity is reported
    data["evidence"] = {"references": sum(r.status == "parsed" for r in p.references), "online": len(p.web_sources), "online_full": full,
                        "online_abstract": len(p.web_sources) - full}
    data["structure"] = structure.describe(p)     # every segment of this article, in reading order — the interface's single source
    return data
