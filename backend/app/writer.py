"""RAF writing engine.

Corpus pipeline:  parse references → extract metadata → chunk → plan research queries → multi-source web research
                  → hybrid neural/lexical index → statistical analysis.
Segment pipeline (per rhetorical move of the segment's blueprint):
                  retrieve (hybrid RRF + MMR) → evidence notes (paraphrased, cited) → draft paragraphs
                  → critic scores the blueprint checklist → refine → de-cliché → originality guard → number verification.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import numpy as np

from . import analysis as analysis_mod
from . import citations, jobs, llm, originality, research, store
from .blueprints import BLUEPRINTS, COMMON_RULES, Blueprint, Move, generation_order
from .ingest import chunk_text, heuristic_metadata, llm_metadata, read_any, strip_back_matter
from .models import AnalysisResult, Figure, GenerateRequest, Project, QualityReport, Segment, Table, Version
from .rag import Chunk, HybridIndex

log = logging.getLogger("raf.writer")

AUTHOR_SYSTEM = (
    "You are RAF, a senior academic author and peer reviewer who writes publication-ready scholarly articles. "
    "You write in fluent, natural, human academic English with precise terminology and original phrasing."
)


# ====================================================================== workspace
class Workspace:
    def __init__(self, pid: str) -> None:
        self.pid = pid
        self.dir = store.project_dir(pid)
        self._index: HybridIndex | None = None
        self._fp: originality.SourceFingerprint | None = None

    @property
    def project(self) -> Project:
        p = store.load(self.pid)
        if p is None:
            raise KeyError(self.pid)
        return p

    def log(self, message: str, **data) -> None:
        jobs.emit(self.pid, "log", message, **data)

    @property
    def index(self) -> HybridIndex:
        if self._index is None:
            self._index = HybridIndex.load(self.dir / "index")
        return self._index

    @property
    def fingerprint(self) -> originality.SourceFingerprint:
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


# ====================================================================== corpus
def build_corpus(ws: Workspace, req: GenerateRequest) -> None:
    p = ws.project
    jobs.emit(ws.pid, "stage", "Reading and indexing reference documents", stage="parsing")
    chunks: list[Chunk] = []
    ref_tables: list = []
    parsed_refs = []
    for ref in p.references:
        path = ws.dir / "uploads" / ref.filename
        try:
            ws.log(f"Parsing {ref.filename}")
            doc = read_any(path)
            if len(doc.text) < 300:
                raise ValueError("no extractable text (scanned PDF without OCR?)")
            meta = heuristic_metadata(doc, ref.filename)
            meta = llm_metadata(doc, meta)
            body = strip_back_matter(doc.text)
            (ws.dir / "index" / f"ref_{ref.id}.txt").write_text(body, encoding="utf-8")
            ref_tables.extend(doc.tables)
            ref.title, ref.authors, ref.year = meta["title"], meta["authors"], meta["year"]
            ref.venue, ref.doi = meta.get("venue", ""), meta.get("doi", "")
            ref.pages, ref.chars, ref.status, ref.error = doc.pages, len(body), "parsed", ""
            parsed_refs.append((ref, body))
            ws.log(f"✓ {ref.title[:90]} — {ref.pages or '?'} pages, {len(body):,} characters")
        except Exception as exc:  # noqa: BLE001
            ref.status, ref.error = "failed", str(exc)
            ws.log(f"✗ Could not read {ref.filename}: {exc}")

    labels = {}
    for i, (ref, body) in enumerate(parsed_refs, 1):
        label = f"R{i}"
        labels[ref.id] = label
        pieces = chunk_text(body)
        ref.chunks = len(pieces)
        chunks += [Chunk(id=f"{label}-{j}", text=t, source_id=ref.id, source_kind="reference", label=label) for j, t in enumerate(pieces)]
    (ws.dir / "index" / "ref_tables.json").write_text(json.dumps(ref_tables[:40]), encoding="utf-8")
    store.mutate(ws.pid, lambda proj: setattr(proj, "references", p.references))

    # ---- online research
    web = []
    if req.web_research:
        jobs.emit(ws.pid, "stage", "Researching the topic online", stage="research")
        queries = plan_queries(p, [r.title for r, _ in parsed_refs])
        ws.log("Research queries: " + " | ".join(queries))
        web = research.research(queries, p.discipline or p.topic, progress=ws.log)
        web = rank_web_sources(web, f"{p.title} {p.topic}", limit=36)
        ws.log(f"Kept {len(web)} relevant online sources after de-duplication and relevance ranking")
    store.mutate(ws.pid, lambda proj: setattr(proj, "web_sources", web))
    for i, w in enumerate(web, 1):
        label = f"W{i}"
        text = f"{w.title}. {w.abstract}"
        pieces = chunk_text(text, target_words=200) or [text[:1500]]
        chunks += [Chunk(id=f"{label}-{j}", text=t, source_id=w.id, source_kind="web", label=label) for j, t in enumerate(pieces[:4])]

    jobs.emit(ws.pid, "stage", "Building the hybrid retrieval index", stage="indexing")
    idx = HybridIndex()
    info = idx.build(chunks)
    idx.save(ws.dir / "index")
    ws._index, ws._fp = idx, None
    ws.log(f"Indexed {info['chunks']} passages · retrieval: {'neural embeddings + ' if info['neural'] else ''}BM25 + TF-IDF with rank fusion and MMR")

    # ---- analysis
    if req.data_analysis and any(k in req.segments for k in ("methodology", "results", "discussion", "conclusion", "abstract", "appendices")):
        jobs.emit(ws.pid, "stage", "Acquiring data and running statistical analysis", stage="analysis")
        datasets = [ws.dir / "datasets" / f for f in p.dataset_files]
        result = analysis_mod.run_analysis(ws.dir, p.title, p.topic, datasets, ref_tables, ws.log)
        store.mutate(ws.pid, lambda proj: setattr(proj, "analysis", result))
        ws.log(f"Analysis complete: {len(result.findings)} findings, {len(result.tables)} tables, {len(result.figures)} figures")


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
    evidence_segments = {"introduction", "literature_review", "methodology", "results", "discussion", "conclusion", "limitations"}
    if evidence_segments & set(keys) and "references" not in keys:
        keys.append("references")
        ws.log("References added automatically because the selected segments cite sources")

    def init(p: Project):
        p.selected = keys
        p.options = {**p.options, "web_research": req.web_research, "data_analysis": req.data_analysis, "depth": req.depth}
        p.stage = "processing"
        for k in keys:
            if k not in p.segments or p.segments[k].status != "approved":
                p.segments[k] = Segment(key=k, title=BLUEPRINTS[k].title, status="queued")
    store.mutate(pid, init)

    build_corpus(ws, req)
    for key in generation_order(keys):
        if ws.project.segments[key].status == "approved":
            continue
        write_segment(ws, key, req.depth)
    store.mutate(pid, lambda p: setattr(p, "stage", "studio"))
    jobs.emit(pid, "done", "All selected segments are drafted and ready for review")


def write_segment(ws: Workspace, key: str, depth: str = "thorough") -> None:
    bp = BLUEPRINTS[key]
    jobs.emit(ws.pid, "stage", f"Writing: {bp.title}", stage="writing", key=key)
    ws.set_segment(key, status="working", error="")
    try:
        builder = {
            "title": build_title, "abstract": build_abstract, "keywords": build_keywords, "references": build_references,
            "appendices": build_appendices, "literature_review": build_literature_review, "methodology": build_methodology,
            "results": build_results,
        }.get(bp.special or key, build_generic)
        content, evidence, extras = builder(ws, bp, depth)
        finalize(ws, key, content, evidence, reason="initial draft", depth=depth, **extras)
    except Exception as exc:  # noqa: BLE001
        log.exception("segment %s failed", key)
        ws.set_segment(key, status="failed", error=str(exc))
        ws.log(f"{bp.title} failed: {exc}")


def finalize(ws: Workspace, key: str, content: str, evidence: str, reason: str, depth: str = "thorough",
             figures: list[Figure] | None = None, tables: list[Table] | None = None, notes: list[str] | None = None,
             skip_guard: bool = False) -> None:
    bp = BLUEPRINTS[key]
    p = ws.project
    rewritten, overlap, flagged = 0, 0.0, 0
    if not skip_guard:
        content = originality.destyle(content)
        jobs.emit(ws.pid, "stage", f"Originality & integrity checks: {bp.title}", stage="guard", key=key)
        content, check, rewritten = originality.enforce(content, ws.fingerprint, progress=ws.log, rounds=2 if depth == "thorough" else 1)
        overlap, flagged = check.overlap, len(check.flagged)
    words = len(re.sub(r"\[\[.*?\]\]|\[[RW]\d+.*?\]", "", content).split())
    q = QualityReport(
        words=words, target_words=int(p.target_words * bp.word_share), ngram_overlap=round(overlap, 4),
        flagged_sentences=flagged, rewritten_sentences=rewritten, readability=originality.readability(content) if words > 80 else None,
        citations=len(citations.MARKER.findall(content)),
        unverified_numbers=[] if skip_guard else originality.unverified_numbers(content, evidence),
    )
    seg = p.segments.get(key) or Segment(key=key, title=bp.title)
    fields = {"content": content, "quality": q, "status": "draft", "versions": [*seg.versions, Version(content=content, reason=reason)][-20:]}
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
    # Interleave so that different queries (and sources) are represented before the cap.
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


def rules_text(bp: Blueprint) -> str:
    return "\n".join(f"- {r}" for r in (*COMMON_RULES, *bp.rules))


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
        + f"WRITING RULES:\n{rules_text(bp)}\n\n"
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
    revised = llm.generate(
        AUTHOR_SYSTEM,
        f"Revise the '{bp.title}' section below to fix the reviewer's issues.\n\nISSUES:\n{issues}\n\n"
        f"SECTION:\n{text}\n\nSUPPORTING EVIDENCE (use only if needed to fix unsupported claims):\n{evidence[:6000]}\n\n"
        f"RULES:\n{rules_text(bp)}\n- Keep every citation marker that remains relevant, keep lines like [[TABLE 1]] or [[FIGURE 1]] unchanged.\n"
        f"- Keep roughly the same length (~{words} words).\nOutput only the revised section.",
        temperature=0.6, max_tokens=int(words * 2.2) + 400,
    )
    return revised if len(revised.split()) > words * 0.6 else text


def run_moves(ws: Workspace, bp: Blueprint, moves: list[Move], total_words: int, depth: str, extra_context: str = "",
              extra_evidence: str = "") -> tuple[str, str]:
    p = ws.project
    subs = {"title": p.title, "topic": p.topic or p.title}
    body, evidence_log = "", [extra_evidence]
    share_sum = sum(m.share for m in moves) or 1
    for i, move in enumerate(moves, 1):
        jobs.emit(ws.pid, "stage", f"{bp.title} · move {i}/{len(moves)}: {move.name}", stage="writing", key=bp.key, move=move.name)
        words = max(90, int(total_words * move.share / share_sum))
        queries = [q.format(**subs) for q in move.queries] or []
        material = ""
        if queries and bp.needs_evidence:
            chunks = retrieve(ws, queries + [f"{move.name} {p.title}"], k_each=4, cap=10)
            ws.log(f"Retrieved {len(chunks)} passages from {len({c.source_id for c in chunks})} sources for “{move.name}”")
            ev = evidence_block(chunks, p)
            evidence_log.append(ev)
            material = take_notes(ws, bp, move, chunks) if depth == "thorough" else ev
        if extra_evidence:
            material = f"{material}\n\n{extra_evidence}".strip()
        para = draft_move(ws, bp, move, material or "(No external evidence needed; rely on the article context.)", words, body, extra_context)
        body = f"{body}\n\n{para.strip()}".strip()
    evidence = "\n\n".join(evidence_log)
    if depth == "thorough":
        body = critique_and_refine(ws, bp, body, evidence)
    return body, evidence


# ====================================================================== builders
def build_generic(ws: Workspace, bp: Blueprint, depth: str):
    p = ws.project
    ctx = article_context(p, bp.depends_on)
    findings = findings_text(p.analysis) if bp.key in {"discussion", "conclusion", "limitations"} else ""
    extra_ctx = f"ARTICLE CONTEXT:\n{ctx}" if ctx else ""
    body, evidence = run_moves(ws, bp, list(bp.moves), int(p.target_words * bp.word_share), depth, extra_ctx, findings)
    return body, evidence + "\n" + ctx, {}


def build_literature_review(ws: Workspace, bp: Blueprint, depth: str):
    p = ws.project
    themes = discover_themes(ws)
    ws.log("Literature themes identified: " + "; ".join(t["name"] for t in themes))
    moves = list(bp.moves)
    for t in themes:
        moves.append(Move(t["name"], f"Synthesise the literature on this theme: {t['focus']} Compare and contrast authors, evaluate the strength of evidence, and note unresolved debates.",
                          tuple([t["name"], *t.get("queries", [])][:3]), 0.8 / max(1, len(themes))))
    hypotheses = " If the evidence supports it, finish with clearly labelled hypotheses (H1, H2 …) that the analysis can test." if p.analysis and p.analysis.findings else ""
    moves.append(Move("Synthesis and research gap", "Integrate the themes into an overall picture, identify precisely what remains unknown or contested, and explain how this article addresses that gap." + hypotheses,
                      (f"research gap {p.topic or p.title}", f"future research needed {p.title}"), 0.2))
    ctx = article_context(p, ("introduction",), 350)
    body, evidence = run_moves(ws, bp, moves, int(p.target_words * bp.word_share), depth, f"ARTICLE CONTEXT:\n{ctx}" if ctx else "")
    # Sub-headings for themes make long reviews navigable: insert them as '### ' lines is avoided (destyle strips).
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
    body, evidence = run_moves(ws, bp, moves, int(p.target_words * bp.word_share), depth, f"{protocol}\n\nARTICLE CONTEXT:\n{ctx}", protocol)
    return body, evidence, {}


def build_results(ws: Workspace, bp: Blueprint, depth: str):
    p = ws.project
    a = p.analysis
    ctx = article_context(p, ("introduction", "methodology"), 300)
    if not (a and a.findings):
        return build_synthesis_results(ws, bp, depth, ctx)

    groups = list(dict.fromkeys([d["name"] for d in a.datasets]))
    total = int(p.target_words * bp.word_share)
    body_parts = []
    intro = llm.generate(
        AUTHOR_SYSTEM,
        f"Article: {p.title}\n{ctx}\n\n{findings_text(a)}\n\nWrite one short opening paragraph (60–90 words) for the Results section "
        "that tells the reader what analyses are reported and in what order. No numbers yet, no interpretation. Output only the paragraph.",
        temperature=0.6, max_tokens=250,
    )
    body_parts.append(intro.strip())
    for g in groups:
        jobs.emit(ws.pid, "stage", f"Results · reporting “{g}”", stage="writing", key="results")
        g_findings = [f for f in a.findings if f.startswith(f"[{g}]")]
        g_tables = [t for t in a.tables if t.group == g]
        g_figs = [f for f in a.figures if f.group == g]
        items = "\n".join([f"- Table {t.number}: {t.caption}" for t in g_tables] + [f"- Figure {f.number}: {f.caption}" for f in g_figs])
        para = llm.generate(
            AUTHOR_SYSTEM,
            f"Article: {p.title}\nSECTION: Results — {g}\n\nFINDINGS (use numbers exactly as written, never add others):\n"
            + "\n".join(f"- {f.split('] ', 1)[-1]}" for f in g_findings)
            + f"\n\nTABLES AND FIGURES AVAILABLE:\n{items or '(none)'}\n\nRULES:\n{rules_text(bp)}\n\n"
            f"Write about {max(150, total // max(1, len(groups)))} words reporting these findings objectively. Refer to each table and figure by number "
            "('Table 2 summarises…', '(see Figure 1)'). Report test statistic, p-value and effect size together. No citations, no interpretation. Output only prose.",
            temperature=0.55, max_tokens=int(total * 2) + 300,
        )
        block = para.strip() + "\n\n" + "\n\n".join([f"[[TABLE {t.number}]]" for t in g_tables] + [f"[[FIGURE {f.number}]]" for f in g_figs])
        body_parts.append(block.strip())
    body = "\n\n".join(body_parts)
    evidence = findings_text(a) + "\n" + "\n".join(f"{t.caption} {t.note} " + " ".join(" ".join(r) for r in t.rows) for t in a.tables)
    if depth == "thorough":
        body = critique_and_refine(ws, bp, body, evidence)
        body = _restore_placeholders(body, a)
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
    ws.log("No numerical dataset available — reporting a structured evidence synthesis instead of statistics")
    chunks = retrieve(ws, [f"findings results {p.title}", f"empirical evidence {p.topic}", f"outcomes effects {p.title}", f"key conclusions {p.topic}"], k_each=5, cap=16)
    ev = evidence_block(chunks, p, max_words=140)
    data = llm.generate_json(
        "You build evidence-synthesis tables for systematic reviews. Reply with JSON only.",
        f"Article: {p.title}\n\nEVIDENCE:\n{ev}\n\nGroup the evidence into 3–6 findings themes. For each give: theme (short), "
        "principal_evidence (one paraphrased sentence, include numbers only if printed in the evidence), direction "
        "(Supportive / Mixed / Contradictory), sources (list of labels like R1). JSON: {\"rows\": [{...}]}",
        default={}, max_tokens=1200,
    )
    rows = [r for r in (data.get("rows") or []) if isinstance(r, dict) and r.get("theme")][:6]
    labels = citations.label_map(p)
    table = Table(number=1, caption="Synthesis of principal findings across the reviewed evidence", columns=["Theme", "Principal evidence", "Direction", "Sources"],
                  rows=[[str(r.get("theme")), str(r.get("principal_evidence", "")), str(r.get("direction", "")),
                         "; ".join(citations.short_label(labels[l]) for l in r.get("sources", []) if isinstance(l, str) and l in labels)] for r in rows],
                  note="Direction indicates whether the balance of evidence supports, partly supports, or contradicts the theme.", group="synthesis")
    moves = [Move("Evidence synthesis", "Report the findings theme by theme, stating the pattern of evidence, its consistency across sources, and the strength of support. Refer to Table 1. Do not interpret implications yet.", (), 1.0)]
    material = take_notes(ws, bp, moves[0], chunks) if depth == "thorough" else ev
    material += "\n\nSYNTHESIS TABLE ROWS:\n" + "\n".join(" | ".join(r) for r in table.rows)
    body = draft_move(ws, bp, moves[0], material, int(p.target_words * bp.word_share), "", f"ARTICLE CONTEXT:\n{ctx}")
    body = body.strip() + "\n\n[[TABLE 1]]"
    return body, ev, {"tables": [table] if table.rows else [], "figures": []}


def build_abstract(ws: Workspace, bp: Blueprint, depth: str):
    p = ws.project
    ctx = article_context(p, ("introduction", "methodology", "results", "discussion", "conclusion"), 380)
    if not ctx:
        ctx = findings_text(p.analysis) or f"Topic: {p.topic}"
    text = llm.generate(
        AUTHOR_SYSTEM,
        f"ARTICLE TITLE: {p.title}\n\n{ctx}\n\n{findings_text(p.analysis)}\n\nRULES:\n{rules_text(bp)}\n\n"
        "Write the abstract now as one paragraph of 180–250 words. No citations, no headings. Output only the abstract.",
        temperature=0.6, max_tokens=700,
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
    bp = BLUEPRINTS[key]
    p = ws.project
    seg = p.segments[key]
    ws.set_segment(key, status="revising")
    jobs.emit(pid, "stage", f"Revising {bp.title}", stage="revising", key=key)
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
            + f"RULES:\n{rules_text(bp)}\n- Apply the revision request faithfully; change nothing else unnecessarily.\n"
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


def regenerate_segment(pid: str, key: str) -> None:
    ws = Workspace(pid)
    write_segment(ws, key, ws.project.options.get("depth", "thorough"))


def manual_edit(pid: str, key: str, content: str) -> Project:
    ws = Workspace(pid)
    p = ws.project
    seg = p.segments[key]
    q = seg.quality.model_copy()
    q.words = len(content.split())
    q.citations = len(citations.MARKER.findall(content))
    if ws.index.chunks and BLUEPRINTS[key].special not in {"references", "title", "keywords", "appendices"}:
        chk = originality.check(content, ws.fingerprint)
        q.ngram_overlap, q.flagged_sentences = round(chk.overlap, 4), len(chk.flagged)
    return ws.set_segment(key, content=content, quality=q, status="draft", versions=[*seg.versions, Version(content=content, reason="manual edit")][-20:])
