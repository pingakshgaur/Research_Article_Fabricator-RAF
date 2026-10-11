"""Project History: an append-only record of everything that happened to an article.

Stored in  data/projects/<id>/history.jsonl , one JSON object per line:

    {"t": time, "actor": "you" | "RAF", "kind": "segment.revised", "segment": "discussion", "summary": "...", "meta": {...}}

Unlike Project.log (the Fabrication console, capped at 400 lines) this file is never trimmed. Projects made before
version 1.5 get a history rebuilt from what their project.json still knows: creation, segment versions and the run.
"""
from __future__ import annotations

import difflib
import json
import logging
import threading
import time
from pathlib import Path

from . import llm_settings, store
from . import structure
from .models import Project

log = logging.getLogger("raf.history")
_lock = threading.Lock()
RAF_REASONS = ("initial draft", "revision", "tool:", "humanize", "article review")


def _path(pid: str) -> Path:
    return store.project_dir(pid) / "history.jsonl"


def record(pid: str, kind: str, summary: str, *, actor: str = "you", segment: str = "", **meta) -> None:
    """Add one line to the project's history. Never raises: a history problem must not break the action itself."""
    event = {"t": time.time(), "actor": actor, "kind": kind, "segment": segment, "summary": summary, "meta": meta}
    try:
        with _lock:
            path = _path(pid)
            if not path.exists():
                _backfill(pid, path)
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001
        log.exception("could not write history for %s", pid)


def read(pid: str) -> list[dict]:
    """Every recorded event, newest first."""
    with _lock:
        path = _path(pid)
        if not path.exists():
            _backfill(pid, path)
        events = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return sorted(events, key=lambda e: e["t"], reverse=True)


def from_reason(title: str, reason: str) -> tuple[str, str, str]:
    """(kind, actor, summary) for a segment version, from the reason RAF stored with it."""
    if reason.startswith("initial draft"):
        return "segment.drafted", "RAF", f"{title} drafted" + (f" ({reason[14:].strip('() ')})" if len(reason) > 14 else "")
    if reason.startswith("revision round:"):
        return "segment.revised", "RAF", f"{title} revised in {reason[15:].strip()}"
    if reason.startswith("revision:"):
        return "segment.revised", "RAF", f"{title} revised — “{reason[9:].strip()}”"
    if reason.startswith("tool:"):
        return "segment.tool", "RAF", f"{reason[5:].strip().replace('_', ' ').capitalize()} applied to {title}"
    if reason.startswith("humanize"):
        return "segment.tool", "RAF", f"Humanize applied to {title} ({reason[9:].strip()})"
    if reason.startswith("article review:"):
        return "segment.revised", "RAF", f"{title} fixed after the article review ({reason[15:].strip()})"
    if reason.startswith("rebuilt"):
        return "segment.rebuilt", "RAF", f"{title} {reason}"
    if reason.startswith("restored"):
        return "segment.restored", "you", f"{title} {reason}"
    if reason.startswith("imported"):
        return "segment.imported", "you", f"{title} replaced from an imported document"
    return "segment.edited", "you", f"You edited {title}"


def _backfill(pid: str, path: Path) -> None:
    """First use on a project: write what can still be known about its past, so the timeline does not start empty."""
    p = store.load(pid)
    events = []
    if p is not None:
        events.append({"t": p.created, "actor": "you", "kind": "project.created", "segment": "", "summary": f"Project created — “{p.title}”", "meta": {}})
        if p.run.first_started and p.run.first_started < time.time() - 5:
            events.append({"t": p.run.first_started, "actor": "you", "kind": "run.started", "segment": "", "summary": "Fabrication started", "meta": {}})
        for key, seg in p.segments.items():
            for i, v in enumerate(seg.versions):
                kind, actor, summary = from_reason(seg.title, v.reason)
                events.append({"t": v.created, "actor": actor, "kind": kind, "segment": key, "summary": summary,
                               "meta": {"version": i + 1, "words": len(v.content.split())}})
        if p.run.finished:
            events.append({"t": p.run.finished, "actor": "RAF", "kind": "run.completed", "segment": "", "summary": "Fabrication completed", "meta": {"seconds": p.run.elapsed_before}})
        events = [{**e, "meta": {**e["meta"], "reconstructed": True}} for e in events if e["t"] < time.time() - 5]
    events.sort(key=lambda e: e["t"])
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events), encoding="utf-8")


def words_delta(before: str, after: str) -> dict:
    return {"words_before": len(before.split()), "words": len(after.split())}


# ---------------------------------------------------------------------------- AI-use statement
def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def ai_statement(p: Project) -> dict:
    """A disclosure paragraph built only from recorded facts, plus the facts themselves."""
    from .main import API_VERSION   # imported here: main imports this module

    events = read(p.id)
    drafted, human, changed_words, total_words = [], [], 0.0, 0
    for key in structure.order(p, p.segments):   # article order
        seg = p.segments[key]
        if not seg.content or key in {"references", "appendices"}:
            continue
        by_raf = [v for v in seg.versions if v.reason.startswith(RAF_REASONS)]
        if not by_raf:
            human.append(seg.title)
            continue
        drafted.append(seg.title)
        a, b = by_raf[-1].content.split(), seg.content.split()
        total_words += len(b)
        changed_words += (1 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()) * len(b) if a != b else 0
    tools = sorted({e["summary"].split(" applied to ")[0] for e in events if e["kind"] == "segment.tool"})
    runs = [e["meta"] for e in events if e["kind"] in {"run.started", "run.resumed"}]
    cloud = sorted({m for r in runs for m in r.get("cloud_models", [])})      # models reached through an API key, with their provider
    models = sorted({m for r in runs for m in r.get("models", [r["model"]] if r.get("model") else [])}) or ([] if cloud else [llm_settings.get()["model"]])
    facts = {
        "raf_version": API_VERSION, "models": models, "cloud_models": cloud, "drafted_by_raf": drafted, "written_by_author": human, "tools_used": tools,
        "revisions_requested": sum(e["kind"] == "segment.revised" for e in events),
        "manual_edits": sum(e["kind"] == "segment.edited" for e in events),
        "share_changed_by_hand": round(100 * changed_words / total_words) if total_words else 0,
        "online_sources": len(p.web_sources), "uploaded_references": sum(r.status == "parsed" for r in p.references),
        "statistics_computed": bool(p.analysis and p.analysis.findings),
        "approved": sum(s.status == "approved" for s in p.segments.values()), "segments": len(p.segments),
    }
    if not drafted:
        return {"statement": "", "facts": facts}
    parts = [
        f"During the preparation of this work the author(s) used RAF (Research Article Fabricator, version {API_VERSION}), a tool that runs "
        + " and ".join(([f"the {_join(models)} language model on the author's own computer"] if models else [])
                       + ([f"the {_join(cloud)} language model{'s' if len(cloud) > 1 else ''} through the provider's online service"] if cloud else []))
        + f", to draft the following parts of the manuscript: {_join(drafted)}."
    ]
    if facts["uploaded_references"] or facts["online_sources"]:
        src = [f"{facts['uploaded_references']} reference documents supplied by the author(s)"] if facts["uploaded_references"] else []
        if facts["online_sources"]:
            src.append(f"{facts['online_sources']} sources retrieved from public scholarly databases")
        parts.append(f"The tool drafted from {_join(src)}, and checked each cited claim against the source it cites.")
    if facts["statistics_computed"]:
        parts.append("All statistics, tables and figures were computed by the tool's statistics engine (Python: pandas, SciPy, statsmodels), not generated by the language model.")
    if tools:
        parts.append(f"The tool's text functions ({_join([t.lower() for t in tools])}) were also used on parts of the text.")
    review = "The author(s) reviewed the output"
    if facts["manual_edits"]:
        review += f", edited it by hand ({facts['manual_edits']} manual edit{'s' if facts['manual_edits'] != 1 else ''}"
        review += f"; about {facts['share_changed_by_hand']}% of the drafted text was changed)" if facts["share_changed_by_hand"] else ")"
    if facts["revisions_requested"]:
        review += f", directed {facts['revisions_requested']} revision{'s' if facts['revisions_requested'] != 1 else ''}"
    if human:
        review += f", wrote the {_join(human)} without the tool"
    parts.append(review + ", and take(s) full responsibility for the content of the publication.")
    return {"statement": " ".join(parts), "facts": facts}
