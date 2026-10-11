"""File-system persistence: data/projects/<id>/{project.json, uploads/, figures/, index/, exports/, datasets/, revisions/, history.jsonl}."""
from __future__ import annotations

import json
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path

from .config import settings
from .models import Project

_ROOT = settings.data_dir / "projects"
_ROOT.mkdir(parents=True, exist_ok=True)
_locks: dict[str, threading.RLock] = {}
_global = threading.Lock()
_summaries: dict[str, tuple[float, dict]] = {}   # project id -> (project.json mtime, summary); keeps the Library fast

SCHEMA_VERSION = 5
BODY = {"abstract", "introduction", "literature_review", "methodology", "results", "discussion", "conclusion", "limitations"}
MAX_BACKUP_BYTES = 2 * 1024**3


def _upgrade(data: dict) -> dict:
    """Bring a project saved by an older RAF up to the current layout. One step per schema version."""
    if data.get("schema_version", 1) < 2:        # 1.5 added schema_version and archived
        data.setdefault("archived", False)
    if data.get("schema_version", 1) < 3:        # 1.6 added the article structure: titles, custom_segments, order, excluded
        for key, empty in (("titles", {}), ("custom_segments", {}), ("order", []), ("excluded", [])):
            data.setdefault(key, empty)
    if data.get("schema_version", 1) < 4:        # 1.7 added mode ("write" | "format")
        data.setdefault("mode", "write")
    if data.get("schema_version", 1) < 5:        # 1.8 added source_mode; online sources gained oa_url, fulltext, chars, pinned (all defaulted)
        data.setdefault("source_mode", "references")
    data["schema_version"] = SCHEMA_VERSION
    return data


def lock_for(pid: str) -> threading.RLock:
    with _global:
        return _locks.setdefault(pid, threading.RLock())


def project_dir(pid: str) -> Path:
    d = _ROOT / pid
    for sub in ("uploads", "figures", "index", "exports", "datasets"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d


def save(p: Project) -> Project:
    with lock_for(p.id):
        p.updated = time.time()
        path = project_dir(p.id) / "project.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(p.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)
    return p


def load(pid: str) -> Project | None:
    path = _ROOT / pid / "project.json"
    if not path.exists():
        return None
    with lock_for(pid):
        return Project.model_validate(_upgrade(json.loads(path.read_text(encoding="utf-8"))))


def list_all() -> list[Project]:
    out = []
    for d in _ROOT.iterdir():
        if (d / "project.json").exists():
            p = load(d.name)
            if p:
                out.append(p)
    return sorted(out, key=lambda p: p.updated, reverse=True)


def summary(p: Project) -> dict:
    segs = p.segments.values()
    return {"id": p.id, "title": p.title, "stage": p.stage, "created": p.created, "updated": p.updated, "archived": p.archived,
            "article_type": p.article_type, "discipline": p.discipline, "references": len(p.references),
            "segments": len(p.segments), "approved": sum(s.status == "approved" for s in segs),
            "words": sum(s.quality.words for s in segs if s.key in BODY), "seconds": round(p.run.elapsed_before)}


def summaries() -> list[dict]:
    """One line per project for the Library. Only projects whose file changed since the last call are read again."""
    out = []
    for d in _ROOT.iterdir():
        try:
            mtime = (d / "project.json").stat().st_mtime
        except OSError:
            continue
        cached = _summaries.get(d.name)
        if not cached or cached[0] != mtime:
            p = load(d.name)
            if not p:
                continue
            cached = _summaries[d.name] = (mtime, summary(p))
        out.append(cached[1])
    return sorted(out, key=lambda s: s["updated"], reverse=True)


def delete(pid: str) -> None:
    shutil.rmtree(_ROOT / pid, ignore_errors=True)
    _summaries.pop(pid, None)


def mutate(pid: str, fn) -> Project:
    """Load → apply fn(project) → save, atomically with respect to other writers."""
    with lock_for(pid):
        p = load(pid)
        if p is None:
            raise KeyError(pid)
        fn(p)
        return save(p)


# ---------------------------------------------------------------------------- copies and backups
def _adopt(pid: str, title_suffix: str = "") -> Project:
    """Make the project.json inside folder `pid` belong to that folder: its id, no running work, an empty console."""
    path = _ROOT / pid / "project.json"
    p = Project.model_validate(_upgrade(json.loads(path.read_text(encoding="utf-8"))))
    if title_suffix:
        p.created = time.time()
    p.id, p.title, p.archived, p.log = pid, p.title + title_suffix, False, []
    if p.run.status == "running":
        p.run.status, p.run.session_started = "stopped", None
    for seg in p.segments.values():
        if seg.status in {"working", "revising"}:
            seg.status = "draft" if seg.content else "queued"
    return save(p)


def duplicate(pid: str) -> Project:
    new = uuid.uuid4().hex[:12]
    with lock_for(pid):
        shutil.copytree(_ROOT / pid, _ROOT / new, ignore=shutil.ignore_patterns("*.tmp"))
    return _adopt(new, " (copy)")


def backup(pid: str) -> Path:
    """Write the whole project folder to one .zip and return its path."""
    p = load(pid)
    if p is None:
        raise KeyError(pid)
    out_dir = settings.data_dir / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", p.title)[:50].strip("_") or "project"
    out = out_dir / f"{slug}_{pid}.raf.zip"
    base = _ROOT / pid
    with lock_for(pid), zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(base.rglob("*")):
            if f.is_file() and f.suffix != ".tmp":
                z.write(f, f.relative_to(base).as_posix())
    return out


def restore_backup(archive: Path) -> Project:
    """Create a project from a backup .zip. An id that is already in use gets a new one, so nothing is overwritten."""
    with zipfile.ZipFile(archive) as z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if "project.json" not in {i.filename for i in infos}:
            raise ValueError("This is not a RAF backup: it has no project.json.")
        if sum(i.file_size for i in infos) > MAX_BACKUP_BYTES:
            raise ValueError("The backup is larger than 2 GB when unpacked.")
        for i in infos:   # refuse anything that would be written outside the project folder
            name = i.filename.replace("\\", "/")
            if name.startswith("/") or ":" in name or ".." in name.split("/"):
                raise ValueError(f"The backup contains an unsafe path: {i.filename}")
        data = json.loads(z.read("project.json").decode("utf-8"))
        Project.model_validate(_upgrade(dict(data)))   # raises if the file is not a RAF project
        wanted = str(data.get("id", ""))
        taken = bool(re.fullmatch(r"[a-z0-9]{6,32}", wanted)) and (_ROOT / wanted).exists()
        pid = wanted if re.fullmatch(r"[a-z0-9]{6,32}", wanted) and not taken else uuid.uuid4().hex[:12]
        target = _ROOT / pid
        target.mkdir(parents=True)
        for i in infos:
            dest = target / i.filename.replace("\\", "/")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(z.read(i))
    project_dir(pid)
    return _adopt(pid, " (restored)" if taken else "")
