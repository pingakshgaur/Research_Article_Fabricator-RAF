"""Checkpoints: durable progress markers so an interrupted fabrication resumes exactly where it stopped.

Stored in  data/projects/<id>/index/checkpoints.json

  corpus.<stage>   = {"signature": ..., "at": ...}          parsing · research · indexing · analysis
  segments.<key>   = {"words": target, "steps": {name: value}}
                     steps are e.g. "themes", "notes:2:Establishing the niche", "draft:2:…", "refined", "results:group"

A corpus checkpoint is only honoured when its signature (inputs that affect the result) still matches, and a segment's
steps are discarded when its word target changes — so resuming never mixes stale work into a changed request.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable


def signature(*parts: Any) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


class Checkpoints:
    def __init__(self, directory: Path, on_save: Callable[[str], None] | None = None) -> None:
        self.path = directory / "index" / "checkpoints.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.on_save = on_save or (lambda label: None)
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            self.data = {}
        self.data.setdefault("corpus", {})
        self.data.setdefault("segments", {})

    def _write(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    # ------------------------------------------------------------------ corpus stages
    def corpus_done(self, stage: str, sig: str) -> bool:
        with self._lock:
            return self.data["corpus"].get(stage, {}).get("signature") == sig

    def mark_corpus(self, stage: str, sig: str, label: str) -> None:
        with self._lock:
            self.data["corpus"][stage] = {"signature": sig, "at": time.time()}
            self._write()
        self.on_save(label)

    # ------------------------------------------------------------------ segment steps
    def _segment(self, key: str, words: int) -> dict:
        seg = self.data["segments"].get(key)
        if not seg or seg.get("words") != words:
            seg = {"words": words, "steps": {}}
            self.data["segments"][key] = seg
        return seg

    def get(self, key: str, words: int, step: str, default=None):
        with self._lock:
            return self._segment(key, words)["steps"].get(step, default)

    def put(self, key: str, words: int, step: str, value, label: str | None = None) -> None:
        with self._lock:
            self._segment(key, words)["steps"][step] = value
            self._write()
        if label:
            self.on_save(label)

    def clear_segment(self, key: str) -> None:
        with self._lock:
            if self.data["segments"].pop(key, None) is not None:
                self._write()

    def summary(self) -> dict:
        with self._lock:
            return {
                "corpus": sorted(self.data["corpus"]),
                "segments": {k: len(v.get("steps", {})) for k, v in self.data["segments"].items()},
            }
