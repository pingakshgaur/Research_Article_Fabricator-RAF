"""LaTeX export: the article as a .zip with main.tex, references.bib, the figures and a short read-me.

Each of RAF's five templates maps to a LaTeX set-up:

    modern_report      article + coloured sans headings, shaded abstract, contents
    classic_journal    article, centred serif title, ruled abstract, indented paragraphs
    apa_manuscript     apa7 class in manuscript mode
    conference         IEEEtran, two columns
    minimal_monograph  article with wide margins and large serif headings

Citations are real: RAF's markers become \\parencite{…} and the sources go into references.bib, so the journal's own
style can restyle them (biblatex + biber). A project made by "Format an existing article" has no structured sources;
its reference list is printed as the author wrote it.

Only widely available packages are used. RAF does not compile the result itself.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from . import citations, publisher
from .models import Project

BIBLATEX = {   # RAF citation style -> biblatex set-up
    "APA": r"\usepackage[style=apa,backend=biber]{biblatex}",
    "Harvard": r"\usepackage[style=authoryear,maxcitenames=2,backend=biber]{biblatex}",
    "Chicago": r"\usepackage[authordate,backend=biber]{biblatex-chicago}",
    "IEEE": r"\usepackage[style=ieee,backend=biber]{biblatex}",
}
SPECIAL = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
           "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "<": r"\textless{}", ">": r"\textgreater{}", "|": r"\textbar{}"}
UNICODE = {   # characters pdfLaTeX cannot be trusted with, written the LaTeX way
    "“": "``", "”": "''", "‘": "`", "’": "'", "–": "--", "—": "---", "…": r"\ldots{}", " ": "~", " ": r"\,", "•": r"\textbullet{}",
    "×": r"$\times$", "≥": r"$\geq$", "≤": r"$\leq$", "±": r"$\pm$", "−": r"$-$", "→": r"$\rightarrow$", "←": r"$\leftarrow$", "·": r"$\cdot$",
    "≈": r"$\approx$", "≠": r"$\neq$", "∞": r"$\infty$", "√": r"$\surd$", "°": r"\textdegree{}", "€": r"\texteuro{}", "£": r"\pounds{}", "§": r"\S{}",
    "²": r"\textsuperscript{2}", "³": r"\textsuperscript{3}", "¹": r"\textsuperscript{1}", "½": r"$\frac{1}{2}$", "‰": r"\textperthousand{}",
    "α": r"$\alpha$", "β": r"$\beta$", "γ": r"$\gamma$", "δ": r"$\delta$", "ε": r"$\varepsilon$", "η": r"$\eta$", "θ": r"$\theta$", "κ": r"$\kappa$",
    "λ": r"$\lambda$", "μ": r"$\mu$", "π": r"$\pi$", "ρ": r"$\rho$", "σ": r"$\sigma$", "τ": r"$\tau$", "φ": r"$\varphi$", "χ": r"$\chi$", "ω": r"$\omega$",
    "Δ": r"$\Delta$", "Σ": r"$\Sigma$", "Ω": r"$\Omega$", "✓": r"$\checkmark$",
}
ROWS_PER_TABLE = 30     # a float cannot break across pages, so longer tables are continued in a second float


def esc(text: str) -> str:
    """Plain text -> LaTeX source."""
    return "".join(SPECIAL.get(ch) or UNICODE.get(ch) or ch for ch in str(text))


def rich(text: str, on: bool) -> str:
    """Escape, keeping bold / italic / superscript / subscript where the article carries them (formatted imports)."""
    wrap = {"b": r"\textbf{%s}", "i": r"\textit{%s}", "sup": r"\textsuperscript{%s}", "sub": r"\textsubscript{%s}", "": "%s"}
    return "".join(wrap[style] % esc(part) for part, style in publisher.inline_runs(text, on))


def prose(text: str, keys: dict[str, str], on: bool) -> str:
    """A paragraph with RAF's citation markers turned into \\parencite commands."""
    out = []
    for i, part in enumerate(citations.MARKER.split(text)):
        if i % 2 == 0:
            out.append(rich(part, on))
            continue
        cited = [keys[label] for label in re.split(r"\s*[,;]\s*", part) if label in keys]
        if cited:
            out.append(r"\parencite{" + ",".join(dict.fromkeys(cited)) + "}")
    return re.sub(r"\s+([.,;:])(?!\d)", r"\1", "".join(out)).strip()


def _table(t, columns: int) -> list[str]:
    cols = max(len(t.columns), max((len(r) for r in t.rows), default=0), 1)
    spec = "@{}" + r">{\raggedright\arraybackslash}X" * cols + "@{}"
    pad = lambda cells: " & ".join(esc(c) for c in [*cells, *[""] * (cols - len(cells))][:cols]) + r" \\"
    out = []
    chunks = [t.rows[i:i + ROWS_PER_TABLE] for i in range(0, len(t.rows), ROWS_PER_TABLE)] or [[]]
    for n, rows in enumerate(chunks):
        caption = esc(t.caption.rstrip(".")) + ("." if n == 0 else " (continued).")
        out += [r"\begin{table}[htbp]", r"\caption*{\textbf{" + esc(publisher.table_label(t)) + ".} " + caption + "}",
                r"\footnotesize" if columns == 2 or cols > 5 else r"\small", r"\begin{tabularx}{\linewidth}{" + spec + "}", r"\toprule",
                " & ".join(r"\textbf{" + esc(c) + "}" for c in [*t.columns, *[""] * (cols - len(t.columns))][:cols]) + r" \\", r"\midrule",
                *[pad([str(v) for v in row]) for row in rows], r"\bottomrule", r"\end{tabularx}"]
        if t.note and n == len(chunks) - 1:
            out.append(r"\par\smallskip{\footnotesize\textit{Note.} " + esc(t.note) + "}")
        out += [r"\end{table}", ""]
    return out


def _preamble(tpl, pal, style: str, has_bib: bool) -> list[str]:
    cls = {"apa_manuscript": r"\documentclass[man,12pt,a4paper]{apa7}", "conference": r"\documentclass[conference,a4paper]{IEEEtran}"}.get(
        tpl.key, r"\documentclass[%dpt,a4paper]{article}" % (11 if tpl.body_pt >= 10.5 else 10))
    top, right, bottom, left = tpl.margins_cm
    out = [cls, r"\usepackage{iftex}", r"\ifPDFTeX", r"  \usepackage[T1]{fontenc}", r"  \usepackage[utf8]{inputenc}", r"  \usepackage{textcomp}", r"\else", r"  \usepackage{fontspec}", r"\fi",
           r"\usepackage{amssymb}", r"\usepackage{graphicx}", r"\usepackage{booktabs}", r"\usepackage{tabularx}", r"\usepackage{array}", r"\usepackage{xcolor}",
           r"\usepackage{caption}", r"\usepackage{csquotes}"]
    if tpl.key not in {"apa_manuscript", "conference"}:
        out.append(r"\usepackage[a4paper,top=%.2fcm,right=%.2fcm,bottom=%.2fcm,left=%.2fcm]{geometry}" % (top, right, bottom, left))
        out.append(r"\usepackage{titlesec}")
    if tpl.key == "apa_manuscript":
        out.append(r"\usepackage[american]{babel}")
    out += [r"\definecolor{accent}{HTML}{%s}" % pal["accent"], r"\definecolor{accentfill}{HTML}{%s}" % pal["fill"]]
    if has_bib:
        out += [BIBLATEX.get(style, BIBLATEX["APA"]), r"\addbibresource{references.bib}"]
        if tpl.key == "apa_manuscript" and style == "APA":
            out.append(r"\DeclareLanguageMapping{american}{american-apa}")
    if tpl.key == "modern_report":
        out += [r"\titleformat*{\section}{\sffamily\bfseries\Large\color{accent}}", r"\titleformat*{\subsection}{\sffamily\bfseries\large\color{accent}}"]
    elif tpl.key == "classic_journal":
        out += [r"\titleformat*{\section}{\bfseries\large}", r"\setlength{\parindent}{0.6cm}"]
    elif tpl.key == "minimal_monograph":
        out += [r"\titleformat*{\section}{\bfseries\LARGE}", r"\titleformat*{\subsection}{\bfseries\Large}", r"\raggedright", r"\setlength{\parskip}{0.7em}"]
    if tpl.key in {"modern_report", "minimal_monograph"}:
        out.append(r"\setlength{\parskip}{0.6em}\setlength{\parindent}{0pt}")
    out.append(r"\usepackage[hidelinks]{hyperref}")
    return out


def _front(a, tpl) -> list[str]:
    title = esc(a.title) + (": " + esc(a.subtitle) if a.subtitle else "")
    authors = ", ".join(esc(x) for x in a.authors)
    keywords = ", ".join(esc(k.strip()) for k in re.split(r"[;,]", a.keywords) if k.strip())
    abstract = rich(a.abstract, a.rich)
    if tpl.key == "apa_manuscript":
        short = esc(a.title if len(a.title) <= 50 else a.title[:47].rsplit(" ", 1)[0] + "…")
        out = [r"\title{" + title + "}", r"\shorttitle{" + short + "}", r"\authorsnames{" + (authors or "Author") + "}",
               r"\authorsaffiliations{" + (esc(a.affiliation) or "Affiliation") + "}"]
        if abstract:
            out.append(r"\abstract{" + abstract + "}")
        if keywords:
            out.append(r"\keywords{" + keywords + "}")
        return [*out, r"\begin{document}", r"\maketitle", ""]
    if tpl.key == "conference":
        out = [r"\title{" + title + "}", r"\author{\IEEEauthorblockN{" + (authors or "Author") + "}" + (r"\IEEEauthorblockA{" + esc(a.affiliation) + "}" if a.affiliation else "") + "}",
               r"\begin{document}", r"\maketitle"]
        if abstract:
            out += [r"\begin{abstract}", abstract, r"\end{abstract}"]
        if keywords:
            out += [r"\begin{IEEEkeywords}", keywords, r"\end{IEEEkeywords}"]
        return [*out, ""]
    centred = tpl.title_align == "center"
    env = "center" if centred else "flushleft"
    font = "" if tpl.heading_serif else r"\sffamily"
    out = [r"\begin{document}", r"\begin{" + env + "}"]
    if tpl.kicker:
        out.append(r"{" + font + r"\bfseries\footnotesize\color{accent} " + esc(tpl.kicker) + r"\par}\vspace{6pt}")
    out.append(r"{" + font + r"\bfseries\LARGE " + esc(a.title) + r"\par}")
    if a.subtitle:
        out.append(r"\vspace{4pt}{\itshape\large " + esc(a.subtitle) + r"\par}")
    out.append(r"\vspace{8pt}")
    if authors:
        out.append(r"{\bfseries " + authors + r"\par}")
    if a.affiliation:
        out.append(r"{\itshape " + esc(a.affiliation) + r"\par}")
    out += [r"{\small " + esc(a.date) + r"\par}", r"\end{" + env + "}"]
    if tpl.cover in {"band", "rule"}:
        out.append(r"{\color{accent}\hrule height 1.2pt}\vspace{10pt}")
    if abstract:
        kw = (r"\par\smallskip\textbf{Keywords:} \textit{" + keywords + "}") if keywords else ""
        if tpl.abstract_style == "box":
            out += [r"\noindent\colorbox{accentfill}{\parbox{\dimexpr\linewidth-2\fboxsep\relax}{\vspace{4pt}{" + font + r"\bfseries\color{accent} Abstract}\par\smallskip",
                    abstract + kw + r"\vspace{4pt}}}", r"\vspace{10pt}"]
        elif tpl.abstract_style == "rules":
            out += [r"{\color{accent}\hrule}\vspace{6pt}", r"\begin{center}{\bfseries\color{accent} ABSTRACT}\end{center}", r"\noindent " + abstract + kw, r"\vspace{6pt}{\color{accent}\hrule}\vspace{10pt}"]
        else:
            out += [r"\noindent{\bfseries\large\color{accent} Abstract}\par\smallskip", r"\noindent " + abstract + kw, r"\vspace{10pt}"]
    if tpl.toc:
        out += [r"\tableofcontents", r"\newpage"]
    return [*out, ""]


def to_latex(p: Project, out: Path, template: str | None = None, palette: str | None = None, only_approved: bool = False, enrich: bool = False) -> Path:
    """Write <out> (a .zip). `enrich` asks Crossref for volume, issue and pages of sources that have a DOI."""
    tpl, pal = publisher.resolve_style(template, palette)
    a = publisher.assemble(p, only_approved=only_approved, markers=True)
    keys = citations.bib_keys(p, a.cite_order)
    has_bib = bool(keys)
    body: list[str] = []
    figures: list[Path] = []
    for s in a.sections:
        if s.key == "references" and has_bib:      # RAF's own list: printed by biblatex from references.bib
            body += [r"\nocite{*}", r"\printbibliography[title={" + esc(s.heading) + "}]", ""]
            continue
        body.append((r"\section{%s}" if s.number else r"\section*{%s}") % esc(s.heading))
        if not s.number and tpl.toc:
            body.append(r"\addcontentsline{toc}{section}{" + esc(s.heading) + "}")
        if s.key == "references":                  # a formatted import: the list as the author wrote it
            body += [r"\begin{list}{}{\setlength{\leftmargin}{1.5em}\setlength{\itemindent}{-1.5em}\setlength{\itemsep}{2pt}}",
                     *[r"\item " + esc(publisher.plain(b.text)) for b in s.blocks if b.kind == "ref"], r"\end{list}", ""]
            continue
        for b in s.blocks:
            if b.kind == "p":
                body += [prose(b.text, keys, a.rich), ""]
            elif b.kind == "subhead":
                body += [r"\subsection*{" + esc(b.text) + "}", ""]
            elif b.kind == "ref":
                body += [r"\noindent\hangindent=1.5em " + esc(publisher.plain(b.text)), ""]
            elif b.kind == "table" and b.table:
                body += _table(b.table, tpl.columns)
            elif b.kind == "figure" and b.figure and (a.project_dir / b.figure.path).exists():
                figures.append(a.project_dir / b.figure.path)
                body += [r"\begin{figure}[htbp]", r"\centering", r"\includegraphics[width=\linewidth,height=0.45\textheight,keepaspectratio]{figures/" + Path(b.figure.path).name + "}",
                         r"\caption*{\textbf{Figure " + str(b.figure.number) + ".} " + esc(b.figure.caption.rstrip(".")) + ".}", r"\end{figure}", ""]
    tex = "\n".join([f"% {a.title} — exported by RAF (Research Article Fabricator). Compile with latexmk, or upload the .zip to Overleaf.",
                     *_preamble(tpl, pal, p.citation_style, has_bib), "", *_front(a, tpl), *body, r"\end{document}", ""])
    readme = "\n".join([
        f"{a.title}", "", "Files", "  main.tex         the article", *(["  references.bib   every source of the reference list (BibTeX)"] if has_bib else []),
        *(["  figures/         the charts"] if figures else []), "",
        "Overleaf", "  New Project -> Upload Project -> choose this .zip. It compiles as it is.", "",
        "On your own computer (TeX Live or MiKTeX)", "  latexmk -pdf main.tex" + ("      (runs biber for the references by itself)" if has_bib else ""), "",
        f"Layout: {tpl.name}." + (f" Citations: biblatex, {p.citation_style} style; change the \\usepackage line for biblatex in main.tex to restyle them." if has_bib else ""),
        "Table and figure numbers are written out as in the article, so the text and its references to them always agree.", ""])
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("main.tex", tex)
        if has_bib:
            z.writestr("references.bib", citations.bibtex(p, a.cite_order, enrich=enrich))
        for f in dict.fromkeys(figures):
            z.write(f, f"figures/{f.name}")
        z.writestr("README.txt", readme)
    return out
