"""The Studio: revise, text tools, regenerate, manual edits, approval and segment versions."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import history, store, structure, writer
from ..models import ManualEdit, Project, ReviseRequest, Segment, ToolRequest
from .common import get, segment_free, segment_or_404, start_segment_job, view

router = APIRouter(prefix="/api")


@router.post("/projects/{pid}/segments/{key}/revise")
def revise(pid: str, key: str, body: ReviseRequest):
    p = get(pid)
    seg = segment_or_404(p, key)
    if len(body.instruction.strip()) < 3:
        raise HTTPException(422, "Describe the change you want.")
    start_segment_job(pid, key, f"Revising {seg.title}",
                      lambda: writer.revise_segment(pid, key, body.instruction, body.selection, reason=f"revision: {body.instruction[:80]}"))
    return view(get(pid))


@router.post("/projects/{pid}/segments/{key}/tool")
def tool(pid: str, key: str, body: ToolRequest):
    p = get(pid)
    seg = segment_or_404(p, key)
    label = f"{body.tool.replace('_', ' ').title()} · {seg.title}"
    if body.tool == "humanize":
        start_segment_job(pid, key, label, lambda: writer.humanize_segment(pid, key, body.selection))
    else:
        instruction = writer.TOOL_INSTRUCTIONS[body.tool]
        start_segment_job(pid, key, label, lambda: writer.revise_segment(pid, key, instruction, body.selection, reason=f"tool: {body.tool}"))
    return view(get(pid))


@router.post("/projects/{pid}/segments/{key}/regenerate")
def regenerate(pid: str, key: str):
    p = get(pid)
    seg = segment_or_404(p, key)
    if structure.blueprint_for(p, key).special == "manual":
        raise HTTPException(422, "This segment is written by you; RAF does not generate it.")
    start_segment_job(pid, key, f"Regenerating {seg.title}", lambda: writer.regenerate_segment(pid, key))
    history.record(pid, "segment.regenerate", f"You asked RAF to rewrite {seg.title} from scratch", segment=key)
    return view(get(pid))


@router.put("/projects/{pid}/segments/{key}")
def edit(pid: str, key: str, body: ManualEdit):
    p = get(pid)
    segment_free(pid, key)
    if key not in p.segments:
        if key not in {"title", "keywords", "abstract"}:
            raise HTTPException(404, "Segment not found")
        # Front matter can be written by hand even when RAF did not generate it.
        def add(proj: Project):
            proj.segments[key] = Segment(key=key, title=structure.title_of(proj, key), status="draft")
        store.mutate(pid, add)
    return view(writer.manual_edit(pid, key, body.content))


@router.post("/projects/{pid}/segments/{key}/approve")
def approve(pid: str, key: str, approved: bool = True):
    seg = segment_or_404(get(pid), key)
    segment_free(pid, key)

    def apply(p: Project):
        p.segments[key].status = "approved" if approved else "draft"
    p = store.mutate(pid, apply)
    if (seg.status == "approved") != approved:
        history.record(pid, "segment.approved" if approved else "segment.unapproved",
                       f"{seg.title} approved" if approved else f"Approval of {seg.title} withdrawn", segment=key, words=seg.quality.words)
    return view(p)


@router.post("/projects/{pid}/segments/{key}/restore/{index}")
def restore(pid: str, key: str, index: int):
    seg = segment_or_404(get(pid), key)
    segment_free(pid, key)
    if not 0 <= index < len(seg.versions):
        raise HTTPException(404, "Version not found")
    return view(writer.manual_edit(pid, key, seg.versions[index].content, reason=f"restored to version {index + 1}"))


@router.get("/projects/{pid}/files/{path:path}")
def project_file(pid: str, path: str):
    get(pid)
    base = store.project_dir(pid).resolve()
    target = (base / path).resolve()
    if base not in target.parents or not target.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(target)
