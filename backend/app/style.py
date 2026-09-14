"""Style & naturalness engine.

1. Metrics      — measurable properties of prose that separate careful human academic writing from formulaic text:
                  sentence-length variation, repeated sentence openers, stock connectors, generic phrasing, reflexive
                  triplets, lexical diversity and paragraph uniformity. Combined into a 0–100 naturalness score with
                  concrete, per-paragraph fix instructions.
2. Field profile — the same metrics measured on the user's own reference articles, so drafts are steered toward the
                  conventions of that discipline (typical sentence length, variation, passive voice) instead of a
                  generic model style.
3. Humanize     — paragraph-by-paragraph rewriting with a fact inventory (citations, numbers, key terms, propositions)
                  and a verification gate. A rewrite is accepted only if it keeps every citation and number, keeps the
                  key terms and meaning, stays within length bounds and actually improves the style metrics;
                  otherwise the original paragraph is kept. That is what keeps context and content loss at (or near) zero.

This module improves the quality of writing. It does not try to game AI detectors, which are unreliable, and it is not
a substitute for the author's own review and any disclosure their venue requires.
"""
from __future__ import annotations

import json
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import llm
from .ingest import split_sentences

MARKER = re.compile(r"\[(?:[RW]\d+(?:\s*[,;]\s*)?)+\]")
PLACEHOLDER = re.compile(r"^\[\[(TABLE|FIGURE) \d+\]\]$")
NUMBER = re.compile(r"(?<![\w\[])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")
WORD = re.compile(r"[A-Za-z][A-Za-z'\-]+")

STOCK_OPENERS = ("moreover", "furthermore", "additionally", "in addition", "overall", "ultimately", "in conclusion", "in summary",
                 "notably", "importantly", "consequently", "thus,", "hence,", "indeed,", "interestingly", "crucially", "significantly,")
GENERIC_PHRASES = (
    "plays a crucial role", "plays a key role", "plays a vital role", "plays a pivotal role", "it is important to note", "it is worth noting",
    "in today's", "rapidly evolving", "ever-evolving", "a wide range of", "a variety of", "various aspects", "significant impact",
    "shed light on", "sheds light on", "pave the way", "paves the way", "multifaceted", "nuanced understanding", "landscape of",
    "delve", "underscore", "underscores the importance", "highlights the importance", "crucial", "pivotal", "holistic", "seamless",
    "leverage", "foster", "realm", "tapestry", "intricate", "navigate the", "embark", "testament to",
    "valuable insights", "key insights", "robust framework", "comprehensive understanding", "serves as a", "a myriad of",
    "game-changer", "cutting-edge",
)
FORMULAIC_WORDS = {w.strip(",") for phrase in (*GENERIC_PHRASES, *STOCK_OPENERS) for w in phrase.split()} | {
    "important", "significant", "various", "several", "however", "therefore", "overall", "essential", "vital", "notably"}
STOP = set("""a an and are as at be been but by can could did do does for from had has have how however if in into is it its may might
more most not of on or our such than that the their them then there these they this those through to under was we were what when where
which while who will with within would also between both each other only very""".split())


# ============================================================================================ metrics
def _sentences(text: str) -> list[str]:
    body = "\n".join(line for line in text.splitlines() if not PLACEHOLDER.match(line.strip()))
    return [s for s in split_sentences(MARKER.sub("", body)) if len(s.split()) >= 3]


def metrics(text: str) -> dict:
    sents = _sentences(text)
    words = WORD.findall(MARKER.sub("", text))
    if len(sents) < 2 or len(words) < 30:
        return {"sentences": len(sents), "words": len(words), "score": None}
    lengths = [len(s.split()) for s in sents]
    mean = statistics.mean(lengths)
    sd = statistics.pstdev(lengths)
    openers = [re.sub(r"[^a-z]", "", s.split()[0].lower()) for s in sents]
    repeated_openers = sum(1 for a, b in zip(openers, openers[1:]) if a and a == b) / max(1, len(openers) - 1)
    top_opener_share = max(openers.count(o) for o in set(openers)) / len(openers)
    stock = sum(1 for s in sents if s.lower().startswith(STOCK_OPENERS)) / len(sents)
    low = " ".join(words).lower()
    generic = sum(low.count(p) for p in GENERIC_PHRASES) / (len(words) / 100)
    triplets = len(re.findall(r"\b\w+(?:\s\w+)?,\s\w+(?:\s\w+)?,?\s(?:and|or)\s\w+", text)) / len(sents)
    lw = [w.lower() for w in words]
    window = 50
    mattr = statistics.mean(len(set(lw[i:i + window])) / window for i in range(0, max(1, len(lw) - window), 10)) if len(lw) > window else len(set(lw)) / len(lw)
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if len(p.split()) > 20 and not PLACEHOLDER.match(p.strip())]
    para_cv = statistics.pstdev([len(p.split()) for p in paragraphs]) / statistics.mean([len(p.split()) for p in paragraphs]) if len(paragraphs) >= 3 else None
    passive = sum(1 for s in sents if re.search(r"\b(is|are|was|were|be|been|being)\s+(\w+ly\s+)?\w+(ed|en)\b", s)) / len(sents)
    m = {
        "sentences": len(sents), "words": len(words),
        "mean_sentence_words": round(mean, 1), "sentence_length_variation": round(sd / mean, 2),
        "short_sentence_share": round(sum(l <= 12 for l in lengths) / len(lengths), 2),
        "repeated_openers": round(repeated_openers, 2), "top_opener_share": round(top_opener_share, 2),
        "stock_connector_share": round(stock, 2), "generic_phrases_per_100_words": round(generic, 2),
        "triplet_rate": round(triplets, 2), "lexical_diversity": round(mattr, 2),
        "paragraph_length_variation": round(para_cv, 2) if para_cv is not None else None,
        "passive_share": round(passive, 2),
    }
    m["score"] = score(m)
    return m


def score(m: dict, profile: dict | None = None) -> int:
    """0–100: higher means varied, specific, non-formulaic prose."""
    target_var = (profile or {}).get("sentence_length_variation", 0.5)
    s = 100.0
    s -= max(0, target_var - m["sentence_length_variation"]) * 90          # monotone rhythm
    s -= max(0, 0.12 - m["short_sentence_share"]) * 80                      # no short sentences at all
    s -= m["repeated_openers"] * 60 + max(0, m["top_opener_share"] - 0.2) * 60
    s -= m["stock_connector_share"] * 120
    s -= m["generic_phrases_per_100_words"] * 9
    s -= max(0, m["triplet_rate"] - 0.15) * 60
    s -= max(0, 0.72 - m["lexical_diversity"]) * 120
    if m.get("paragraph_length_variation") is not None:
        s -= max(0, 0.18 - m["paragraph_length_variation"]) * 60             # identical paragraph sizes
    return int(max(0, min(100, round(s))))


def issues(m: dict, profile: dict | None = None) -> list[str]:
    """Concrete editing instructions derived from the metrics."""
    if m.get("score") is None:
        return []
    target_mean = (profile or {}).get("mean_sentence_words")
    out = []
    if m["sentence_length_variation"] < (profile or {}).get("sentence_length_variation", 0.5) - 0.08:
        out.append(f"Sentence lengths are too uniform (average {m['mean_sentence_words']} words). Mix short sentences (6–12 words) for key points with longer qualified ones.")
    if target_mean and abs(m["mean_sentence_words"] - target_mean) > 7:
        out.append(f"Published articles in this field average about {target_mean:.0f} words per sentence; move toward that.")
    if m["repeated_openers"] > 0.1 or m["top_opener_share"] > 0.25:
        out.append("Too many sentences open the same way. Vary how sentences begin (subject, clause, context, time).")
    if m["stock_connector_share"] > 0.08:
        out.append("Remove stock connectors at sentence starts (Moreover, Furthermore, Additionally, Overall); let the logic connect the sentences.")
    if m["generic_phrases_per_100_words"] > 0.6:
        out.append("Replace generic phrasing (crucial, pivotal, landscape, plays a key role, sheds light) with specific, concrete wording.")
    if m["triplet_rate"] > 0.2:
        out.append("Avoid reflexive lists of three; keep only the items that matter.")
    if m["lexical_diversity"] < 0.68:
        out.append("Vocabulary is repetitive; use precise alternatives rather than repeating the same terms and verbs.")
    if m.get("paragraph_length_variation") is not None and m["paragraph_length_variation"] < 0.15:
        out.append("Paragraphs are all the same size; let paragraph length follow the weight of each point.")
    return out


def phrase_hits(text: str) -> list[str]:
    low = text.lower()
    return sorted({p for p in GENERIC_PHRASES if p in low})


# ============================================================================================ field profile
def field_profile(index_dir: Path) -> dict:
    """Style statistics of the user's reference articles (cached)."""
    cache = index_dir / "style_profile.json"
    if cache.exists():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    samples = []
    for f in sorted(index_dir.glob("ref_*.txt"))[:20]:
        paras = [p for p in re.split(r"\n\s*\n", f.read_text(encoding="utf-8")) if 60 <= len(p.split()) <= 300]
        samples.extend(paras[len(paras) // 4: len(paras) // 4 + 6])
    if len(samples) < 5:
        return {}
    ms = [m for m in (metrics(p) for p in samples) if m.get("score") is not None]
    if not ms:
        return {}
    profile = {k: round(statistics.median(m[k] for m in ms), 2) for k in ("mean_sentence_words", "sentence_length_variation", "passive_share", "short_sentence_share")}
    profile["paragraphs_sampled"] = len(ms)
    cache.write_text(json.dumps(profile), encoding="utf-8")
    return profile


def profile_rule(profile: dict) -> str:
    if not profile:
        return ""
    lo = max(5, round(profile["mean_sentence_words"] * (1 - profile["sentence_length_variation"])))
    hi = round(profile["mean_sentence_words"] * (1 + profile["sentence_length_variation"]))
    return (f"Match the conventions of published work in this field (measured on the user's references): sentences average about "
            f"{profile['mean_sentence_words']:.0f} words and range naturally from about {lo} to {hi}; about "
            f"{profile['passive_share'] * 100:.0f}% of sentences use the passive voice.")


# ============================================================================================ humanize
def inventory(paragraph: str) -> dict:
    """Deterministic fact inventory used by the verification gate."""
    text = MARKER.sub(lambda m: " ", paragraph)
    words = [w.lower() for w in WORD.findall(text)]
    freq: dict[str, int] = {}
    for w in words:
        if len(w) >= 5 and w not in STOP and w not in FORMULAIC_WORDS:
            freq[w] = freq.get(w, 0) + 1
    capitalised = {w for w in re.findall(r"(?<!^)(?<![.!?]\s)\b([A-Z][a-zA-Z]{2,}(?:\s[A-Z][a-zA-Z]{2,})*)", text)}
    return {
        "markers": sorted(set(re.sub(r"\s", "", m) for m in MARKER.findall(paragraph))),
        "labels": sorted({l for m in MARKER.findall(paragraph) for l in re.findall(r"[RW]\d+", m)}),
        "numbers": sorted(set(NUMBER.findall(text))),
        "terms": [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:14]],
        "names": sorted(capitalised)[:12],
    }


def _stem(w: str) -> str:
    return w.lower()[:6]


def verify(original: str, rewrite: str, inv: dict, claims: list[str], before: dict) -> tuple[bool, list[str], dict]:
    problems = []
    new_inv = inventory(rewrite)
    missing_labels = [l for l in inv["labels"] if l not in new_inv["labels"]]
    if missing_labels:
        problems.append(f"citations dropped: {', '.join(missing_labels)}")
    added_labels = [l for l in new_inv["labels"] if l not in inv["labels"]]
    if added_labels:
        problems.append(f"new citations invented: {', '.join(added_labels)}")
    missing_numbers = [n for n in inv["numbers"] if n not in rewrite]
    if missing_numbers:
        problems.append(f"numbers dropped: {', '.join(missing_numbers)}")
    new_numbers = [n for n in new_inv["numbers"] if n not in inv["numbers"] and n not in original]
    if new_numbers:
        problems.append(f"numbers added: {', '.join(new_numbers)}")
    low = rewrite.lower()
    missing_names = [n for n in inv["names"] if n.lower() not in low]
    if len(missing_names) > max(1, len(inv["names"]) // 4):
        problems.append(f"names dropped: {', '.join(missing_names[:5])}")
    stems = {_stem(w) for w in WORD.findall(rewrite)}
    term_recall = sum(_stem(t) in stems for t in inv["terms"]) / max(1, len(inv["terms"]))
    if term_recall < 0.7:
        problems.append(f"key terms lost ({term_recall:.0%} kept)")
    lost_claims = []
    for c in claims:
        cw = [_stem(w) for w in WORD.findall(c) if len(w) >= 4 and w.lower() not in STOP]
        if cw and sum(w in stems for w in cw) / len(cw) < 0.5:
            lost_claims.append(c)
    if lost_claims:
        problems.append("propositions weakened or dropped: " + " | ".join(lost_claims[:3]))
    ratio = len(rewrite.split()) / max(1, len(original.split()))
    if not 0.78 <= ratio <= 1.3:
        problems.append(f"length changed too much ({ratio:.0%} of original)")
    if re.search(r"^(here is|here's|sure|certainly|i have|this revised|revised paragraph)", rewrite.strip(), re.I):
        problems.append("contains commentary about the rewrite")
    after = metrics(rewrite)
    if before.get("score") is not None and after.get("score") is not None and after["score"] < before["score"]:
        problems.append(f"style did not improve ({before['score']} → {after['score']})")
    return not problems, problems, after


def extract_claims(paragraph: str) -> list[str]:
    data = llm.generate_json(
        "You list the atomic propositions of academic text. Reply with JSON only.",
        "List every distinct factual claim, argument or finding in this paragraph as a short proposition (max 18 words each), "
        "in order. Keep names, numbers and qualifiers.\n\nPARAGRAPH:\n" + MARKER.sub("", paragraph) + "\n\nJSON: {\"claims\": [\"...\"]}",
        default={}, max_tokens=500,
    )
    return [c for c in (data.get("claims") or []) if isinstance(c, str) and c.strip()][:14]


def rewrite_paragraph(paragraph: str, *, title: str, section: str, tone_rule: str, profile: dict, deep: bool) -> tuple[str, dict]:
    before = metrics(paragraph)
    inv = inventory(paragraph)
    claims = extract_claims(paragraph) if deep else []
    fixes = issues(before, profile) or ["Make the prose read like a careful specialist wrote it: specific wording, varied rhythm, logical links instead of stock connectors."]
    hits = phrase_hits(paragraph)
    base_prompt = (
        f"ARTICLE: {title}\nSECTION: {section}\n{tone_rule}\n{profile_rule(profile)}\n\n"
        "Rewrite the paragraph below the way an experienced researcher in this field would write it for a journal.\n\n"
        "NON-NEGOTIABLE CONTENT RULES:\n"
        "- Keep every proposition, qualification and piece of reasoning. Do not add facts, examples, names or numbers.\n"
        f"- Keep these citation markers attached to the same claims: {', '.join(inv['markers']) or 'none'}\n"
        f"- Keep these numbers exactly: {', '.join(inv['numbers']) or 'none'}\n"
        f"- Keep these names and key terms: {', '.join(inv['names'] + inv['terms'][:10]) or 'none'}\n"
        + ("- Propositions that must all survive:\n" + "\n".join(f"  • {c}" for c in claims) + "\n" if claims else "")
        + "- Stay within ±15% of the original length and keep it one paragraph.\n\n"
        "STYLE FIXES TO MAKE:\n" + "\n".join(f"- {f}" for f in fixes)
        + (f"\n- Replace these formulaic phrases: {', '.join(hits)}" if hits else "")
        + "\n- Prefer concrete subjects and precise verbs; keep hedges only where the evidence is uncertain.\n\n"
        f"PARAGRAPH:\n{paragraph}\n\nOutput only the rewritten paragraph."
    )
    attempt_prompt = base_prompt
    report = {"before": before.get("score"), "after": before.get("score"), "accepted": False, "problems": []}
    for attempt in range(2 if deep else 1):
        try:
            candidate = llm.generate(
                "You are a senior academic editor who rewrites prose for clarity, precision and a natural scholarly voice without changing its content.",
                attempt_prompt, temperature=0.8 if attempt == 0 else 0.6, max_tokens=int(len(paragraph.split()) * 2.2) + 200,
            ).strip().strip('"')
        except llm.LLMError as exc:
            report["problems"] = [f"model error: {exc}"]
            break
        candidate = re.sub(r"\n\s*\n", " ", candidate)
        ok, problems, after = verify(paragraph, candidate, inv, claims, before)
        if ok:
            report.update(accepted=True, after=after.get("score"), problems=[])
            return candidate, report
        report["problems"] = problems
        attempt_prompt = base_prompt + "\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED because: " + "; ".join(problems) + ". Fix these and try again."
    return paragraph, report


def humanize_text(text: str, *, title: str, section: str, tone_rule: str, profile: dict, deep: bool = True,
                  only_below: int | None = None, progress=None) -> tuple[str, dict]:
    """Rewrite paragraph by paragraph. `only_below` limits the pass to paragraphs scoring under that value."""
    blocks = re.split(r"(\n\s*\n)", text)
    targets = []
    for i, block in enumerate(blocks):
        b = block.strip()
        if not b or PLACEHOLDER.match(b) or len(b.split()) < 35 or re.match(r"^Appendix [A-Z]\.", b):
            continue
        m = metrics(b)
        if only_below is not None and (m.get("score") is None or m["score"] >= only_below):
            continue
        targets.append(i)
    before_all = metrics(text)
    report = {"paragraphs": sum(1 for b in blocks if b.strip() and not PLACEHOLDER.match(b.strip())), "attempted": len(targets),
              "rewritten": 0, "kept": [], "score_before": before_all.get("score")}
    if progress and targets:
        progress(f"Humanize: rewriting {len(targets)} paragraph(s) with content verification")

    def work(i):
        return i, rewrite_paragraph(blocks[i].strip(), title=title, section=section, tone_rule=tone_rule, profile=profile, deep=deep)

    with ThreadPoolExecutor(max_workers=max(1, llm.runtime.capacity)) as pool:
        for i, (new, rep) in pool.map(work, targets):
            if rep["accepted"]:
                blocks[i] = new
                report["rewritten"] += 1
            else:
                report["kept"].append({"paragraph": targets.index(i) + 1, "reasons": rep["problems"][:3]})
    out = "".join(blocks)
    report["score_after"] = metrics(out).get("score")
    orig_inv, new_inv = inventory(text), inventory(out)
    report["citations_preserved"] = f"{sum(l in new_inv['labels'] for l in orig_inv['labels'])}/{len(orig_inv['labels'])}"
    report["numbers_preserved"] = f"{sum(n in out for n in orig_inv['numbers'])}/{len(orig_inv['numbers'])}"
    return out, report
