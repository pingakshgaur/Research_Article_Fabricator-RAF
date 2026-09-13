"""Citation markers ([R3], [W7]) → formatted in-text citations and reference lists (APA, Harvard, Chicago, IEEE)."""
from __future__ import annotations

import re

from .models import Project, Reference, WebSource

MARKER = re.compile(r"\[((?:[RW]\d+)(?:\s*[,;]\s*[RW]\d+)*)\]")


def label_map(p: Project) -> dict[str, Reference | WebSource]:
    m: dict[str, Reference | WebSource] = {}
    for i, r in enumerate([r for r in p.references if r.status == "parsed"], 1):
        m[f"R{i}"] = r
    for i, w in enumerate(p.web_sources, 1):
        m[f"W{i}"] = w
    return m


def surname(author: str) -> str:
    author = author.strip()
    if "," in author:
        return author.split(",")[0].strip()
    parts = author.split()
    return parts[-1] if parts else author


def short_label(src: Reference | WebSource) -> str:
    year = src.year or "n.d."
    names = [surname(a) for a in src.authors if a.strip()]
    if not names:
        return f"{_short_title(src.title)}, {year}"
    if len(names) == 1:
        return f"{names[0]}, {year}"
    if len(names) == 2:
        return f"{names[0]} & {names[1]}, {year}"
    return f"{names[0]} et al., {year}"


def _short_title(title: str) -> str:
    words = title.split()
    return "“" + " ".join(words[:5]) + ("…" if len(words) > 5 else "") + "”"


def cited_labels(texts: list[str]) -> list[str]:
    """Labels in order of first appearance."""
    order: list[str] = []
    for t in texts:
        for group in MARKER.findall(t):
            for lab in re.split(r"\s*[,;]\s*", group):
                if lab not in order:
                    order.append(lab)
    return order


def render_in_text(text: str, p: Project, order: list[str]) -> str:
    labels = label_map(p)
    numeric = p.citation_style == "IEEE"

    def repl(m: re.Match) -> str:
        labs = [l for l in re.split(r"\s*[,;]\s*", m.group(1)) if l in labels]
        if not labs:
            return ""
        if numeric:
            nums = sorted({order.index(l) + 1 for l in labs if l in order})
            return "[" + ", ".join(map(str, nums)) + "]"
        seen, parts = set(), []
        for l in labs:
            s = short_label(labels[l])
            if s not in seen:
                seen.add(s)
                parts.append(s)
        return "(" + "; ".join(parts) + ")"

    out = MARKER.sub(repl, text)
    return re.sub(r"\s+([.,;])", r"\1", out)


def format_reference(src: Reference | WebSource, style: str, number: int | None = None) -> str:
    authors = [a for a in src.authors if a.strip()]
    year = src.year or "n.d."
    title = src.title.strip().rstrip(".") or "Untitled"
    venue = src.venue.strip()
    doi = f"https://doi.org/{src.doi}" if src.doi else ""
    url = getattr(src, "url", "") or ""
    link = doi or url

    def apa_names(names: list[str]) -> str:
        fmt = [_apa_name(n) for n in names[:20]]
        if not fmt:
            return ""
        if len(fmt) == 1:
            return fmt[0]
        return ", ".join(fmt[:-1]) + ", & " + fmt[-1]

    if style == "IEEE":
        names = ", ".join(_ieee_name(n) for n in authors[:6]) + (" et al." if len(authors) > 6 else "")
        parts = [f"[{number}]", f"{names}," if names else "", f"“{title},”", f"{venue}," if venue else "", f"{year}."]
        return " ".join(x for x in parts if x) + (f" {link}" if link else "")
    if style == "Chicago":
        names = "; ".join(authors[:10])
        return " ".join(x for x in [f"{names}." if names else "", f"{year}.", f"“{title}.”", f"{venue}." if venue else "", link] if x)
    if style == "Harvard":
        names = apa_names(authors).replace(", &", " and")
        return " ".join(x for x in [names, f"({year})", f"'{title}',", f"{venue}." if venue else "", f"Available at: {link}" if link else ""] if x)
    # APA 7
    names = apa_names(authors)
    lead = f"{names} ({year})." if names else f"{title}. ({year})."
    body = f"{title}." if names else ""
    return " ".join(x for x in [lead, body, f"{venue}." if venue else "", link] if x)


def _apa_name(n: str) -> str:
    n = n.strip()
    if "," in n:
        last, first = [x.strip() for x in n.split(",", 1)]
    else:
        bits = n.split()
        if len(bits) == 1:
            return n
        last, first = bits[-1], " ".join(bits[:-1])
    initials = " ".join(f"{w[0]}." for w in re.split(r"[\s\-.]+", first) if w and w[0].isalpha())
    return f"{last}, {initials}".strip(", ")


def _ieee_name(n: str) -> str:
    apa = _apa_name(n)
    if ", " in apa:
        last, initials = apa.split(", ", 1)
        return f"{initials} {last}"
    return apa


def reference_list(p: Project, texts: list[str]) -> tuple[list[str], list[str]]:
    """Returns (formatted entries, label order). Uploaded references are always listed; web sources only when cited."""
    labels = label_map(p)
    order = [l for l in cited_labels(texts) if l in labels]
    for l in labels:
        if l.startswith("R") and l not in order:
            order.append(l)
    if p.citation_style == "IEEE":
        return [format_reference(labels[l], "IEEE", i) for i, l in enumerate(order, 1)], order
    entries = sorted((format_reference(labels[l], p.citation_style) for l in order), key=lambda s: s.lower().lstrip("“'\""))
    return entries, order
