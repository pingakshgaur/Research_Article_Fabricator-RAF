"""Library actions on whole projects: rename, duplicate, archive, back up to a .zip and restore from one."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import history, store
from ..config import settings
from .common import busy, get, view

router = APIRouter(prefix="/api")


class Rename(BaseModel):
    title: str


@router.post("/projects/{pid}/rename")
def rename(pid: str, body: Rename):
    old = get(pid).title
    title = body.title.strip()
    if len(title) < 5:
        raise HTTPException(422, "Please give the article a meaningful title.")
    p = store.mutate(pid, lambda proj: setattr(proj, "title", title))
    if old != title:
        history.record(pid, "project.updated", f"Project renamed — “{title}”", changes={"title": [old, title]})
    return view(p)


@router.post("/projects/{pid}/duplicate")
def duplicate(pid: str):
    source = get(pid)
    busy(pid)
    history.read(pid)   # makes sure the source has its history file, so the copy inherits the article's past
    p = store.duplicate(pid)
    history.record(p.id, "project.created", f"Project created as a copy of “{source.title}”", copied_from=pid)
    history.record(pid, "project.duplicated", f"Project duplicated — “{p.title}”", copy=p.id)
    return view(p)


@router.post("/projects/{pid}/archive")
def archive(pid: str, archived: bool = True):
    get(pid)
    p = store.mutate(pid, lambda proj: setattr(proj, "archived", archived))
    history.record(pid, "project.archived" if archived else "project.unarchived", "Project archived" if archived else "Project taken out of the archive")
    return view(p)


@router.get("/projects/{pid}/backup")
def backup(pid: str):
    get(pid)
    busy(pid)
    history.record(pid, "project.backed_up", "Backup made")   # recorded first, so the backup contains its own entry
    path = store.backup(pid)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.post("/projects/restore")
async def restore(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(422, "Choose a RAF backup (.zip) file.")
    tmp_dir = settings.data_dir / "backups"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = tmp_dir / f"upload_{uuid.uuid4().hex[:8]}.zip"
    try:
        with open(tmp, "wb") as fh:
            while chunk := await file.read(1024 * 1024):
                fh.write(chunk)
        p = store.restore_backup(tmp)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - a wrong or damaged file is the user's to fix, not a server error
        raise HTTPException(422, f"The backup could not be restored: {exc}") from exc
    finally:
        tmp.unlink(missing_ok=True)
    history.record(p.id, "project.restored", f"Project restored from the backup {file.filename}")
    return view(p)
