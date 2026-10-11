"""Pydantic data model for a RAF project. A project is persisted as one JSON file."""
from __future__ import annotations

import time
import uuid
from typing import Literal

from pydantic import BaseModel, Field

from .config import settings


def _id() -> str:
    return uuid.uuid4().hex[:12]


SegmentStatus = Literal["pending", "queued", "working", "draft", "revising", "approved", "failed"]


class Reference(BaseModel):
    id: str = Field(default_factory=_id)
    filename: str
    kind: Literal["pdf", "docx", "md", "txt"]
    title: str = ""
    authors: list[str] = []
    year: str = ""
    venue: str = ""
    doi: str = ""
    pages: int = 0
    chars: int = 0
    chunks: int = 0
    status: Literal["uploaded", "parsed", "failed"] = "uploaded"
    error: str = ""


class WebSource(BaseModel):
    id: str = Field(default_factory=_id)
    source: str               # e.g. "openalex", "arxiv", "wikipedia"
    title: str
    url: str = ""
    authors: list[str] = []
    year: str = ""
    venue: str = ""
    doi: str = ""
    abstract: str = ""
    oa_url: str = ""          # where an open-access copy of the full paper can be downloaded, when a database says so
    fulltext: bool = False    # RAF downloaded and read the whole paper (index/web_<id>.txt); otherwise title and abstract only
    chars: int = 0
    pinned: bool = False      # the author marked it as one that must be used


class Figure(BaseModel):
    id: str = Field(default_factory=_id)
    number: int = 0
    caption: str
    path: str                 # relative to project dir
    note: str = ""
    group: str = ""


class Table(BaseModel):
    id: str = Field(default_factory=_id)
    number: int = 0
    caption: str
    columns: list[str]
    rows: list[list[str]]
    note: str = ""
    group: str = ""


class Version(BaseModel):
    content: str
    created: float = Field(default_factory=time.time)
    reason: str = "draft"


class QualityReport(BaseModel):
    words: int = 0
    target_words: int = 0
    ngram_overlap: float = 0.0
    flagged_sentences: int = 0
    rewritten_sentences: int = 0
    readability: float | None = None
    citations: int = 0
    unverified_numbers: list[str] = []
    checklist: dict[str, bool] = {}
    grounding: dict = {}          # hallucination filter summary
    flags: list[dict] = []        # sentences still needing attention: {sentence, verdict, reason}
    style: dict = {}              # naturalness metrics and score
    humanize: dict = {}           # last Humanize run report


class Segment(BaseModel):
    key: str
    title: str
    status: SegmentStatus = "pending"
    content: str = ""
    versions: list[Version] = []
    figures: list[Figure] = []
    tables: list[Table] = []
    quality: QualityReport = Field(default_factory=QualityReport)
    notes: list[str] = []
    error: str = ""


class CustomSegment(BaseModel):
    """A segment the author added to one project (see structure.py)."""
    key: str
    title: str
    purpose: str = ""                 # what the segment should do, in the author's words
    kind: Literal["generated", "manual"] = "generated"   # written by RAF from the purpose, or written by the author
    words: int = 400
    cites: bool = True                # draw on the sources and cite them
    numbered: bool = True             # gets a section number in the published article
    moves: list[dict] = []            # parts of the segment: {name, instruction, queries, share}; empty = RAF's default three


class AnalysisResult(BaseModel):
    datasets: list[dict] = []           # provenance of each dataset used
    findings: list[str] = []            # plain-language, number-bearing statements
    tables: list[Table] = []
    figures: list[Figure] = []
    methods: list[str] = []             # statistical procedures actually executed


class Project(BaseModel):
    schema_version: int = 5                       # layout of this file; older projects are upgraded on load (store.py)
    id: str = Field(default_factory=_id)
    created: float = Field(default_factory=time.time)
    updated: float = Field(default_factory=time.time)
    title: str
    topic: str = ""
    discipline: str = ""
    article_type: str = "Empirical research article"
    citation_style: Literal["APA", "Harvard", "IEEE", "Chicago"] = "APA"
    target_words: int = 6000
    authors: list[str] = []
    affiliation: str = ""
    references: list[Reference] = []
    dataset_files: list[str] = []
    web_sources: list[WebSource] = []
    selected: list[str] = []
    segments: dict[str, Segment] = {}
    analysis: AnalysisResult | None = None
    options: dict = Field(default_factory=lambda: {"web_research": settings.web_research, "data_analysis": True})
    segment_lengths: dict[str, int] = {}          # user-chosen word targets per segment
    titles: dict[str, str] = {}                   # the author's own titles for built-in segments
    custom_segments: dict[str, CustomSegment] = {}
    order: list[str] = []                         # reading order of the body, as arranged by the author (empty = usual order)
    excluded: list[str] = []                      # segments kept in the project but left out of the document
    tone: dict = Field(default_factory=lambda: {"name": "academic", "intensity": 50})
    publish_style: dict = Field(default_factory=lambda: {"template": "modern_report", "palette": "violet"})
    review: dict = {}                             # article-level consistency review
    archived: bool = False                        # hidden from the default Library view
    # where the evidence comes from: the author's files (10–20), files topped up by research (1+), or research alone (none)
    source_mode: Literal["references", "mixed", "research"] = "references"
    mode: Literal["write", "format"] = "write"    # "format": an existing article brought in only to be typeset (formatter.py)
    run: "RunInfo" = Field(default_factory=lambda: RunInfo())
    stage: Literal["setup", "references", "segments", "processing", "studio", "published"] = "setup"
    log: list[dict] = []


class RunInfo(BaseModel):
    """Fabrication timer. Time accumulates across resumed sessions."""
    status: Literal["idle", "running", "stopped", "review", "completed"] = "idle"   # "review": paused for the author to approve the reading list
    first_started: float | None = None
    session_started: float | None = None
    elapsed_before: float = 0.0                   # seconds from earlier sessions of this run
    finished: float | None = None
    sessions: int = 0
    stages: dict[str, float] = {}                 # stage -> seconds spent
    stage_started: dict[str, float] = {}          # stage -> start time of the open interval
    segment_seconds: dict[str, float] = {}
    segment_started: dict[str, float] = {}
    agents: int = 1
    checkpoints: int = 0
    estimate: dict = {}                           # pre-run time estimate (see estimate.py)


class ProjectCreate(BaseModel):
    title: str
    topic: str = ""
    discipline: str = ""
    article_type: str = "Empirical research article"
    citation_style: Literal["APA", "Harvard", "IEEE", "Chicago"] = "APA"
    target_words: int = 6000
    authors: list[str] = []
    affiliation: str = ""


class GenerateRequest(BaseModel):
    segments: list[str]
    web_research: bool = True
    data_analysis: bool = True
    depth: Literal["quick", "thorough"] = "thorough"
    agents: int = Field(default=1, ge=1, le=3)    # 1 solo · 2 duo · 3 trio
    lengths: dict[str, int] = {}
    resume: bool = False                          # continue from checkpoints instead of rewriting drafts
    tone: dict | None = None
    hallucination_filter: bool = True
    style_pass: bool = True
    sources_confirmed: bool = False               # the author approved the reading list found by online research (Mixed / Research-only)


class LengthsUpdate(BaseModel):
    lengths: dict[str, int]


class ToneUpdate(BaseModel):
    name: Literal["academic", "analytical", "persuasive", "explanatory", "reflective"]
    intensity: int = Field(ge=0, le=100)


class PublishStyle(BaseModel):
    template: str = "modern_report"
    palette: str = "violet"


class ReviseRequest(BaseModel):
    instruction: str
    selection: str = ""       # optional excerpt the instruction applies to


class ToolRequest(BaseModel):
    tool: Literal["expand", "condense", "formalize", "simplify", "add_citations", "polish", "humanize", "strengthen_argument"]
    selection: str = ""


class ManualEdit(BaseModel):
    content: str


Project.model_rebuild()
