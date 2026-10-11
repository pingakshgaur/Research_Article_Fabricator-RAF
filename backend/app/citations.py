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
    return re.sub(r"\s+([.,;])(?!\d)", r"\1", out)      # not before a digit: "p = .05" keeps its space


def format_reference(src: Reference | WebSource, style: str, number: int | None = None) -> str:
    authors = [a for a in src.authors if a.strip()]
    year = src.year or "n.d."
    title = src.title.strip().rstrip(".") or "Untitled"
    venue = src.venue.strip()
    # volume, issue and pages exist only on sources completed from Crossref (see `details`); they follow the venue
    volume, issue, pages = (str(getattr(src, k, "") or "") for k in ("volume", "issue", "pages"))
    if venue and (volume or pages):
        venue += (f", {volume}" + (f"({issue})" if issue else "") if volume else "") + (f", {pages}" if pages else "")
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


# ---------------------------------------------------------------------------- BibTeX and RIS
def _ascii(text: str) -> str:
    import unicodedata
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower())


def bib_keys(p: Project, labels: list[str]) -> dict[str, str]:
    """label (R1, W3 …) -> citation key such as smith2021digital; unique within the project."""
    sources = label_map(p)
    keys: dict[str, str] = {}
    for label in labels:
        src = sources.get(label)
        if src is None:
            continue
        who = _ascii(surname(src.authors[0])) if src.authors else ""
        word = next((w for w in (_ascii(x) for x in src.title.split()) if len(w) > 3), "source")
        base = (who or word) + (re.sub(r"\D", "", src.year)[:4] or "nd") + (word if who else "")
        key, n = base, 1
        while key in keys.values():
            n += 1
            key = base + chr(96 + n)       # smith2021digital, smith2021digitalb …
        keys[label] = key
    return keys


def _bib_name(n: str) -> str:
    n = n.strip()
    if "," in n or " " not in n:
        return n
    parts = n.split()
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


_BIB_ESCAPE = {"&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": "", "}": "", "~": r"\textasciitilde{}", "^": "", "\\": ""}


def _bib(text: str) -> str:
    return "".join(_BIB_ESCAPE.get(ch, ch) for ch in str(text))


def details(doi: str) -> dict:
    """Volume, issue and pages of a work from Crossref, or {} when it cannot be reached. Best effort; never raises."""
    import httpx

    from .config import settings
    try:
        r = httpx.get(f"https://api.crossref.org/works/{doi}", params={"mailto": settings.contact_email}, timeout=6)
        if r.status_code != 200:
            return {}
        m = r.json()["message"]
        return {k: str(m[src]) for k, src in (("volume", "volume"), ("issue", "issue"), ("pages", "page")) if m.get(src)}
    except Exception:  # noqa: BLE001
        return {}


def bibtex(p: Project, labels: list[str], enrich: bool = False) -> str:
    """The reference list as BibTeX. `enrich` completes sources that have a DOI with volume, issue and pages from Crossref."""
    sources, keys, out = label_map(p), bib_keys(p, labels), []
    for label, key in keys.items():
        src = sources[label]
        extra = details(src.doi) if enrich and src.doi else {}
        url = getattr(src, "url", "") or ""
        kind = "article" if src.venue and getattr(src, "source", "") not in {"web", "wikipedia"} else "online" if url else "misc"
        fields = [("author", " and ".join(_bib_name(a) for a in src.authors if a.strip())), ("title", "{" + _bib(src.title.strip().rstrip(".")) + "}"),
                  ("journal" if kind == "article" else "organization" if kind == "online" else "howpublished", _bib(src.venue)),
                  ("year", re.sub(r"\D", "", src.year)[:4]), ("volume", extra.get("volume", "")), ("number", extra.get("issue", "")),
                  ("pages", extra.get("pages", "").replace("-", "--").replace("----", "--")), ("doi", src.doi), ("url", "" if src.doi else url)]
        body = ",\n".join(f"  {name} = {{{value if name in ('title', 'doi', 'url') else _bib(value)}}}" for name, value in fields if value)
        out.append(f"@{kind}{{{key},\n{body}\n}}")
    return "\n\n".join(out) + "\n"


def ris(p: Project, labels: list[str]) -> str:
    """The reference list in RIS, the format Zotero, Mendeley and EndNote import."""
    sources, out = label_map(p), []
    for label in labels:
        src = sources.get(label)
        if src is None:
            continue
        url = getattr(src, "url", "") or ""
        lines = [("TY", "JOUR" if src.venue and getattr(src, "source", "") not in {"web", "wikipedia"} else "ELEC" if url else "GEN"),
                 *[("AU", _bib_name(a)) for a in src.authors if a.strip()], ("TI", src.title.strip().rstrip(".")), ("JO", src.venue),
                 ("PY", re.sub(r"\D", "", src.year)[:4]), ("DO", src.doi), ("UR", f"https://doi.org/{src.doi}" if src.doi else url), ("ER", "")]
        out.append("\n".join(f"{tag}  - {value}" for tag, value in lines if value or tag == "ER"))
    return "\n\n".join(out) + "\n"
