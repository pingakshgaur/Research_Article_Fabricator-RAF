"""The project's record: History, Article Revisions (save, compare, restore) and revision rounds."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import history, jobs, revisions, rounds, store
from .common import busy, engine_ready, get, slug, view

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ history
@router.get("/projects/{pid}/history")
def get_history(pid: str):
    get(pid)
    return history.read(pid)


@router.get("/projects/{pid}/ai-statement")
def ai_statement(pid: str):
    return history.ai_statement(get(pid))


# ------------------------------------------------------------------ revisions
class RevisionBody(BaseModel):
    name: str = ""
    note: str = ""


def _revision(pid: str, n: int) -> dict:
    try:
        return revisions.get(pid, n)
    except KeyError:
        raise HTTPException(404, "Revision not found") from None


def _side(value: str) -> str | int:
    if value == "current":
        return value
    if not value.isdigit():
        raise HTTPException(422, "Compare a revision number or “current”.")
    return int(value)


@router.get("/projects/{pid}/revisions")
def list_revisions(pid: str):
    get(pid)
    return revisions.list_(pid)


@router.post("/projects/{pid}/revisions")
def save_revision(pid: str, body: RevisionBody):
    get(pid)
    busy(pid)
    rev = revisions.snapshot(pid, body.name, note=body.note)
    if rev is None:
        raise HTTPException(422, "There is nothing to save yet: no segment has any text.")
    return rev


@router.patch("/projects/{pid}/revisions/{n}")
def rename_revision(pid: str, n: int, body: RevisionBody):
    get(pid)
    _revision(pid, n)
    return revisions.rename(pid, n, body.name, body.note)


@router.delete("/projects/{pid}/revisions/{n}")
def delete_revision(pid: str, n: int):
    get(pid)
    _revision(pid, n)
    revisions.delete(pid, n)
    return {"ok": True}


@router.post("/projects/{pid}/revisions/{n}/restore")
def restore_revision(pid: str, n: int, key: str | None = None):
    get(pid)
    busy(pid)
    rev = _revision(pid, n)
    if key and key not in rev["segments"]:
        raise HTTPException(404, "That segment is not part of this revision.")
    return view(revisions.restore(pid, n, key))


@router.get("/projects/{pid}/compare")
def compare(pid: str, a: str, b: str = "current"):
    get(pid)
    try:
        return revisions.compare(pid, _side(a), _side(b))
    except KeyError:
        raise HTTPException(404, "Revision not found") from None


@router.get("/projects/{pid}/compare/export/{fmt}")
def export_changes(pid: str, fmt: str, a: str, b: str = "current"):
    p = get(pid)
    if fmt not in {"docx", "pdf"}:
        raise HTTPException(422, "Format must be docx or pdf")
    out = store.project_dir(pid) / "exports" / f"{slug(p.title)}_changes.{fmt}"
    try:
        revisions.export_changes(pid, _side(a), _side(b), fmt, out)
    except KeyError:
        raise HTTPException(404, "Revision not found") from None
    history.record(pid, "article.changes_exported", f"Changes-highlighted {fmt.upper()} exported", a=a, b=b)
    return FileResponse(out, filename=out.name)


# ------------------------------------------------------------------ revision rounds
class RoundCreate(BaseModel):
    comments: str
    name: str = ""


class RoundUpdate(BaseModel):
    name: str | None = None
    points: list[dict] | None = None
    letter: str | None = None


def _round(pid: str, rid: str) -> dict:
    try:
        return rounds.get(pid, rid)
    except KeyError:
        raise HTTPException(404, "Revision round not found") from None


@router.get("/projects/{pid}/rounds")
def list_rounds(pid: str):
    get(pid)
    return rounds.list_(pid)


@router.post("/projects/{pid}/rounds")
def create_round(pid: str, body: RoundCreate):
    p = get(pid)
    busy(pid)
    if len(body.comments.split()) < 5:
        raise HTTPException(422, "Paste the comments you received.")
    if not rounds.editable(p):
        raise HTTPException(422, "There is no written segment to revise yet.")
    rnd = rounds.create(pid, body.comments, body.name)
    if not jobs.start(pid, "Reading the comments", lambda: rounds.analyse(pid, rnd["id"])):
        raise HTTPException(409, "RAF is busy with this project. Please wait for it to finish.")
    return rnd


@router.get("/projects/{pid}/rounds/{rid}")
def get_round(pid: str, rid: str):
    get(pid)
    return _round(pid, rid)


@router.put("/projects/{pid}/rounds/{rid}")
def update_round(pid: str, rid: str, body: RoundUpdate):
    p = get(pid)
    rnd = _round(pid, rid)
    if body.name is not None:
        rnd["name"] = body.name.strip()[:80] or rnd["name"]
    if body.letter is not None:
        rnd["letter"] = body.letter
    if body.points is not None:
        if rnd["status"] != "ready":
            raise HTTPException(409, "The points of this round can no longer be changed.")
        allowed = set(rounds.editable(p))
        points = []
        for i, pt in enumerate(body.points, 1):
            comment, instruction = str(pt.get("comment", "")).strip(), str(pt.get("instruction", "")).strip()
            if not comment or pt.get("segment") not in allowed:
                continue
            points.append({"n": i, "comment": comment[:900], "segment": pt["segment"], "instruction": (instruction or comment)[:600],
                           "decision": "skip" if pt.get("decision") == "skip" else "accept", "state": "", "response": "", "change": ""})
        rnd["points"] = points
    return rounds.save(pid, rnd)


@router.post("/projects/{pid}/rounds/{rid}/apply")
def apply_round(pid: str, rid: str):
    get(pid)
    busy(pid)
    rnd = _round(pid, rid)
    if rnd["status"] != "ready":
        raise HTTPException(409, "This round has already been applied." if rnd["status"] == "done" else "This round is not ready yet.")
    if not any(pt["decision"] == "accept" for pt in rnd["points"]):
        raise HTTPException(422, "Accept at least one point to apply.")
    engine_ready()
    if not jobs.start(pid, f"Revision round · {rnd['name']}", lambda: rounds.apply(pid, rid)):
        raise HTTPException(409, "RAF is busy with this project. Please wait for it to finish.")
    return rnd


@router.delete("/projects/{pid}/rounds/{rid}")
def delete_round(pid: str, rid: str):
    get(pid)
    busy(pid)
    _round(pid, rid)
    rounds.delete(pid, rid)
    return {"ok": True}


@router.get("/projects/{pid}/rounds/{rid}/letter.docx")
def letter_docx(pid: str, rid: str):
    p = get(pid)
    rnd = _round(pid, rid)
    if not rnd["letter"].strip():
        raise HTTPException(422, "This round has no response letter yet.")
    out = store.project_dir(pid) / "exports" / f"{slug(p.title)}_response_{slug(rnd['name'], 'round')}.docx"
    return FileResponse(rounds.letter_docx(rnd["letter"], out), filename=out.name)
