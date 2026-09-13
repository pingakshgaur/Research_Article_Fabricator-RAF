"""Hybrid retrieval: neural embeddings (Ollama) + BM25 + TF-IDF, fused with Reciprocal Rank Fusion,
then diversified with Maximal Marginal Relevance so each segment sees varied evidence."""
from __future__ import annotations

import json
import logging
import pickle
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import llm

log = logging.getLogger("raf.rag")

_TOKEN = re.compile(r"[a-zA-Z][a-zA-Z0-9\-]{1,}")
_STOP = set(
    """a an and are as at be been but by can could did do does for from had has have how however if in into is it its
    may might more most not of on or our such than that the their them then there these they this those through to
    under was we were what when where which while who will with within would also between both each other using used
    use study studies research paper results result""".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in (w.lower() for w in _TOKEN.findall(text)) if t not in _STOP]


@dataclass
class Chunk:
    id: str
    text: str
    source_id: str      # Reference.id or WebSource.id
    source_kind: str    # "reference" | "web"
    label: str          # short citation label, e.g. "Smith et al. (2021)"


class HybridIndex:
    def __init__(self) -> None:
        self.chunks: list[Chunk] = []
        self._bm25 = None
        self._tfidf = None
        self._tfidf_matrix = None
        self._emb: np.ndarray | None = None

    # ------------------------------------------------------------ build
    def build(self, chunks: list[Chunk]) -> dict:
        self.chunks = chunks
        texts = [c.text for c in chunks]
        if not texts:
            return {"chunks": 0, "neural": False}
        try:
            from rank_bm25 import BM25Okapi

            self._bm25 = BM25Okapi([tokenize(t) or ["_"] for t in texts])
        except ImportError:
            self._bm25 = None
        from sklearn.feature_extraction.text import TfidfVectorizer

        self._tfidf = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1, max_features=60000, stop_words="english")
        self._tfidf_matrix = self._tfidf.fit_transform(texts)
        vectors = llm.embed(texts)
        self._emb = _normalize(np.array(vectors, dtype=np.float32)) if vectors else None
        log.info("Index built: %s chunks, neural=%s", len(texts), self._emb is not None)
        return {"chunks": len(texts), "neural": self._emb is not None}

    # ------------------------------------------------------------ search
    def search(self, query: str, k: int = 8, kinds: set[str] | None = None, diversity: float = 0.35) -> list[Chunk]:
        if not self.chunks:
            return []
        n = len(self.chunks)
        rankings: list[np.ndarray] = []
        scores_for_mmr = None

        if self._bm25 is not None:
            bm = np.asarray(self._bm25.get_scores(tokenize(query) or ["_"]))
            rankings.append(np.argsort(-bm))
        tf = (self._tfidf_matrix @ self._tfidf.transform([query]).T).toarray().ravel()
        rankings.append(np.argsort(-tf))
        scores_for_mmr = tf
        if self._emb is not None:
            qv = llm.embed([query])
            if qv:
                sims = self._emb @ _normalize(np.array(qv, dtype=np.float32))[0]
                rankings.append(np.argsort(-sims))
                scores_for_mmr = sims

        fused = np.zeros(n)
        for ranking in rankings:  # Reciprocal Rank Fusion
            fused[ranking] += 1.0 / (60 + np.arange(1, n + 1))

        candidates = [i for i in np.argsort(-fused)[: max(k * 4, 24)] if not kinds or self.chunks[i].source_kind in kinds]
        return [self.chunks[i] for i in self._mmr(candidates, fused, k, diversity)]

    def _mmr(self, candidates: list[int], relevance: np.ndarray, k: int, diversity: float) -> list[int]:
        if not candidates:
            return []
        if self._emb is not None:
            vecs = self._emb[candidates]
        else:
            m = self._tfidf_matrix[candidates]
            vecs = m.toarray()
            vecs = _normalize(vecs)
        rel = relevance[candidates]
        rel = (rel - rel.min()) / (np.ptp(rel) or 1)
        chosen: list[int] = []
        per_source: dict[str, int] = {}
        while len(chosen) < min(k, len(candidates)):
            best, best_score = None, -1e9
            for pos, _ in enumerate(candidates):
                if pos in chosen:
                    continue
                redundancy = max((float(vecs[pos] @ vecs[c]) for c in chosen), default=0.0)
                src = self.chunks[candidates[pos]].source_id
                source_penalty = 0.08 * per_source.get(src, 0)  # spread evidence across sources
                score = (1 - diversity) * rel[pos] - diversity * redundancy - source_penalty
                if score > best_score:
                    best, best_score = pos, score
            chosen.append(best)
            src = self.chunks[candidates[best]].source_id
            per_source[src] = per_source.get(src, 0) + 1
        return [candidates[c] for c in chosen]

    # ------------------------------------------------------------ persistence
    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        with open(directory / "index.pkl", "wb") as fh:
            pickle.dump({"chunks": self.chunks, "bm25": self._bm25, "tfidf": self._tfidf, "matrix": self._tfidf_matrix, "emb": self._emb}, fh)
        (directory / "chunks.json").write_text(json.dumps([c.__dict__ for c in self.chunks], indent=1), encoding="utf-8")

    @classmethod
    def load(cls, directory: Path) -> "HybridIndex":
        idx = cls()
        path = directory / "index.pkl"
        if path.exists():
            with open(path, "rb") as fh:
                data = pickle.load(fh)
            idx.chunks, idx._bm25, idx._tfidf = data["chunks"], data["bm25"], data["tfidf"]
            idx._tfidf_matrix, idx._emb = data["matrix"], data["emb"]
        return idx


def _normalize(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    norms[norms == 0] = 1
    return m / norms
