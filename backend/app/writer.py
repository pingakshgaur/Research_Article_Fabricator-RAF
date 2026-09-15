"""RAF writing engine.

Corpus pipeline:  parse references → extract metadata → chunk → plan research queries → multi-source web research
                  → hybrid neural/lexical index → statistical analysis.
Segment pipeline (per rhetorical move of the segment's blueprint):
                  retrieve (hybrid RRF + MMR) → evidence notes (paraphrased, cited) → draft paragraphs
                  → critic scores the blueprint checklist → refine → de-cliché → originality guard → number verification.

Reliability features
  * Checkpoints   — every finished corpus stage, literature theme set, evidence note, drafted move and refinement is
                    saved (checkpoints.py), so "Resume" continues from the exact step that was interrupted.
  * Fallbacks     — each stage degrades instead of stopping: research/analysis failures continue without them, a failing
                    segment is retried in quick mode and then with a single-pass emergency draft, model memory errors
                    lower concurrency/GPU offload (llm.py), and a restarting Ollama is waited for.
  * Agents        — 1 (solo), 2 (duo) or 3 (trio) parallel model workers: independent segments are written side by side
                    following the dependency graph, and evidence notes are prepared ahead of the drafting agent.
  * Timer         — Project.run records total, per-stage and per-segment time across resumed sessions.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

import numpy as np

from . import analysis as analysis_mod
from . import citations, estimate, factcheck, jobs, llm, originality, research, store, style
from .blueprints import BLUEPRINTS, COMMON_RULES, Blueprint, Move, generation_order, length_profile, tone_instruction
from .checkpoints import Checkpoints, signature
from .ingest import chunk_text, heuristic_metadata, llm_metadata, read_any, strip_back_matter
from .models import AnalysisResult, Figure, GenerateRequest, Project, QualityReport, RunInfo, Segment, Table, Version
from .rag import Chunk, HybridIndex

log = logging.getLogger("raf.writer")

AUTHOR_SYSTEM = (
    "You are RAF, a senior academic author and peer reviewer who writes publication-ready scholarly articles. "
    "You write in fluent, natural, human academic English with precise terminology and original phrasing."
)
EVIDENCE_SEGMENTS = ("introduction", "literature_review", "methodology", "results", "discussion", "conclusion", "limitations")
LENGTH_LIMITS = {"abstract": (100, 400)}
DEFAULT_LIMITS = (100, 6000)
_lane = threading.local()
_checkpoints: dict[str, Checkpoints] = {}
_checkpoints_lock = threading.Lock()


def lane_prefix() -> str:
    lane = getattr(_lane, "value", 0)
    return f"[Agent {lane}] " if lane and llm.runtime.capacity > 1 else ""


# ====================================================================== workspace
class Workspace:
    def __init__(self, pid: str) -> None:
        self.pid = pid
        self.dir = store.project_dir(pid)
        self._index: HybridIndex | None = None
        self._fp: originality.SourceFingerprint | None = None
        self._lock = threading.RLock()
        # One checkpoint store per project: parallel Studio jobs must not overwrite each other's saved steps.
        with _checkpoints_lock:
            if pid not in _checkpoints:
                _checkpoints[pid] = Checkpoints(self.dir, on_save=self._checkpoint_saved)
            self.cp = _checkpoints[pid]

    @property
    def project(self) -> Project:
        p = store.load(self.pid)
        if p is None:
            raise KeyError(self.pid)
        return p

    def log(self, message: str, **data) -> None:
        jobs.emit(self.pid, "log", lane_prefix() + message, **data)

    def stage(self, message: str, stage: str, **data) -> None:
        jobs.emit(self.pid, "stage", lane_prefix() + message, stage=stage, **data)

    def _checkpoint_saved(self, label: str) -> None:
        def bump(p: Project):
            p.run.checkpoints += 1
        try:
            store.mutate(self.pid, bump)
        except KeyError:
            return
        jobs.emit(self.pid, "checkpoint", f"⚑ Checkpoint saved · {label}")

    @property
    def index(self) -> HybridIndex:
        with self._lock:
            if self._index is None:
                self._index = HybridIndex.load(self.dir / "index")
            return self._index

    @property
    def fingerprint(self) -> originality.SourceFingerprint:
        with self._lock:
            if self._fp is None:
                texts = [c.text for c in self.index.chunks]
                for f in (self.dir / "index").glob("ref_*.txt"):
                    texts.append(f.read_text(encoding="utf-8"))
                self._fp = originality.SourceFingerprint(texts)
            return self._fp

    def set_segment(self, key: str, **fields) -> Project:
        def apply(p: Project):
            seg = p.segments.get(key) or Segment(key=key, title=BLUEPRINTS[key].title)
            for k, v in fields.items():
                setattr(seg, k, v)
            p.segments[key] = seg
        p = store.mutate(self.pid, apply)
        if "status" in fields:
            jobs.emit(self.pid, "segment", f"{BLUEPRINTS[key].title}: {fields['status']}", key=key, status=fields["status"])
        return p

    # ------------------------------------------------------------------ timer
    def begin_stage(self, stage: str) -> None:
        now = time.time()

        def apply(p: Project):
            _close_stages(p.run, now)
            p.run.stage_started[stage] = now
        store.mutate(self.pid, apply)

    def segment_clock(self, key: str, running: bool) -> None:
        now = time.time()

        def apply(p: Project):
            if running:
                p.run.segment_started[key] = now
            elif key in p.run.segment_started:
                started = p.run.segment_started.pop(key)
                p.run.segment_seconds[key] = round(p.run.segment_seconds.get(key, 0) + now - started, 1)
        store.mutate(self.pid, apply)


def _close_stages(run: RunInfo, now: float) -> None:
    for name, started in list(run.stage_started.items()):
        run.stages[name] = round(run.stages.get(name, 0) + now - started, 1)
    run.stage_started = {}


def segment_words(p: Project, key: str) -> int:
    bp = BLUEPRINTS[key]
    if key in p.segment_lengths:
        return int(p.segment_lengths[key])
    suggested = length_profile(p.article_type, p.target_words)["segments"].get(key)
    if suggested:
        return int(suggested["suggested"])
    return max(0, int(p.target_words * bp.word_share))


def clamp_length(key: str, words: int) -> int:
    lo, hi = LENGTH_LIMITS.get(key, DEFAULT_LIMITS)
    return max(lo, min(hi, int(words)))


# ====================================================================== corpus
def build_corpus(ws: Workspace, req: GenerateRequest) -> None:
    p = ws.project
    ws.begin_stage("parsing")
    ws.stage("Reading and indexing reference documents", "parsing")
    ref_tables: list = []
    parsed_refs: list[tuple] = []
    legacy_tables = ws.dir / "index" / "ref_tables.json"
    to_describe = []

    for ref in p.references:
        path = ws.dir / "uploads" / ref.filename
        cached_text = ws.dir / "index" / f"ref_{ref.id}.txt"
        cached_tables = ws.dir / "index" / f"ref_{ref.id}.tables.json"
        if ref.status == "parsed" and cached_text.exists():  # checkpoint from an earlier run
            if cached_tables.exists():
                ref_tables.extend(json.loads(cached_tables.read_text(encoding="utf-8")))
            parsed_refs.append((ref, cached_text.read_text(encoding="utf-8")))
            ws.log(f"↺ Reusing {ref.title[:90]} (read in an earlier run)")
            continue
        try:  # PDF libraries are not thread-safe: parse sequentially, describe (LLM) in parallel below
            ws.log(f"Parsing {ref.filename}")
            doc = read_any(path)
            if len(doc.text) < 300:
                raise ValueError("no extractable text (scanned PDF without OCR?)")
            to_describe.append((ref, doc))
        except Exception as exc:  # noqa: BLE001
            ref.status, ref.error = "failed", str(exc)
            ws.log(f"✗ Could not read {ref.filename}: {exc}")

    def describe(item):
        ref, doc = item
        meta = heuristic_metadata(doc, ref.filename)
        try:
            meta = llm_metadata(doc, meta)
        except Exception as exc:  # noqa: BLE001 - fallback: layout/PDF metadata only
            ws.log(f"⚠ Metadata model call failed for {ref.filename} ({exc}); using layout metadata")
        body = strip_back_matter(doc.text)
        (ws.dir / "index" / f"ref_{ref.id}.txt").write_text(body, encoding="utf-8")
        (ws.dir / "index" / f"ref_{ref.id}.tables.json").write_text(json.dumps(doc.tables[:10]), encoding="utf-8")
        ref.title, ref.authors, ref.year = meta["title"], meta["authors"], meta["year"]
        ref.venue, ref.doi = meta.get("venue", ""), meta.get("doi", "")
        ref.pages, ref.chars, ref.status, ref.error = doc.pages, len(body), "parsed", ""

        def save(proj: Project):  # per-reference checkpoint
            proj.references = [ref if r.id == ref.id else r for r in proj.references]
        store.mutate(ws.pid, save)
        ws.log(f"✓ {ref.title[:90]} — {ref.pages or '?'} pages, {len(body):,} characters")
        return ref, body, doc.tables

    if to_describe:
        with ThreadPoolExecutor(max_workers=llm.runtime.capacity) as pool:
            for ref, body, tables in pool.map(describe, to_describe):
                parsed_refs.append((ref, body))
                ref_tables.extend(tables)
        ws.cp.mark_corpus("parsing", signature(sorted(r.id for r, _ in parsed_refs)), f"{len(parsed_refs)} references read")

    order = {r.id: i for i, r in enumerate(p.references)}
    parsed_refs.sort(key=lambda x: order.get(x[0].id, 0))
    chunks: list[Chunk] = []
    for i, (ref, body) in enumerate(parsed_refs, 1):
        label = f"R{i}"
        pieces = chunk_text(body)
        ref.chunks = len(pieces)
        chunks += [Chunk(id=f"{label}-{j}", text=t, source_id=ref.id, source_kind="reference", label=label) for j, t in enumerate(pieces)]
    if not ref_tables and legacy_tables.exists():
        ref_tables = json.loads(legacy_tables.read_text(encoding="utf-8"))
    legacy_tables.write_text(json.dumps(ref_tables[:40]), encoding="utf-8")

    def save_refs(proj: Project):
        chunk_counts = {r.id: r.chunks for r, _ in parsed_refs}
        for r in proj.references:
            if r.id in chunk_counts:
                r.chunks = chunk_counts[r.id]
        failed = {r.id: r for r in p.references if r.status == "failed"}
        proj.references = [failed.get(r.id, r) for r in proj.references]
    store.mutate(ws.pid, save_refs)

    # ---- online research
    web = []
    research_key = f"{p.title}|{p.topic}|{p.discipline}"
    research_sig = signature(research_key)
    p = ws.project
    if req.web_research:
        ws.begin_stage("research")
        ws.stage("Researching the topic online", "research")
        if p.web_sources and (ws.cp.corpus_done("research", research_sig) or p.options.get("research_key", research_key) == research_key):
            web = p.web_sources
            ws.log(f"↺ Reusing {len(web)} online sources found in an earlier run (change the title or topic to research again)")
        else:
            try:
                queries = plan_queries(p, [r.title for r, _ in parsed_refs])
                ws.log("Research queries: " + " | ".join(queries))
                web = research.research(queries, p.discipline or p.topic, progress=ws.log)
                web = rank_web_sources(web, f"{p.title} {p.topic}", limit=36)
                ws.log(f"Kept {len(web)} relevant online sources after de-duplication and relevance ranking")
            except Exception as exc:  # noqa: BLE001 - fallback: continue with the uploaded references only
                log.exception("research failed")
                ws.log(f"⚠ Online research failed ({type(exc).__name__}: {exc}); continuing with your references only")
                web = []

        def save_web(proj: Project):
            proj.web_sources = web
            proj.options = {**proj.options, "research_key": research_key}
        store.mutate(ws.pid, save_web)
        if web:
            ws.cp.mark_corpus("research", research_sig, f"{len(web)} online sources")
    for i, w in enumerate(web, 1):
        label = f"W{i}"
        text = f"{w.title}. {w.abstract}"
        pieces = chunk_text(text, target_words=200) or [text[:1500]]
        chunks += [Chunk(id=f"{label}-{j}", text=t, source_id=w.id, source_kind="web", label=label) for j, t in enumerate(pieces[:4])]

    # ---- index
    ws.begin_stage("indexing")
    ws.stage("Building the hybrid retrieval index", "indexing")
    index_sig = signature([c.id for c in chunks], len(chunks))
    if ws.cp.corpus_done("indexing", index_sig) and (ws.dir / "index" / "index.pkl").exists():
        ws._index = HybridIndex.load(ws.dir / "index")
        ws._fp = None
        ws.log(f"↺ Reusing the retrieval index ({len(ws._index.chunks)} passages)")
    else:
        idx = HybridIndex()
        try:
            info = idx.build(chunks)
        except Exception as exc:  # noqa: BLE001 - fallback: lighter lexical index
            ws.log(f"⚠ Full index failed ({exc}); building a lighter lexical index")
            idx = HybridIndex()
            info = idx.build([Chunk(**{**c.__dict__, "text": c.text[:1200]}) for c in chunks])
        idx.save(ws.dir / "index")
        ws._index, ws._fp = idx, None
        ws.log(f"Indexed {info['chunks']} passages · retrieval: {'neural embeddings + ' if info['neural'] else ''}BM25 + TF-IDF with rank fusion and MMR")
        ws.cp.mark_corpus("indexing", index_sig, f"index of {info['chunks']} passages")

    # ---- analysis
    if req.data_analysis and any(k in req.segments for k in ("methodology", "results", "discussion", "conclusion", "abstract", "appendices")):
        ws.begin_stage("analysis")
        ws.stage("Acquiring data and running statistical analysis", "analysis")
        p = ws.project
        analysis_sig = signature(p.title, p.topic, p.dataset_files, sorted(r.id for r, _ in parsed_refs))
        if ws.cp.corpus_done("analysis", analysis_sig) and p.analysis is not None:
            ws.log(f"↺ Reusing the earlier analysis ({len(p.analysis.findings)} findings)")
        else:
            datasets = [ws.dir / "datasets" / f for f in p.dataset_files]
            ok = True
            try:
                result = analysis_mod.run_analysis(ws.dir, p.title, p.topic, datasets, ref_tables, ws.log)
            except Exception as exc:  # noqa: BLE001 - analysis is optional; never let it stop the article
                log.exception("analysis failed")
                ws.log(f"⚠ Data analysis could not be completed ({type(exc).__name__}: {exc}); continuing with an evidence synthesis instead")
                result, ok = AnalysisResult(), False
            store.mutate(ws.pid, lambda proj: setattr(proj, "analysis", result))
            ws.log(f"Analysis complete: {len(result.findings)} findings, {len(result.tables)} tables, {len(result.figures)} figures")
            if ok:
                ws.cp.mark_corpus("analysis", analysis_sig, "data analysis")


def plan_queries(p: Project, ref_titles: list[str]) -> list[str]:
    data = llm.generate_json(
        "You are a research librarian designing database search strategies. Reply with JSON only.",
        f"Article title: {p.title}\nTopic description: {p.topic}\nDiscipline: {p.discipline}\n"
        f"Titles of the author's reference articles:\n- " + "\n- ".join(ref_titles[:20]) + "\n\n"
        "Design 5 distinct, concise search queries (3–7 words each) covering: the core topic, key theories, "
        "empirical evidence, methods, and recent developments. JSON: {\"queries\": [..]}",
        default={}, max_tokens=300,
    )
    queries = [q for q in (data.get("queries") or []) if isinstance(q, str) and q.strip()][:5]
    return queries or [p.title, f"{p.title} empirical evidence", f"{p.topic or p.title} review"]


def rank_web_sources(web, query: str, limit: int):
    if not web:
        return []
    from sklearn.feature_extraction.text import TfidfVectorizer

    docs = [f"{w.title} {w.abstract}" for w in web]
    vec = TfidfVectorizer(stop_words="english", sublinear_tf=True).fit(docs + [query])
    sims = (vec.transform(docs) @ vec.transform([query]).T).toarray().ravel()
    scholarly_bonus = np.array([0.05 if w.source not in {"web", "wikipedia"} else 0 for w in web])
    order = np.argsort(-(sims + scholarly_bonus))
    return [web[i] for i in order[:limit] if sims[i] > 0.02]


# ====================================================================== generation entry points
def generate_article(pid: str, req: GenerateRequest) -> None:
    ws = Workspace(pid)
    keys = list(dict.fromkeys(req.segments))
    if set(EVIDENCE_SEGMENTS) & set(keys) and "references" not in keys:
        keys.append("references")
        ws.log("References added automatically because the selected segments cite sources")
    llm.runtime.configure(req.agents, notify=ws.log)
    now = time.time()

    def init(p: Project):
        p.selected = keys
        p.options = {**p.options, "web_research": req.web_research, "data_analysis": req.data_analysis, "depth": req.depth, "agents": req.agents,
                     "hallucination_filter": req.hallucination_filter, "style_pass": req.style_pass}
        if req.tone:
            p.tone = {"name": req.tone.get("name", "academic"), "intensity": int(req.tone.get("intensity", 50))}
        for k, words in req.lengths.items():
            if k in BLUEPRINTS:
                p.segment_lengths[k] = clamp_length(k, words)
        p.stage = "processing"
        for k in keys:
            seg = p.segments.get(k)
            keep = seg is not None and seg.content and (seg.status == "approved" or (req.resume and seg.status == "draft"))
            if not keep:
                p.segments[k] = Segment(key=k, title=BLUEPRINTS[k].title, status="queued", versions=seg.versions if seg else [])
        if not req.resume or p.run.status in {"idle", "completed"}:
            p.run = RunInfo(first_started=now)
        p.run.status, p.run.session_started, p.run.finished = "running", now, None
        p.run.sessions += 1
        p.run.agents = req.agents
    store.mutate(pid, init)
    if not req.resume:
        for k in keys:
            ws.cp.clear_segment(k)
    ws.log(("▶ Resuming from the last checkpoint" if req.resume else "▶ Starting fabrication")
           + f" · {req.agents} agent{'s' if req.agents > 1 else ''} · {req.depth} mode")

    try:
        estimate_run(ws, req, keys)
        build_corpus(ws, req)
        ws.begin_stage("writing")
        run_segments(ws, keys, req.depth, req.agents)
        if req.depth == "thorough":
            review_and_fix(ws, keys)
    except Exception:
        _stop_run(ws, keys, "stopped")
        raise
    _stop_run(ws, keys, "completed")
    p = ws.project
    try:
        estimate.record(p)
    except Exception:  # noqa: BLE001 - calibration is best-effort
        log.exception("could not record timing history")
    failed = [s.title for k, s in p.segments.items() if k in keys and s.status == "failed"]
    if failed:
        jobs.emit(pid, "log", f"⚠ Finished with {len(failed)} segment(s) needing attention: {', '.join(failed)} — use Regenerate in the Studio")
    store.mutate(pid, lambda proj: setattr(proj, "stage", "studio"))
    elapsed = p.run.elapsed_before
    jobs.emit(pid, "done", f"All selected segments are drafted and ready for review · total time {int(elapsed // 3600)}h {int(elapsed % 3600 // 60)}m {int(elapsed % 60)}s")


def estimate_run(ws: Workspace, req: GenerateRequest, keys: list[str]) -> None:
    """Probe the model speed (a few seconds) and publish the estimated fabrication time before any real work."""
    ws.stage("Estimating fabrication time", "estimate")
    try:
        speed = estimate.probe_speed()
        estimate.remember_speed(speed["model"], speed["tok_s"])
        result = estimate.compute(ws.project, req, keys, speed)
    except Exception as exc:  # noqa: BLE001 - never let the estimate stop the article
        log.exception("time estimate failed")
        ws.log(f"⚠ Could not estimate the fabrication time ({exc}); starting anyway")
        return
    store.mutate(ws.pid, lambda proj: setattr(proj.run, "estimate", result))
    st = result["stages"]
    parts = [f"{name} {estimate.fmt(st[key])}" for key, name in
             (("parsing", "reading"), ("research", "research"), ("analysis", "analysis"), ("writing", "writing"), ("guard", "review")) if st[key] >= 30]
    speed_note = f"{result['tok_s']} tok/s" + ("" if result["speed_source"] == "probe" else f" from {result['speed_source']}")
    ws.log(f"⏱ Estimated fabrication time ≈ {estimate.fmt(result['total'])} · " + " · ".join(parts)
           + f" (model speed {speed_note}, measured in {result['probe_seconds']}s)")


def _stop_run(ws: Workspace, keys: list[str], status: str) -> None:
    now = time.time()

    def apply(p: Project):
        _close_stages(p.run, now)
        for key, started in list(p.run.segment_started.items()):
            p.run.segment_seconds[key] = round(p.run.segment_seconds.get(key, 0) + now - started, 1)
        p.run.segment_started = {}
        if p.run.session_started:
            p.run.elapsed_before = round(p.run.elapsed_before + now - p.run.session_started, 1)
        p.run.session_started = None
        p.run.status = status
        if status == "completed":
            p.run.finished = now
        for k in keys:
            if k in p.segments and p.segments[k].status == "working":
                p.segments[k].status = "queued"   # resumable from its checkpoints
    store.mutate(ws.pid, apply)


def run_segments(ws: Workspace, keys: list[str], depth: str, agents: int) -> None:
    """Dependency-aware scheduler: up to `agents` segments are written at the same time."""
    selected = set(keys)
    pending = [k for k in generation_order(keys)]
    running: dict = {}
    lanes = list(range(1, agents + 1))

    def deps_of(key: str) -> list[str]:
        if key == "references":
            return [k for k in keys if k in EVIDENCE_SEGMENTS]
        return [d for d in BLUEPRINTS[key].depends_on if d in selected]

    def job(key: str, lane: int) -> None:
        _lane.value = lane
        try:
            write_segment(ws, key, depth)
        finally:
            _lane.value = 0

    with ThreadPoolExecutor(max_workers=agents) as pool:
        while pending or running:
            segs = ws.project.segments
            settled = {k for k in keys if segs.get(k) and (segs[k].status in {"failed", "approved"} or (segs[k].status == "draft" and segs[k].content))}
            for key in list(pending):
                if key in settled:
                    pending.remove(key)
                    ws.log(f"↺ Keeping the existing {segs[key].status} of {segs[key].title}")
                    continue
                if not lanes:
                    break
                if all(d in settled for d in deps_of(key)):
                    pending.remove(key)
                    lane = lanes.pop(0)
                    running[pool.submit(job, key, lane)] = (key, lane)
            if not running:
                if not pending:
                    break
                key = pending.pop(0)   # unresolvable dependency (should not happen): write it anyway
                lane = lanes.pop(0)
                running[pool.submit(job, key, lane)] = (key, lane)
            done, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for fut in done:
                key, lane = running.pop(fut)
                lanes.append(lane)
                lanes.sort()
                fut.result()


def write_segment(ws: Workspace, key: str, depth: str = "thorough") -> None:
    """Write one segment with a fallback ladder: requested depth → quick → single-pass emergency draft."""
    bp = BLUEPRINTS[key]
    ws.stage(f"Writing: {bp.title}", "writing", key=key)
    ws.set_segment(key, status="working", error="")
    ws.segment_clock(key, True)
    attempts = [depth] + (["quick"] if depth == "thorough" else []) + ["emergency"]
    try:
        for n, mode in enumerate(attempts):
            try:
                if mode == "emergency":
                    if bp.special in {"references", "appendices", "keywords", "title"}:
                        raise RuntimeError("no emergency builder for this segment")
                    ws.log(f"⚠ {bp.title}: using the single-pass emergency draft")
                    content, evidence, extras = build_emergency(ws, bp)
                else:
                    builder = {
                        "title": build_title, "abstract": build_abstract, "keywords": build_keywords, "references": build_references,
                        "appendices": build_appendices, "literature_review": build_literature_review, "methodology": build_methodology,
                        "results": build_results,
                    }.get(bp.special or key, build_generic)
                    content, evidence, extras = builder(ws, bp, mode)
                if not content.strip():
                    raise RuntimeError("the model returned an empty draft")
                finalize(ws, key, content, evidence, reason="initial draft" if n == 0 else f"initial draft ({mode} fallback)", depth=mode, **extras)
                ws.cp.clear_segment(key)
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("segment %s failed in %s mode", key, mode)
                if n + 1 < len(attempts):
                    ws.log(f"⚠ {bp.title} hit a problem in {mode} mode ({type(exc).__name__}: {str(exc)[:160]}); falling back to {attempts[n + 1]} mode — saved progress is kept")
                else:
                    ws.set_segment(key, status="failed", error=str(exc))
                    ws.log(f"✗ {bp.title} could not be written: {exc}")
    finally:
        ws.segment_clock(key, False)


def finalize(ws: Workspace, key: str, content: str, evidence: str, reason: str, depth: str = "thorough",
             figures: list[Figure] | None = None, tables: list[Table] | None = None, notes: list[str] | None = None,
             skip_guard: bool = False) -> None:
    bp = BLUEPRINTS[key]
    p = ws.project
    rewritten, overlap, flagged = 0, 0.0, 0
    grounding, flags, style_report = {}, [], {}
    if not skip_guard:
        content = originality.destyle(content)
        words_target = segment_words(p, key)
        cp_step = f"guarded:{reason}"
        cacheable = reason.startswith("initial draft")   # revisions are never restored from a checkpoint
        cached = ws.cp.get(key, words_target, cp_step) if cacheable else None
        if cached is not None:
            content, grounding, flags, style_report = cached["content"], cached["grounding"], cached["flags"], cached["style"]
            ws.log(f"↺ {bp.title} · integrity-filtered version restored from checkpoint")
        else:
            deep = depth == "thorough"
            # ---- hallucination filter
            if p.options.get("hallucination_filter", True):
                ws.stage(f"Hallucination filter: {bp.title}", "guard", key=key)
                try:
                    content, grounding, flags = factcheck.filter_segment(
                        content, ws, key=key, title=p.title, section=bp.title, purpose=bp.description,
                        evidence=evidence, rules=rules_text(bp, p), deep=deep, progress=ws.log)
                    if grounding.get("checked"):
                        ws.log(f"Hallucination filter · {bp.title}: {grounding['checked']} claims checked · {grounding['supported']} supported · "
                               f"{grounding.get('corrected', 0)} corrected · {grounding.get('removed', 0)} removed · {len(flags)} flagged for review")
                except Exception as exc:  # noqa: BLE001 - fallback: keep the draft, say that the filter did not finish
                    log.exception("hallucination filter failed")
                    ws.log(f"⚠ Hallucination filter could not finish for {bp.title} ({exc}); claims are unverified")
            # ---- naturalness pass on weak paragraphs
            if p.options.get("style_pass", True) and deep:
                ws.stage(f"Style & naturalness pass: {bp.title}", "guard", key=key)
                try:
                    content, style_report = style.humanize_text(
                        content, title=p.title, section=bp.title, tone_rule=tone_instruction(p.tone),
                        profile=style.field_profile(ws.dir / "index"), deep=False, only_below=65, progress=ws.log)
                except Exception as exc:  # noqa: BLE001
                    ws.log(f"⚠ Style pass skipped for {bp.title} ({exc})")
            if cacheable:
                ws.cp.put(key, words_target, cp_step, {"content": content, "grounding": grounding, "flags": flags, "style": style_report},
                          label=f"{bp.title} · integrity-filtered")
        ws.stage(f"Originality & integrity checks: {bp.title}", "guard", key=key)
        try:
            content, check, rewritten = originality.enforce(content, ws.fingerprint, progress=ws.log, rounds=2 if depth == "thorough" else 1)
            overlap, flagged = check.overlap, len(check.flagged)
        except Exception as exc:  # noqa: BLE001 - fallback: keep the draft, report that the guard did not finish
            ws.log(f"⚠ Originality guard could not finish for {bp.title} ({exc}); please re-run a tool on this segment later")
    words = len(re.sub(r"\[\[.*?\]\]|\[[RW]\d+.*?\]", "", content).split())
    q = QualityReport(
        words=words, target_words=segment_words(p, key) if bp.word_share or key == "abstract" else 0, ngram_overlap=round(overlap, 4),
        flagged_sentences=flagged, rewritten_sentences=rewritten, readability=originality.readability(content) if words > 80 else None,
        citations=len(citations.MARKER.findall(content)),
        unverified_numbers=[] if skip_guard else originality.unverified_numbers(content, evidence),
        grounding=grounding, flags=[f for f in flags if f["sentence"] in content or f["sentence"][:80] in content][:30],
        style={**style.metrics(content), **({"pass": {k: style_report[k] for k in ("attempted", "rewritten")}} if style_report else {})},
    )
    seg = p.segments.get(key) or Segment(key=key, title=bp.title)
    fields = {"content": content, "quality": q, "status": "draft", "error": "", "versions": [*seg.versions, Version(content=content, reason=reason)][-20:]}
    if figures is not None:
        fields["figures"] = figures
    if tables is not None:
        fields["tables"] = tables
    if notes is not None:
        fields["notes"] = notes
    if q.unverified_numbers:
        ws.log(f"{bp.title}: numbers not found in evidence flagged for review: {', '.join(q.unverified_numbers[:8])}")
    ws.set_segment(key, **fields)
    ws.log(f"✓ {bp.title}: {words} words · source overlap {overlap:.1%} · {rewritten} sentence(s) re-expressed")


# ====================================================================== shared helpers
def evidence_block(chunks: list[Chunk], p: Project, max_words: int = 170) -> str:
    labels = citations.label_map(p)
    lines = []
    for c in chunks:
        src = labels.get(c.label)
        who = citations.short_label(src) if src else c.label
        words = c.text.split()
        lines.append(f"[{c.label}] ({who}): {' '.join(words[:max_words])}{'…' if len(words) > max_words else ''}")
    return "\n\n".join(lines)


def retrieve(ws: Workspace, queries: list[str], k_each: int = 5, cap: int = 10) -> list[Chunk]:
    seen, out = set(), []
    for q in queries:
        for c in ws.index.search(q, k=k_each):
            if c.id not in seen:
                seen.add(c.id)
                out.append(c)
    return out[:cap]


def article_context(p: Project, keys: tuple[str, ...], words_each: int = 450) -> str:
    parts = []
    for k in keys:
        seg = p.segments.get(k)
        if seg and seg.content:
            text = re.sub(r"\[\[.*?\]\]", "", seg.content)
            w = text.split()
            parts.append(f"--- {seg.title} (already written) ---\n{' '.join(w[:words_each])}{' …' if len(w) > words_each else ''}")
    return "\n\n".join(parts)


def rules_text(bp: Blueprint, p: Project | None = None) -> str:
    extra = []
    if p is not None:
        extra.append(tone_instruction(p.tone))
        rule = style.profile_rule(style.field_profile(store.project_dir(p.id) / "index"))
        if rule:
            extra.append(rule)
    return "\n".join(f"- {r}" for r in (*COMMON_RULES, *bp.rules, *extra))


def findings_text(a: AnalysisResult | None) -> str:
    if not a or not a.findings:
        return ""
    return "ANALYSIS FINDINGS (computed by RAF's statistics engine — the only permitted source of statistics):\n" + "\n".join(f"- {f}" for f in a.findings)


def take_notes(ws: Workspace, bp: Blueprint, move: Move, chunks: list[Chunk]) -> str:
    p = ws.project
    return llm.generate(
        AUTHOR_SYSTEM,
        f"ARTICLE: {p.title}\nSECTION: {bp.title} — move: {move.name}\nGOAL OF THIS MOVE: {move.instruction}\n\n"
        f"EVIDENCE PASSAGES:\n{evidence_block(chunks, p)}\n\n"
        "Read the evidence and write 6–10 research notes useful for this move. Each note must:\n"
        "- capture one idea, finding, definition, argument or disagreement in YOUR OWN words (no copied phrasing),\n"
        "- keep any concrete figures exactly as printed,\n"
        "- end with the source label(s) in square brackets, e.g. [R2] or [R2, W5].\n"
        "Also note where sources agree or conflict. Return the notes as a plain list, one per line starting with '- '.",
        temperature=0.4, max_tokens=900,
    )


def draft_move(ws: Workspace, bp: Blueprint, move: Move, material: str, words: int, previous: str, extra_context: str = "") -> str:
    p = ws.project
    prompt = (
        f"ARTICLE TITLE: {p.title}\nTOPIC: {p.topic}\nDISCIPLINE: {p.discipline or 'not specified'}\nARTICLE TYPE: {p.article_type}\n"
        f"SECTION: {bp.title}\nRHETORICAL MOVE: {move.name}\nWHAT THIS PART MUST DO: {move.instruction}\n\n"
        f"{extra_context}\n\n"
        f"MATERIAL (research notes / evidence with source labels):\n{material}\n\n"
        + (f"THE SECTION SO FAR (continue seamlessly from it; do not repeat it):\n…{' '.join(previous.split()[-160:])}\n\n" if previous else "")
        + f"WRITING RULES:\n{rules_text(bp, p)}\n\n"
        f"Write approximately {words} words ({max(1, round(words / 150))} paragraph(s)) for this move only. "
        "Cite with the exact labels from the material, e.g. [R1] or [R2, W4]. Output only the prose."
    )
    return llm.generate(AUTHOR_SYSTEM, prompt, temperature=0.72, max_tokens=int(words * 2.2) + 300)


def critique_and_refine(ws: Workspace, bp: Blueprint, text: str, evidence: str) -> str:
    if not bp.checks:
        return text
    p = ws.project
    verdict = llm.generate_json(
        "You are a demanding journal peer reviewer. Reply with JSON only.",
        f"Evaluate this '{bp.title}' section of the article '{p.title}'.\n\nSECTION:\n{text}\n\n"
        f"Answer each checklist question with true/false, then list up to 5 concrete, fixable weaknesses "
        f"(logic gaps, repetition, unsupported claims, weak transitions, generic wording).\n"
        f"CHECKLIST: {json.dumps(list(bp.checks))}\n"
        "JSON: {\"checklist\": {\"question\": true|false}, \"weaknesses\": [\"...\"]}",
        default={}, max_tokens=700,
    )
    checklist = verdict.get("checklist") if isinstance(verdict.get("checklist"), dict) else {}
    weaknesses = [w for w in (verdict.get("weaknesses") or []) if isinstance(w, str)][:5]
    failed = [q for q, ok in checklist.items() if ok is False]
    ws.log(f"Peer-review pass on {bp.title}: {len(checklist) - len(failed)}/{len(checklist)} checks met, {len(weaknesses)} weakness(es)")
    if not failed and not weaknesses:
        return text
    issues = "\n".join(f"- Unmet requirement: {q}" for q in failed) + "\n" + "\n".join(f"- {w}" for w in weaknesses)
    words = len(text.split())
    try:
        revised = llm.generate(
            AUTHOR_SYSTEM,
            f"Revise the '{bp.title}' section below to fix the reviewer's issues.\n\nISSUES:\n{issues}\n\n"
            f"SECTION:\n{text}\n\nSUPPORTING EVIDENCE (use only if needed to fix unsupported claims):\n{evidence[:6000]}\n\n"
            f"RULES:\n{rules_text(bp, p)}\n- Keep every citation marker that remains relevant, keep lines like [[TABLE 1]] or [[FIGURE 1]] unchanged.\n"
            f"- Keep roughly the same length (~{words} words).\nOutput only the revised section.",
            temperature=0.6, max_tokens=int(words * 2.2) + 400,
        )
    except llm.LLMError as exc:  # fallback: keep the unrefined draft
        ws.log(f"⚠ Refinement of {bp.title} skipped ({exc}); keeping the reviewed draft")
        return text
    return revised if len(revised.split()) > words * 0.6 else text


def run_moves(ws: Workspace, bp: Blueprint, moves: list[Move], total_words: int, depth: str, extra_context: str = "",
              extra_evidence: str = "") -> tuple[str, str]:
    """Draft a segment move by move. Research agents prepare evidence notes for later moves while the writing agent
    drafts earlier ones; every note, draft and the refinement is checkpointed."""
    p = ws.project
    cp, key, n = ws.cp, bp.key, len(moves)
    subs = {"title": p.title, "topic": p.topic or p.title}
    share_sum = sum(m.share for m in moves) or 1
    evidence_log = [extra_evidence]
    plans = []
    for i, move in enumerate(moves, 1):
        queries = [q.format(**subs) for q in move.queries]
        chunks = retrieve(ws, queries + [f"{move.name} {p.title}"], k_each=4, cap=10) if queries and bp.needs_evidence else []
        ev = evidence_block(chunks, p) if chunks else ""
        evidence_log.append(ev)
        plans.append({"i": i, "move": move, "chunks": chunks, "ev": ev, "words": max(90, int(total_words * move.share / share_sum))})

    lane = getattr(_lane, "value", 0)

    def notes_task(plan):
        _lane.value = lane
        step = f"notes:{plan['i']}"
        cached = cp.get(key, total_words, step)
        if cached is not None:
            return cached
        ws.stage(f"{bp.title} · researching move {plan['i']}/{n}: {plan['move'].name}", "writing", key=key, move=plan["move"].name)
        notes = take_notes(ws, bp, plan["move"], plan["chunks"])
        cp.put(key, total_words, step, notes, label=f"{bp.title} · notes for move {plan['i']}/{n}")
        return notes

    body = ""
    with ThreadPoolExecutor(max_workers=max(1, llm.runtime.capacity)) as pool:
        futures = {}
        if depth == "thorough":
            for plan in plans:
                if plan["chunks"] and cp.get(key, total_words, f"draft:{plan['i']}") is None:
                    futures[plan["i"]] = pool.submit(notes_task, plan)
        for plan in plans:
            i, move = plan["i"], plan["move"]
            draft = cp.get(key, total_words, f"draft:{i}")
            if draft is not None:
                ws.log(f"↺ {bp.title} · move {i}/{n} restored from checkpoint")
            else:
                ws.stage(f"{bp.title} · move {i}/{n}: {move.name}", "writing", key=key, move=move.name)
                material = plan["ev"]
                if i in futures:
                    try:
                        material = futures[i].result()
                    except Exception as exc:  # noqa: BLE001 - fallback: draft straight from the evidence
                        ws.log(f"⚠ Notes for “{move.name}” failed ({exc}); drafting directly from the evidence")
                if extra_evidence:
                    material = f"{material}\n\n{extra_evidence}".strip()
                draft = draft_move(ws, bp, move, material or "(No external evidence needed; rely on the article context.)", plan["words"], body, extra_context).strip()
                cp.put(key, total_words, f"draft:{i}", draft, label=f"{bp.title} · move {i}/{n} drafted")
            body = f"{body}\n\n{draft}".strip()

    evidence = "\n\n".join(evidence_log)
    if depth == "thorough" and bp.checks:
        refined = cp.get(key, total_words, "refined")
        if refined is not None:
            ws.log(f"↺ {bp.title} · peer-reviewed version restored from checkpoint")
            body = refined
        else:
            ws.stage(f"{bp.title} · peer review & refinement", "writing", key=key)
            body = critique_and_refine(ws, bp, body, evidence)
            cp.put(key, total_words, "refined", body, label=f"{bp.title} · peer-reviewed")
    return body, evidence


# ====================================================================== builders
def build_generic(ws: Workspace, bp: Blueprint, depth: str):
    p = ws.project
    ctx = article_context(p, bp.depends_on)
    findings = findings_text(p.analysis) if bp.key in {"discussion", "conclusion", "limitations"} else ""
    extra_ctx = f"ARTICLE CONTEXT:\n{ctx}" if ctx else ""
    body, evidence = run_moves(ws, bp, list(bp.moves), segment_words(p, bp.key), depth, extra_ctx, findings)
    return body, evidence + "\n" + ctx, {}


def build_emergency(ws: Workspace, bp: Blueprint):
    """Last-resort fallback: one retrieval and one model call for the whole segment."""
    p = ws.project
    words = segment_words(p, bp.key) or 400
    chunks = retrieve(ws, [f"{bp.title} {p.title}", p.topic or p.title], k_each=6, cap=10) if bp.needs_evidence and ws.index.chunks else []
    ev = evidence_block(chunks, p, max_words=120) if chunks else ""
    ctx = article_context(p, bp.depends_on, 250)
    text = llm.generate(
        AUTHOR_SYSTEM,
        f"ARTICLE TITLE: {p.title}\nTOPIC: {p.topic}\nSECTION: {bp.title}\nPURPOSE: {bp.description}\n\n"
        + (f"ARTICLE CONTEXT:\n{ctx}\n\n" if ctx else "") + (f"EVIDENCE:\n{ev}\n\n" if ev else "") + f"{findings_text(p.analysis)}\n\n"
        f"RULES:\n{rules_text(bp, p)}\n\nWrite the complete section in about {words} words. Output only the prose.",
        temperature=0.65, max_tokens=int(words * 2.2) + 300,
    )
    if bp.key == "abstract":
        text = citations.MARKER.sub("", text)
    return text.strip(), ev + ctx + findings_text(p.analysis), {}


def build_literature_review(ws: Workspace, bp: Blueprint, depth: str):
    p = ws.project
    words = segment_words(p, bp.key)
    themes = ws.cp.get(bp.key, words, "themes")
    if themes is None:
        ws.stage("Review of Literature · discovering themes in the corpus", "writing", key=bp.key)
        themes = discover_themes(ws)
        ws.cp.put(bp.key, words, "themes", themes, label="Review of Literature · themes identified")
    else:
        ws.log("↺ Literature themes restored from checkpoint")
    ws.log("Literature themes identified: " + "; ".join(t["name"] for t in themes))
    moves = list(bp.moves)
    for t in themes:
        moves.append(Move(t["name"], f"Synthesise the literature on this theme: {t['focus']} Compare and contrast authors, evaluate the strength of evidence, and note unresolved debates.",
                          tuple([t["name"], *t.get("queries", [])][:3]), 0.8 / max(1, len(themes))))
    hypotheses = " If the evidence supports it, finish with clearly labelled hypotheses (H1, H2 …) that the analysis can test." if p.analysis and p.analysis.findings else ""
    moves.append(Move("Synthesis and research gap", "Integrate the themes into an overall picture, identify precisely what remains unknown or contested, and explain how this article addresses that gap." + hypotheses,
                      (f"research gap {p.topic or p.title}", f"future research needed {p.title}"), 0.2))
    ctx = article_context(p, ("introduction",), 350)
    body, evidence = run_moves(ws, bp, moves, words, depth, f"ARTICLE CONTEXT:\n{ctx}" if ctx else "")
    return body, evidence, {"notes": [f"Theme: {t['name']}" for t in themes]}


def discover_themes(ws: Workspace) -> list[dict]:
    """Cluster reference passages (TF-IDF → k-means) and let the SLM name each cluster."""
    from sklearn.cluster import KMeans
    from sklearn.feature_extraction.text import TfidfVectorizer

    p = ws.project
    chunks = [c for c in ws.index.chunks if c.source_kind == "reference"] or ws.index.chunks
    if len(chunks) < 8:
        return [{"name": "Empirical evidence", "focus": "the main empirical findings on the topic.", "queries": [p.title]}]
    k = int(min(5, max(3, len(chunks) // 40)))
    vec = TfidfVectorizer(stop_words="english", max_df=0.6, min_df=2, sublinear_tf=True, ngram_range=(1, 2))
    X = vec.fit_transform([c.text for c in chunks])
    km = KMeans(n_clusters=k, n_init=10, random_state=7).fit(X)
    terms = np.array(vec.get_feature_names_out())
    clusters = []
    for ci in range(k):
        centroid = km.cluster_centers_[ci]
        top = terms[centroid.argsort()[::-1][:12]].tolist()
        members = np.where(km.labels_ == ci)[0]
        if len(members) == 0:
            continue
        dists = X[members] @ centroid
        rep = [chunks[members[i]].text[:500] for i in np.argsort(-np.asarray(dists).ravel())[:3]]
        sources = len({chunks[i].source_id for i in members})
        clusters.append({"terms": top, "examples": rep, "sources": sources})
    listing = "\n\n".join(f"CLUSTER {i + 1} ({c['sources']} sources) key terms: {', '.join(c['terms'])}\nExcerpts:\n" + "\n".join(f"> {e}" for e in c["examples"]) for i, c in enumerate(clusters))
    data = llm.generate_json(
        "You are an expert in systematic literature reviews. Reply with JSON only.",
        f"Article: {p.title}\n\nThe reference corpus was clustered into these groups:\n{listing}\n\n"
        "Name each cluster as a scholarly review theme (3–8 words), describe its focus in one sentence, and give 2 search queries. "
        "Merge clusters that are really the same theme. Order themes logically (foundations → mechanisms → outcomes → context). "
        "JSON: {\"themes\": [{\"name\": \"\", \"focus\": \"\", \"queries\": [\"\", \"\"]}]}",
        default={}, max_tokens=800,
    )
    themes = [t for t in (data.get("themes") or []) if isinstance(t, dict) and t.get("name")][:5]
    return themes or [{"name": ", ".join(c["terms"][:3]).title(), "focus": "the literature on " + ", ".join(c["terms"][:5]) + ".", "queries": c["terms"][:2]} for c in clusters]


def analysis_protocol(p: Project) -> str:
    refs = [r for r in p.references if r.status == "parsed"]
    lines = ["ANALYSIS PROTOCOL (facts about what was actually done — describe only these):",
             f"- Literature base: {len(refs)} peer-reviewed/scholarly reference documents supplied for the study, analysed in full text.",]
    if p.web_sources:
        dbs = sorted({w.source for w in p.web_sources})
        lines.append(f"- Supplementary literature search across {', '.join(dbs)}; {len(p.web_sources)} additional sources retained after relevance screening and de-duplication.")
    a = p.analysis
    if a and a.datasets:
        for d in a.datasets:
            desc = f"- Dataset “{d['name']}”: source {d.get('origin')}; {d.get('rows')} observations"
            if d.get("unit"):
                desc += f" (unit of analysis: {d['unit']})"
            if d.get("years"):
                desc += f"; period {d['years']}"
            if d.get("indicators"):
                desc += "; variables: " + "; ".join(f"{k} = {v}" for k, v in d["indicators"].items())
            elif d.get("variables"):
                desc += "; variables: " + ", ".join(d["variables"])
            lines.append(desc)
        lines.append("- Statistical procedures, in order: " + "; ".join(dict.fromkeys(a.methods)))
        lines.append("- Software: Python (pandas, SciPy, statsmodels); significance level α = .05.")
    else:
        lines.append("- No primary or secondary numerical dataset was analysed; the study is a structured qualitative synthesis of the literature (thematic analysis of the full texts).")
    return "\n".join(lines)


def build_methodology(ws: Workspace, bp: Blueprint, depth: str):
    p = ws.project
    protocol = analysis_protocol(p)
    ctx = article_context(p, bp.depends_on, 300)
    moves = list(bp.moves)
    if not (p.analysis and p.analysis.datasets):
        moves = [m if m.name != "Variables and measurement" else Move("Analytical framework", "Describe the coding and thematic synthesis procedure: screening, full-text reading, coding, theme development and cross-source comparison.", (), 0.2) for m in moves]
    body, evidence = run_moves(ws, bp, moves, segment_words(p, bp.key), depth, f"{protocol}\n\nARTICLE CONTEXT:\n{ctx}", protocol)
    return body, evidence, {}


def build_results(ws: Workspace, bp: Blueprint, depth: str):
    p = ws.project
    a = p.analysis
    ctx = article_context(p, ("introduction", "methodology"), 300)
    if not (a and a.findings):
        return build_synthesis_results(ws, bp, depth, ctx)

    total = segment_words(p, bp.key)
    cp = ws.cp
    groups = list(dict.fromkeys([d["name"] for d in a.datasets]))
    intro = cp.get(bp.key, total, "results:intro")
    if intro is None:
        intro = llm.generate(
            AUTHOR_SYSTEM,
            f"Article: {p.title}\n{ctx}\n\n{findings_text(a)}\n\nWrite one short opening paragraph (60–90 words) for the Results section "
            "that tells the reader what analyses are reported and in what order. No numbers yet, no interpretation. Output only the paragraph.",
            temperature=0.6, max_tokens=250,
        ).strip()
        cp.put(bp.key, total, "results:intro", intro, label="Results · opening paragraph")
    body_parts = [intro]
    for gi, g in enumerate(groups, 1):
        g_tables = [t for t in a.tables if t.group == g]
        g_figs = [f for f in a.figures if f.group == g]
        para = cp.get(bp.key, total, f"results:{gi}")
        if para is None:
            ws.stage(f"Results · reporting “{g}”", "writing", key="results")
            g_findings = [f for f in a.findings if f.startswith(f"[{g}]")]
            items = "\n".join([f"- Table {t.number}: {t.caption}" for t in g_tables] + [f"- Figure {f.number}: {f.caption}" for f in g_figs])
            para = llm.generate(
                AUTHOR_SYSTEM,
                f"Article: {p.title}\nSECTION: Results — {g}\n\nFINDINGS (use numbers exactly as written, never add others):\n"
                + "\n".join(f"- {f.split('] ', 1)[-1]}" for f in g_findings)
                + f"\n\nTABLES AND FIGURES AVAILABLE:\n{items or '(none)'}\n\nRULES:\n{rules_text(bp, p)}\n\n"
                f"Write about {max(150, total // max(1, len(groups)))} words reporting these findings objectively. Refer to each table and figure by number "
                "('Table 2 summarises…', '(see Figure 1)'). Report test statistic, p-value and effect size together. No citations, no interpretation. Output only prose.",
                temperature=0.55, max_tokens=int(total * 2) + 300,
            ).strip()
            cp.put(bp.key, total, f"results:{gi}", para, label=f"Results · {g}")
        block = para + "\n\n" + "\n\n".join([f"[[TABLE {t.number}]]" for t in g_tables] + [f"[[FIGURE {f.number}]]" for f in g_figs])
        body_parts.append(block.strip())
    body = "\n\n".join(body_parts)
    evidence = findings_text(a) + "\n" + "\n".join(f"{t.caption} {t.note} " + " ".join(" ".join(r) for r in t.rows) for t in a.tables)
    if depth == "thorough":
        refined = cp.get(bp.key, total, "refined")
        if refined is None:
            refined = _restore_placeholders(critique_and_refine(ws, bp, body, evidence), a)
            cp.put(bp.key, total, "refined", refined, label="Results · peer-reviewed")
        body = refined
    return body, evidence, {"figures": a.figures, "tables": a.tables}


def _restore_placeholders(body: str, a: AnalysisResult) -> str:
    for t in a.tables:
        if f"[[TABLE {t.number}]]" not in body:
            body += f"\n\n[[TABLE {t.number}]]"
    for f in a.figures:
        if f"[[FIGURE {f.number}]]" not in body:
            body += f"\n\n[[FIGURE {f.number}]]"
    return body


def build_synthesis_results(ws: Workspace, bp: Blueprint, depth: str, ctx: str):
    p = ws.project
    total = segment_words(p, bp.key)
    cp = ws.cp
    ws.log("No numerical dataset available — reporting a structured evidence synthesis instead of statistics")
    chunks = retrieve(ws, [f"findings results {p.title}", f"empirical evidence {p.topic}", f"outcomes effects {p.title}", f"key conclusions {p.topic}"], k_each=5, cap=16)
    ev = evidence_block(chunks, p, max_words=140)
    rows = cp.get(bp.key, total, "synthesis:rows")
    if rows is None:
        ws.stage("Results · building the evidence-synthesis table", "writing", key="results")
        data = llm.generate_json(
            "You build evidence-synthesis tables for systematic reviews. Reply with JSON only.",
            f"Article: {p.title}\n\nEVIDENCE:\n{ev}\n\nGroup the evidence into 3–6 findings themes. For each give: theme (short), "
            "principal_evidence (one paraphrased sentence, include numbers only if printed in the evidence), direction "
            "(Supportive / Mixed / Contradictory), sources (list of labels like R1). JSON: {\"rows\": [{...}]}",
            default={}, max_tokens=1200,
        )
        rows = [r for r in (data.get("rows") or []) if isinstance(r, dict) and r.get("theme")][:6]
        cp.put(bp.key, total, "synthesis:rows", rows, label="Results · synthesis table")
    labels = citations.label_map(p)
    table = Table(number=1, caption="Synthesis of principal findings across the reviewed evidence", columns=["Theme", "Principal evidence", "Direction", "Sources"],
                  rows=[[str(r.get("theme")), str(r.get("principal_evidence", "")), str(r.get("direction", "")),
                         "; ".join(citations.short_label(labels[l]) for l in r.get("sources", []) if isinstance(l, str) and l in labels)] for r in rows],
                  note="Direction indicates whether the balance of evidence supports, partly supports, or contradicts the theme.", group="synthesis")
    move = Move("Evidence synthesis", "Report the findings theme by theme, stating the pattern of evidence, its consistency across sources, and the strength of support. Refer to Table 1. Do not interpret implications yet.", (), 1.0)
    body = cp.get(bp.key, total, "synthesis:body")
    if body is None:
        material = cp.get(bp.key, total, "notes:1")
        if material is None and depth == "thorough":
            material = take_notes(ws, bp, move, chunks)
            cp.put(bp.key, total, "notes:1", material, label="Results · evidence notes")
        material = (material or ev) + "\n\nSYNTHESIS TABLE ROWS:\n" + "\n".join(" | ".join(r) for r in table.rows)
        ws.stage("Results · drafting the synthesis", "writing", key="results")
        body = draft_move(ws, bp, move, material, total, "", f"ARTICLE CONTEXT:\n{ctx}").strip() + ("\n\n[[TABLE 1]]" if table.rows else "")
        cp.put(bp.key, total, "synthesis:body", body, label="Results · synthesis drafted")
    return body, ev, {"tables": [table] if table.rows else [], "figures": []}


def build_abstract(ws: Workspace, bp: Blueprint, depth: str):
    p = ws.project
    words = segment_words(p, bp.key)
    ctx = article_context(p, ("introduction", "methodology", "results", "discussion", "conclusion"), 380)
    if not ctx:
        ctx = findings_text(p.analysis) or f"Topic: {p.topic}"
    text = llm.generate(
        AUTHOR_SYSTEM,
        f"ARTICLE TITLE: {p.title}\n\n{ctx}\n\n{findings_text(p.analysis)}\n\nRULES:\n{rules_text(bp, p)}\n\n"
        f"Write the abstract now as one paragraph of about {words} words. No citations, no headings. Output only the abstract.",
        temperature=0.6, max_tokens=int(words * 2.2) + 200,
    )
    text = citations.MARKER.sub("", text).replace("  ", " ").replace(" .", ".")
    return text.strip(), ctx + findings_text(p.analysis), {}


def build_keywords(ws: Workspace, bp: Blueprint, depth: str):
    from sklearn.feature_extraction.text import TfidfVectorizer

    p = ws.project
    article = " ".join(s.content for k, s in p.segments.items() if k not in {"references", "keywords"} and s.content) or p.title + " " + p.topic
    corpus = [c.text for c in ws.index.chunks[:600]] or [p.topic or p.title]
    vec = TfidfVectorizer(ngram_range=(1, 3), stop_words="english", sublinear_tf=True, max_df=0.5).fit(corpus + [article])
    scores = vec.transform([article]).toarray().ravel()
    terms = vec.get_feature_names_out()
    candidates = [terms[i] for i in scores.argsort()[::-1][:30] if not re.search(r"\d", terms[i])]
    data = llm.generate_json(
        "You assign indexing keywords to scholarly articles. Reply with JSON only.",
        f"Title: {p.title}\nAbstract/overview: {(p.segments.get('abstract') or Segment(key='a', title='')).content or p.topic}\n"
        f"Statistically salient terms: {', '.join(candidates)}\n\nChoose 5–7 keywords (1–3 words each) that a researcher would search for. "
        "Prefer established disciplinary terms; avoid repeating the title verbatim. JSON: {\"keywords\": [..]}",
        default={}, max_tokens=200,
    )
    kws = [k.strip() for k in (data.get("keywords") or []) if isinstance(k, str) and k.strip()][:7] or candidates[:6]
    return "; ".join(kws), "", {"skip_guard": True}


def build_title(ws: Workspace, bp: Blueprint, depth: str):
    p = ws.project
    ctx = article_context(p, ("abstract", "introduction", "results"), 250)
    data = llm.generate_json(
        "You are a journal editor who crafts precise scholarly titles. Reply with JSON only.",
        f"Working title: {p.title}\nTopic: {p.topic}\n{ctx}\n\nRULES:\n" + "\n".join(f"- {r}" for r in bp.rules)
        + "\n\nPropose 4 improved titles (some with a subtitle after a colon). Put the best first. JSON: {\"titles\": [..]}",
        default={}, max_tokens=300,
    )
    titles = [t.strip() for t in (data.get("titles") or []) if isinstance(t, str) and t.strip()] or [p.title]
    return titles[0], "", {"notes": [f"Alternative: {t}" for t in titles[1:]] + [f"Working title: {p.title}"], "skip_guard": True}


def build_references(ws: Workspace, bp: Blueprint, depth: str):
    p = ws.project
    texts = [s.content for k, s in p.segments.items() if k != "references"]
    entries, _ = citations.reference_list(p, texts)
    return "\n".join(entries), "", {"skip_guard": True}


def build_appendices(ws: Workspace, bp: Blueprint, depth: str):
    p = ws.project
    parts = ["Appendix A. Data provenance and analysis protocol", analysis_protocol(p).replace("ANALYSIS PROTOCOL (facts about what was actually done — describe only these):\n", "")]
    tables: list[Table] = []
    n = 100
    a = p.analysis
    if a and a.datasets:
        rows = []
        for d in a.datasets:
            for var, desc in (d.get("indicators") or {v: d.get("origin", "") for v in d.get("variables", [])}).items():
                rows.append([var, desc, d["name"]])
        if rows:
            n += 1
            tables.append(Table(number=n, caption="Variable dictionary", columns=["Variable", "Definition / source", "Dataset"], rows=rows, group="appendix"))
            parts.append("Appendix B. Variable dictionary")
            parts.append(f"[[TABLE {n}]]")
    refs = [r for r in p.references if r.status == "parsed"]
    if refs:
        n += 1
        tables.append(Table(number=n, caption="Reference corpus supplied for the study", columns=["#", "Title", "Year", "Pages"],
                            rows=[[str(i), r.title[:120], r.year or "n.d.", str(r.pages or "–")] for i, r in enumerate(refs, 1)], group="appendix"))
        parts.append("Appendix C. Reference corpus")
        parts.append(f"[[TABLE {n}]]")
    if p.web_sources:
        n += 1
        tables.append(Table(number=n, caption="Supplementary sources retrieved through database search", columns=["Database", "Title", "Year"],
                            rows=[[w.source, w.title[:120], w.year or "n.d."] for w in p.web_sources], group="appendix"))
        parts.append("Appendix D. Supplementary literature search")
        parts.append(f"[[TABLE {n}]]")
    return "\n\n".join(parts), "", {"tables": tables, "skip_guard": True}


# ====================================================================== revision & text tools
TOOL_INSTRUCTIONS = {
    "expand": "Expand this text by roughly 40%: deepen the argument, add supporting evidence with citations, and add a well-developed example or counterpoint.",
    "condense": "Condense this text by roughly 35% without losing any key argument, finding or citation. Remove redundancy.",
    "formalize": "Raise the academic register: more precise terminology, measured hedging, and tighter logical connectives.",
    "simplify": "Improve clarity for a broad academic audience: shorter sentences, plainer wording, same meaning and citations.",
    "add_citations": "Strengthen the evidential basis: add citations from the evidence to every claim that currently lacks support, adding brief supporting detail where helpful.",
    "polish": "Polish grammar, flow and transitions between sentences and paragraphs without changing content.",
    "humanize": "Make the prose read as naturally human-written: vary rhythm and sentence openings, remove formulaic or repetitive phrasing, keep the scholarly tone.",
    "strengthen_argument": "Sharpen the argument: make claims more specific, make the logical chain explicit, and address an obvious counter-argument using the evidence.",
}


def revise_segment(pid: str, key: str, instruction: str, selection: str = "", reason: str = "revision") -> None:
    ws = Workspace(pid)
    llm.runtime.notify = ws.log
    bp = BLUEPRINTS[key]
    p = ws.project
    seg = p.segments[key]
    ws.set_segment(key, status="revising")
    ws.stage(f"Revising {bp.title}", "revising", key=key)
    try:
        if bp.special in {"references"}:
            content, evidence, extras = build_references(ws, bp, "quick")
            finalize(ws, key, content, evidence, reason=reason, **extras)
            return
        if bp.special in {"title", "keywords"}:
            new = llm.generate(AUTHOR_SYSTEM, f"Current {bp.title.lower()}: {seg.content}\nArticle: {p.title}\nInstruction: {instruction}\n"
                               f"Return only the revised {bp.title.lower()}" + (" as a semicolon-separated list." if key == "keywords" else "."), temperature=0.6, max_tokens=200)
            finalize(ws, key, new.strip().strip('"'), "", reason=reason, skip_guard=True)
            return

        chunks = retrieve(ws, [f"{instruction} {p.title}", f"{bp.title} {p.topic or p.title}"], k_each=5, cap=8) if bp.needs_evidence and ws.index.chunks else []
        evidence = evidence_block(chunks, p) if chunks else ""
        findings = findings_text(p.analysis) if key in {"results", "discussion", "conclusion", "limitations", "abstract", "methodology"} else ""
        protocol = analysis_protocol(p) if key == "methodology" else ""
        target = selection.strip() if selection.strip() and selection.strip() in seg.content else seg.content
        words = len(target.split())
        new = llm.generate(
            AUTHOR_SYSTEM,
            f"ARTICLE: {p.title}\nSECTION: {bp.title}\nSECTION PURPOSE: {bp.description}\n\n"
            f"AUTHOR'S REVISION REQUEST: {instruction}\n\n"
            + (f"PASSAGE TO REVISE (only this passage; it sits inside the longer section):\n{target}\n\n" if target is not seg.content else f"CURRENT SECTION:\n{target}\n\n")
            + (f"EVIDENCE AVAILABLE:\n{evidence}\n\n" if evidence else "") + (f"{findings}\n\n" if findings else "") + (f"{protocol}\n\n" if protocol else "")
            + f"RULES:\n{rules_text(bp, p)}\n- Apply the revision request faithfully; change nothing else unnecessarily.\n"
            "- Keep citation markers like [R2] that remain relevant and keep lines like [[TABLE 1]] / [[FIGURE 1]] exactly.\n"
            f"- Current length is ~{words} words; change length only if the request implies it.\n"
            "Output only the revised text.",
            temperature=0.65, max_tokens=int(max(words, 120) * 2.6) + 400,
        )
        new = new.strip()
        content = seg.content.replace(target, new, 1) if target is not seg.content else new
        if key == "results" and p.analysis:
            content = _restore_placeholders(content, AnalysisResult(tables=seg.tables, figures=seg.figures))
        finalize(ws, key, content, "\n".join([evidence, findings, protocol, seg.content]), reason=reason, depth="quick")
    except Exception as exc:  # noqa: BLE001
        ws.set_segment(key, status="draft", error=str(exc))
        raise


def review_and_fix(ws: Workspace, keys: list[str], apply_fixes: bool = True) -> dict:
    """Article-level consistency review; the most important issues are fixed automatically in draft segments."""
    p = ws.project
    sig = signature({k: p.segments[k].content for k in keys if k in p.segments})
    if ws.cp.corpus_done("review", sig) and p.review:
        ws.log("↺ Article review restored from checkpoint")
        return p.review
    ws.begin_stage("guard")
    ws.stage("Article review · checking consistency across all segments", "guard")
    try:
        report = factcheck.review_article(p, {k: s.content for k, s in p.segments.items() if k in keys and s.content})
    except Exception as exc:  # noqa: BLE001
        ws.log(f"⚠ Article review skipped ({exc})")
        return {}
    applied = 0
    for issue in report["issues"]:
        seg = ws.project.segments.get(issue["segment"])
        issue["applied"] = False
        if not apply_fixes or seg is None or seg.status != "draft" or applied >= 3:
            continue
        ws.log(f"Article review · fixing {seg.title}: {issue['issue'][:140]}")
        try:
            revise_segment(ws.pid, issue["segment"], issue["instruction"], reason=f"article review: {issue['type']}")
            issue["applied"] = True
            applied += 1
        except Exception as exc:  # noqa: BLE001
            ws.log(f"⚠ Could not apply review fix to {seg.title}: {exc}")
    report["at"] = time.time()
    store.mutate(ws.pid, lambda proj: setattr(proj, "review", report))
    ws.cp.mark_corpus("review", signature({k: ws.project.segments[k].content for k in keys if k in ws.project.segments}), "article review")
    ws.log(f"Article review: {len(report['issues'])} issue(s) found, {applied} fixed automatically")
    return report


def humanize_segment(pid: str, key: str, selection: str = "") -> None:
    """Studio Humanize tool: paragraph-level rewriting with a fact inventory and verification gate."""
    ws = Workspace(pid)
    llm.runtime.notify = ws.log
    bp = BLUEPRINTS[key]
    p = ws.project
    seg = p.segments[key]
    ws.set_segment(key, status="revising")
    ws.stage(f"Humanizing {bp.title}", "revising", key=key)
    try:
        target = selection.strip() if selection.strip() and selection.strip() in seg.content else seg.content
        new, report = style.humanize_text(
            target, title=p.title, section=bp.title, tone_rule=tone_instruction(p.tone),
            profile=style.field_profile(ws.dir / "index"), deep=True, progress=ws.log)
        content = seg.content.replace(target, new, 1) if target is not seg.content else new
        ws.log(f"Humanize · {bp.title}: rewrote {report['rewritten']}/{report['attempted']} paragraph(s) · style score "
               f"{report['score_before']} → {report['score_after']} · citations kept {report['citations_preserved']} · numbers kept {report['numbers_preserved']}")
        q = seg.quality.model_copy()
        q.style = style.metrics(content)
        q.humanize = {**report, "at": time.time()}
        ws.set_segment(key, content=content, quality=q, status="draft", error="",
                       versions=[*seg.versions, Version(content=content, reason=f"humanize: {report['rewritten']}/{report['attempted']} paragraphs")][-20:])
    except Exception as exc:  # noqa: BLE001
        ws.set_segment(key, status="draft", error=str(exc))
        raise


def regenerate_segment(pid: str, key: str) -> None:
    ws = Workspace(pid)
    p = ws.project
    llm.runtime.ensure(int(p.options.get("agents", 1)), notify=ws.log)
    ws.cp.clear_segment(key)
    write_segment(ws, key, p.options.get("depth", "thorough"))


def manual_edit(pid: str, key: str, content: str) -> Project:
    ws = Workspace(pid)
    p = ws.project
    seg = p.segments[key]
    q = seg.quality.model_copy()
    q.words = len(content.split())
    q.citations = len(citations.MARKER.findall(content))
    if BLUEPRINTS[key].special not in {"references", "title", "keywords", "appendices"} and ws.index.chunks:
        chk = originality.check(content, ws.fingerprint)
        q.ngram_overlap, q.flagged_sentences = round(chk.overlap, 4), len(chk.flagged)
        q.style = style.metrics(content)
    q.flags = [f for f in q.flags if f.get("sentence", "")[:80] in content]   # an edited-away sentence is no longer flagged
    return ws.set_segment(key, content=content, quality=q, status="draft", error="", versions=[*seg.versions, Version(content=content, reason="manual edit")][-20:])


def recover_interrupted_runs() -> None:
    """On server start, turn runs that were cut off (server stopped mid-fabrication) into resumable 'stopped' runs."""
    for p in store.list_all():
        interrupted = p.run.status == "running"
        # Studio jobs (regenerate/revise) can be cut off too, even after the fabrication run completed.
        if not interrupted and not any(s.status in {"working", "revising"} for s in p.segments.values()):
            continue

        def apply(proj: Project):
            end = proj.updated
            if interrupted:
                if proj.run.session_started:
                    proj.run.elapsed_before = round(proj.run.elapsed_before + max(0.0, end - proj.run.session_started), 1)
                _close_stages(proj.run, end)
                proj.run.session_started, proj.run.status = None, "stopped"
            for key, started in list(proj.run.segment_started.items()):
                proj.run.segment_seconds[key] = round(proj.run.segment_seconds.get(key, 0) + max(0.0, end - started), 1)
            proj.run.segment_started = {}
            for seg in proj.segments.values():
                if seg.status in {"working", "revising"}:
                    seg.status = "queued" if not seg.content else "draft"
        store.mutate(p.id, apply)
