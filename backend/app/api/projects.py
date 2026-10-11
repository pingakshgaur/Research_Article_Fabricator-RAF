"""Projects: catalogue, create / read / update / delete, uploads and per-project settings."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from .. import app_settings, history, jobs, publisher, store, structure, writer
from ..blueprints import BLUEPRINTS, TONES, catalogue, length_profile
from ..config import settings
from ..ingest import SUPPORTED
from ..models import LengthsUpdate, Project, ProjectCreate, PublishStyle, Reference, ToneUpdate
from .common import busy, get, safe_name, view

router = APIRouter(prefix="/api")
DATASET_TYPES = {".csv", ".tsv", ".xlsx", ".xls"}
STAGES = {"setup": "Topic & title", "references": "References", "segments": "Segments", "processing": "Fabrication", "studio": "Studio", "published": "Publish"}
FIELD_NAMES = {"title": "title", "topic": "topic", "discipline": "discipline", "article_type": "article type", "citation_style": "citation style",
               "target_words": "target length", "authors": "authors", "affiliation": "affiliation"}


# ------------------------------------------------------------------ catalogue
@router.get("/segments")
def segments():
    out = []
    for item in catalogue():
        bp = BLUEPRINTS[item["key"]]
        lo, hi = writer.LENGTH_LIMITS.get(bp.key, writer.DEFAULT_LIMITS)
        item["word_share"] = bp.word_share
        item["lengthable"] = bp.word_share > 0 or bp.key == "abstract"
        item["min_words"], item["max_words"] = lo, hi
        out.append(item)
    return out


@router.get("/tones")
def tones():
    return [{"key": k, "label": v["label"], "summary": v["summary"], "levels": list(v["levels"])} for k, v in TONES.items()]


@router.get("/length-profile")
def get_length_profile(article_type: str = "Empirical research article", target_words: int = 6000):
    return length_profile(article_type, max(1000, min(40000, target_words)))


# ------------------------------------------------------------------ projects
@router.get("/projects")
def list_projects():
    return store.summaries()


@router.post("/projects")
def create_project(body: ProjectCreate):
    if len(body.title.strip()) < 5:
        raise HTTPException(422, "Please give the article a meaningful title.")
    defaults = app_settings.get()   # a new article starts with the run options and tone chosen in Settings
    p = store.save(Project(**body.model_dump(), stage="references", options=dict(defaults["run"]), tone=dict(defaults["tone"])))
    history.record(p.id, "project.created", f"Project created — “{p.title}”", article_type=p.article_type, citation_style=p.citation_style)
    return view(p)


@router.get("/projects/{pid}")
def get_project(pid: str):
    return view(get(pid))


@router.patch("/projects/{pid}")
def update_project(pid: str, body: ProjectCreate):
    old = get(pid)
    new = body.model_dump()
    changed = [k for k, v in new.items() if getattr(old, k) != v]
    p = store.mutate(pid, lambda proj: [setattr(proj, k, v) for k, v in new.items()])
    if changed:
        history.record(pid, "project.updated", "Article details changed — " + ", ".join(FIELD_NAMES[k] for k in changed),
                       changes={k: [getattr(old, k), new[k]] for k in changed})
    return view(p)


@router.delete("/projects/{pid}")
def delete_project(pid: str):
    busy(pid)
    store.delete(pid)
    return {"ok": True}


@router.post("/projects/{pid}/stage/{stage}")
def set_stage(pid: str, stage: str):
    if stage not in STAGES:
        raise HTTPException(422, "Unknown stage")
    old = get(pid).stage
    p = store.mutate(pid, lambda proj: setattr(proj, "stage", stage))
    if old != stage:
        history.record(pid, "stage.changed", f"Moved to {STAGES[stage]}", stage=stage, previous=old)
    return view(p)


# ------------------------------------------------------------------ uploads
@router.post("/projects/{pid}/references")
async def upload_references(pid: str, files: list[UploadFile] = File(...)):
    p = get(pid)
    busy(pid)
    if len(p.references) + len(files) > settings.max_references:
        raise HTTPException(422, f"RAF accepts at most {settings.max_references} reference articles.")
    added = []
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in SUPPORTED:
            raise HTTPException(422, f"{f.filename}: only PDF, DOCX, Markdown and TXT references are supported.")
        name = safe_name(f.filename or f"reference{suffix}")
        if any(r.filename == name for r in p.references):
            continue
        content = await f.read()
        if len(content) > 60 * 1024 * 1024:
            raise HTTPException(413, f"{f.filename} is larger than 60 MB.")
        (store.project_dir(pid) / "uploads" / name).write_bytes(content)
        added.append(Reference(filename=name, kind=SUPPORTED[suffix], title=Path(name).stem.replace("_", " ")))
    p = store.mutate(pid, lambda proj: proj.references.extend(added))
    if added:
        history.record(pid, "references.added", f"{len(added)} reference{'s' if len(added) != 1 else ''} added ({len(p.references)} in total)",
                       files=[r.filename for r in added])
    return view(p)


@router.delete("/projects/{pid}/references/{rid}")
def delete_reference(pid: str, rid: str):
    busy(pid)
    gone = [r for r in get(pid).references if r.id == rid]

    def rm(p: Project):
        for r in p.references:
            if r.id == rid:
                (store.project_dir(pid) / "uploads" / r.filename).unlink(missing_ok=True)
        p.references = [r for r in p.references if r.id != rid]
    p = store.mutate(pid, rm)
    if gone:
        history.record(pid, "references.removed", f"Reference removed — {gone[0].title or gone[0].filename}", files=[gone[0].filename])
    return view(p)


@router.post("/projects/{pid}/datasets")
async def upload_datasets(pid: str, files: list[UploadFile] = File(...)):
    get(pid)
    names = []
    for f in files:
        if Path(f.filename or "").suffix.lower() not in DATASET_TYPES:
            raise HTTPException(422, "Datasets must be CSV, TSV or Excel files.")
        name = safe_name(f.filename or "data.csv")
        (store.project_dir(pid) / "datasets" / name).write_bytes(await f.read())
        names.append(name)
    p = store.mutate(pid, lambda proj: proj.dataset_files.extend(n for n in names if n not in proj.dataset_files))
    history.record(pid, "datasets.added", f"Dataset added — {', '.join(names)}", files=names)
    return view(p)


@router.delete("/projects/{pid}/datasets/{name}")
def delete_dataset(pid: str, name: str):
    (store.project_dir(pid) / "datasets" / safe_name(name)).unlink(missing_ok=True)
    p = store.mutate(pid, lambda proj: setattr(proj, "dataset_files", [d for d in proj.dataset_files if d != name]))
    history.record(pid, "datasets.removed", f"Dataset removed — {name}", files=[name])
    return view(p)


# ------------------------------------------------------------------ where the evidence comes from
@router.put("/projects/{pid}/source-mode")
def set_source_mode(pid: str, mode: str):
    old = get(pid).source_mode
    if mode not in {"references", "mixed", "research"}:
        raise HTTPException(422, "Unknown source mode.")
    busy(pid)
    p = store.mutate(pid, lambda proj: setattr(proj, "source_mode", mode))
    if old != mode:
        names = {"references": "My references", "mixed": "Mixed", "research": "Research only"}
        history.record(pid, "settings.changed", f"Sources: {names[mode]}", source_mode=mode, previous=old)
    return view(p)


@router.delete("/projects/{pid}/sources/{sid}")
def remove_source(pid: str, sid: str):
    """Take an online source off the reading list (before writing: it changes how sources are numbered)."""
    gone = [w for w in get(pid).web_sources if w.id == sid]
    if not gone:
        raise HTTPException(404, "Source not found")
    busy(pid)
    p = store.mutate(pid, lambda proj: setattr(proj, "web_sources", [w for w in proj.web_sources if w.id != sid]))
    (store.project_dir(pid) / "index" / f"web_{sid}.txt").unlink(missing_ok=True)
    history.record(pid, "sources.removed", f"Online source removed from the reading list — {gone[0].title[:120]}")
    return view(p)


@router.put("/projects/{pid}/sources/{sid}/pin")
def pin_source(pid: str, sid: str, pinned: bool = True):
    p = get(pid)
    if not any(w.id == sid for w in p.web_sources):
        raise HTTPException(404, "Source not found")

    def apply(proj: Project):
        for w in proj.web_sources:
            if w.id == sid:
                w.pinned = pinned
    return view(store.mutate(pid, apply))


# ------------------------------------------------------------------ per-project settings
@router.put("/projects/{pid}/lengths")
def set_lengths(pid: str, body: LengthsUpdate):
    """Word targets per segment. Applies to segments that have not started yet (even during a run)."""
    p = get(pid)
    locked = {k for k, s in p.segments.items() if s.status in {"working", "draft", "approved", "revising"} and jobs.running(pid)}
    changed = {}

    def apply(proj: Project):
        for key, words in body.lengths.items():
            if structure.exists(proj, key) and key not in locked:
                value = writer.clamp_length(key, words)
                if proj.segment_lengths.get(key) != value:
                    changed[key] = value
                proj.segment_lengths[key] = value
    p = store.mutate(pid, apply)
    if changed:
        history.record(pid, "settings.changed", "Length changed — " + ", ".join(f"{structure.title_of(p, k)} {v} words" for k, v in changed.items()), lengths=changed)
    return view(p)


@router.put("/projects/{pid}/tone")
def set_tone(pid: str, body: ToneUpdate):
    old = get(pid).tone
    p = store.mutate(pid, lambda proj: setattr(proj, "tone", body.model_dump()))
    if old != p.tone:
        history.record(pid, "settings.changed", f"Tone set to {TONES[body.name]['label']} · intensity {body.intensity}", tone=p.tone)
    return view(p)


@router.put("/projects/{pid}/publish-style")
def set_publish_style(pid: str, body: PublishStyle):
    old = get(pid).publish_style
    if body.template not in publisher.TEMPLATES or body.palette not in publisher.PALETTES:
        raise HTTPException(422, "Unknown template or colour style.")
    p = store.mutate(pid, lambda proj: setattr(proj, "publish_style", body.model_dump()))
    if old != p.publish_style:
        history.record(pid, "settings.changed", f"Layout set to {publisher.TEMPLATES[body.template].name} · {publisher.PALETTES[body.palette]['name']}", style=p.publish_style)
    return view(p)
