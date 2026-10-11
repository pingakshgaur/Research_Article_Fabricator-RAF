"""Publishing: templates, export to DOCX / PDF / Markdown, and re-import of an edited document."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response

from .. import citations, history, latex, publisher, revisions, store, structure, writer
from ..ingest import SUPPORTED
from .common import busy, get, slug, view

router = APIRouter(prefix="/api")
FORMAT_NAMES = {"docx": "Word", "pdf": "PDF", "md": "Markdown", "tex": "LaTeX"}
LIST_FORMATS = {"bib": ("BibTeX", "application/x-bibtex"), "ris": ("RIS", "application/x-research-info-systems")}


@router.get("/publish/styles")
def publish_styles():
    return publisher.styles_catalogue()


@router.get("/projects/{pid}/export/{fmt}")
def export(pid: str, fmt: str, draft: bool = False, template: str | None = None, palette: str | None = None):
    p = get(pid)
    if not p.segments:
        raise HTTPException(422, "Nothing to publish yet.")
    if fmt in LIST_FORMATS:      # the reference list alone, for Zotero, Mendeley, EndNote or a .bib file; needs no approval
        texts = [p.segments[k].content for k in structure.order(p, p.segments) if k != "references" and structure.included(p, k)]
        order = citations.reference_list(p, texts)[1]
        if not order:
            raise HTTPException(422, "This article has no structured sources to export. Its reference list is plain text.")
        text = citations.bibtex(p, order, enrich=bool(p.options.get("web_research"))) if fmt == "bib" else citations.ris(p, order)
        history.record(pid, "article.references_exported", f"Reference list exported as {LIST_FORMATS[fmt][0]} ({len(order)} sources)", format=fmt)
        return Response(text, media_type=LIST_FORMATS[fmt][1], headers={"Content-Disposition": f'attachment; filename="{slug(p.title)}_references.{fmt}"'})
    if fmt not in FORMAT_NAMES:
        raise HTTPException(422, "Format must be docx, pdf, md, tex, bib or ris")
    writer.sync_references(pid)
    p = get(pid)
    # segments left out of the document do not hold up publishing; neither does a hand-written one that is still empty
    pending = [s.title for k, s in p.segments.items() if s.status != "approved" and structure.included(p, k)
               and (s.content or structure.blueprint_for(p, k).special not in {"manual", "references"})]      # … nor an empty reference list
    if pending and not draft:
        raise HTTPException(422, "Approve every segment before publishing: " + ", ".join(pending))
    template = template or p.publish_style.get("template")
    palette = palette or p.publish_style.get("palette")
    if template not in publisher.TEMPLATES or palette not in publisher.PALETTES:
        raise HTTPException(422, "Unknown template or colour style.")
    store.mutate(pid, lambda proj: setattr(proj, "publish_style", {"template": template, "palette": palette}))
    article = publisher.assemble(p, only_approved=not draft)
    name = slug(article.title)
    out_dir = store.project_dir(pid) / "exports"
    layout = "" if fmt == "md" else f" · {publisher.TEMPLATES[template].name} · {publisher.PALETTES[palette]['name']}"

    def note():   # a publish is a milestone: the article as published is kept as a revision
        if draft:
            history.record(pid, "article.draft_exported", f"Draft exported as {FORMAT_NAMES[fmt]}{layout}", format=fmt, template=template, palette=palette)
            return
        store.mutate(pid, lambda proj: setattr(proj, "stage", "published"))
        rev = revisions.snapshot(pid, f"Published · {FORMAT_NAMES[fmt]}", auto=True, trigger="publish")
        history.record(pid, "article.published", f"Published as {FORMAT_NAMES[fmt]}{layout}", format=fmt, template=template, palette=palette,
                       revision=rev["n"] if rev else None)

    if fmt == "md":
        text = publisher.to_markdown(article)
        note()
        return Response(text, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{name}.md"'})
    if fmt == "tex":
        path = latex.to_latex(p, out_dir / f"{name}{'_preview' if draft else ''}_latex.zip", template, palette, only_approved=not draft,
                              enrich=bool(p.options.get("web_research")))
        note()
        return FileResponse(path, media_type="application/zip", filename=path.name)
    if fmt == "docx":
        path = publisher.to_docx(article, out_dir / f"{name}.docx", template, palette)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        path = publisher.to_pdf(article, out_dir / f"{name}{'_preview' if draft else ''}.pdf", template, palette)
        media = "application/pdf"
    note()
    return FileResponse(path, media_type=media, filename=path.name)


@router.post("/projects/{pid}/import")
async def import_doc(pid: str, file: UploadFile = File(...)):
    p = get(pid)
    busy(pid)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED:
        raise HTTPException(422, "Import a DOCX, PDF or Markdown file.")
    tmp = store.project_dir(pid) / "exports" / f"import{suffix}"
    tmp.write_bytes(await file.read())
    sections = publisher.import_document(p, tmp)
    if not sections:
        raise HTTPException(422, "No matching section headings were found in the document.")
    revisions.snapshot(pid, "Before import", auto=True, trigger="import")
    history.record(pid, "article.imported", f"Document imported — {file.filename} ({len(sections)} segments replaced)", file=file.filename, segments=list(sections))
    for key, content in sections.items():
        writer.manual_edit(pid, key, content, reason="imported document")
    return {"updated": list(sections), "project": view(get(pid))}
