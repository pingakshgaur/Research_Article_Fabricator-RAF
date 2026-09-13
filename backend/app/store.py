"""File-system persistence: data/projects/<id>/{project.json, uploads/, figures/, index/, exports/}."""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

from .config import settings
from .models import Project

_ROOT = settings.data_dir / "projects"
_ROOT.mkdir(parents=True, exist_ok=True)
_locks: dict[str, threading.RLock] = {}
_global = threading.Lock()


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
        return Project.model_validate(json.loads(path.read_text(encoding="utf-8")))


def list_all() -> list[Project]:
    out = []
    for d in _ROOT.iterdir():
        if (d / "project.json").exists():
            p = load(d.name)
            if p:
                out.append(p)
    return sorted(out, key=lambda p: p.updated, reverse=True)


def delete(pid: str) -> None:
    shutil.rmtree(_ROOT / pid, ignore_errors=True)


def mutate(pid: str, fn) -> Project:
    """Load → apply fn(project) → save, atomically with respect to other writers."""
    with lock_for(pid):
        p = load(pid)
        if p is None:
            raise KeyError(pid)
        fn(p)
        return save(p)
