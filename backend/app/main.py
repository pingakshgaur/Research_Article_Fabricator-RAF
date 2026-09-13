"""RAF — Research Article Fabricator API."""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse

from . import jobs, llm, publisher, store, writer
from .blueprints import BLUEPRINTS, catalogue
from .config import settings
from .ingest import SUPPORTED
from .models import GenerateRequest, ManualEdit, Project, ProjectCreate, Reference, ReviseRequest, ToolRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = FastAPI(title="RAF — Research Article Fabricator", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"])

DATASET_TYPES = {".csv", ".tsv", ".xlsx", ".xls"}


def _get(pid: str) -> Project:
    p = store.load(pid)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def _busy(pid: str) -> None:
    if jobs.running(pid):
        raise HTTPException(409, f"RAF is busy with “{jobs.running(pid)}” for this project. Please wait for it to finish.")


def _safe_name(name: str) -> str:
    stem, suffix = Path(name).stem, Path(name).suffix.lower()
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:80] + suffix


def _view(p: Project) -> dict:
    data = p.model_dump()
    data["busy"] = jobs.running(p.id)
    return data


# ------------------------------------------------------------------ system
@app.get("/api/health")
def health():
    return {"status": "ok", **llm.health(), "limits": {"min_references": settings.min_references, "max_references": settings.max_references}}


@app.get("/api/segments")
def segments():
    return catalogue()


# ------------------------------------------------------------------ projects
@app.get("/api/projects")
def list_projects():
    return [{"id": p.id, "title": p.title, "stage": p.stage, "updated": p.updated, "references": len(p.references),
             "segments": len(p.segments), "approved": sum(s.status == "approved" for s in p.segments.values())} for p in store.list_all()]


@app.post("/api/projects")
def create_project(body: ProjectCreate):
    if len(body.title.strip()) < 5:
        raise HTTPException(422, "Please give the article a meaningful title.")
    p = Project(**body.model_dump(), stage="references")
    return _view(store.save(p))


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    return _view(_get(pid))


@app.patch("/api/projects/{pid}")
def update_project(pid: str, body: ProjectCreate):
    return _view(store.mutate(pid, lambda p: [setattr(p, k, v) for k, v in body.model_dump().items()]))


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    _busy(pid)
    store.delete(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/stage/{stage}")
def set_stage(pid: str, stage: str):
    if stage not in {"setup", "references", "segments", "processing", "studio", "published"}:
        raise HTTPException(422, "Unknown stage")
    return _view(store.mutate(pid, lambda p: setattr(p, "stage", stage)))


# ------------------------------------------------------------------ uploads
@app.post("/api/projects/{pid}/references")
async def upload_references(pid: str, files: list[UploadFile] = File(...)):
    p = _get(pid)
    _busy(pid)
    if len(p.references) + len(files) > settings.max_references:
        raise HTTPException(422, f"RAF accepts at most {settings.max_references} reference articles.")
    added = []
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in SUPPORTED:
            raise HTTPException(422, f"{f.filename}: only PDF, DOCX, Markdown and TXT references are supported.")
        name = _safe_name(f.filename or f"reference{suffix}")
        if any(r.filename == name for r in p.references):
            continue
        content = await f.read()
        if len(content) > 60 * 1024 * 1024:
            raise HTTPException(413, f"{f.filename} is larger than 60 MB.")
        (store.project_dir(pid) / "uploads" / name).write_bytes(content)
        added.append(Reference(filename=name, kind=SUPPORTED[suffix], title=Path(name).stem.replace("_", " ")))
    return _view(store.mutate(pid, lambda proj: proj.references.extend(added)))


@app.delete("/api/projects/{pid}/references/{rid}")
def delete_reference(pid: str, rid: str):
    _busy(pid)

    def rm(p: Project):
        for r in p.references:
            if r.id == rid:
                (store.project_dir(pid) / "uploads" / r.filename).unlink(missing_ok=True)
        p.references = [r for r in p.references if r.id != rid]
    return _view(store.mutate(pid, rm))


@app.post("/api/projects/{pid}/datasets")
async def upload_datasets(pid: str, files: list[UploadFile] = File(...)):
    _get(pid)
    names = []
    for f in files:
        if Path(f.filename or "").suffix.lower() not in DATASET_TYPES:
            raise HTTPException(422, "Datasets must be CSV, TSV or Excel files.")
        name = _safe_name(f.filename or "data.csv")
        (store.project_dir(pid) / "datasets" / name).write_bytes(await f.read())
        names.append(name)
    return _view(store.mutate(pid, lambda p: p.dataset_files.extend(n for n in names if n not in p.dataset_files)))


@app.delete("/api/projects/{pid}/datasets/{name}")
def delete_dataset(pid: str, name: str):
    (store.project_dir(pid) / "datasets" / _safe_name(name)).unlink(missing_ok=True)
    return _view(store.mutate(pid, lambda p: setattr(p, "dataset_files", [d for d in p.dataset_files if d != name])))


# ------------------------------------------------------------------ generation
@app.post("/api/projects/{pid}/generate")
def generate(pid: str, body: GenerateRequest):
    p = _get(pid)
    _busy(pid)
    if not body.segments or any(s not in BLUEPRINTS for s in body.segments):
        raise HTTPException(422, "Select at least one valid segment.")
    if len(p.references) < settings.min_references:
        raise HTTPException(422, f"Upload at least {settings.min_references} reference articles (currently {len(p.references)}).")
    health = llm.health()
    if not health["ollama"]:
        raise HTTPException(503, "Ollama is not reachable. Start it with `ollama serve`.")
    if not health["model_available"]:
        raise HTTPException(503, f"Model {settings.model} is not installed. Run `ollama pull {settings.model}`.")
    store.mutate(pid, lambda proj: setattr(proj, "stage", "processing"))
    jobs.start(pid, "Article generation", lambda: writer.generate_article(pid, body))
    return _view(_get(pid))


@app.get("/api/projects/{pid}/events")
async def events(pid: str):
    _get(pid)
    q = jobs.subscribe(pid)

    async def stream():
        try:
            yield jobs.sse({"kind": "hello", "busy": jobs.running(pid)})
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield jobs.sse(event)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            jobs.unsubscribe(pid, q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ studio
def _segment_or_404(p: Project, key: str):
    if key not in p.segments:
        raise HTTPException(404, "Segment not found")
    return p.segments[key]


@app.post("/api/projects/{pid}/segments/{key}/revise")
def revise(pid: str, key: str, body: ReviseRequest):
    p = _get(pid)
    _segment_or_404(p, key)
    _busy(pid)
    if len(body.instruction.strip()) < 3:
        raise HTTPException(422, "Describe the change you want.")
    jobs.start(pid, f"Revising {BLUEPRINTS[key].title}", lambda: writer.revise_segment(pid, key, body.instruction, body.selection, reason=f"revision: {body.instruction[:80]}"))
    return _view(_get(pid))


@app.post("/api/projects/{pid}/segments/{key}/tool")
def tool(pid: str, key: str, body: ToolRequest):
    p = _get(pid)
    _segment_or_404(p, key)
    _busy(pid)
    instruction = writer.TOOL_INSTRUCTIONS[body.tool]
    jobs.start(pid, f"{body.tool.replace('_', ' ').title()} · {BLUEPRINTS[key].title}", lambda: writer.revise_segment(pid, key, instruction, body.selection, reason=f"tool: {body.tool}"))
    return _view(_get(pid))


@app.post("/api/projects/{pid}/segments/{key}/regenerate")
def regenerate(pid: str, key: str):
    p = _get(pid)
    _segment_or_404(p, key)
    _busy(pid)
    jobs.start(pid, f"Regenerating {BLUEPRINTS[key].title}", lambda: writer.regenerate_segment(pid, key))
    return _view(_get(pid))


@app.put("/api/projects/{pid}/segments/{key}")
def edit(pid: str, key: str, body: ManualEdit):
    _segment_or_404(_get(pid), key)
    _busy(pid)
    return _view(writer.manual_edit(pid, key, body.content))


@app.post("/api/projects/{pid}/segments/{key}/approve")
def approve(pid: str, key: str, approved: bool = True):
    _segment_or_404(_get(pid), key)

    def apply(p: Project):
        p.segments[key].status = "approved" if approved else "draft"
    return _view(store.mutate(pid, apply))


@app.post("/api/projects/{pid}/segments/{key}/restore/{index}")
def restore(pid: str, key: str, index: int):
    seg = _segment_or_404(_get(pid), key)
    if not 0 <= index < len(seg.versions):
        raise HTTPException(404, "Version not found")
    return _view(writer.manual_edit(pid, key, seg.versions[index].content))


@app.get("/api/projects/{pid}/files/{path:path}")
def project_file(pid: str, path: str):
    base = store.project_dir(pid).resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(target)


# ------------------------------------------------------------------ publishing
@app.get("/api/projects/{pid}/export/{fmt}")
def export(pid: str, fmt: str, draft: bool = False):
    p = _get(pid)
    if not p.segments:
        raise HTTPException(422, "Nothing to publish yet.")
    pending = [s.title for s in p.segments.values() if s.status != "approved"]
    if pending and not draft:
        raise HTTPException(422, "Approve every segment before publishing: " + ", ".join(pending))
    article = publisher.assemble(p, only_approved=not draft)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", article.title)[:60].strip("_") or "article"
    out_dir = store.project_dir(pid) / "exports"
    if fmt == "docx":
        path = publisher.to_docx(article, out_dir / f"{slug}.docx")
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif fmt == "pdf":
        path = publisher.to_pdf(article, out_dir / f"{slug}.pdf")
        media = "application/pdf"
    elif fmt == "md":
        return Response(publisher.to_markdown(article), media_type="text/markdown",
                        headers={"Content-Disposition": f'attachment; filename="{slug}.md"'})
    else:
        raise HTTPException(422, "Format must be docx, pdf or md")
    if not draft:
        store.mutate(pid, lambda proj: setattr(proj, "stage", "published"))
    return FileResponse(path, media_type=media, filename=path.name)


@app.post("/api/projects/{pid}/import")
async def import_doc(pid: str, file: UploadFile = File(...)):
    p = _get(pid)
    _busy(pid)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(422, "Import a DOCX, PDF or Markdown file.")
    tmp = store.project_dir(pid) / "exports" / f"import{suffix}"
    tmp.write_bytes(await file.read())
    sections = publisher.import_document(p, tmp)
    if not sections:
        raise HTTPException(422, "No matching section headings were found in the document.")
    for key, content in sections.items():
        writer.manual_edit(pid, key, content)
    return {"updated": list(sections), "project": _view(_get(pid))}


# ------------------------------------------------------------------ static frontend (Docker single-image mode)
_static = Path(__file__).resolve().parents[1] / "static"
if _static.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_static, html=True), name="ui")
