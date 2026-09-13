"""Publishing: assemble approved segments into a professional DOCX, PDF or Markdown document, and re-import
edited DOCX / Markdown / PDF files back into segments."""
from __future__ import annotations

import base64
import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import citations, store
from .blueprints import BLUEPRINTS
from .models import Figure, Project, Table

ACCENT_HEX = "3B1782"      # deep violet, prints well in colour and greyscale
RULE_HEX = "C9BFE0"
PLACEHOLDER = re.compile(r"^\[\[(TABLE|FIGURE) (\d+)\]\]$")


# ====================================================================== article model
@dataclass
class Block:
    kind: str                  # "p" | "table" | "figure" | "ref" | "subhead"
    text: str = ""
    table: Table | None = None
    figure: Figure | None = None


@dataclass
class Section:
    key: str
    heading: str
    number: str
    blocks: list[Block] = field(default_factory=list)


@dataclass
class Article:
    title: str
    subtitle: str
    authors: list[str]
    affiliation: str
    date: str
    abstract: str
    keywords: str
    sections: list[Section]
    project_dir: Path


def assemble(p: Project, only_approved: bool = False) -> Article:
    segs = {k: s for k, s in p.segments.items() if s.content and (s.status == "approved" or not only_approved)}
    body_texts = [s.content for k, s in segs.items() if k != "references"]
    _, order = citations.reference_list(p, body_texts)

    title_text = segs["title"].content.strip() if "title" in segs else p.title
    title, _, subtitle = title_text.partition(": ")
    abstract = citations.render_in_text(segs["abstract"].content, p, order) if "abstract" in segs else ""
    keywords = segs["keywords"].content if "keywords" in segs else ""

    sections: list[Section] = []
    numbered = 0
    for key in sorted(segs, key=lambda k: BLUEPRINTS[k].display_order):
        if key in {"title", "abstract", "keywords"}:
            continue
        seg = segs[key]
        if key in {"references", "appendices"}:
            number = ""
        else:
            numbered += 1
            number = str(numbered)
        sec = Section(key=key, heading=seg.title, number=number)
        tables = {t.number: t for t in seg.tables}
        figures = {f.number: f for f in seg.figures}
        for raw in re.split(r"\n\s*\n", seg.content):
            raw = raw.strip()
            if not raw:
                continue
            m = PLACEHOLDER.match(raw)
            if m:
                kind, num = m.group(1), int(m.group(2))
                if kind == "TABLE" and num in tables:
                    sec.blocks.append(Block("table", table=tables[num]))
                elif kind == "FIGURE" and num in figures:
                    sec.blocks.append(Block("figure", figure=figures[num]))
                continue
            if key == "references":
                for line in raw.splitlines():
                    if line.strip():
                        sec.blocks.append(Block("ref", text=line.strip()))
                continue
            if key == "appendices" and re.match(r"^Appendix [A-Z]\.", raw):
                sec.blocks.append(Block("subhead", text=raw))
                continue
            for para in raw.split("\n") if key == "appendices" else [raw]:
                text = citations.render_in_text(para.strip().lstrip("- "), p, order)
                if text:
                    sec.blocks.append(Block("p", text=text))
        sections.append(sec)
    return Article(title=title.strip(), subtitle=subtitle.strip(), authors=p.authors, affiliation=p.affiliation,
                   date=dt.date.today().strftime("%d %B %Y"), abstract=abstract, keywords=keywords, sections=sections,
                   project_dir=store.project_dir(p.id))


def table_label(t: Table) -> str:
    return f"Table A{t.number - 100}" if t.number > 100 else f"Table {t.number}"


def _clean_caption(caption: str) -> str:
    return caption.rstrip(".") + "."


# ====================================================================== DOCX
def to_docx(a: Article, out: Path) -> Path:
    import docx
    from docx.enum.section import WD_SECTION
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    accent = RGBColor.from_string(ACCENT_HEX)
    d = docx.Document()
    sec = d.sections[0]
    sec.page_height, sec.page_width = Cm(29.7), Cm(21.0)
    sec.left_margin = sec.right_margin = Cm(2.5)
    sec.top_margin, sec.bottom_margin = Cm(2.4), Cm(2.2)

    styles = d.styles
    normal = styles["Normal"]
    normal.font.name, normal.font.size = "Cambria", Pt(11)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Cambria")
    normal.paragraph_format.space_after = Pt(8)
    normal.paragraph_format.line_spacing = 1.25
    for lvl, size in ((1, 15), (2, 12.5)):
        h = styles[f"Heading {lvl}"]
        h.font.name, h.font.size, h.font.bold, h.font.color.rgb = "Calibri", Pt(size), True, accent
        h.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
        h.paragraph_format.space_before, h.paragraph_format.space_after = Pt(18 if lvl == 1 else 12), Pt(6)
        h.paragraph_format.keep_with_next = True

    def field(paragraph, instr: str):
        run = paragraph.add_run()
        for tag, text in (("begin", None), (None, instr), ("separate", None), (None, "1"), ("end", None)):
            if tag:
                el = OxmlElement("w:fldChar")
                el.set(qn("w:fldCharType"), tag)
            elif text == instr:
                el = OxmlElement("w:instrText")
                el.set(qn("xml:space"), "preserve")
                el.text = instr
            else:
                el = OxmlElement("w:t")
                el.text = text
            run._r.append(el)
        return run

    def shade(cell, hex_fill: str):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hex_fill)
        tcPr.append(shd)

    def bottom_rule(paragraph, color=RULE_HEX, size="8"):
        pPr = paragraph._p.get_or_add_pPr()
        bdr = OxmlElement("w:pBdr")
        b = OxmlElement("w:bottom")
        for k, v in (("w:val", "single"), ("w:sz", size), ("w:space", "4"), ("w:color", color)):
            b.set(qn(k), v)
        bdr.append(b)
        pPr.append(bdr)

    def borders(table, color="8C7BB5"):
        tblPr = table._tbl.tblPr
        el = OxmlElement("w:tblBorders")
        for edge in ("top", "bottom", "insideH"):
            e = OxmlElement(f"w:{edge}")
            for k, v in (("w:val", "single"), ("w:sz", "6" if edge == "insideH" else "12"), ("w:color", color if edge != "insideH" else "DDD6EA")):
                e.set(qn(k), v)
            el.append(e)
        tblPr.append(el)

    # ---- header / footer
    hp = sec.header.paragraphs[0]
    hp.text = a.title if len(a.title) < 90 else a.title[:87] + "…"
    hp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for r in hp.runs:
        r.font.size, r.font.color.rgb, r.font.name = Pt(8.5), RGBColor(0x6B, 0x63, 0x7A), "Calibri"
    fp = sec.footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run("Page ")
    r.font.size = Pt(9)
    field(fp, "PAGE").font.size = Pt(9)
    r = fp.add_run(" of ")
    r.font.size = Pt(9)
    field(fp, "NUMPAGES").font.size = Pt(9)

    # ---- title block
    p = d.add_paragraph()
    p.paragraph_format.space_before = Pt(36)
    run = p.add_run("RESEARCH ARTICLE")
    run.font.size, run.font.bold, run.font.color.rgb, run.font.name = Pt(9), True, accent, "Calibri"
    t = d.add_paragraph()
    run = t.add_run(a.title)
    run.font.size, run.font.bold, run.font.name = Pt(22), True, "Calibri"
    t.paragraph_format.space_after = Pt(4)
    t.paragraph_format.line_spacing = 1.05
    if a.subtitle:
        s = d.add_paragraph()
        run = s.add_run(a.subtitle)
        run.font.size, run.font.italic, run.font.color.rgb = Pt(14), True, RGBColor(0x44, 0x3C, 0x55)
    meta = d.add_paragraph()
    if a.authors:
        run = meta.add_run(", ".join(a.authors))
        run.font.bold, run.font.size = True, Pt(11)
        meta.add_run("\n")
    if a.affiliation:
        run = meta.add_run(a.affiliation + "\n")
        run.font.size, run.font.italic = Pt(10), True
    run = meta.add_run(a.date)
    run.font.size, run.font.color.rgb = Pt(9.5), RGBColor(0x6B, 0x63, 0x7A)
    bottom_rule(meta, ACCENT_HEX, "12")

    if a.abstract:
        box = d.add_table(rows=1, cols=1)
        box.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = box.rows[0].cells[0]
        shade(cell, "F3EFFB")
        head = cell.paragraphs[0]
        run = head.add_run("Abstract")
        run.font.bold, run.font.color.rgb, run.font.name, run.font.size = True, accent, "Calibri", Pt(11)
        body = cell.add_paragraph(a.abstract)
        body.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        body.paragraph_format.space_after = Pt(6)
        if a.keywords:
            kw = cell.add_paragraph()
            run = kw.add_run("Keywords: ")
            run.font.bold = True
            run.font.size = Pt(10)
            run = kw.add_run(a.keywords)
            run.font.italic, run.font.size = True, Pt(10)
        d.add_paragraph()
    elif a.keywords:
        kw = d.add_paragraph()
        kw.add_run("Keywords: ").bold = True
        kw.add_run(a.keywords).italic = True

    toc_title = d.add_paragraph()
    run = toc_title.add_run("Contents")
    run.font.bold, run.font.color.rgb, run.font.name, run.font.size = True, accent, "Calibri", Pt(12)
    toc = d.add_paragraph()
    field(toc, 'TOC \\o "1-2" \\h \\z \\u')
    note = d.add_paragraph()
    run = note.add_run("(Right-click → Update Field to refresh the table of contents.)")
    run.font.size, run.font.italic, run.font.color.rgb = Pt(8), True, RGBColor(0x88, 0x80, 0x99)
    d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ---- sections
    for s in a.sections:
        if s.key == "appendices":
            d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        d.add_heading(f"{s.number}. {s.heading}" if s.number else s.heading, level=1)
        for b in s.blocks:
            if b.kind == "p":
                para = d.add_paragraph(b.text)
                para.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            elif b.kind == "subhead":
                d.add_heading(b.text, level=2)
            elif b.kind == "ref":
                para = d.add_paragraph(b.text)
                para.paragraph_format.left_indent = Cm(1.0)
                para.paragraph_format.first_line_indent = Cm(-1.0)
                para.paragraph_format.space_after = Pt(5)
                for r in para.runs:
                    r.font.size = Pt(10)
            elif b.kind == "table" and b.table:
                tb = b.table
                cap = d.add_paragraph()
                cap.paragraph_format.keep_with_next = True
                run = cap.add_run(f"{table_label(tb)}. ")
                run.font.bold, run.font.size, run.font.color.rgb = True, Pt(10), accent
                run = cap.add_run(_clean_caption(tb.caption))
                run.font.size, run.font.italic = Pt(10), True
                cols = max(len(tb.columns), max((len(r) for r in tb.rows), default=0))
                table = d.add_table(rows=1, cols=cols)
                table.alignment = WD_TABLE_ALIGNMENT.CENTER
                borders(table)
                for i, col in enumerate(tb.columns):
                    c = table.rows[0].cells[i]
                    shade(c, "EDE6FA")
                    c.paragraphs[0].add_run(col).bold = True
                for row in tb.rows:
                    cells = table.add_row().cells
                    for i, val in enumerate(row[:cols]):
                        cells[i].paragraphs[0].add_run(str(val))
                for row in table.rows:
                    for c in row.cells:
                        for para in c.paragraphs:
                            para.paragraph_format.space_after = Pt(2)
                            para.paragraph_format.line_spacing = 1.0
                            for r in para.runs:
                                r.font.size, r.font.name = Pt(9), "Calibri"
                if tb.note:
                    n = d.add_paragraph()
                    run = n.add_run("Note. ")
                    run.font.italic, run.font.size = True, Pt(8.5)
                    run = n.add_run(tb.note)
                    run.font.size = Pt(8.5)
                else:
                    d.add_paragraph()
            elif b.kind == "figure" and b.figure:
                img = a.project_dir / b.figure.path
                if img.exists():
                    fig_p = d.add_paragraph()
                    fig_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    fig_p.paragraph_format.keep_with_next = True
                    from PIL import Image as PILImage

                    w_px, h_px = PILImage.open(img).size
                    fig_p.add_run().add_picture(str(img), width=Cm(min(15.0, 11.5 * w_px / h_px)))
                    cap = d.add_paragraph()
                    cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    run = cap.add_run(f"Figure {b.figure.number}. ")
                    run.font.bold, run.font.size, run.font.color.rgb = True, Pt(10), accent
                    run = cap.add_run(_clean_caption(b.figure.caption))
                    run.font.italic, run.font.size = True, Pt(10)

    d.core_properties.title = a.title
    d.core_properties.author = ", ".join(a.authors) or "RAF"
    d.core_properties.keywords = a.keywords
    d.save(out)
    return out


# ====================================================================== PDF
def to_pdf(a: Article, out: Path) -> Path:
    from xml.sax.saxutils import escape

    import matplotlib
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, NextPageTemplate, PageBreak, PageTemplate,
                                    Paragraph, Spacer, Table as RLTable, TableStyle)
    from reportlab.platypus.tableofcontents import TableOfContents

    font_dir = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    serif, sans = "Times-Roman", "Helvetica"
    try:
        for name, file in (("RafSerif", "DejaVuSerif.ttf"), ("RafSerif-Bold", "DejaVuSerif-Bold.ttf"), ("RafSerif-Italic", "DejaVuSerif-Italic.ttf"),
                           ("RafSans", "DejaVuSans.ttf"), ("RafSans-Bold", "DejaVuSans-Bold.ttf"), ("RafSans-Oblique", "DejaVuSans-Oblique.ttf")):
            pdfmetrics.registerFont(TTFont(name, str(font_dir / file)))
        pdfmetrics.registerFontFamily("RafSerif", normal="RafSerif", bold="RafSerif-Bold", italic="RafSerif-Italic", boldItalic="RafSerif-Bold")
        pdfmetrics.registerFontFamily("RafSans", normal="RafSans", bold="RafSans-Bold", italic="RafSans-Oblique", boldItalic="RafSans-Bold")
        serif, sans = "RafSerif", "RafSans"
    except Exception:  # noqa: BLE001 - fall back to core fonts
        pass

    accent = colors.HexColor("#" + ACCENT_HEX)
    muted = colors.HexColor("#6B637A")
    S = {
        "body": ParagraphStyle("body", fontName=serif, fontSize=10, leading=15, alignment=TA_JUSTIFY, spaceAfter=7),
        "h1": ParagraphStyle("h1", fontName=sans + ("-Bold" if sans == "RafSans" else "-Bold"), fontSize=13.5, leading=18, textColor=accent, spaceBefore=16, spaceAfter=7, keepWithNext=1),
        "h2": ParagraphStyle("h2", fontName=sans + "-Bold", fontSize=11, leading=15, textColor=accent, spaceBefore=10, spaceAfter=5, keepWithNext=1),
        "kicker": ParagraphStyle("kicker", fontName=sans + "-Bold", fontSize=8, textColor=accent, spaceAfter=10, leading=10),
        "title": ParagraphStyle("title", fontName=sans + "-Bold", fontSize=22, leading=27, spaceAfter=6),
        "subtitle": ParagraphStyle("subtitle", fontName=serif + ("-Italic" if serif == "RafSerif" else ""), fontSize=13, leading=17, textColor=colors.HexColor("#443C55"), spaceAfter=12),
        "meta": ParagraphStyle("meta", fontName=serif, fontSize=9.5, leading=13, textColor=muted),
        "abs": ParagraphStyle("abs", fontName=serif, fontSize=9.5, leading=14, alignment=TA_JUSTIFY),
        "cap": ParagraphStyle("cap", fontName=serif, fontSize=9, leading=12, spaceBefore=8, spaceAfter=4, keepWithNext=1),
        "figcap": ParagraphStyle("figcap", fontName=serif, fontSize=9, leading=12, alignment=TA_CENTER, spaceBefore=4, spaceAfter=12),
        "cell": ParagraphStyle("cell", fontName=sans, fontSize=7.8, leading=10),
        "cellh": ParagraphStyle("cellh", fontName=sans + "-Bold", fontSize=7.8, leading=10),
        "note": ParagraphStyle("note", fontName=serif, fontSize=7.8, leading=10, textColor=muted, spaceAfter=10),
        "ref": ParagraphStyle("ref", fontName=serif, fontSize=9, leading=12.5, leftIndent=18, firstLineIndent=-18, spaceAfter=4),
        "toc1": ParagraphStyle("toc1", fontName=serif, fontSize=10, leading=16),
    }

    class Doc(BaseDocTemplate):
        def afterFlowable(self, flowable):
            if isinstance(flowable, Paragraph) and flowable.style.name in {"h1", "h2"}:
                level = 0 if flowable.style.name == "h1" else 1
                key = f"h{id(flowable)}"
                self.canv.bookmarkPage(key)
                self.canv.addOutlineEntry(flowable.getPlainText(), key, level=level)
                self.notify("TOCEntry", (level, flowable.getPlainText(), self.page, key))

    doc = Doc(str(out), pagesize=A4, leftMargin=2.3 * cm, rightMargin=2.3 * cm, topMargin=2.3 * cm, bottomMargin=2.2 * cm,
              title=a.title, author=", ".join(a.authors) or "RAF", subject="Research article", keywords=a.keywords)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
    short = a.title if len(a.title) < 95 else a.title[:92] + "…"

    def first(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(accent)
        canvas.rect(0, A4[1] - 0.45 * cm, A4[0], 0.45 * cm, stroke=0, fill=1)
        canvas.restoreState()

    def later(canvas, _doc):
        canvas.saveState()
        canvas.setFont(sans, 7.5)
        canvas.setFillColor(muted)
        canvas.drawRightString(A4[0] - doc.rightMargin, A4[1] - 1.4 * cm, short)
        canvas.setStrokeColor(colors.HexColor("#" + RULE_HEX))
        canvas.setLineWidth(0.5)
        canvas.line(doc.leftMargin, A4[1] - 1.55 * cm, A4[0] - doc.rightMargin, A4[1] - 1.55 * cm)
        canvas.drawCentredString(A4[0] / 2, 1.2 * cm, f"{canvas.getPageNumber()}")
        canvas.restoreState()

    doc.addPageTemplates([PageTemplate("first", [frame], onPage=first), PageTemplate("later", [frame], onPage=later)])

    def para(text: str, style: str) -> Paragraph:
        return Paragraph(escape(text), S[style])

    story = [NextPageTemplate("later"), Spacer(1, 1.2 * cm), para("RESEARCH ARTICLE", "kicker"), para(a.title, "title")]
    if a.subtitle:
        story.append(para(a.subtitle, "subtitle"))
    meta = []
    if a.authors:
        meta.append(f"<b>{escape(', '.join(a.authors))}</b>")
    if a.affiliation:
        meta.append(f"<i>{escape(a.affiliation)}</i>")
    meta.append(escape(a.date))
    story += [Paragraph("<br/>".join(meta), S["meta"]), Spacer(1, 14)]
    if a.abstract:
        inner = [Paragraph(f"<font color='#{ACCENT_HEX}'><b>Abstract</b></font>", S["abs"]), Spacer(1, 4), para(a.abstract, "abs")]
        if a.keywords:
            inner += [Spacer(1, 6), Paragraph(f"<b>Keywords:</b> <i>{escape(a.keywords)}</i>", S["abs"])]
        box = RLTable([[inner]], colWidths=[doc.width])
        box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3EFFB")), ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 14), ("RIGHTPADDING", (0, 0), (-1, -1), 14),
                                 ("TOPPADDING", (0, 0), (-1, -1), 12), ("BOTTOMPADDING", (0, 0), (-1, -1), 12)]))
        story += [box, Spacer(1, 16)]
    toc = TableOfContents()
    toc.levelStyles = [S["toc1"], ParagraphStyle("toc2", parent=S["toc1"], leftIndent=16, fontSize=9)]
    story += [Paragraph(f"<font color='#{ACCENT_HEX}'><b>Contents</b></font>", S["body"]), toc, PageBreak()]

    for s in a.sections:
        if s.key == "appendices":
            story.append(PageBreak())
        story.append(para(f"{s.number}. {s.heading}" if s.number else s.heading, "h1"))
        for b in s.blocks:
            if b.kind == "p":
                story.append(para(b.text, "body"))
            elif b.kind == "subhead":
                story.append(para(b.text, "h2"))
            elif b.kind == "ref":
                story.append(para(b.text, "ref"))
            elif b.kind == "table" and b.table:
                tb = b.table
                cols = max(len(tb.columns), max((len(r) for r in tb.rows), default=1))
                data = [[Paragraph(escape(c), S["cellh"]) for c in tb.columns] + [""] * (cols - len(tb.columns))]
                data += [[Paragraph(escape(str(v)), S["cell"]) for v in r[:cols]] + [""] * (cols - len(r[:cols])) for r in tb.rows]
                weights = [max(4, min(40, max(len(str(r[i])) if i < len(r) else 0 for r in [tb.columns, *tb.rows]))) for i in range(cols)]
                widths = [doc.width * w / sum(weights) for w in weights]
                t = RLTable(data, colWidths=widths, repeatRows=1)
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDE6FA")), ("LINEABOVE", (0, 0), (-1, 0), 1.1, accent),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.6, accent), ("LINEBELOW", (0, -1), (-1, -1), 1.1, accent),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAF8FE")]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]))
                cap = Paragraph(f"<font color='#{ACCENT_HEX}'><b>{table_label(tb)}.</b></font> <i>{escape(_clean_caption(tb.caption))}</i>", S["cap"])
                story.append(cap)
                story.append(t)
                story.append(Paragraph(f"<i>Note.</i> {escape(tb.note)}", S["note"]) if tb.note else Spacer(1, 10))
            elif b.kind == "figure" and b.figure:
                img_path = a.project_dir / b.figure.path
                if img_path.exists():
                    from PIL import Image as PILImage

                    w, h = PILImage.open(img_path).size
                    width = min(doc.width, 15 * cm)
                    height = width * h / w
                    if height > 11.5 * cm:
                        height, width = 11.5 * cm, 11.5 * cm * w / h
                    story.append(KeepTogether([Image(str(img_path), width=width, height=height),
                                               Paragraph(f"<font color='#{ACCENT_HEX}'><b>Figure {b.figure.number}.</b></font> <i>{escape(_clean_caption(b.figure.caption))}</i>", S["figcap"])]))
    doc.multiBuild(story)
    return out


# ====================================================================== Markdown
def to_markdown(a: Article) -> str:
    lines = [f"# {a.title}"]
    if a.subtitle:
        lines.append(f"## {a.subtitle}")
    if a.authors:
        lines.append(f"**{', '.join(a.authors)}**  ")
    if a.affiliation:
        lines.append(f"*{a.affiliation}*  ")
    lines.append(a.date + "\n")
    if a.abstract:
        lines += ["## Abstract", a.abstract, ""]
    if a.keywords:
        lines += [f"**Keywords:** {a.keywords}", ""]
    for s in a.sections:
        lines.append(f"## {s.number + '. ' if s.number else ''}{s.heading}\n")
        for b in s.blocks:
            if b.kind == "p":
                lines.append(b.text + "\n")
            elif b.kind == "subhead":
                lines.append(f"### {b.text}\n")
            elif b.kind == "ref":
                lines.append(f"- {b.text}")
            elif b.kind == "table" and b.table:
                t = b.table
                lines.append(f"\n**{table_label(t)}.** *{_clean_caption(t.caption)}*\n")
                lines.append("| " + " | ".join(t.columns) + " |")
                lines.append("|" + "---|" * len(t.columns))
                for r in t.rows:
                    lines.append("| " + " | ".join(str(x).replace("|", "/") for x in r) + " |")
                if t.note:
                    lines.append(f"\n*Note.* {t.note}")
                lines.append("")
            elif b.kind == "figure" and b.figure:
                img = a.project_dir / b.figure.path
                if img.exists():
                    data = base64.b64encode(img.read_bytes()).decode()
                    lines.append(f"![Figure {b.figure.number}](data:image/png;base64,{data})\n")
                lines.append(f"**Figure {b.figure.number}.** *{_clean_caption(b.figure.caption)}*\n")
        lines.append("")
    return "\n".join(lines)


# ====================================================================== import
def import_document(p: Project, path: Path) -> dict[str, str]:
    """Split an edited DOCX / Markdown / PDF back into segments by matching its headings to segment titles."""
    from rapidfuzz import fuzz, process

    from .ingest import read_any

    doc = read_any(path)
    text = doc.text
    titles = {BLUEPRINTS[k].title: k for k in p.segments}
    aliases = {"Literature Review": "literature_review", "Results": "results", "Analysis": "results", "Conclusion": "conclusion",
               "Conclusions": "conclusion", "Limitations": "limitations", "Future Research": "limitations", "Bibliography": "references"}
    choices = {**titles, **{k: v for k, v in aliases.items() if v in p.segments}}

    lines = text.splitlines()
    marks: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        clean = re.sub(r"^\d+(\.\d+)*\.?\s*", "", re.sub(r"^#+\s*", "", line.strip()))
        if not clean or len(clean) > 60:
            continue
        match = process.extractOne(clean, list(choices), scorer=fuzz.ratio)
        if match and match[1] >= 88:
            marks.append((i, choices[match[0]]))
    out: dict[str, str] = {}
    for n, (start, key) in enumerate(marks):
        end = marks[n + 1][0] if n + 1 < len(marks) else len(lines)
        body = "\n".join(lines[start + 1 : end]).strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        if body and key not in out:
            out[key] = body
    return out
