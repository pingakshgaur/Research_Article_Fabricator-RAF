"""Runtime configuration. Everything is overridable through environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- Local language model (Ollama) ---
    ollama_url: str = _env("RAF_OLLAMA_URL", "http://localhost:11434")
    model: str = _env("RAF_MODEL", "gemma4:12b")
    # Optional dedicated embedding model (e.g. `ollama pull nomic-embed-text`).
    # When it is not installed RAF falls back to TF-IDF + BM25 retrieval.
    embed_model: str = _env("RAF_EMBED_MODEL", "nomic-embed-text")
    # gemma4:12b supports 262K tokens, but a large window costs a lot of VRAM.
    # 32K comfortably holds the evidence packs RAF builds for one segment.
    num_ctx: int = _env_int("RAF_NUM_CTX", 16384)
    llm_timeout: int = _env_int("RAF_LLM_TIMEOUT", 900)
    # Layers offloaded to the GPU. -1 lets Ollama decide; 0 forces CPU-only (use this if CUDA crashes on small GPUs).
    num_gpu: int = _env_int("RAF_NUM_GPU", -1)

    # --- Workflow rules ---
    min_references: int = _env_int("RAF_MIN_REFS", 10)
    max_references: int = _env_int("RAF_MAX_REFS", 20)
    web_research: bool = _env_bool("RAF_WEB_RESEARCH", True)
    research_results_per_source: int = _env_int("RAF_RESULTS_PER_SOURCE", 5)
    http_timeout: int = _env_int("RAF_HTTP_TIMEOUT", 25)
    contact_email: str = _env("RAF_CONTACT_EMAIL", "raf@example.org")  # polite pool for OpenAlex/Crossref/NCBI

    # --- Originality guard ---
    max_ngram_overlap: float = float(_env("RAF_MAX_NGRAM_OVERLAP", "0.04"))
    sentence_similarity_limit: float = float(_env("RAF_SENTENCE_SIM_LIMIT", "82"))

    # --- Storage ---
    data_dir: Path = field(default_factory=lambda: Path(_env("RAF_DATA_DIR", str(Path(__file__).resolve().parents[1] / "data"))))

    cors_origins: tuple[str, ...] = tuple(
        o.strip() for o in _env("RAF_CORS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080").split(",") if o.strip()
    )


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
