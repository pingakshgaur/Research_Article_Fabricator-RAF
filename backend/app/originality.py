"""Originality guard.

Generated text is checked against the full source corpus (uploaded references + web sources) with two detectors:
  1. Shingle overlap — the share of the draft's 7-word sequences that also occur in any source.
  2. Sentence similarity — each drafted sentence is compared with the most similar source sentences using
     token-set and partial fuzzy ratios (RapidFuzz); near-paraphrases above the threshold are flagged.
Flagged sentences are re-expressed by the SLM with new structure and vocabulary (keeping meaning and citation
markers) and re-checked, up to two rounds. A style pass removes machine-sounding clichés, and every number in
the draft is verified against the evidence so no statistic is fabricated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import llm
from .config import settings
from .ingest import split_sentences

SHINGLE = 7
_WORD = re.compile(r"[a-z0-9]+")
_MARKER = re.compile(r"\[(?:[RW]\d+(?:\s*[,;]\s*)?)+\]")
_PLACEHOLDER = re.compile(r"^\[\[(TABLE|FIGURE) \d+\]\]$", re.M)

CLICHES = {
    r"\bin the realm of\b": "in",
    r"\bdelve(s|d)? into\b": "examine",
    r"\bin today's (fast-paced|rapidly changing|modern) world\b": "at present",
    r"\bit is (important|worth|crucial) to note that\b": "",
    r"\bplays? a (crucial|pivotal|vital|key) role in\b": "shapes",
    r"\ba testament to\b": "evidence of",
    r"\bnavigat(e|ing) the (complex|intricate) landscape of\b": "addressing",
    r"\bever-evolving\b": "changing",
    r"\bunderscore(s|d)? the (importance|significance) of\b": "highlight",
    r"\bserves as a\b": "is a",
    r"\bmoreover,\s": "In addition, ",
    r"\bfurthermore,\s": "Further, ",
    r"\bin conclusion,\s": "",
    r"\btapestry\b": "combination",
    r"\bseamless(ly)?\b": "smooth",
    r"\bleverag(e|es|ing)\b": "use",
    r"\bholistic\b": "comprehensive",
    r"\bparadigm shift\b": "fundamental change",
}


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _shingles(words: list[str]) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


class SourceFingerprint:
    """Pre-computed shingles and sentences for the whole corpus."""

    def __init__(self, texts: list[str]) -> None:
        self.shingles: set[tuple[str, ...]] = set()
        self.sentences: list[str] = []
        for t in texts:
            self.shingles |= _shingles(_words(t))
            self.sentences.extend(s for s in split_sentences(t) if 8 <= len(s.split()) <= 80)
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english")
        self._matrix = self._vec.fit_transform(self.sentences) if self.sentences else None

    def nearest(self, sentence: str, k: int = 5) -> list[str]:
        if self._matrix is None:
            return []
        sims = (self._matrix @ self._vec.transform([sentence]).T).toarray().ravel()
        return [self.sentences[i] for i in sims.argsort()[::-1][:k] if sims[i] > 0.15]


@dataclass
class Check:
    overlap: float
    flagged: list[str]


def check(text: str, fp: SourceFingerprint) -> Check:
    from rapidfuzz import fuzz

    clean = _PLACEHOLDER.sub("", _MARKER.sub("", text))
    words = _words(clean)
    sh = _shingles(words)
    overlap = len(sh & fp.shingles) / len(sh) if sh else 0.0
    flagged = []
    for sent in split_sentences(clean):
        if len(sent.split()) < 7:
            continue
        s_sh = _shingles(_words(sent))
        if s_sh & fp.shingles and len(s_sh & fp.shingles) >= 2:
            flagged.append(sent)
            continue
        for src in fp.nearest(sent):
            score = max(fuzz.token_sort_ratio(sent, src), fuzz.partial_ratio(sent, src) if len(sent) > 60 else 0)
            if score >= settings.sentence_similarity_limit:
                flagged.append(sent)
                break
    return Check(overlap=overlap, flagged=flagged)


def enforce(text: str, fp: SourceFingerprint, progress=None, rounds: int = 2) -> tuple[str, Check, int]:
    """Rewrite any passage that is too close to a source. Returns (text, final check, sentences rewritten)."""
    rewritten = 0
    result = check(text, fp)
    for _ in range(rounds):
        if not result.flagged and result.overlap <= settings.max_ngram_overlap:
            break
        if progress:
            progress(f"Originality guard: {len(result.flagged)} sentence(s) too close to sources (overlap {result.overlap:.1%}); re-expressing")
        for sent in result.flagged[:25]:
            original = _find_with_markers(text, sent)
            if not original:
                continue
            new = llm.generate(
                "You are an expert academic editor. Re-express a sentence so it is fully original while keeping its exact meaning.",
                "Rewrite the sentence below with a different grammatical structure and fresh vocabulary. Keep every factual detail, "
                "number and any citation markers like [R2] exactly. Return only the rewritten sentence.\n\n"
                f"SENTENCE: {original}",
                temperature=0.85, max_tokens=250,
            ).strip().strip('"')
            if new and len(new) > 20 and "\n" not in new:
                text = text.replace(original, new, 1)
                rewritten += 1
        result = check(text, fp)
    return text, result, rewritten


def _find_with_markers(text: str, sentence_without_markers: str) -> str | None:
    """Locate the sentence in the original text, including any citation markers it contained."""
    for sent in split_sentences(text):
        if _MARKER.sub("", sent).split() == sentence_without_markers.split():
            return sent
    head = " ".join(sentence_without_markers.split()[:6])
    idx = text.find(head)
    if idx >= 0:
        end = text.find(". ", idx)
        return text[idx : end + 1 if end > 0 else len(text)]
    return None


def destyle(text: str) -> str:
    """Remove machine-sounding clichés and normalise typography."""
    for pattern, repl in CLICHES.items():
        text = re.sub(pattern, repl, text, flags=re.I)
    text = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\s+([,.;:])", r"\1", text)
    text = re.sub(r"^\s*#+\s.*$", "", text, flags=re.M)          # stray headings from the model
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)                  # bold emphasis is not academic style
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_NUM = re.compile(r"(?<![\w\[])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?")


def unverified_numbers(text: str, evidence: str) -> list[str]:
    """Numbers in the draft that do not appear anywhere in the evidence (years and small integers are tolerated)."""
    body = _PLACEHOLDER.sub("", _MARKER.sub("", text))
    body = re.sub(r"\b(Table|Figure|H|RQ|Hypothesis)\s*\d+", "", body)
    ev = evidence.replace(",", "")
    out = []
    for n in set(_NUM.findall(body)):
        bare = n.rstrip("%").replace(",", "")
        try:
            val = float(bare)
        except ValueError:
            continue
        if val <= 10 and "." not in bare:
            continue
        if 1900 <= val <= 2100 and "." not in bare:
            continue
        if bare not in ev and bare.lstrip("0") not in ev:
            out.append(n)
    return sorted(out)


def readability(text: str) -> float | None:
    try:
        import textstat

        return round(textstat.flesch_reading_ease(text), 1)
    except Exception:  # noqa: BLE001
        return None
