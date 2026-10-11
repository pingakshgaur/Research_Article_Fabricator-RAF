"""The structure of one article: which segments it has, under what titles, in what order, and which go into the document.

RAF's twelve built-in segments (blueprints.py) are the starting point of every project, not a limit. A project can
  * rename a built-in segment          Project.titles
  * add its own segments               Project.custom_segments   (written by RAF from a purpose, or written by the author)
  * put body segments in another order Project.order
  * leave a segment out of the document without deleting it      Project.excluded

Everything else in RAF asks this module instead of reading the global BLUEPRINTS table:
`blueprint_for` for the writing rules of a segment, `order` for the reading order, `generation_order` and `deps` for
the writing order, `describe` for what the interface shows.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import replace

from .blueprints import BLUEPRINTS, Blueprint, Move, length_profile
from .models import CustomSegment, Project

FRONT = ("title", "abstract", "keywords")            # typeset as the title block; always first, never numbered
UNNUMBERED = {"references", "appendices"}
LENGTH_LIMITS = {"abstract": (100, 400)}
DEFAULT_LIMITS = (100, 6000)
MAX_CUSTOM = 12
CUSTOM_CHECKS = ("Does the section do what its stated purpose asks?", "Are its factual claims supported by citations?",
                 "Is it specific to this article rather than generic?", "Does it connect to the rest of the article?")

GALLERY = [   # common additions, one click each
    {"id": "theoretical_framework", "title": "Theoretical Framework", "kind": "generated", "after": "literature_review", "words": 600,
     "purpose": "Set out the theory or conceptual model the study rests on, define its constructs and explain how they relate to each other."},
    {"id": "hypotheses", "title": "Hypothesis Development", "kind": "generated", "after": "literature_review", "words": 500,
     "purpose": "Derive the study's hypotheses or propositions step by step from the reviewed literature and state each one explicitly."},
    {"id": "case_description", "title": "Case Description", "kind": "generated", "after": "methodology", "words": 500,
     "purpose": "Describe the case, setting or organisation that was studied: its context, relevant history and why it was chosen."},
    {"id": "policy_context", "title": "Policy Context", "kind": "generated", "after": "introduction", "words": 450,
     "purpose": "Explain the policy, regulatory or institutional background of the topic and how it has changed."},
    {"id": "acknowledgements", "title": "Acknowledgements", "kind": "manual", "starter": "The authors thank … for …"},
    {"id": "funding", "title": "Funding", "kind": "manual",
     "starter": "This research received no specific grant from any funding agency in the public, commercial or not-for-profit sectors."},
    {"id": "conflict", "title": "Conflict of Interest", "kind": "manual", "starter": "The authors declare no conflict of interest."},
    {"id": "data_availability", "title": "Data Availability", "kind": "manual",
     "starter": "The data that support the findings of this study are available from the corresponding author upon reasonable request."},
    {"id": "contributions", "title": "Author Contributions", "kind": "manual",
     "starter": "Conceptualisation: …; Methodology: …; Formal analysis: …; Writing – original draft: …; Writing – review and editing: …"},
    {"id": "ai_use", "title": "AI-Use Statement", "kind": "manual", "starter": ""},   # filled from the project's History when added
]


def _plain(text: str, limit: int) -> str:
    """One clean line. Braces are dropped because titles and purposes end up inside str.format() query templates."""
    return " ".join(str(text).replace("{", "").replace("}", "").split())[:limit]


# ---------------------------------------------------------------------------- lookups
def exists(p: Project, key: str) -> bool:
    return key in BLUEPRINTS or key in p.custom_segments or key in p.segments


def is_custom(key: str) -> bool:
    return key not in BLUEPRINTS


def default_moves(title: str, purpose: str) -> list[dict]:
    """Three parts that suit almost any section; used until the author (or RAF's proposal) replaces them."""
    return [
        {"name": "Purpose and context", "share": 0.25, "queries": [f"{title} {{topic}}", f"{title} background {{title}}"],
         "instruction": f"Open by establishing what this section covers and why the article needs it. Section purpose: {purpose}"},
        {"name": "Core content", "share": 0.55, "queries": [f"{title} {{title}}", f"{title} evidence {{topic}}", f"{title} theory findings"],
         "instruction": f"Develop the substance of the section in full: {purpose} Compare what different sources say, and be specific to this article's topic."},
        {"name": "Link to the article", "share": 0.2, "queries": [],
         "instruction": "Close by stating what this section establishes for the article's aim and how it leads into what follows."},
    ]


def _custom(p: Project, key: str) -> CustomSegment:
    c = p.custom_segments.get(key)
    if c is None:
        seg = p.segments.get(key)
        if seg is None:
            raise KeyError(key)
        c = CustomSegment(key=key, title=seg.title, kind="manual")     # definition lost (e.g. a very old revision): keep the text editable
    return c


def blueprint_for(p: Project, key: str) -> Blueprint:
    """The writing rules of a segment in this project: a built-in blueprint (under the project's title for it) or a custom one."""
    if key in BLUEPRINTS:
        title = p.titles.get(key)
        return replace(BLUEPRINTS[key], title=title) if title else BLUEPRINTS[key]
    c = _custom(p, key)
    manual = c.kind == "manual"
    # Stored parts are brace-free (clean_moves), so only the built-in default parts carry {title}/{topic} query templates.
    moves = () if manual else tuple(Move(m["name"], m["instruction"], tuple(m.get("queries", [])), float(m.get("share", 0.3)))
                                    for m in (c.moves or default_moves(c.title, c.purpose)))
    display = order(p).index(key) if key in order(p) else 99
    return Blueprint(
        key=key, title=c.title, description=c.purpose or f"{c.title} — a section added by the author.", order=_generation_rank(p, key), display_order=display,
        word_share=0.0, moves=moves, rules=(f"This section's purpose: {c.purpose}",) if c.purpose and not manual else (),
        checks=() if manual else CUSTOM_CHECKS, depends_on=tuple(_preceding_body(p, key)[-2:]) if not manual else (),
        needs_evidence=c.cites and not manual, citations=True, special="manual" if manual else "", extra={"custom": True, "numbered": c.numbered, "kind": c.kind})


def title_of(p: Project, key: str) -> str:
    return blueprint_for(p, key).title


def cites(p: Project, key: str) -> bool:
    """Does RAF write this segment from evidence, with citations? (Then the article needs a reference list.)"""
    if key in BLUEPRINTS:
        bp = BLUEPRINTS[key]
        return bp.citations and bp.needs_evidence
    c = _custom(p, key)
    return c.kind == "generated" and c.cites


def lengthable(p: Project, key: str) -> bool:
    if key in BLUEPRINTS:
        return BLUEPRINTS[key].word_share > 0 or key == "abstract"
    return _custom(p, key).kind == "generated"


def numbered(p: Project, key: str) -> bool:
    if key in BLUEPRINTS:
        return key not in UNNUMBERED and key not in FRONT
    return _custom(p, key).numbered


def included(p: Project, key: str) -> bool:
    return key not in p.excluded


# ---------------------------------------------------------------------------- order
def order(p: Project, keys=None) -> list[str]:
    """Reading order. Front matter first; the rest as the author arranged it, new or unknown keys in their usual place."""
    known = list(BLUEPRINTS) + [k for k in p.custom_segments if k not in BLUEPRINTS] + [k for k in p.segments if k not in BLUEPRINTS and k not in p.custom_segments]
    usual = sorted((k for k in BLUEPRINTS if k not in FRONT), key=lambda k: BLUEPRINTS[k].display_order)
    arranged = [k for k in p.order if k in known and k not in FRONT]
    for k in known:
        if k in FRONT or k in arranged:
            continue
        if k in BLUEPRINTS:        # a built-in the saved order does not mention: after its usual predecessor
            before = [x for x in usual[:usual.index(k)] if x in arranged]
            arranged.insert(arranged.index(before[-1]) + 1 if before else 0, k)
        else:                      # a custom segment without a place yet: just before the reference list
            arranged.insert(arranged.index("references") if "references" in arranged else len(arranged), k)
    out = [*FRONT, *arranged]
    return out if keys is None else [k for k in out if k in set(keys)]


def _preceding_body(p: Project, key: str) -> list[str]:
    """Evidence-based segments that come before `key` in the article."""
    seq = order(p)
    return [k for k in seq[:seq.index(key)] if cites(p, k)] if key in seq else []


def _generation_rank(p: Project, key: str) -> float:
    """Where a custom segment falls in the writing sequence: right after the evidence-based segment it follows."""
    c = _custom(p, key)
    if c.kind == "manual":
        return 96.0
    before = _preceding_body(p, key)
    builtin = [k for k in before if k in BLUEPRINTS]
    if not builtin:                                    # placed before the Introduction
        return 5 + 0.1 * (len(before) + 1)
    return BLUEPRINTS[builtin[-1]].order + 0.1 * (len(before) - before.index(builtin[-1]))


def generation_order(p: Project, keys: list[str]) -> list[str]:
    return sorted(keys, key=lambda k: blueprint_for(p, k).order)


def deps(p: Project, key: str, keys: list[str]) -> list[str]:
    """Segments among `keys` that must be written before `key`."""
    if key == "references":
        return [k for k in keys if cites(p, k)]
    return [d for d in blueprint_for(p, key).depends_on if d in set(keys)]


# ---------------------------------------------------------------------------- lengths
def clamp_length(key: str, words: int) -> int:
    lo, hi = LENGTH_LIMITS.get(key, DEFAULT_LIMITS)
    return max(lo, min(hi, int(words)))


def segment_words(p: Project, key: str) -> int:
    if key in p.segment_lengths:
        return int(p.segment_lengths[key])
    if key not in BLUEPRINTS:
        c = _custom(p, key)
        return int(c.words) if c.kind == "generated" else 0
    suggested = length_profile(p.article_type, p.target_words)["segments"].get(key)
    if suggested:
        return int(suggested["suggested"])
    return max(0, int(p.target_words * BLUEPRINTS[key].word_share))


# ---------------------------------------------------------------------------- what the interface shows
def describe(p: Project) -> list[dict]:
    out = []
    for key in order(p):
        if p.mode == "format" and key in BLUEPRINTS and key not in p.segments:
            continue        # an article brought in for formatting has only the segments its document had
        bp = blueprint_for(p, key)
        seg = p.segments.get(key)
        custom = key not in BLUEPRINTS
        lo, hi = LENGTH_LIMITS.get(key, DEFAULT_LIMITS)
        out.append({
            "key": key, "title": bp.title, "default_title": bp.title if custom else BLUEPRINTS[key].title, "description": bp.description,
            "kind": bp.extra.get("kind", "builtin") if custom else "builtin", "custom": custom, "front": key in FRONT,
            "included": included(p, key), "numbered": numbered(p, key), "written": bool(seg and seg.content), "status": seg.status if seg else "",
            "depends_on": list(bp.depends_on), "word_share": bp.word_share, "lengthable": lengthable(p, key), "words": segment_words(p, key),
            "min_words": lo, "max_words": hi, "cites": cites(p, key),
            **({"purpose": p.custom_segments[key].purpose, "moves": p.custom_segments[key].moves, "cites_sources": p.custom_segments[key].cites}
               if key in p.custom_segments else {}),
        })
    return out


# ---------------------------------------------------------------------------- changes (call inside store.mutate)
def rename(p: Project, key: str, title: str) -> str:
    """Give a segment another title; an empty title puts a built-in segment back to its usual name."""
    title = _plain(title, 90)
    if key in p.custom_segments:
        if len(title) < 2:
            raise ValueError("Give the segment a title.")
        p.custom_segments[key].title = title
    elif key in BLUEPRINTS:
        if title and title != BLUEPRINTS[key].title:
            p.titles[key] = title
        else:
            p.titles.pop(key, None)
            title = BLUEPRINTS[key].title
    else:
        raise KeyError(key)
    if key in p.segments:
        p.segments[key].title = title
    return title


def add_custom(p: Project, *, title: str, purpose: str = "", kind: str = "generated", after: str = "", words: int = 400, cites_sources: bool = True,
               numbered_: bool | None = None, moves: list[dict] | None = None, limit: bool = True) -> str:
    """`limit=False` is for a whole document brought in for formatting: any number of sections, under any titles."""
    title, purpose = _plain(title, 90), _plain(purpose, 600)
    if len(title) < 2:
        raise ValueError("Give the segment a title.")
    if kind not in {"generated", "manual"}:
        raise ValueError("A segment is written either by RAF or by you.")
    if kind == "generated" and len(purpose) < 15:
        raise ValueError("Say in a sentence or two what the segment should do, so RAF knows what to write.")
    if limit and len(p.custom_segments) >= MAX_CUSTOM:
        raise ValueError(f"A project can have at most {MAX_CUSTOM} added segments.")
    if limit and any(title.lower() == title_of(p, k).lower() for k in order(p)):
        raise ValueError(f"This article already has a segment called “{title}”.")
    key = "c_" + uuid.uuid4().hex[:8]
    seq = [k for k in order(p) if k not in FRONT]
    p.custom_segments[key] = CustomSegment(key=key, title=title, purpose=purpose, kind=kind, words=clamp_length(key, words or 400), cites=bool(cites_sources),
                                           numbered=kind == "generated" if numbered_ is None else bool(numbered_), moves=clean_moves(moves or []))
    if after in seq:
        seq.insert(seq.index(after) + 1, key)
    elif after in FRONT:
        seq.insert(0, key)
    else:
        seq.insert(seq.index("references") if "references" in seq else len(seq), key)
    p.order = seq
    return key


def clean_moves(moves: list[dict]) -> list[dict]:
    """Parts of a custom segment as the author or RAF's proposal gave them, reduced to safe, bounded fields."""
    out = []
    for m in moves[:6]:
        if not isinstance(m, dict) or not _plain(m.get("name", ""), 80) or not _plain(m.get("instruction", ""), 600):
            continue
        try:
            share = min(1.0, max(0.05, float(m.get("share", 0.3))))
        except (TypeError, ValueError):
            share = 0.3
        queries = [_plain(q, 120) for q in (m.get("queries") or []) if isinstance(q, str) and _plain(q, 120)][:3]
        out.append({"name": _plain(m["name"], 80), "instruction": _plain(m["instruction"], 600), "queries": queries, "share": share})
    return out


def remove_custom(p: Project, key: str) -> None:
    if key not in p.custom_segments:
        raise KeyError(key)
    del p.custom_segments[key]
    p.segments.pop(key, None)
    p.segment_lengths.pop(key, None)
    p.order = [k for k in p.order if k != key]
    p.excluded = [k for k in p.excluded if k != key]
    p.selected = [k for k in p.selected if k != key]


def set_order(p: Project, keys: list[str]) -> None:
    """Arrange the body. Keys that are missing keep their relative place; front matter cannot be moved."""
    wanted = [k for k in dict.fromkeys(keys) if exists(p, k) and k not in FRONT]
    rest = [k for k in order(p) if k not in FRONT and k not in wanted]
    p.order = [*wanted, *rest]


def set_included(p: Project, key: str, value: bool) -> None:
    if not exists(p, key):
        raise KeyError(key)
    p.excluded = [k for k in p.excluded if k != key] + ([] if value else [key])
