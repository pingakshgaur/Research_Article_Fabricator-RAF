"""Fabrication time estimate, computed in the first seconds of a run.

1. Speed probe (≤ PROBE_SECONDS): a tiny streamed generation with the real model settings measures output tokens/sec.
   It also warms the model, so the first real call does not pay the load time again.
2. Work inventory: which references still need reading, whether research / index / analysis can be reused,
   which segments are left and their word targets, depth, filters and number of agents.
3. Cost model: per-stage and per-segment seconds, calibrated on real RAF runs at REFERENCE_TOKS tokens/sec and
   scaled by the measured speed. Parallel segments are placed on agent lanes exactly like the scheduler does.
4. Self-calibration: every completed run stores estimated vs actual seconds in <data_dir>/timing_history.json;
   the median ratio of recent runs corrects later estimates, so accuracy improves with use.
"""
from __future__ import annotations

import json
import logging
import statistics
import threading
import time

import httpx

from . import llm, llm_settings, store
from .blueprints import BLUEPRINTS, generation_order
from .config import settings

log = logging.getLogger("raf.estimate")

HISTORY = settings.data_dir / "timing_history.json"
PROBE_SECONDS = 14.0
REFERENCE_TOKS = 3.7           # probe tokens/sec (warm, 40 tokens) on the machine the coefficients were measured on
_history_lock = threading.Lock()

# Seconds for a segment at REFERENCE_TOKS with one agent: fixed + per_word × target words.
SEGMENT_COST = {
    "quick": {
        "introduction": (390, 0.48), "literature_review": (250, 0.47), "methodology": (14, 0.47), "results": (30, 0.45),
        "discussion": (14, 0.46), "conclusion": (14, 0.46), "limitations": (14, 0.46), "abstract": (0, 0.39),
        "title": (37, 0), "keywords": (22, 0), "references": (1, 0), "appendices": (45, 0), "_default": (14, 0.47),
    },
    "thorough": {
        "introduction": (1000, 3.65), "literature_review": (450, 3.18), "methodology": (0, 3.24), "results": (60, 0.57),
        "discussion": (0, 3.89), "conclusion": (0, 3.18), "limitations": (0, 3.61), "abstract": (0, 1.07),
        "title": (44, 0), "keywords": (23, 0), "references": (1, 0), "appendices": (90, 0), "_default": (0, 3.5),
    },
}
NO_GUARD = {"title", "keywords", "references", "appendices"}
FILTER_OFF = 0.82              # hallucination filter adds ~18% to evidence segments
STYLE_OFF = 0.92               # thorough style pass adds ~8%
CONTENTION = {1: 1.0, 2: 1.45, 3: 1.95}   # per-segment slow-down when lanes share one GPU/CPU
THROUGHPUT = {1: 1.0, 2: 1.38, 3: 1.54}   # total speed-up for independent calls (reference metadata)

PARSE_LOCAL = 3.0              # PDF/DOCX text extraction per reference
PARSE_LLM = 38.0               # metadata call per reference
RESEARCH_NETWORK, RESEARCH_LLM = 16.0, 19.0
ANALYSIS_BASE, ANALYSIS_PER_DATASET = 30.0, 20.0
REVIEW_BASE, REVIEW_PER_WORD = 75.0, 0.26


# ---------------------------------------------------------------------------- speed probe
def probe_speed(deadline: float = PROBE_SECONDS) -> dict:
    """Measure output tokens/sec with the real model options. Never takes much longer than `deadline`."""
    s = llm_settings.get()
    payload = {
        "model": s["model"], "prompt": "Write one plain sentence about why libraries keep old newspapers.", "stream": True,
        "think": False, "keep_alive": s["keep_alive"],
        "options": llm_settings.build_options(s, temperature=0.2, max_tokens=40, num_gpu=llm.runtime.effective_gpu(s)),
    }
    started = time.monotonic()
    first = last = None
    tokens = 0
    done: dict = {}
    try:
        with httpx.Client(timeout=httpx.Timeout(deadline, connect=3.0)) as client:
            with client.stream("POST", f"{settings.ollama_url}/api/generate", json=payload) as r:
                if r.status_code != 200:
                    raise RuntimeError(f"HTTP {r.status_code}")
                for line in r.iter_lines():
                    now = time.monotonic()
                    if line:
                        d = json.loads(line)
                        if d.get("done"):
                            done = d
                            break
                        if d.get("response"):
                            tokens += 1
                            first = first or now
                            last = now
                    if now - started > deadline:
                        break
    except Exception as exc:  # noqa: BLE001 - a failed probe falls back to the last known speed
        log.info("speed probe incomplete: %s", exc)
    toks = 0.0
    if done.get("eval_duration") and done.get("eval_count", 0) >= 4:
        toks = done["eval_count"] / (done["eval_duration"] / 1e9)
    elif tokens >= 5 and last and first and last > first:
        toks = (tokens - 1) / (last - first)
    return {"tok_s": round(toks, 2), "seconds": round(time.monotonic() - started, 1), "model": s["model"]}


# ---------------------------------------------------------------------------- history
def _load_history() -> dict:
    try:
        return json.loads(HISTORY.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"runs": [], "last_speed": {}}


def _save_history(data: dict) -> None:
    tmp = HISTORY.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(HISTORY)


def _calibration(depth: str) -> dict[str, float]:
    """Median actual/estimated ratio per component over recent comparable runs (1.0 when there is no history)."""
    runs = [r for r in _load_history().get("runs", []) if r.get("depth") == depth][-6:]
    out = {}
    for part in ("segments", "parsing", "research", "analysis", "review"):
        ratios = [r["ratios"][part] for r in runs if part in r.get("ratios", {})]
        if ratios:
            med = min(2.0, max(0.5, statistics.median(ratios)))
            out[part] = round(1 + (med - 1) * min(1.0, len(ratios) / 3), 3)   # trust grows with the number of runs
        else:
            out[part] = 1.0
    return out


# ---------------------------------------------------------------------------- cost model
def segment_seconds(key: str, words: int, depth: str, filter_on: bool, style_on: bool) -> float:
    table = SEGMENT_COST["thorough" if depth == "thorough" else "quick"]
    fixed, per_word = table.get(key, table["_default"])
    secs = fixed + per_word * words
    if key not in NO_GUARD:
        if not filter_on:
            secs *= FILTER_OFF
        if depth == "thorough" and not style_on:
            secs *= STYLE_OFF
    return secs


def simulate_lanes(keys: list[str], durations: dict[str, float], agents: int, settled: set[str]) -> float:
    """Wall-clock seconds for the dependency-aware scheduler in writer.run_segments."""
    selected = set(keys)
    evidence = {"introduction", "literature_review", "methodology", "results", "discussion", "conclusion", "limitations"}

    def deps(key: str) -> list[str]:
        if key == "references":
            return [k for k in keys if k in evidence]
        return [d for d in BLUEPRINTS[key].depends_on if d in selected]

    pending = [k for k in generation_order(keys) if k not in settled]
    done = set(settled)
    running: list[tuple[float, str]] = []   # (finish time, key)
    clock = 0.0
    while pending or running:
        for key in list(pending):
            if len(running) >= agents:
                break
            if all(d in done for d in deps(key)):
                pending.remove(key)
                running.append((clock + durations.get(key, 0.0), key))
        if not running:                      # unresolvable dependency: the scheduler writes it anyway
            key = pending.pop(0)
            running.append((clock + durations.get(key, 0.0), key))
        running.sort()
        clock, key = running.pop(0)
        done.add(key)
    return clock


def compute(p, req, keys: list[str], speed: dict) -> dict:
    """Estimate the remaining work of a run. `p` is the project after the run was initialised."""
    tok_s = speed.get("tok_s") or 0.0
    history = _load_history()
    source = "probe"
    if tok_s <= 0:
        tok_s = history.get("last_speed", {}).get(speed.get("model", ""), 0.0) or REFERENCE_TOKS
        source = "previous run" if history.get("last_speed", {}).get(speed.get("model", "")) else "default"
    factor = min(8.0, max(0.12, REFERENCE_TOKS / tok_s))
    agents = max(1, min(3, int(req.agents)))
    depth = req.depth
    cal = _calibration(depth)
    raw: dict[str, float] = {}

    # ---- reading references (cached text from an earlier run is reused)
    index_dir = store.project_dir(p.id) / "index"
    new_refs = [r for r in p.references if not (r.status == "parsed" and (index_dir / f"ref_{r.id}.txt").exists())]
    raw["parsing"] = len(new_refs) * (PARSE_LOCAL + PARSE_LLM * factor / THROUGHPUT[agents])

    # ---- online research (reused when the title/topic did not change)
    research_key = f"{p.title}|{p.topic}|{p.discipline}"
    research_reused = bool(p.web_sources) and p.options.get("research_key", research_key) == research_key
    raw["research"] = 0.0 if not req.web_research or research_reused else RESEARCH_NETWORK + RESEARCH_LLM * factor

    # ---- index
    index_reused = not new_refs and (research_reused or not req.web_research) and (index_dir / "index.pkl").exists()
    ref_chars = sum(r.chars for r in p.references) or len(p.references) * 120_000
    raw["indexing"] = 0.5 if index_reused else 3.0 + ref_chars / 1_000_000 * 4

    # ---- data analysis
    wants_analysis = req.data_analysis and any(k in keys for k in ("methodology", "results", "discussion", "conclusion", "abstract", "appendices"))
    analysis_reused = p.analysis is not None and not new_refs
    raw["analysis"] = 0.0 if not wants_analysis else 1.0 if analysis_reused else (ANALYSIS_BASE + ANALYSIS_PER_DATASET * len(p.dataset_files)) * (0.5 + 0.5 * factor)

    # ---- segments
    from .writer import segment_words   # local import: writer imports this module
    settled = {k for k in keys if (s := p.segments.get(k)) and s.content and s.status in {"approved", "draft"}}
    seg_est: dict[str, float] = {}
    for k in keys:
        if k in settled:
            continue
        words = segment_words(p, k) if (BLUEPRINTS[k].word_share or k == "abstract") else 0
        base = segment_seconds(k, words, depth, req.hallucination_filter, req.style_pass) * factor
        seg_est[k] = round(base * CONTENTION[agents] * cal["segments"], 1)
    writing = simulate_lanes(keys, seg_est, agents, settled)

    # ---- article review (thorough only)
    body_words = sum(segment_words(p, k) for k in keys if BLUEPRINTS[k].word_share)
    raw["review"] = (REVIEW_BASE + REVIEW_PER_WORD * body_words) * factor if depth == "thorough" and seg_est else 0.0

    stages = {
        "parsing": raw["parsing"] * cal["parsing"], "research": raw["research"] * cal["research"], "indexing": raw["indexing"],
        "analysis": raw["analysis"] * cal["analysis"], "writing": writing, "guard": raw["review"] * cal["review"],
    }
    stages = {k: round(v, 1) for k, v in stages.items()}
    remaining = sum(stages.values())
    return {
        "created": time.time(),
        "tok_s": round(tok_s, 2), "speed_source": source, "probe_seconds": speed.get("seconds", 0.0), "model": speed.get("model", ""),
        "depth": depth, "agents": agents,
        "elapsed_at_start": round(p.run.elapsed_before, 1),
        "remaining": round(remaining, 1),
        "total": round(p.run.elapsed_before + speed.get("seconds", 0.0) + remaining, 1),
        "stages": stages,
        "segments": seg_est,
        "raw": {**{k: round(v, 1) for k, v in raw.items()},
                "segments": round(sum(seg_est.values()) / (CONTENTION[agents] * cal["segments"]), 1) if seg_est else 0.0},
        "calibration": cal,
        "inventory": {"new_references": len(new_refs), "research_reused": research_reused, "index_reused": index_reused,
                      "segments_to_write": len(seg_est), "segments_kept": len(settled)},
    }


# ---------------------------------------------------------------------------- learning from finished runs
def record(p) -> None:
    """Store estimated vs actual seconds of a completed run to calibrate future estimates."""
    est = p.run.estimate or {}
    if not est.get("raw"):
        return
    agents = est.get("agents", 1)
    raw = est["raw"]
    actual_stages = p.run.stages
    ratios = {}
    seg_actual = sum(p.run.segment_seconds.get(k, 0) for k in est.get("segments", {}))
    if raw.get("segments", 0) > 60 and seg_actual > 0:
        ratios["segments"] = round(seg_actual / (raw["segments"] * CONTENTION.get(agents, 1)), 3)
    for part, stage in (("parsing", "parsing"), ("research", "research"), ("analysis", "analysis"), ("review", "guard")):
        if raw.get(part, 0) > 20 and actual_stages.get(stage, 0) > 0:
            ratios[part] = round(actual_stages[stage] / raw[part], 3)
    total_actual = p.run.elapsed_before
    with _history_lock:
        data = _load_history()
        if est.get("speed_source") == "probe" and est.get("model"):
            data.setdefault("last_speed", {})[est["model"]] = est["tok_s"]
        data.setdefault("runs", []).append({
            "at": time.time(), "project": p.id, "depth": est.get("depth"), "agents": agents, "tok_s": est.get("tok_s"),
            "estimated_total": est.get("total"), "actual_total": round(total_actual, 1), "ratios": ratios,
        })
        data["runs"] = data["runs"][-40:]
        _save_history(data)
    log.info("timing history: estimated %.0fs, actual %.0fs, ratios %s", est.get("total", 0), total_actual, ratios)


def remember_speed(model: str, tok_s: float) -> None:
    if tok_s <= 0 or not model:
        return
    with _history_lock:
        data = _load_history()
        data.setdefault("last_speed", {})[model] = tok_s
        _save_history(data)


def fmt(seconds: float) -> str:
    s = int(max(0, seconds))
    h, m = s // 3600, (s % 3600) // 60
    return f"{h}h {m:02d}m" if h else f"{m}m {s % 60:02d}s" if m else f"{s}s"
