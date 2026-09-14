"""Hallucination filter.

Runs on every drafted segment before it reaches the Studio, in four layers:

1. Sanitiser     — removes model commentary ("Here is…"), placeholders ("[insert…]", "(Author, Year)"), repeated
                   sentences, truncated endings, and citation labels that point to sources that do not exist.
2. Coherence     — a reviewer pass flags paragraphs that are off-topic, self-contradictory or empty padding; those
                   paragraphs are rewritten from the evidence (thorough mode).
3. Grounding     — every checkable claim (cited, numeric, or naming specific actors, places or years) is compared with
                   the passages of the source it cites. Clear lexical support is accepted directly; everything else goes
                   to a batched judge that labels it supported / partial / unsupported / contradicted. Uncited claims
                   that a source clearly supports get the citation added.
4. Repair        — unsupported and contradicted sentences are corrected from the evidence or removed; the corrected
                   paragraph is re-checked. Anything that still cannot be verified is listed in the Studio's integrity
                   report and highlighted in the text, so nothing questionable is hidden.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from . import citations, llm
from .ingest import split_sentences
from .rag import tokenize

MARKER = re.compile(r"\[((?:[RW]\d+)(?:\s*[,;]\s*[RW]\d+)*)\]")
PLACEHOLDER_LINE = re.compile(r"^\[\[(TABLE|FIGURE) \d+\]\]$")
NUMBER = re.compile(r"(?<![\w\[])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")
YEAR = re.compile(r"\b(19|20)\d{2}\b")
PROPER = re.compile(r"(?<!^)(?<![.!?]\s)\b[A-Z][a-z]{2,}(?:\s[A-Z][a-z]{2,})*")
META = re.compile(r"^\s*(here is|here's|sure[,!]|certainly[,!]|below is|i have (rewritten|revised|written)|as an ai|note:|revised (section|paragraph)|this (section|paragraph) (has been|was) (revised|rewritten)).*$", re.I | re.M)
FAKE = re.compile(r"\[(insert|citation needed|add citation|source|ref|todo)[^\]]*\]|\((author|authors|et al\.?),?\s*(year|n\.d\.|20xx)\)|\bXX+\b|lorem ipsum", re.I)
GENERIC_WORDS = set("study studies research researcher researchers finding findings evidence suggest suggests show shows article paper "
                    "analysis literature approach approaches important significant various several different context contexts".split())
SUPPORT_THRESHOLD = 0.62
JUDGE_BATCH = 6


def _content_stems(text: str) -> set[str]:
    return {w[:6] for w in tokenize(MARKER.sub("", text)) if len(w) >= 4 and w not in GENERIC_WORDS}


def lexical_support(sentence: str, passage: str) -> float:
    s = _content_stems(sentence)
    if not s:
        return 1.0
    return len(s & _content_stems(passage)) / len(s)


# ============================================================================================ 1. sanitiser
def sanitise(text: str, valid_labels: set[str]) -> tuple[str, list[dict]]:
    flags = []
    text = META.sub("", text)
    text = FAKE.sub("", text)
    text = re.sub(r"^\s*#+\s.*$", "", text, flags=re.M)

    def fix_markers(m: re.Match) -> str:
        labels = [l for l in re.split(r"\s*[,;]\s*", m.group(1))]
        good = [l for l in labels if l in valid_labels]
        bad = [l for l in labels if l not in valid_labels]
        if bad:
            flags.append({"sentence": "", "verdict": "invalid_citation", "reason": f"citation to non-existent source {', '.join(bad)} removed"})
        return f"[{', '.join(good)}]" if good else ""

    text = MARKER.sub(fix_markers, text)
    seen, paragraphs = set(), []
    for para in re.split(r"\n\s*\n", text):
        p = para.strip()
        if not p:
            continue
        if PLACEHOLDER_LINE.match(p):
            paragraphs.append(p)
            continue
        kept = []
        for s in split_sentences(p):
            key = re.sub(r"\W+", " ", MARKER.sub("", s)).strip().lower()
            if len(key) > 25 and key in seen:
                flags.append({"sentence": s[:160], "verdict": "duplicate", "reason": "repeated sentence removed"})
                continue
            seen.add(key)
            kept.append(s)
        if kept and not re.search(r"[.!?)\]\"”]$", kept[-1]) and len(kept[-1].split()) < 40:
            flags.append({"sentence": kept[-1][:160], "verdict": "truncated", "reason": "unfinished sentence removed"})
            kept = kept[:-1]
        if kept:
            paragraphs.append(" ".join(kept))
    cleaned = "\n\n".join(paragraphs)
    cleaned = re.sub(r"[ \t]+([.,;:])", r"\1", cleaned)
    return re.sub(r"[ \t]{2,}", " ", cleaned), flags


# ============================================================================================ 2. coherence
def coherence_pass(text: str, *, title: str, section: str, purpose: str, evidence: str, rules: str) -> tuple[str, list[dict]]:
    paras = re.split(r"\n\s*\n", text)
    numbered = "\n\n".join(f"[{i + 1}] {p}" for i, p in enumerate(paras) if not PLACEHOLDER_LINE.match(p.strip()))
    verdict = llm.generate_json(
        "You are a meticulous journal referee checking whether text makes sense. Reply with JSON only.",
        f"ARTICLE: {title}\nSECTION: {section} — {purpose}\n\nPARAGRAPHS:\n{numbered}\n\n"
        "Identify only paragraphs with a real problem: off-topic for this section, internally contradictory, logically "
        "incoherent, making sweeping claims with no basis, or empty padding that says nothing specific. Ignore minor style.\n"
        "JSON: {\"problems\": [{\"paragraph\": 1, \"issue\": \"what is wrong\", \"fix\": \"what the paragraph should do instead\"}]}",
        default={}, max_tokens=700,
    )
    problems = [p for p in (verdict.get("problems") or []) if isinstance(p, dict) and isinstance(p.get("paragraph"), int) and 1 <= p["paragraph"] <= len(paras)][:4]
    flags = []
    for prob in problems:
        i = prob["paragraph"] - 1
        original = paras[i]
        if PLACEHOLDER_LINE.match(original.strip()):
            continue
        try:
            new = llm.generate(
                "You are RAF, a senior academic author. You repair flawed paragraphs using only the supplied evidence.",
                f"ARTICLE: {title}\nSECTION: {section}\nPROBLEM: {prob.get('issue', '')}\nWHAT IT SHOULD DO: {prob.get('fix', '')}\n\n"
                f"PARAGRAPH:\n{original}\n\nEVIDENCE (the only permitted source of facts):\n{evidence[:5000]}\n\nRULES:\n{rules}\n"
                "- Keep valid citation markers such as [R2]; never invent sources, numbers or names.\n"
                "Output only the repaired paragraph.",
                temperature=0.5, max_tokens=int(len(original.split()) * 2.2) + 200,
            ).strip()
        except llm.LLMError:
            continue
        if len(new.split()) >= 0.5 * len(original.split()):
            paras[i] = re.sub(r"\n\s*\n", " ", new)
            flags.append({"sentence": original[:160], "verdict": "repaired", "reason": f"paragraph rewritten: {prob.get('issue', '')}"})
    return "\n\n".join(paras), flags


# ============================================================================================ 3. grounding
def _claims(text: str) -> list[dict]:
    out = []
    for pi, para in enumerate(re.split(r"\n\s*\n", text)):
        if PLACEHOLDER_LINE.match(para.strip()):
            continue
        for s in split_sentences(para):
            labels = [l for g in MARKER.findall(s) for l in re.split(r"\s*[,;]\s*", g)]
            bare = MARKER.sub("", s)
            numeric = bool(NUMBER.search(re.sub(r"\b(Table|Figure|H|RQ)\s*\d+", "", bare)))
            specific = bool(PROPER.search(bare)) or bool(YEAR.search(bare))
            if labels or numeric or specific:
                out.append({"sentence": s, "paragraph": pi, "labels": labels, "numeric": numeric})
    return out


def ground(text: str, ws, evidence: str, *, deep: bool, max_claims: int = 45) -> tuple[str, dict, list[dict]]:
    p = ws.project
    label_map = citations.label_map(p)
    index = ws.index
    claims = _claims(text)[:max_claims]
    stats = {"checked": len(claims), "supported": 0, "partial": 0, "unsupported": 0, "contradicted": 0, "unverified": 0,
             "auto_cited": 0, "corrected": 0, "removed": 0}
    to_judge = []
    for c in claims:
        bare = MARKER.sub("", c["sentence"])
        if evidence and lexical_support(bare, evidence) >= 0.8 and not c["labels"]:
            c["verdict"] = "supported"      # restates the article's own findings/protocol/context
            continue
        if c["labels"]:
            ids = {label_map[l].id for l in c["labels"] if l in label_map}
            passages = index.search_within(bare, ids, k=3) if ids else []
        else:
            passages = index.search_within(bare, None, k=3)
        c["passages"] = passages
        best = max((lexical_support(bare, ch.text) for ch in passages), default=0.0)
        c["support"] = best
        if best >= SUPPORT_THRESHOLD:
            c["verdict"] = "supported"
            if not c["labels"] and passages and (c["numeric"] or best >= 0.75):
                c["add_label"] = passages[0].label
        else:
            to_judge.append(c)
    # Quick mode judges the weakest claims first, within a budget; thorough mode judges all of them.
    to_judge.sort(key=lambda c: (not c["numeric"], c.get("support", 0)))
    for c in to_judge[(max_claims if deep else 20):]:
        c["verdict"] = "unverified"
    to_judge = to_judge[:(max_claims if deep else 20)]

    def judge(batch: list[dict]) -> None:
        blocks = []
        for i, c in enumerate(batch, 1):
            psg = "\n".join(f"  ({ch.label}) {' '.join(ch.text.split()[:120])}" for ch in c.get("passages", [])[:2]) or "  (no matching passage)"
            blocks.append(f"CLAIM {i}: {MARKER.sub('', c['sentence'])}\nCITED: {', '.join(c['labels']) or 'none'}\nPASSAGES:\n{psg}")
        data = llm.generate_json(
            "You are a fact-checker for academic manuscripts. Judge each claim strictly against its passages. Reply with JSON only.",
            "For each claim decide:\n- supported: the passages state it (paraphrase is fine)\n- partial: the gist is there but a detail (scope, number, "
            "direction, certainty) is overstated or wrong\n- unsupported: the passages do not say it\n- contradicted: the passages say the opposite\n"
            "For partial/unsupported/contradicted, give a corrected sentence that says only what the passages support (keep it close to the original), "
            "or an empty string if nothing can be salvaged.\n\n" + "\n\n".join(blocks)
            + "\n\nJSON: {\"verdicts\": [{\"claim\": 1, \"label\": \"supported|partial|unsupported|contradicted\", \"reason\": \"short\", \"correction\": \"\"}]}",
            default={}, max_tokens=180 * len(batch) + 200,
        )
        for v in data.get("verdicts") or []:
            try:
                c = batch[int(v.get("claim")) - 1]
            except (TypeError, ValueError, IndexError):
                continue
            label = str(v.get("label", "")).lower()
            if label in {"supported", "partial", "unsupported", "contradicted"}:
                c["verdict"], c["reason"], c["correction"] = label, str(v.get("reason", ""))[:200], str(v.get("correction", "")).strip()
        for c in batch:
            c.setdefault("verdict", "unverified")

    batches = [to_judge[i:i + JUDGE_BATCH] for i in range(0, len(to_judge), JUDGE_BATCH)]
    with ThreadPoolExecutor(max_workers=max(1, llm.runtime.capacity)) as pool:
        list(pool.map(judge, batches))

    # ---- 4. repair
    flags: list[dict] = []
    paragraphs = re.split(r"\n\s*\n", text)
    by_para: dict[int, list[dict]] = {}
    for c in claims:
        verdict = c.get("verdict", "unverified")
        stats[verdict] = stats.get(verdict, 0) + 1
        sent = c["sentence"]
        para = paragraphs[c["paragraph"]]
        if c.get("add_label") and sent in para and not MARKER.search(sent):
            new_sent = re.sub(r"([.!?])$", f" [{c['add_label']}]\\1", sent)
            paragraphs[c["paragraph"]] = para.replace(sent, new_sent, 1)
            stats["auto_cited"] += 1
        elif verdict == "partial" and c.get("correction") and _safe_correction(sent, c["correction"], c):
            fixed = _keep_markers(sent, c["correction"])
            paragraphs[c["paragraph"]] = para.replace(sent, fixed, 1)
            stats["corrected"] += 1
        elif verdict in {"unsupported", "contradicted"}:
            by_para.setdefault(c["paragraph"], []).append(c)
        elif verdict == "partial":
            flags.append({"sentence": sent[:220], "verdict": "partial", "reason": c.get("reason", "detail not fully supported")})

    for pi, bad in by_para.items():
        para = paragraphs[pi]
        evidence_text = "\n".join(f"({ch.label}) {' '.join(ch.text.split()[:130])}" for c in bad for ch in c.get("passages", [])[:2])
        try:
            repaired = llm.generate(
                "You are RAF, a senior academic author who corrects unsupported claims using only the given evidence.",
                "Some sentences in this paragraph are not supported by the cited sources.\n\nUNSUPPORTED SENTENCES:\n"
                + "\n".join(f"- {c['sentence']}  (reason: {c.get('reason') or c['verdict']})" for c in bad)
                + f"\n\nEVIDENCE:\n{evidence_text or '(none)'}\n\nPARAGRAPH:\n{para}\n\n"
                "Rewrite the paragraph so each listed sentence either states only what the evidence supports (with the correct citation marker) "
                "or is removed. Keep every other sentence exactly as it is. Never invent facts, names, numbers or sources. Output only the paragraph.",
                temperature=0.35, max_tokens=int(len(para.split()) * 2.2) + 200,
            ).strip()
            repaired = re.sub(r"\n\s*\n", " ", repaired)
        except llm.LLMError:
            repaired = ""
        if repaired and len(repaired.split()) >= 0.4 * len(para.split()):
            para = repaired
        for c in bad:
            if c["sentence"] in para:     # survived the repair unchanged → remove if the paragraph can stand without it
                sentences = split_sentences(para)
                if len(sentences) > 2:
                    para = " ".join(s for s in sentences if s != c["sentence"])
                    stats["removed"] += 1
                else:
                    flags.append({"sentence": c["sentence"][:220], "verdict": c["verdict"], "reason": c.get("reason", "not supported by the cited source")})
            else:
                stats["corrected"] += 1
        paragraphs[pi] = para

    for c in claims:
        if c.get("verdict") == "unverified" and c["numeric"]:
            flags.append({"sentence": c["sentence"][:220], "verdict": "unverified", "reason": "specific figure could not be matched to a source"})
    checked = max(1, stats["checked"])
    stats["grounding_score"] = round(100 * (stats["supported"] + 0.5 * stats["partial"]) / checked)
    return "\n\n".join(paragraphs), stats, flags


def _keep_markers(original: str, correction: str) -> str:
    markers = MARKER.findall(original)
    correction = MARKER.sub("", correction).strip()
    if markers and not MARKER.search(correction):
        correction = re.sub(r"([.!?])?$", lambda m: f" [{markers[-1]}]" + (m.group(1) or "."), correction, count=1)
    return correction


def _safe_correction(original: str, correction: str, claim: dict) -> bool:
    if len(correction.split()) < 5:
        return False
    passages = " ".join(ch.text for ch in claim.get("passages", []))
    new_numbers = [n for n in NUMBER.findall(correction) if n not in original and n not in passages]
    return not new_numbers


# ============================================================================================ entry point
def filter_segment(text: str, ws, *, key: str, title: str, section: str, purpose: str, evidence: str, rules: str,
                   deep: bool, progress=None) -> tuple[str, dict, list[dict]]:
    p = ws.project
    valid = set(citations.label_map(p))
    text, flags = sanitise(text, valid)
    if deep and key not in {"abstract"}:
        if progress:
            progress(f"Hallucination filter · coherence review of {section}")
        try:
            text, coherence_flags = coherence_pass(text, title=title, section=section, purpose=purpose, evidence=evidence, rules=rules)
            flags += coherence_flags
        except Exception as exc:  # noqa: BLE001
            flags.append({"sentence": "", "verdict": "skipped", "reason": f"coherence review failed: {exc}"})
    stats = {}
    if ws.index.chunks:
        if progress:
            progress(f"Hallucination filter · verifying claims in {section} against their sources")
        text, stats, ground_flags = ground(text, ws, evidence, deep=deep)
        flags += ground_flags
    stats["sanitised"] = sum(1 for f in flags if f["verdict"] in {"duplicate", "truncated", "invalid_citation"})
    stats["paragraphs_repaired"] = sum(1 for f in flags if f["verdict"] == "repaired")
    visible = [f for f in flags if f["verdict"] in {"partial", "unsupported", "contradicted", "unverified"} and f["sentence"]]
    return text, stats, visible


# ============================================================================================ article review
def review_article(project, segments: dict[str, str]) -> dict:
    """Whole-article consistency: research questions answered, numbers consistent, terminology, contradictions."""
    issues = []
    abstract = segments.get("abstract", "")
    body = " ".join(v for k, v in segments.items() if k in {"results", "discussion", "conclusion", "methodology"})
    findings = " ".join(project.analysis.findings) if project.analysis else ""
    for n in sorted(set(NUMBER.findall(abstract))):
        bare = n.rstrip("%").replace(",", "")
        if len(bare) > 1 and bare not in body.replace(",", "") and bare not in findings.replace(",", "") and not YEAR.fullmatch(bare):
            issues.append({"segment": "abstract", "type": "number mismatch",
                           "issue": f"The abstract reports {n}, which does not appear in the Methodology, Results, Discussion or Conclusion.",
                           "instruction": f"Correct or remove the figure {n} so every number in the abstract matches the Results section exactly."})
    kw = segments.get("keywords", "")
    if kw and not 4 <= len([k for k in kw.split(";") if k.strip()]) <= 8:
        issues.append({"segment": "keywords", "type": "format", "issue": "Keywords should number 5–7.", "instruction": "Provide 5–7 keywords separated by semicolons."})

    def head(k: str, n: int) -> str:
        return " ".join(re.sub(r"\[\[.*?\]\]", "", segments.get(k, "")).split()[:n])

    overview = "\n\n".join(f"--- {k.upper()} ---\n{head(k, n)}" for k, n in
                           (("abstract", 260), ("introduction", 500), ("results", 450), ("discussion", 450), ("conclusion", 300), ("limitations", 200)) if segments.get(k))
    data = llm.generate_json(
        "You are a handling editor checking a manuscript for consistency before peer review. Reply with JSON only.",
        f"TITLE: {project.title}\n\n{overview}\n\n"
        "Check: (1) are the aims/research questions in the Introduction answered in the Discussion/Conclusion? (2) do the Abstract and "
        "Conclusion match the Results? (3) contradictions between sections? (4) the same concept named inconsistently? "
        "(5) conclusions that go beyond the evidence? Report at most 5 real problems.\n"
        "JSON: {\"issues\": [{\"segment\": \"abstract|introduction|literature_review|methodology|results|discussion|conclusion|limitations\", "
        "\"type\": \"short label\", \"issue\": \"what is wrong\", \"instruction\": \"a precise revision instruction for that segment\"}]}",
        default={}, max_tokens=900,
    )
    for it in data.get("issues") or []:
        if isinstance(it, dict) and it.get("segment") in segments and it.get("instruction"):
            issues.append({k: str(it.get(k, ""))[:400] for k in ("segment", "type", "issue", "instruction")})
    return {"issues": issues[:8]}
