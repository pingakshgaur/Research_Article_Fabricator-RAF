"""Format an existing article: bring a finished document into RAF only to typeset it. Nothing is rewritten.

1. read      — DOCX (headings, bold / italic / superscript / subscript, tables, pictures), Markdown, plain text, or PDF
               (text and headings only, recognised by font size; tables and pictures are lost)
2. outline   — title, authors, abstract, keywords, sections with their sub-headings, reference list
3. project   — a project in mode "format": every section is a segment the author owns (RAF never generates it), already
               approved, so it can be published at once in any template, colour style and format
4. checks    — on request: a style report per section, and a comparison of the citations in the text with the reference list
5. restyle   — experimental: the reference list re-formatted in another author–date style from Crossref metadata; entries
               Crossref cannot identify are left exactly as they were
"""
from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import citations, store, structure, style
from .models import Figure, Project, QualityReport, Segment, Table, Version

MARKS = re.compile(r"([*^~])")
NUMBERING = re.compile(r"^\s*(?:(?:\d{1,2}(?:\.\d{1,2})*|[IVXLC]{1,6})[.)]?\s+|(?:chapter|section)\s+\d+[.:]?\s+)", re.I)
KNOWN = {"abstract", "summary", "introduction", "background", "literature review", "review of literature", "related work", "theoretical framework",
         "methodology", "methods", "materials and methods", "method", "data", "results", "findings", "analysis", "results and discussion", "discussion",
         "conclusion", "conclusions", "limitations", "implications", "future research", "acknowledgements", "acknowledgments", "funding",
         "references", "bibliography", "works cited", "appendix", "appendices", "keywords", "contents", "table of contents", "declarations",
         "conflict of interest", "data availability", "author contributions"}
REFERENCE_HEADS = {"references", "bibliography", "works cited", "reference list", "literature cited", "references cited"}
ABSTRACT_HEADS = {"abstract", "summary", "executive summary"}
SKIP_HEADS = {"contents", "table of contents"}


@dataclass
class Item:
    kind: str                      # "h" | "p" | "table" | "image"
    text: str = ""
    level: int = 0
    rows: list = field(default_factory=list)
    path: str = ""


def lit(text: str) -> str:
    """Text taken from a document: its own asterisks, carets and tildes must not be read as formatting marks."""
    return MARKS.sub(r"\\\1", text)


def looks_like_heading(text: str, bold: bool = False) -> bool:
    """For documents without heading styles: a short line that is numbered, in capitals, bold on its own, or a usual section name."""
    words = text.split()
    if not 1 <= len(words) <= 12 or text.rstrip().endswith((".", ",", ";", ":")) and not NUMBERING.match(text):
        return False
    bare = NUMBERING.sub("", text).strip().rstrip(":").lower()
    return bare in KNOWN or bool(NUMBERING.match(text) and len(words) <= 10 and text[-1] not in ".,;") or (text.isupper() and len(text) > 3) or (bold and len(words) <= 10)


def clean_heading(text: str) -> str:
    text = NUMBERING.sub("", " ".join(text.split())).strip().rstrip(":")
    return text.title() if text.isupper() and len(text) > 3 else text


# ============================================================================================ readers
def read_docx(path: Path, fig_dir: Path) -> tuple[list[Item], dict]:
    import docx
    from docx.oxml.ns import qn
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    items: list[Item] = []
    pictures = 0

    def marked(par) -> tuple[str, bool]:
        """Paragraph text with **bold**, *italic*, ^super^ and ~sub~ marks; and whether the whole paragraph is bold."""
        parts, bold_chars, chars = [], 0, 0
        inner = par.iter_inner_content() if hasattr(par, "iter_inner_content") else par.runs
        for run in inner:
            text = run.text
            if not text:
                continue
            chars += len(text.strip())
            font = getattr(run, "font", None)
            mark = ""
            if font is not None:      # a Run (a Hyperlink has no font of its own)
                mark = "sup" if font.superscript else "sub" if font.subscript else "b" if run.bold else "i" if run.italic else ""
                bold_chars += len(text.strip()) if run.bold else 0
            if parts and parts[-1][1] == mark:
                parts[-1][0] += text
            else:
                parts.append([text, mark])
        whole_bold = chars > 0 and bold_chars == chars
        wrap = {"b": "**%s**", "i": "*%s*", "sup": "^%s^", "sub": "~%s~", "": "%s"}
        out = ""
        for text, mark in parts:
            if mark and text.strip() and not (whole_bold and mark == "b"):
                lead, core, tail = text[:len(text) - len(text.lstrip())], text.strip(), text[len(text.rstrip()):]
                out += lead + wrap[mark] % lit(core) + tail       # marks hug the words, spaces stay outside
            else:
                out += lit(text)
        return " ".join(out.split()), whole_bold

    for child in d.element.body.iterchildren():
        if child.tag == qn("w:tbl"):
            rows = [[" ".join(c.text.split()) for c in row.cells] for row in DocxTable(child, d).rows]
            if len(rows) > 1:
                items.append(Item("table", rows=rows))
            continue
        if child.tag != qn("w:p"):
            continue
        par = Paragraph(child, d)
        for blip in child.iter(qn("a:blip")):          # pictures placed in this paragraph
            rid = blip.get(qn("r:embed"))
            part = d.part.related_parts.get(rid) if rid else None
            if part is None:
                continue
            try:
                from PIL import Image
                image = Image.open(io.BytesIO(part.blob))
                pictures += 1
                name = f"figure_{pictures}.png"
                (image.convert("RGBA") if image.mode in {"P", "LA"} else image).save(fig_dir / name, "PNG")
                items.append(Item("image", path=f"figures/{name}"))
            except Exception:  # noqa: BLE001 - a picture format Pillow cannot read (e.g. EMF) is skipped
                continue
        text, bold = marked(par)
        if not text:
            continue
        name = (par.style.name or "").lower() if par.style is not None else ""
        if name == "title":
            items.append(Item("h", par.text.strip(), level=0))
        elif name.startswith("heading"):
            items.append(Item("h", par.text.strip(), level=int(re.sub(r"\D", "", name) or 1)))
        elif looks_like_heading(par.text.strip(), bold):
            items.append(Item("h", par.text.strip(), level=2 if re.match(r"^\s*\d+\.\d+", par.text) else 1))
        else:
            items.append(Item("p", text))
    cp = d.core_properties
    return items, {"author": cp.author or ""}


def read_markdown(path: Path) -> tuple[list[Item], dict]:
    text = path.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n")
    styled = path.suffix.lower() in {".md", ".markdown"}
    items: list[Item] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip("\n")
        if not block.strip():
            continue
        lines = block.split("\n")
        m = re.match(r"^(#{1,6})\s+(.+?)\s*#*$", lines[0])
        if m and styled:
            items.append(Item("h", m.group(2).strip(), level=len(m.group(1))))
            lines = lines[1:]
            if not lines:
                continue
        if styled and len(lines) >= 2 and all(l.strip().startswith("|") for l in lines):
            rows = [[c.strip() for c in l.strip().strip("|").split("|")] for l in lines]
            rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c) for c in r)]
            if len(rows) > 1:
                items.append(Item("table", rows=rows))
                continue
        if re.fullmatch(r"!\[[^\]]*\]\([^)]*\)", block.strip()):     # pictures in Markdown are links to files RAF does not have
            continue
        joined = " ".join(l.strip() for l in lines)
        if not styled and len(lines) == 1 and looks_like_heading(joined):
            items.append(Item("h", joined, level=2 if re.match(r"^\s*\d+\.\d+", joined) else 1))
        elif styled and all(re.match(r"^\s*[-*+]\s+", l) for l in lines):      # a list: one paragraph per entry
            items += [Item("p", re.sub(r"^\s*[-*+]\s+", "", l).strip()) for l in lines]
        else:
            items.append(Item("p", joined if styled else lit(joined)))
    return items, {}


def read_pdf(path: Path) -> tuple[list[Item], dict]:
    """Text blocks of a PDF; headings are told apart by font size and weight. Running headers, footers and page numbers are dropped."""
    import pymupdf

    doc = pymupdf.open(path)
    blocks, sizes = [], Counter()
    for page_no, page in enumerate(doc):
        for b in page.get_text("dict")["blocks"]:
            lines = [(max((s["size"] for s in l["spans"]), default=0), all(s["flags"] & 16 for s in l["spans"] if s["text"].strip()),
                      "".join(s["text"] for s in l["spans"]).strip()) for l in b.get("lines", [])]
            lines = [l for l in lines if l[2]]
            if not lines:
                continue
            text = re.sub(r"(\w)-\s+(\w)", r"\1\2", " ".join(l[2] for l in lines))
            size = round(max(l[0] for l in lines), 1)
            sizes[size] += len(text)
            blocks.append({"page": page_no, "text": " ".join(text.split()), "size": size, "bold": all(l[1] for l in lines), "lines": len(lines)})
    if not blocks:
        return [], {}
    body = sizes.most_common(1)[0][0]
    repeated = {t for t, n in Counter(b["text"] for b in blocks if len(b["text"]) < 90).items() if n >= 3}      # running headers
    items: list[Item] = []
    largest = max((b["size"] for b in blocks if b["page"] == 0), default=body)
    for b in blocks:
        text = b["text"]
        if text in repeated or re.fullmatch(r"(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?", text, re.I):
            continue
        short = len(text.split()) <= 14 and b["lines"] <= 2
        if b["page"] == 0 and b["size"] == largest and largest > body + 2 and not any(i.kind == "h" and i.level == 0 for i in items):
            items.append(Item("h", text, level=0))
        elif short and (b["size"] >= body + 0.8 or (b["bold"] and looks_like_heading(text, True)) or looks_like_heading(text)):
            items.append(Item("h", text, level=1 if b["size"] >= body + 2 or not re.match(r"^\s*\d+\.\d+", text) else 2))
        else:
            items.append(Item("p", lit(text)))
    return items, {k: v for k, v in (doc.metadata or {}).items() if v}


def read(path: Path, fig_dir: Path) -> tuple[list[Item], dict]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return read_docx(path, fig_dir)
    if suffix in {".md", ".markdown", ".txt"}:
        return read_markdown(path)
    if suffix == ".pdf":
        return read_pdf(path)
    raise ValueError("Upload a DOCX, Markdown, plain-text or PDF file.")


# ============================================================================================ outline -> project
def create_project(path: Path, filename: str, defaults: dict | None = None) -> tuple[Project, dict]:
    """Read the document and make a format-mode project of it. Returns (project, a summary of what was found)."""
    p = store.save(Project(title=Path(filename).stem.replace("_", " ")[:200] or "Imported article", mode="format", stage="studio",
                           citation_style=(defaults or {}).get("citation_style", "APA"), options={"web_research": False, "data_analysis": False}))
    fig_dir = store.project_dir(p.id) / "figures"
    try:
        items, meta = read(path, fig_dir)
    except Exception:
        store.delete(p.id)
        raise
    if not any(i.kind == "p" for i in items):
        store.delete(p.id)
        raise ValueError("No text could be read from this file. A scanned PDF has to be run through OCR first.")

    heads = [i for i in items if i.kind == "h"]
    titles = [i for i in heads if i.level == 0]
    levels = sorted({i.level for i in heads if i.level > 0})
    title = titles[0].text if titles else ""
    if not title and levels and sum(i.level == levels[0] for i in heads) == 1 and len(levels) > 1 and items.index(next(i for i in heads if i.level == levels[0])) <= 1:
        first = next(i for i in heads if i.level == levels[0])      # one top-level heading at the very start, sections below it: that is the title
        title, first.level = first.text, 0
        levels = levels[1:]
    top = levels[0] if levels else 1

    front: list[str] = []
    sections: list[dict] = []
    current = None
    numbering = {"table": 0, "figure": 0}
    for n, item in enumerate(items):
        if item.kind == "h":
            if item.level == 0:
                continue
            if item.level <= top:
                current = {"title": clean_heading(item.text), "blocks": [], "tables": [], "figures": []}
                sections.append(current)
            elif current is not None:
                current["blocks"].append(("##" if item.level == top + 1 else "###") + " " + lit(clean_heading(item.text)))
            continue
        if current is None:
            if item.kind == "p":
                front.append(item.text)
            continue
        if item.kind == "p":
            current["blocks"].append(item.text)
        elif item.kind == "table":
            numbering["table"] += 1
            caption = f"Table {numbering['table']}"
            prev = current["blocks"][-1] if current["blocks"] else ""
            m = re.match(r"^(?:\*\*)?table\s+\d+[.:]?(?:\*\*)?\s*(.*)$", publisher_plain(prev), re.I)
            if m and len(prev) < 300:       # the line above a table that starts "Table 2." is its caption
                caption = m.group(1).strip() or caption
                current["blocks"].pop()
            header, *rows = item.rows
            current["tables"].append(Table(number=numbering["table"], caption=caption, columns=[str(c) for c in header], rows=[[str(c) for c in r] for r in rows]))
            current["blocks"].append(f"[[TABLE {numbering['table']}]]")
        elif item.kind == "image":
            numbering["figure"] += 1
            caption = f"Figure {numbering['figure']}"
            nxt = items[n + 1] if n + 1 < len(items) else None
            m = re.match(r"^(?:\*\*)?fig(?:ure|\.)\s+\d+[.:]?(?:\*\*)?\s*(.*)$", publisher_plain(nxt.text), re.I) if nxt and nxt.kind == "p" else None
            if m and len(nxt.text) < 300:   # the line below a picture that starts "Figure 3." is its caption
                caption = m.group(1).strip() or caption
                nxt.kind = "skip"
            current["figures"].append(Figure(number=numbering["figure"], caption=caption, path=item.path))
            current["blocks"].append(f"[[FIGURE {numbering['figure']}]]")

    # ---- front matter
    abstract, keywords, references = "", "", ""
    body_sections = []
    for i, sec in enumerate(sections):
        name = sec["title"].lower()
        text_blocks = [b for b in sec["blocks"] if not b.startswith("[[")]
        if name in SKIP_HEADS:
            continue
        if name in ABSTRACT_HEADS and not abstract:
            abstract = " ".join(b for b in text_blocks if not _keywords(b))
            keywords = next((_keywords(b) for b in text_blocks if _keywords(b)), keywords)
        elif name in {"keywords", "index terms", "key words"}:
            keywords = "; ".join(k.strip() for k in re.split(r"[;,]", " ".join(text_blocks)) if k.strip())
        elif name in REFERENCE_HEADS:
            references = "\n".join(re.sub(r"^\s*[-•]\s+", "", b) for b in text_blocks)
        elif i == 0 and title and not sec["blocks"] and not abstract:
            title = f"{title}: {sec['title']}"      # a heading with nothing under it, right below the title: the subtitle
        elif not sec["blocks"]:
            continue
        else:
            body_sections.append(sec)
    people = [publisher_plain(f) for f in front if not _keywords(f) and not f.lower().startswith("abstract")]
    for f in front:
        if _keywords(f) and not keywords:
            keywords = _keywords(f)
        m = re.match(r"^(?:\*\*)?abstract(?:\*\*)?\s*[:.—-]\s*(.+)$", f, re.I | re.S)
        if m and not abstract:
            abstract = m.group(1).strip()
    if not abstract and len(people) and len(people[-1].split()) > 60:      # a long unlabelled paragraph before the first heading
        abstract = front[-1]
        people = people[:-1]
    short = [x for x in people if len(x.split()) <= 25 and not re.search(r"\b(19|20)\d{2}\b.*\b(19|20)\d{2}\b", x)]
    authors = [a.strip() for a in re.split(r",|;|\band\b|&", short[0]) if 1 <= len(a.split()) <= 5] if short else []
    affiliation = short[1] if len(short) > 1 and not re.fullmatch(r"[\d\s./-]+|\d{1,2} \w+ \d{4}", short[1]) else ""
    title = clean_heading(title) or p.title

    def make(key: str, heading: str, content: str, tables=(), figures=()) -> Segment:
        words = len(publisher_plain(re.sub(r"\[\[.*?\]\]|^#+ ", "", content, flags=re.M)).split())
        return Segment(key=key, title=heading, status="approved", content=content, tables=list(tables), figures=list(figures),
                       versions=[Version(content=content, reason="imported document")], quality=QualityReport(words=words))

    def build(proj: Project):
        proj.title, proj.authors, proj.affiliation = publisher_plain(title)[:300], authors[:12], affiliation[:200]
        proj.segments["title"] = make("title", "Title", publisher_plain(title))
        if abstract:
            proj.segments["abstract"] = make("abstract", "Abstract", abstract)
        if keywords:
            proj.segments["keywords"] = make("keywords", "Keywords", keywords)
        used = set()
        for sec in body_sections[:40]:
            heading = sec["title"][:90] or "Section"
            while heading.lower() in used:
                heading += " (2)"
            used.add(heading.lower())
            key = structure.add_custom(proj, title=heading, kind="manual", numbered_=heading.lower() not in UNNUMBERED_NAMES, limit=False)
            proj.segments[key] = make(key, proj.custom_segments[key].title, "\n\n".join(sec["blocks"]), sec["tables"], sec["figures"])
        if references:
            proj.segments["references"] = make("references", "References", references)
        proj.selected = structure.order(proj, proj.segments)
    p = store.mutate(p.id, build)
    found = {"title": p.title, "authors": p.authors, "abstract": bool(abstract), "keywords": bool(keywords),
             "sections": [s["title"] for s in body_sections], "references": len(references.splitlines()) if references else 0,
             "tables": numbering["table"], "figures": numbering["figure"], "lossy": path.suffix.lower() == ".pdf"}
    return p, found


UNNUMBERED_NAMES = {"acknowledgements", "acknowledgments", "funding", "declarations", "conflict of interest", "conflicts of interest", "data availability",
                    "author contributions", "appendix", "appendices", "ai-use statement", "notes"}


def publisher_plain(text: str) -> str:
    from .publisher import plain
    return plain(text)


def _keywords(text: str) -> str:
    m = re.match(r"^(?:\*\*)?(?:key\s?words|index terms)(?:\*\*)?\s*[:.—-]+\s*(?:\*\*)?\s*(.+)$", text.strip(), re.I)
    return "; ".join(k.strip(" *.") for k in re.split(r"[;,]", m.group(1)) if k.strip(" *.")) if m else ""


# ============================================================================================ checks
AUTHOR_YEAR = re.compile(r"([A-Z][A-Za-z'’\-]+)(?:\s+(?:et al\.?|and\s+[A-Z][A-Za-z'’\-]+|&\s+[A-Z][A-Za-z'’\-]+))?,?\s+\(?((?:19|20)\d{2})[a-z]?\b")
NUMERIC = re.compile(r"\[(\d{1,3}(?:\s*[-–,]\s*\d{1,3})*)\]")
NOT_NAMES = {"In", "The", "Since", "During", "Table", "Figure", "After", "Before", "By", "From", "Until", "Between", "Around", "Early", "Late", "Mid",
             "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"}


def reference_check(p: Project) -> dict:
    """Which works are cited in the text but missing from the reference list, and which are listed but never cited."""
    refs = [l.strip() for l in (p.segments["references"].content.splitlines() if p.segments.get("references") else []) if l.strip()]
    body = "\n".join(publisher_plain(s.content) for k, s in p.segments.items() if k != "references" and structure.included(p, k))
    numbered = [re.match(r"^\[?(\d{1,3})[\].)]\s", r) for r in refs]
    if refs and sum(bool(m) for m in numbered) >= 0.6 * len(refs):       # numbered list: [1], [2] …
        listed = {int(m.group(1)) for m in numbered if m}
        cited: set[int] = set()
        for group in NUMERIC.findall(body):
            for part in re.split(r"\s*,\s*", group):
                lo, _, hi = re.sub(r"\s", "", part).replace("–", "-").partition("-")
                cited |= set(range(int(lo), int(hi or lo) + 1)) if int(hi or lo) - int(lo) < 60 else {int(lo)}
        return {"style": "numbered", "references": len(refs), "citations": len(cited),
                "missing": [f"[{n}]" for n in sorted(cited - listed)], "uncited": [f"[{n}]" for n in sorted(listed - cited)]}
    listed_pairs = {}
    for r in refs:
        year = re.search(r"\b((?:19|20)\d{2})[a-z]?\b", r)
        name = re.match(r"^[\W\d]*([A-Z][A-Za-z'’\-]+)", r)
        if year and name:
            listed_pairs[(name.group(1).lower(), year.group(1))] = r
    cited_pairs = {(m.group(1).lower(), m.group(2)) for m in AUTHOR_YEAR.finditer(body) if m.group(1) not in NOT_NAMES}
    return {"style": "author–date", "references": len(refs), "citations": len(cited_pairs),
            "missing": sorted(f"{a.title()} ({y})" for a, y in cited_pairs - set(listed_pairs)),
            "uncited": sorted(v[:140] for k, v in listed_pairs.items() if k not in cited_pairs)}


def checks(p: Project) -> dict:
    report = []
    for key in structure.order(p, p.segments):
        seg = p.segments[key]
        if key in structure.FRONT or key == "references" or not structure.included(p, key):
            continue
        m = style.metrics(publisher_plain(seg.content))
        if m.get("score") is not None:
            report.append({"key": key, "title": seg.title, "words": m["words"], "score": m["score"], "issues": style.issues(m)})
    return {"style": report, "references": reference_check(p)}


# ============================================================================================ experimental: restyle the reference list
@dataclass
class Work:
    title: str
    authors: list
    year: str
    venue: str
    doi: str
    volume: str = ""
    issue: str = ""
    pages: str = ""
    url: str = ""


def lookup(entry: str) -> Work | None:
    """Identify one reference-list entry with Crossref: by its DOI, or by a bibliographic search that must match the title."""
    import httpx
    from rapidfuzz import fuzz

    from .config import settings
    try:
        doi = re.search(r"\b(10\.\d{4,9}/[^\s\"<>]+)", entry)
        if doi:
            r = httpx.get(f"https://api.crossref.org/works/{doi.group(1).rstrip('.,;)')}", params={"mailto": settings.contact_email}, timeout=8)
            items = [r.json()["message"]] if r.status_code == 200 else []
        else:
            r = httpx.get("https://api.crossref.org/works", params={"query.bibliographic": entry[:400], "rows": 1, "mailto": settings.contact_email}, timeout=8)
            items = r.json()["message"]["items"] if r.status_code == 200 else []
        if not items:
            return None
        m = items[0]
        title = " ".join(m.get("title") or [""])
        if not title or (not doi and fuzz.partial_ratio(title.lower(), entry.lower()) < 90):       # a search hit has to be this very work
            return None
        year = next((str(m[k]["date-parts"][0][0]) for k in ("published-print", "published-online", "issued") if (m.get(k) or {}).get("date-parts", [[None]])[0][0]), "")
        return Work(title=title, authors=[f"{a.get('family', '')}, {a.get('given', '')}".strip(", ") for a in m.get("author") or []], year=year,
                    venue=" ".join(m.get("container-title") or []), doi=m.get("DOI", ""), volume=str(m.get("volume", "") or ""),
                    issue=str(m.get("issue", "") or ""), pages=str(m.get("page", "") or ""))
    except Exception:  # noqa: BLE001 - offline, rate-limited, unexpected reply: the entry simply stays as it is
        return None


def restyle_references(p: Project, target: str) -> dict:
    """Re-format the entries Crossref can identify in `target` style. Returns the new list and what happened to each entry."""
    if target not in {"APA", "Harvard", "Chicago"}:
        raise ValueError("The reference list can be restyled to APA, Harvard or Chicago. Numbered styles would also need every citation in the text renumbered.")
    seg = p.segments.get("references")
    entries = [l.strip() for l in seg.content.splitlines() if l.strip()] if seg else []
    if not entries:
        raise ValueError("This article has no reference list.")
    out, changed, kept = [], 0, []
    for entry in entries:
        work = lookup(entry)
        if work is None:
            out.append(entry)
            kept.append(entry[:120])
        else:
            out.append(citations.format_reference(work, target))
            changed += 1
    return {"content": "\n".join(out), "restyled": changed, "unchanged": kept, "total": len(entries)}
