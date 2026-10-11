"""Format an existing article: upload, checks on request, and the experimental reference restyle."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from .. import app_settings, formatter, history, store, writer
from ..config import settings
from .common import busy, get, safe_name, view

router = APIRouter(prefix="/api")
ACCEPTED = {".docx", ".md", ".markdown", ".txt", ".pdf"}


class Restyle(BaseModel):
    style: str


def _format_project(pid: str):
    p = get(pid)
    if p.mode != "format":
        raise HTTPException(422, "This is available for articles brought in with “Format an existing article”.")
    return p


@router.post("/format")
async def upload(file: UploadFile = File(...)):
    """Make a project from a finished article. Nothing in it is rewritten."""
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ACCEPTED:
        raise HTTPException(422, "Upload a DOCX, Markdown, plain-text or PDF file.")
    content = await file.read()
    if len(content) > 60 * 1024 * 1024:
        raise HTTPException(413, "The file is larger than 60 MB.")
    tmp = settings.data_dir / f"format_{uuid.uuid4().hex[:8]}{suffix}"
    tmp.write_bytes(content)
    try:
        p, found = formatter.create_project(tmp, safe_name(file.filename or f"article{suffix}"), app_settings.get()["article"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - a damaged or unusual file is the user's to replace, not a server error
        raise HTTPException(422, f"The file could not be read: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)
    (store.project_dir(p.id) / "uploads" / safe_name(file.filename or f"article{suffix}")).write_bytes(content)   # the original is kept
    history.record(p.id, "project.created", f"Article brought in for formatting — {file.filename} ({len(found['sections'])} sections, "
                   f"{found['tables']} tables, {found['figures']} figures)", file=file.filename, **{k: found[k] for k in ("tables", "figures", "references")})
    return {"project": view(p), "found": found}


@router.get("/projects/{pid}/format/checks")
def run_checks(pid: str):
    return formatter.checks(_format_project(pid))


@router.post("/projects/{pid}/format/restyle")
def restyle(pid: str, body: Restyle):
    """Experimental: re-format the reference list in another author–date style, entry by entry, from Crossref."""
    p = _format_project(pid)
    busy(pid)
    try:
        out = formatter.restyle_references(p, body.style)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if out["restyled"]:
        writer.manual_edit(pid, "references", out["content"], reason=f"restored: reference list restyled to {body.style}")
        store.mutate(pid, lambda proj: setattr(proj, "citation_style", body.style))
        history.record(pid, "article.references_restyled", f"Reference list restyled to {body.style} — {out['restyled']} of {out['total']} entries", style=body.style)
    return {"restyled": out["restyled"], "unchanged": out["unchanged"], "total": out["total"], "project": view(get(pid))}
