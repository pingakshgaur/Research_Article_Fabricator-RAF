"""The structure of an article: rename segments, add your own, arrange them, leave them out, write one later."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import history, llm, store, structure, writer
from ..models import Project, Segment, Version
from .common import busy, engine_ready, get, segment_free, start_segment_job, view

router = APIRouter(prefix="/api")


class Title(BaseModel):
    title: str = ""


class NewSegment(BaseModel):
    title: str = ""
    purpose: str = ""
    kind: str = "generated"
    after: str = ""                  # key of the segment it follows; empty = just before the references
    words: int = 400
    cites: bool = True
    numbered: bool | None = None
    moves: list[dict] = []
    gallery: str = ""                # id of a ready-made segment from the gallery; fills whatever is left empty


class SegmentPatch(BaseModel):
    purpose: str | None = None
    words: int | None = None
    cites: bool | None = None
    numbered: bool | None = None
    moves: list[dict] | None = None


class Order(BaseModel):
    order: list[str] = Field(max_length=60)


class Proposal(BaseModel):
    title: str
    purpose: str


def _mutate(pid: str, fn) -> Project:
    """Apply a structure change; a rule it breaks (ValueError) or an unknown segment (KeyError) becomes a clear HTTP error."""
    try:
        return store.mutate(pid, fn)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except KeyError:
        raise HTTPException(404, "Segment not found") from None


@router.get("/structure/gallery")
def gallery():
    return structure.GALLERY


@router.put("/projects/{pid}/structure/titles/{key}")
def rename(pid: str, key: str, body: Title):
    p = get(pid)
    if not structure.exists(p, key):
        raise HTTPException(404, "Segment not found")
    old = structure.title_of(p, key)
    p = _mutate(pid, lambda proj: structure.rename(proj, key, body.title))
    new = structure.title_of(p, key)
    if new != old:
        history.record(pid, "structure.renamed", f"Segment renamed — “{old}” is now “{new}”", segment=key, previous=old, title=new)
    return view(p)


@router.post("/projects/{pid}/structure/segments")
def add_segment(pid: str, body: NewSegment):
    p = get(pid)
    busy(pid)
    preset = next((g for g in structure.GALLERY if g["id"] == body.gallery), {}) if body.gallery else {}
    if body.gallery and not preset:
        raise HTTPException(422, "Unknown gallery segment.")
    kind = preset.get("kind", body.kind)
    starter = preset.get("starter", "")
    if preset.get("id") == "ai_use":
        starter = history.ai_statement(p)["statement"] or "During the preparation of this work the author(s) used … to …. The author(s) reviewed and edited the output and take(s) full responsibility for the content."
    made = {}

    def apply(proj: Project):
        key = structure.add_custom(proj, title=body.title or preset.get("title", ""), purpose=body.purpose or preset.get("purpose", ""), kind=kind,
                                   after=body.after or preset.get("after", ""), words=body.words if body.words != 400 or not preset else preset.get("words", 400),
                                   cites_sources=body.cites, numbered_=body.numbered, moves=body.moves)
        made["key"] = key
        if kind == "manual":      # exists at once, ready to be edited in the Studio
            proj.segments[key] = Segment(key=key, title=proj.custom_segments[key].title, status="draft", content=starter,
                                         versions=[Version(content=starter, reason="manual edit")] if starter else [])
            proj.segments[key].quality.words = len(starter.split())
            if key not in proj.selected:
                proj.selected = structure.order(proj, [*proj.selected, key])
    p = _mutate(pid, apply)
    c = p.custom_segments[made["key"]]
    history.record(pid, "structure.added", f"Segment added — “{c.title}” ({'written by RAF' if c.kind == 'generated' else 'written by you'})", segment=c.key, written_by=c.kind)
    return {"key": c.key, "project": view(p)}


@router.patch("/projects/{pid}/structure/segments/{key}")
def edit_segment(pid: str, key: str, body: SegmentPatch):
    p = get(pid)
    if key not in p.custom_segments:
        raise HTTPException(404, "Only segments you added can be changed here.")
    segment_free(pid, key)

    def apply(proj: Project):
        c = proj.custom_segments[key]
        if body.purpose is not None:
            c.purpose = structure._plain(body.purpose, 600)
            if c.kind == "generated" and len(c.purpose) < 15:
                raise ValueError("Say in a sentence or two what the segment should do, so RAF knows what to write.")
        if body.words is not None:
            c.words = structure.clamp_length(key, body.words)
            proj.segment_lengths.pop(key, None)
        if body.cites is not None:
            c.cites = body.cites
        if body.numbered is not None:
            c.numbered = body.numbered
        if body.moves is not None:
            c.moves = structure.clean_moves(body.moves)
    p = _mutate(pid, apply)
    history.record(pid, "structure.changed", f"Segment “{p.custom_segments[key].title}” changed", segment=key)
    return view(p)


@router.delete("/projects/{pid}/structure/segments/{key}")
def delete_segment(pid: str, key: str):
    p = get(pid)
    if key not in p.custom_segments:
        raise HTTPException(404, "Only segments you added can be deleted. A built-in segment can be left out of the document instead.")
    busy(pid)
    title = p.custom_segments[key].title
    p = _mutate(pid, lambda proj: structure.remove_custom(proj, key))
    history.record(pid, "structure.removed", f"Segment deleted — “{title}”", segment=key)
    writer.sync_references(pid)
    return view(get(pid))


@router.put("/projects/{pid}/structure/order")
def set_order(pid: str, body: Order):
    p = get(pid)
    before = structure.order(p)
    p = _mutate(pid, lambda proj: structure.set_order(proj, body.order))
    if structure.order(p) != before:
        history.record(pid, "structure.reordered", "Segments put in a new order — " + " → ".join(structure.title_of(p, k) for k in structure.order(p) if k not in structure.FRONT),
                       order=structure.order(p))
        writer.sync_references(pid)     # numbered citation styles follow the order of first appearance
    return view(get(pid))


@router.put("/projects/{pid}/structure/included/{key}")
def set_included(pid: str, key: str, included: bool = True):
    p = get(pid)
    was = structure.included(p, key)
    p = _mutate(pid, lambda proj: structure.set_included(proj, key, included))
    if was != included:
        title = structure.title_of(p, key)
        history.record(pid, "structure.included" if included else "structure.excluded",
                       f"“{title}” put back into the document" if included else f"“{title}” left out of the document", segment=key)
        writer.sync_references(pid)
    return view(get(pid))


@router.post("/projects/{pid}/structure/propose")
def propose(pid: str, body: Proposal):
    """Ask the model which parts a new segment should have. Returns RAF's default three when the model is not available."""
    p = get(pid)
    title, purpose = structure._plain(body.title, 90), structure._plain(body.purpose, 600)
    if len(title) < 2 or len(purpose) < 15:
        raise HTTPException(422, "Give the segment a title and say in a sentence or two what it should do.")
    moves = []
    if llm.ready():
        data = llm.generate_json(
            "You design the internal structure of sections of scholarly articles. Reply with JSON only.",
            f"ARTICLE: {p.title}\nTOPIC: {p.topic}\nARTICLE TYPE: {p.article_type}\n\nNEW SECTION: {title}\nWHAT IT SHOULD DO: {purpose}\n\n"
            "Break this section into 2 to 4 parts, in the order they should be written. For each give: name (2–5 words), instruction (one or two "
            "sentences telling the writer what this part must do), queries (2 short search phrases for finding evidence in the article's sources), "
            "share (its fraction of the section's length; the shares sum to 1).\n"
            "JSON: {\"parts\": [{\"name\": \"\", \"instruction\": \"\", \"queries\": [\"\", \"\"], \"share\": 0.3}]}",
            default={}, max_tokens=700,
        )
        moves = structure.clean_moves(data.get("parts") or [] if isinstance(data, dict) else [])
    proposed = bool(moves)
    if not moves:      # the defaults with this article's title and topic written into the search phrases, so they store like any other parts
        subs = {"title": structure._plain(p.title, 90), "topic": structure._plain(p.topic or p.title, 90)}
        moves = structure.clean_moves([{**m, "queries": [q.format(**subs) for q in m["queries"]]} for m in structure.default_moves(title, purpose)])
    return {"moves": moves, "by": "model" if proposed else "default"}


@router.post("/projects/{pid}/segments/{key}/write")
def write(pid: str, key: str):
    """Write one segment that is part of the structure but has no text yet (a built-in one added later, or a custom one)."""
    p = get(pid)
    if not structure.exists(p, key):
        raise HTTPException(404, "Segment not found")
    bp = structure.blueprint_for(p, key)
    if bp.special == "manual":
        raise HTTPException(422, "This segment is written by you; open it in the Studio and type.")
    if bp.needs_evidence and not (store.project_dir(pid) / "index" / "index.pkl").exists():
        raise HTTPException(422, "RAF has not read this project's references yet. Run a fabrication first; the new segment can be part of it.")
    engine_ready()

    def prepare(proj: Project):
        old = proj.segments.get(key)
        proj.segments[key] = Segment(key=key, title=bp.title, status="queued", versions=old.versions if old else [])
        proj.selected = structure.order(proj, [*proj.selected, key])
    store.mutate(pid, prepare)
    start_segment_job(pid, key, f"Writing {bp.title}", lambda: writer.regenerate_segment(pid, key))
    history.record(pid, "segment.requested", f"You asked RAF to write {bp.title}", segment=key)
    return view(get(pid))
