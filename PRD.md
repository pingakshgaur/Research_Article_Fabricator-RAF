# Product Requirements Document (PRD)

## RAF — Research Article Fabricator

**Version:** 1.8.2  
**Last Updated:** October 2026  
**Status:** Active Development

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Product Vision & Goals](#2-product-vision--goals)
3. [Target Users & Personas](#3-target-users--personas)
4. [Core Design Principles](#4-core-design-principles)
5. [System Architecture](#5-system-architecture)
6. [Technology Stack](#6-technology-stack)
7. [Feature Specifications](#7-feature-specifications)
   - [7.1 Project Lifecycle](#71-project-lifecycle)
   - [7.2 Document Ingestion](#72-document-ingestion)
   - [7.3 Online Scholarly Research](#73-online-scholarly-research)
   - [7.4 Hybrid RAG Retrieval Engine](#74-hybrid-rag-retrieval-engine)
   - [7.5 Statistical Analysis Engine](#75-statistical-analysis-engine)
   - [7.6 Segment Blueprints & Rhetorical Moves](#76-segment-blueprints--rhetorical-moves)
   - [7.7 Writing Engine & Pipeline](#77-writing-engine--pipeline)
   - [7.8 Hallucination Filter](#78-hallucination-filter)
   - [7.9 Style Engine & Humanize](#79-style-engine--humanize)
   - [7.10 Originality Guard](#710-originality-guard)
   - [7.11 Citation Formatting](#711-citation-formatting)
   - [7.12 Studio — Review & Revision](#712-studio--review--revision)
   - [7.13 Publishing & Export](#713-publishing--export)
   - [7.14 Developer Tools](#714-developer-tools)
   - [7.15 Reliability & Fault Tolerance](#715-reliability--fault-tolerance)
8. [User Flow — End to End](#8-user-flow--end-to-end)
9. [Data Models](#9-data-models)
10. [API Reference](#10-api-reference)
11. [Configuration & Environment Variables](#11-configuration--environment-variables)
12. [Deployment Options](#12-deployment-options)
13. [Frontend Architecture](#13-frontend-architecture)
14. [Backend Architecture](#14-backend-architecture)
15. [Performance & Scalability](#15-performance--scalability)
16. [Security & Privacy](#16-security--privacy)
17. [Known Limitations](#17-known-limitations)
18. [Dependencies](#18-dependencies)
19. [Project Structure](#19-project-structure)

---

## 1. Executive Summary

**RAF (Research Article Fabricator)** is a local, private web application that transforms a **research title and 10–20 uploaded reference articles** into a structured, publication-ready scholarly article. It reads your references, researches the topic across 8 scholarly databases, runs real statistics on user-provided or auto-sourced data, writes each article segment using rhetorical blueprints grounded in academic writing theory, verifies every claim against source evidence, and publishes the approved article as **DOCX, PDF, or Markdown**.

All text generation runs entirely on the user's machine through **Ollama + `gemma4:12b`** — a 12-billion-parameter small language model (SLM). By default RAF uses **no API keys, no cloud LLM, and no telemetry**, and all data remains local. From 1.8.1 the user may add API keys of cloud models; only then, and only for those models, prompts leave the machine (§7.14f).

---

## 2. Product Vision & Goals

### Vision
Empower researchers, academics, and scholars to produce high-quality, evidence-grounded research articles faster, while maintaining full ownership and privacy of their work — without depending on cloud AI services.

### Goals

| # | Goal | Metric |
|---|------|--------|
| G1 | **100% local & private execution** | Zero external API keys; zero telemetry; all data on user's machine |
| G2 | **Evidence-grounded writing** | Every factual claim traced to an uploaded reference or verified web source |
| G3 | **Statistically sound** | All numbers produced by a real statistical engine — the LLM never invents statistics |
| G4 | **Publication-ready output** | Professional DOCX, PDF, and Markdown exports with 5 academic templates and 7 colour palettes |
| G5 | **Resilient pipeline** | Checkpoint-based recovery; multi-tier fallbacks for LLM errors, OOM, and Ollama crashes |
| G6 | **Human-in-the-loop authoring** | Every segment reviewable, revisable, and approvable before publishing |

---

## 3. Target Users & Personas

| Persona | Description | Key Needs |
|---------|-------------|-----------|
| **Academic Researcher** | PhD students, postdocs, faculty publishing journal articles | Correct citations, statistical rigour, privacy for unpublished work |
| **Graduate Student** | Masters/PhD students writing theses, literature reviews | Structured guidance, evidence synthesis, multiple revision rounds |
| **Independent Researcher** | Think-tank analysts, policy researchers | Local execution (no cloud), multiple article types, data analysis |
| **Research Team Lead** | Supervising multi-author publications | Version history, style consistency, template-based publishing |

---

## 4. Core Design Principles

1. **Privacy First** — By default no data leaves the user's machine: the writing model runs locally and only optional scholarly database queries are sent externally. Cloud models are strictly opt-in (the user adds a key), named wherever they are used, and can be switched off globally or per run.
2. **Grounded Generation** — Every claim must be traceable to uploaded evidence or retrieved sources. Statistics come from real computations, never LLM hallucination.
3. **Academic Rigour** — Writing follows established rhetorical models (Swales' CARS, Hopkins & Dudley-Evans, IMRaD) with discipline-specific conventions.
4. **Graceful Degradation** — Every stage has fallbacks. A failing component degrades the output quality, but never stops the entire pipeline.
5. **Human Authority** — The author has final say. Every segment must be reviewed and approved before publishing. All AI-generated content is editable.

---

## 5. System Architecture

```
┌────────────────────────────────────────────────────────────────────────────────┐
│                              User's Browser                                    │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  React 18 SPA (Vite)  — Custom CSS Design System — SSE Event Stream      │  │
│  │  Pages: Home → Setup → References → Segments → Processing → Studio →     │  │
│  │          Publish                                                         │  │
│  └─────────────────────────────┬────────────────────────────────────────────┘  │
└────────────────────────────────┼───────────────────────────────────────────────┘
                                 │  HTTP / SSE  (/api/*)
                                 ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Backend (Port 8000)                         │
│                                                                            │
│  ┌─────────┐  ┌──────────┐  ┌─────────┐  ┌────────────┐  ┌──────────────┐  │
│  │ main.py │  │ writer.py│  │ rag.py  │  │ analysis.py│  │ publisher.py │  │
│  │ (routes)│  │ (engine) │  │ (index) │  │ (stats)    │  │ (export)     │  │
│  └────┬────┘  └────┬─────┘  └────┬────┘  └─────┬──────┘  └──────┬───────┘  │
│       │            │             │             │                │          │
│  ┌────┴────┐  ┌────┴─────┐  ┌────┴────┐  ┌─────┴──────┐  ┌──────┴───────┐  │
│  │ jobs.py │  │blueprints│  │ingest.py│  │ factcheck  │  │ originality  │  │
│  │ store.py│  │ style.py │  │research │  │ citations  │  │ checkpoints  │  │
│  └─────────┘  └──────────┘  └─────────┘  └────────────┘  └──────────────┘  │
│                                                                            │
│                     ┌───────────────────┐                                  │
│                     │   llm.py          │                                  │
│                     │   llm_settings.py │                                  │
│                     └────────┬──────────┘                                  │
└──────────────────────────────┼─────────────────────────────────────────────┘
                               │  HTTP (Ollama API)
                               ▼
                     ┌───────────────────┐
                     │   Ollama Server   │
                     │   (Port 11434)    │
                     │                   │
                     │  gemma4:12b       │
                     │  nomic-embed-text │
                     └───────────────────┘
```

### Data Flow

```
References ─► Parse (PyMuPDF → pypdf → pdfplumber) ─► Metadata (layout + SLM) ─► Chunk
Title/Topic ─► SLM search plan ─► OpenAlex · Crossref · Semantic Scholar · arXiv ·
                                   PubMed · Europe PMC · DOAJ · Wikipedia · Web
                                        │
                   Hybrid Index: Neural Embeddings + BM25 + TF-IDF ─► RRF ─► MMR Diversity
                                        │
Data ─► User Datasets │ World Bank │ Reference Tables ─► Assumption Checks ─► Tests ─►
                                                         ≤4 Tables, ≤4 Figures
                                        │
For each segment (dependency order) ─► Blueprint Moves ─► Retrieve ─► Evidence Notes ─► Draft
                                   ─► Peer-Review Checklist ─► Refine ─► De-cliché ─►
                                      Originality Guard ─► Number Verification
```

---

## 6. Technology Stack

### Backend

| Category | Technologies | Purpose |
|----------|-------------|---------|
| **API Framework** | FastAPI ≥0.115, Uvicorn ≥0.30, Pydantic ≥2.7 | REST API, SSE streaming, request validation |
| **LLM Runtime** | Ollama (local), gemma4:12b, nomic-embed-text | Text generation, embeddings |
| **Document I/O** | PyMuPDF, pypdf, pdfplumber, python-docx, ReportLab, markdown-it-py | PDF/DOCX/MD reading and writing |
| **Retrieval (RAG)** | NumPy, scikit-learn (TF-IDF, KMeans), rank-bm25, RapidFuzz | Hybrid search, fuzzy matching |
| **Online Research** | pyalex, habanero, semanticscholar, arxiv, biopython, wikipedia-api, ddgs, trafilatura | 8 scholarly databases |
| **Data Analysis** | pandas, SciPy, statsmodels, Matplotlib, openpyxl | Statistics, hypothesis testing, charts |
| **HTTP Client** | httpx, truststore | External API calls with OS certificate trust |
| **Quality** | textstat | Readability metrics |

### Frontend

| Category | Technologies | Purpose |
|----------|-------------|---------|
| **Framework** | React 18.3.1, React DOM 18.3.1 | Component-based SPA |
| **Build System** | Vite 5.4.0, @vitejs/plugin-react | Fast dev server, HMR, production bundling |
| **Typography** | Fontsource Variable (Fraunces, Geist, Geist Mono) | Display, body, and monospace fonts |
| **Styling** | Custom CSS (1,397 lines) — zero external libraries | Glassmorphism, dual themes, ambient lighting, film grain |
| **Deployment** | Nginx 1.27 (Docker), multi-stage Node 20 build | SPA routing, SSE proxy, 1h read timeout |

### Infrastructure

| Component | Technology |
|-----------|-----------|
| **Containerization** | Docker Compose (3 services: backend, frontend, optional Ollama) |
| **Backend Image** | python:3.12-slim |
| **Frontend Image** | node:20-alpine → nginx:1.27-alpine (multi-stage) |
| **Persistence** | File-system JSON (no database required) |

---

## 7. Feature Specifications

### 7.1 Project Lifecycle

A project passes through 6 linear stages:

| Stage | Name | Description |
|-------|------|-------------|
| 1 | **Setup** | Define title, topic, discipline, article type, citation style, target length, authors |
| 2 | **References** | Upload 10–20 reference PDFs/DOCX/MD/TXT; optionally upload datasets (CSV/XLSX) |
| 3 | **Segments** | Select which sections to generate; configure lengths, tone, depth, and agents |
| 4 | **Processing** | Live fabrication with real-time progress streaming, timers, and checkpoints |
| 5 | **Studio** | Review, revise, apply text tools, inspect integrity, and approve each segment |
| 6 | **Published** | Download typeset PDF, DOCX, or Markdown; re-import external edits |

**Project Metadata:**
- Title (min 5 characters)
- Topic / research angle (free text)
- Discipline (12 preset disciplines + custom entry)
- Article type: Empirical, Systematic literature review, Conceptual/theoretical, Case study, Mixed-methods
- Citation style: APA, Harvard, Chicago, IEEE
- Target word count: 2,500 – 12,000 (configurable per-segment)
- Authors (comma-separated), Affiliation

---

### 7.2 Document Ingestion

**Supported Formats:** PDF, DOCX, Markdown (.md/.markdown), TXT

**Reading Pipeline (with cascading fallbacks):**
1. **PDF:** PyMuPDF (primary) → pypdf (fallback) → pdfplumber (table extraction fallback)
2. **DOCX:** python-docx — paragraphs, headings (levels 1–6), tables, and core metadata
3. **Markdown/TXT:** markdown-it-py parsing with heading and table extraction

**Processing Steps:**
- **Title Extraction:** Scans first-page font sizes to identify the visual title
- **Metadata Extraction:** SLM-powered JSON extraction of bibliographic fields (title, authors, year, venue, DOI) with regex heuristic fallback
- **Back-Matter Stripping:** Removes References/Bibliography sections to avoid retrieval contamination
- **Chunking:** Sliding window at ~220 words with 40-word overlap, respecting sentence and paragraph boundaries

**Constraints:**
- Individual file limit: 60 MB
- Reference count: configurable min (default 10) and max (default 20)
- No OCR: scanned PDFs without text layers are rejected

**Dataset Ingestion:**
- Formats: CSV, TSV, XLSX, XLS
- Used for statistical analysis; if absent, RAF sources World Bank indicators or reference tables

---

### 7.3 Online Scholarly Research

**8 Key-Free Scholarly Sources:**

| Source | Coverage | Method |
|--------|----------|--------|
| **OpenAlex** | All disciplines | pyalex library → REST fallback |
| **Crossref** | All disciplines (DOI metadata) | habanero library → REST fallback |
| **Semantic Scholar** | All disciplines | semanticscholar library → REST fallback |
| **arXiv** | STEM, CS, math, economics | arxiv library → RSS/Atom → REST fallback |
| **PubMed / NCBI** | Health, life sciences | biopython Entrez → REST fallback |
| **Europe PMC** | Biomedical | REST API |
| **DOAJ** | Open-access, humanities, social | REST API |
| **Wikipedia** | Encyclopaedic background | wikipedia-api → REST fallback |
| **DuckDuckGo** | General web | ddgs + trafilatura/BeautifulSoup extraction |

**Features:**
- Discipline-aware query routing (e.g., PubMed for health, arXiv for STEM)
- SLM-generated search plans
- Per-source thread-safe throttling with configurable delays
- HTTP 429 rate-limit cooldown (10-minute circuit breaker)
- Polite API usage with configurable contact email for rate-limit pools
- Toggleable per-project (Web Research on/off on Segments page)

---

### 7.4 Hybrid RAG Retrieval Engine

**Three-Signal Hybrid Search:**

1. **Neural Embeddings** — Dense vector search via `nomic-embed-text` through Ollama
2. **BM25** — Okapi BM25 lexical ranking (rank-bm25)
3. **TF-IDF** — Sublinear term-frequency with unigram/bigram features (scikit-learn)

**Fusion & Diversification:**
- **Reciprocal Rank Fusion (RRF):**  
  $\text{Score}(d) = \sum_{r \in \text{Rankings}} \frac{1}{60 + \text{Rank}_r(d)}$
- **Maximal Marginal Relevance (MMR)** with source diversity penalty:  
  $\text{MMR}(d) = (1 - \lambda) \cdot \text{Relevance}(d) - \lambda \cdot \max_{c \in \text{Selected}} \text{Sim}(d, c) - 0.08 \cdot \text{SourceCount}(d)$
- Source penalty ensures evidence is drawn from multiple references, not clustered on one

**Specialised Modes:**
- `search_within(source_ids)` — Constrained retrieval for fact-checking specific citations

**Fallback:** If `nomic-embed-text` is not installed, retrieval degrades to BM25 + TF-IDF only

---

### 7.5 Statistical Analysis Engine

**Data Acquisition Hierarchy:**
1. User-uploaded CSV/XLSX datasets
2. World Bank indicators matched to topic (via `wbgapi`)
3. Numeric tables extracted from reference PDFs

**Statistical Pipeline:**

| Step | Tests & Methods |
|------|----------------|
| **Assumption Checks** | Shapiro-Wilk normality test on all numeric features |
| **Bivariate Association** | Pearson (normal) or Spearman (non-normal) correlation with Holm-Bonferroni correction |
| **Two-Group Comparison** | Welch's t-test (Cohen's d) or Mann-Whitney U (rank-biserial r) |
| **Multi-Group Comparison** | One-way ANOVA (η²) or Kruskal-Wallis H (ε²) |
| **Regression** | OLS with HC3 robust standard errors, VIF collinearity checks, Breusch-Pagan heteroskedasticity test; logarithmic transform for skewed variables |
| **Trend Analysis** | OLS trend regression over time, CAGR computation, Spearman monotonicity |

**Output Guardrails:**
- Maximum 4 tables and 4 figures per article
- All findings emitted as factual text strings — the LLM is constrained to cite only these numbers
- Figures rendered via headless Matplotlib with custom academic styling

---

### 7.6 Segment Blueprints & Rhetorical Moves

12 segment types, each with academic writing theory-backed rules:

| Segment | Rhetorical Model | Key Moves |
|---------|-----------------|-----------|
| **Title** | Concise, descriptive | 10–20 words, no hype |
| **Abstract** | IMRaD micro-structure | Context → Aim → Method → Key Result → Conclusion (single paragraph, 180–250 words, zero citations) |
| **Keywords** | TF-IDF saliency | 5–7 indexing terms |
| **Introduction** | Swales' CARS model | Establish Territory → Prior Work → Niche/Gap → Occupy Niche |
| **Literature Review** | Thematic synthesis | K-means corpus clustering → SLM-named themes → Gap statement → Hypotheses (H1, H2…) |
| **Methodology** | Replicability standard | Only procedures RAF actually executed: design, data, procedure, analysis, validity, ethics |
| **Results** | Report-then-interpret-nothing | Numbers, test statistics, p-values verbatim; tables/figures referenced before placement |
| **Discussion** | Hopkins & Dudley-Evans | Restate findings → Compare with literature → Explain mechanisms → Theoretical contribution |
| **Conclusion** | Synthesis | Practical/policy implications, future horizons |
| **Limitations** | Honest constraints | Design, data, and generalizability limitations paired with future research directions |
| **References** | Auto-formatted bibliography | All cited items in chosen citation style |
| **Appendices** | Supplementary | Data dictionaries, analysis protocols |

**Writing Rules (applied to all segments):**
- Every factual claim carries a citation marker (`[R3]`, `[W7]`)
- Never invent statistics, dates, names, or findings
- Synthesize across sources rather than summarizing one at a time
- Varied sentence lengths; no stock connectors ("Moreover", "Furthermore")
- No formulaic wording ("delve", "crucial", "pivotal", "landscape", "plays a key role")
- No bullet points unless blueprint requests them

---

### 7.7 Writing Engine & Pipeline

**Thorough Mode (per segment):**
1. **Retrieve** — Hybrid RRF + MMR retrieval per rhetorical move
2. **Evidence Notes** — Paraphrased, cited notes from retrieved passages
3. **Draft** — SLM generates paragraphs following blueprint moves
4. **Peer-Review** — Critic scores a blueprint-specific checklist
5. **Refine** — Rewrite based on checklist feedback
6. **Hallucination Filter** — 4-layer grounding verification (see §7.8)
7. **Style Pass** — Naturalness scoring and humanize rewriting (see §7.9)
8. **Originality Guard** — Overlap detection and automated rephrasing (see §7.10)
9. **Number Verification** — Every number checked against evidence

**Quick Mode:** Skips separate note-taking, critique, and deep style passes; applies basic grounding and originality check.

**Emergency Mode:** Single-pass draft directly from prompt context if Quick mode fails.

**Dependency-Aware Parallel Scheduling:**
- Resolves topological segment dependencies (e.g., Discussion requires Results + Introduction; Abstract requires all core segments)
- Independent segments are written in parallel across 1–3 agent lanes
- Evidence notes are prepared ahead of the drafting agent
- Uses `ThreadPoolExecutor` with `FIRST_COMPLETED` scheduling

**Tone Meter:**

| Tone | Description |
|------|-------------|
| **Formal Academic** | Objective, impersonal, precise — default journal register |
| **Critical-Analytical** | Weighs evidence, exposes weaknesses, compares explanations |
| **Argumentative** | Advances a clear thesis, defends against counter-arguments |
| **Explanatory** | Clear, accessible — defines terms, guides step by step |
| **Reflective/Narrative** | Personal, contextual — relates experiences to evidence |

Each tone has 3 intensity levels (Subtle → Balanced → Strong) controlled by a 0–100 slider.

---

### 7.8 Hallucination Filter

Four sequential layers before any drafted segment reaches the Studio:

| Layer | Name | Action |
|-------|------|--------|
| 1 | **Sanitiser** | Strips model commentary ("Here is…"), placeholders ("[insert citation]"), repeated/truncated sentences, invalid citation markers |
| 2 | **Coherence** | SLM critic identifies off-topic, self-contradictory, or empty paragraphs; flagged ones are rewritten from evidence |
| 3 | **Grounding** | Each checkable claim verified against cited source passages via lexical overlap (threshold ≥ 0.62); ambiguous claims batch-judged by SLM as supported / partial / unsupported / contradicted; uncited sentences auto-receive citation markers where source support exists |
| 4 | **Repair** | Unsupported/contradicted sentences corrected from evidence or removed; unverifiable numbers flagged in Studio UI |

**Article-Level Review:** After all segments, a cross-document consistency check verifies research questions are answered and numbers agree across sections.

---

### 7.9 Style Engine & Humanize

**Stylometric Metrics:**
- Sentence length variation (SD/Mean ratio)
- Short sentence proportion (≤12 words)
- Repeated sentence openers
- Stock connector density ("Moreover", "Furthermore", etc.)
- Generic academic cliché frequency ("delve", "pivotal", "plays a key role")
- Reflexive triplets
- MATTR lexical diversity
- **Combined Naturalness Score: 0–100**

**Field Profiling:** Measures the same metrics on the user's uploaded references to calibrate drafts to the discipline's conventions (typical sentence length, variation, passive voice ratio).

**Text-tool engine (1.8.2, `textops.py`)** — one engine for Expand, Condense, Formalize, Simplify, Add citations, Polish, Humanize and Strengthen:

| Layer | What it does |
|-------|--------------|
| **Split** | Paragraph by paragraph (`ThreadPoolExecutor` over the engine pool); placeholders and headings set aside; paragraphs over 260 words in windows of about 150 words |
| **Diagnose** | No model: style metrics, `tells()` (stock vocabulary, trailing -ing clauses, summing-up sentences, stacked hedges and other patterns), `rhythm_plan()` (which sentence to split, join or shorten), `informality()`, `uncited()`, reading ease |
| **Rules** | Deterministic, meaning-safe edits: filler phrases, stock sentence openers, contractions, near-duplicate sentences |
| **Rewrite** | One model call per paragraph with a measured brief; neighbours shown for flow only; evidence retrieved per paragraph for the tools that may add sources |
| **Repair** | Dropped citation markers re-attached to the best-matching sentence; markers of sources not offered removed |
| **Gate** | Hard checks: citations, numbers, names, content-word recall (formulaic words excluded), length window per tool and strength, no text borrowed from neighbours, no new stock wording, embedding similarity when an embedding model is installed. Then a fidelity check: the model compares original and rewrite and names contradictions and inventions; only findings quoting the rewrite count |
| **Select** | Up to 2 attempts (3 at Strong), each retry carrying the rejection reason; best passing candidate kept; else rules-only; else unchanged with the reason reported |

`strength` 1–3 scales targets (Expand ×1.2 / 1.4 / 1.7, Condense ×0.82 / 0.66 / 0.5, and so on). Tools that cited new sources hand the segment to `finalize` (hallucination filter); the others save directly. The report is stored in `QualityReport.tool`. The earlier Humanize gate (length within ±15 %, score must rise, 70 % term recall, model-extracted propositions) rejected most rewrites and is gone.

---

### 7.10 Originality Guard

**Dual Detection:**
1. **7-Word Shingle Overlap** — Set intersection of 7-word n-grams between generated prose and all source texts. Maximum threshold: 4% (configurable via `RAF_MAX_NGRAM_OVERLAP`)
2. **Fuzzy Sentence Similarity** — RapidFuzz `token_sort_ratio` and `partial_ratio` against nearest source sentences. Threshold: 82 (configurable via `RAF_SENTENCE_SIM_LIMIT`)

**Automated Re-Expression:** Flagged sentences are re-expressed by the SLM with new grammar and vocabulary, preserving facts and citation markers. Re-checked up to 2 rounds.

**Cliché Removal:** Pattern-based cleanup of machine-sounding phrases ("in the realm of" → "in", "delves into" → "examine", "navigating the complex landscape" → "addressing").

> **Note:** This guard reduces overlap with the user's corpus and retrieved sources. It is not a Turnitin/iThenticate replacement.

---

### 7.11 Citation Formatting

**Supported Styles:**

| Style | In-Text Format | Example |
|-------|---------------|---------|
| **APA 7** | Author-date parenthetical | (Smith et al., 2021) |
| **Harvard** | Author-date parenthetical | (Smith et al., 2021) |
| **Chicago** | Author date | (Smith 2021) |
| **IEEE** | Numeric sequential bracket | [1], [1, 2] |

**Features:**
- Internal tracking markers (`[R1]`, `[W3]`) converted to formatted citations at publish time
- Full bibliography generation with author formatting, year, title, venue, DOI/URL
- Multi-citation grouping (e.g., `[R1, R3, W2]` → `(Jones, 2019; Smith et al., 2021)`)

---

### 7.12 Studio — Review & Revision

**Three-Pane Layout:**

| Pane | Contents |
|------|----------|
| **Left Rail** | Segment navigation with live status dots, spinners for parallel jobs, quick-add front-matter buttons |
| **Centre** | Paper-style typeset reading view with justified text, hoverable citation tooltips, highlighted hallucination flags, text selection bubble |
| **Right Sidebar** | Revision form, text tools, integrity report, hallucination card, style card, article review card, version history |

**Revision Capabilities:**
- **Natural-Language Revision** — Describe a change in plain language, applied to whole segment or selected text
- **8 Text Tools:** Expand, Condense, Formalize, Simplify, Add Citations, Polish, Humanize, Strengthen
- **Regenerate** — Complete re-draft from RAG evidence
- **Manual Editing** — Toggle raw Markdown editor for direct edits
- **Version History** — Full rollback timeline with one-click restoration
- **Approval Gate** — Each segment must be explicitly approved before final publishing

**Front-Matter Editing:**
- Title editor with SLM-generated alternative suggestions
- Keywords chip editor (Enter/comma to add)
- Abstract editor with live word count and target warnings

**Concurrency:**
- Up to 3 parallel segment jobs (revisions/tools) across different segments
- Same-segment operations are serialized to prevent conflicts

---

### 7.13 Publishing & Export

**5 Publication Templates:**

| Template | Description |
|----------|-------------|
| **Modern Report** | Colour band cover, sans-serif headings, shaded abstract/tables, table of contents |
| **Classic Journal** | Centred serif title, ruled abstract, booktabs tables, indented paragraphs |
| **APA 7 Manuscript** | Title page, double spacing, 12pt Times New Roman, running headers, monochrome |
| **Two-Column Conference** | IEEE/ACM-style two-column, Roman numeral headings, compact margins |
| **Minimal Monograph** | Generous margins, bookish typography, understated accents |

**7 Colour Palettes:** Violet, Midnight, Emerald, Crimson, Ochre, Lime, Graphite (+ Monochrome)

**Export Formats:**

| Format | Engine | Features |
|--------|--------|----------|
| **PDF** | ReportLab with TrueType fonts (DejaVu) | Cover page, running headers, page numbers, multi-column support, embedded figures |
| **DOCX** | python-docx with XML-level styling | Native Word heading styles, editable tables, borders, a contents list written into the file and linked to each heading (Word adds page numbers on open) |
| **Markdown** | GitHub-flavoured with base64-embedded figures | Portable, version-control friendly |

**Template Preview System:**
- Full-screen multi-page A4 simulation using the author's actual draft text
- Zoom controls (60%–180%), fit-to-height, page navigation
- Dynamic citation reformatting (APA ↔ IEEE)
- "Use this layout" one-click application

**Round-Trip Editing:**
- Export to DOCX/PDF/MD, edit externally (Word, Google Docs, Obsidian)
- Re-import the edited file; RAF maps sections back to segments via fuzzy heading matching

**Draft Exports:** Available at any time, even before full approval.

---

### 7.14 Developer Tools

A slide-over drawer panel accessible from the app header providing:

| Feature | Details |
|---------|---------|
| **Model Inspector** | Lists installed Ollama models, parameter sizes, quantization, VRAM usage, GPU layer breakdown |
| **Configuration Presets** | Quick-apply: Default, Precise, Creative |
| **Thinking Mode** | Enable/disable chain-of-thought on supported models |
| **Sampling Controls** | Temperature (0–2), Top-p (0–1), Top-k (1–100), Min-p (0–1), Repeat/Presence/Frequency penalties, Seed |
| **Context & Memory** | Context window (4K–262K tokens), Max output tokens, Prompt batch size |
| **Hardware Controls** | GPU offload layers (0–48), CPU threads, Keep-alive duration, Request timeout |
| **Speed Benchmark** | Live speed probe measuring prompt ingestion rate, generation rate (tok/s), model load latency; projected article completion time |
| **Persistence** | Settings saved to `<data_dir>/llm_settings.json`; apply on next model call without restart |

---

### 7.14b Settings, Themes & Admin Lock (1.5)

The Developer Tools drawer became one tab of a full **Settings** page (gear button, `#/raf/settings`).

| Capability | Description |
|------------|-------------|
| **Themes** | Five interface themes — Violet & Lime (original), Rosewood, Aurora, Solar, Ember — each a ten-colour ramp with a dark and a light version. The four new ones are generated from seven named colours per theme through shared `color-mix()` formulas; every text/background pair meets WCAG AA (≥ 4.5 : 1) |
| **Appearance options** | Theme (saved server-side), dark / light (per browser), background effects on/off, optional workspace name |
| **Defaults for new articles** | Authors, affiliation, discipline, article type, citation style, target length, run options and tone; applied when a project is created |
| **Language model** | The former Developer Tools controls, unchanged |
| **Admin lock** | Optional passcode (PBKDF2-SHA256, salted). While set, settings are readable but every change needs a session token (12 h, in memory) obtained by unlocking; 5 wrong attempts → 30 s wait. Protects against casual changes on a shared computer, not against file access |
| **Storage** | `<data_dir>/app_settings.json` |

### 7.14c Article Structure, Custom Theme & Sidebar (1.6)

| Capability | Description |
|------------|-------------|
| **Per-project structure** | `structure.py` replaces every direct use of the global blueprint table: `blueprint_for`, `order`, `generation_order`, `deps`, `describe`. Project fields `titles`, `custom_segments`, `order`, `excluded` (schema version 3) |
| **Rename** | Any body segment; used in Studio, exports, Contents and the importer |
| **Custom segments** | Written by RAF from a stated purpose (default three parts, or parts proposed by the model) or written by the author; gallery of ten common ones; up to 12 per project |
| **Order / leave out** | Drag or step the body into any order; exclude a segment from the document without deleting it; front matter fixed |
| **Write later** | Any segment without text can be written on its own as a background job |
| **References follow** | Rebuilt from the citations of included segments on every relevant change and at export; a hand-edited list is left alone |
| **Custom theme** | One picked colour → accent for both modes, text colour on it, contrasting highlight (opposite hue) and a ten-colour ramp (`customTheme.js`); verified at WCAG AA over 2,386 colours |
| **Sidebar** | Captions and group titles removed, bold rules between groups, Library first; width set by dragging (64–420 px, compact below 132 px), per browser |

### 7.14d LaTeX Export & Format an Existing Article (1.7)

| Capability | Description |
|------------|-------------|
| **LaTeX export** | `.zip` with `main.tex`, `references.bib`, `figures/`, `README.txt`. Templates map to `article` (three variants), `apa7` and `IEEEtran`. Citation markers become `\parencite{key}`; `biblatex` style follows the project's citation style. Tables use `booktabs` + `tabularx`, split into continued floats above 30 rows. Not compiled by RAF |
| **BibTeX / RIS** | Reference list alone; stable unique keys (`smith2021digital`); optional Crossref completion (volume, issue, pages) |
| **Format mode** | `Project.mode = "format"` (schema version 4). A document is read (`formatter.py`), its outline detected, and every section stored as an author-owned segment, pre-approved |
| **Readers** | DOCX (styles, inline formatting, tables, images, captions), Markdown, plain text (heading heuristics), PDF (font-size heuristics; lossy) |
| **Inline formatting** | `**bold**`, `*italic*`, `^sup^`, `~sub~` stored in segment text of format-mode projects only; rendered by all four exporters and the Studio; literal marks escaped with a backslash |
| **Checks** | Deterministic citation-versus-reference-list comparison (author–date and numbered) and per-section style metrics |
| **Reference restyle (experimental)** | Crossref lookup per entry (DOI, or bibliographic search with a title-match threshold); identified entries re-formatted in APA / Harvard / Chicago; others untouched |
| **Spacing fix** | Punctuation clean-up no longer removes the space in statistics such as "p = .05" (affected exports and stored drafts in earlier versions) |

### 7.14e Source Modes & the Window (1.8)

| Capability | Description |
|------------|-------------|
| **Source modes** | `Project.source_mode`: `references` (10–20 files), `mixed` (≥ 1 file), `research` (none; online research mandatory). Schema version 5 |
| **Deeper research** | Second query round from model-proposed follow-ups; up to 60 sources kept; Research-only drops Wikipedia and general web results |
| **Open-access full text** | `research.fetch_fulltext`: address from OpenAlex / Semantic Scholar / arXiv / Europe PMC, else Unpaywall by DOI; PDF ≤ 30 MB read with the normal PDF pipeline into `index/web_<id>.txt`; up to 12 papers; indexed like an uploaded reference (≤ 60 passages) |
| **Reading-list approval** | Run pauses with `run.status = "review"` after research; sources can be removed or pinned; `sources_confirmed` continues. Pinned sources are always added to the evidence shown to the writer |
| **Honest reporting** | Methodology protocol states databases, queries, rounds, sources kept, how many read in full and how many by abstract; project view carries `evidence` counts |
| **Streaming** | `llm.streaming(sink)`: prose calls of the current thread stream from Ollama; JSON calls never do; a retry resets the passage |
| **Live sheets** | `live.py` keeps the current text of each segment being written in memory; emits coalesced `delta` (≈ 8 / s), `sheet` and `edit` events, none persisted; late joiners get a snapshot in the stream's first message |
| **Window view** | Read-only sheets per segment with phase label, live text, struck-through corrections and enlarge-on-click; Console view retained |

### 7.14f Cloud Models through the User's API Keys (1.8.1)

| Capability | Description |
|------------|-------------|
| **Key store** | `providers.py`, `<data_dir>/llm_keys.json`: up to 12 keys; per key provider, model, optional address, agents (1–4), role (all / writing / checks), enabled, status (ok / unchecked / rejected). Provider detected from the key prefix. On add, the provider's model list is requested to verify the key; a rejected key is not stored |
| **Providers** | Claude through the official Anthropic SDK; OpenAI, Gemini, NVIDIA NIM, Groq, Mistral, DeepSeek, OpenRouter and any custom server through the OpenAI-compatible chat API |
| **Rule profiles** | Shared output contract; JSON rule for checks; reasoning headroom per provider; Claude: no sampling parameters, `output_config.effort` medium / low, thinking left adaptive, server-side refusal fallback (`fallbacks: "default"`) on the models that support it; OpenAI-style: parameter negotiation (`max_completion_tokens`, temperature, `response_format`) learned per model at run time |
| **Engine pool** | `llm._Runtime`: the local engine (1–3 agents) plus one engine per key; capacity = sum of agents, at most 8. Modes `local`, `hybrid`, `cloud`. A call takes the engine its thread used last when free, else the first free one (keys in list order, then local) |
| **Failure rules** | auth / quota → key off and marked rejected; rate limit → key rests for `retry-after` (≤ 120 s); server or network trouble → back-off, off after repeated failures; refusal → another engine for that request; no cloud engine left → local model continues; local model unreachable while cloud engines work → left out |
| **Per run** | `GenerateRequest.cloud` (default true), stored with the run options; team logged at the start; `run.started` History meta carries `models` and `cloud_models`; AI-use statement distinguishes local and online models |
| **Estimate** | Lanes = all agents; cloud speed assumed (45 tok/s), flagged `speed_source = "assumed for cloud models"`; such runs are not used for calibration |
| **UI** | Settings → Language model → Cloud models (key manager, Who writes, test, model list, rules); Segments page shows the team with a mark per provider under the agents box; status line shows `+ n cloud` |

### 7.15 Reliability & Fault Tolerance

| Feature | Description |
|---------|-------------|
| **Checkpoints** | Progress saved at every reference parsed, web research completed, index built, analysis done, literature theme discovered, evidence note written, move drafted, and refinement applied. Resume from exact interruption point. |
| **Fallbacks** | Research/analysis failure → continue without. Segment failure → retry Quick mode → emergency single-pass draft. OOM → reduce agents → lower GPU offload → CPU-only. Ollama crash → wait up to 600s for recovery. |
| **Timer** | Total time, per-stage time, per-segment time tracked across resumed sessions |
| **Self-Calibrating Estimates** | Speed probe at run start; actuals stored in `timing_history.json`; median ratio corrects future estimates |
| **Startup Recovery** | On server restart, interrupted runs are detected and marked "stopped" — ready to resume |
| **Atomic Persistence** | Write to .tmp file → atomic replace to prevent corruption during concurrent operations |

---

### 7.16 Library, History & Revisions (1.5)

| Capability | Description |
|------------|-------------|
| **Library page** | All projects with search, stage filter and sorting; rename, duplicate, archive, delete; per-project backup to one `.zip` and restore (never overwrites an existing project) |
| **Project History** | Append-only `history.jsonl` per project: every creation, upload, setting change, run, draft, revision, tool, manual edit, approval, restore, import, export and revision event, with actor (`you` / `RAF`). Filterable timeline, CSV / Markdown export. Rebuilt from saved versions for pre-1.5 projects |
| **AI-use statement** | Disclosure paragraph drafted deterministically from recorded facts (no model call) |
| **Article Revisions** | Named whole-article snapshots (`revisions/r0001.json` + figures). Automatic at publish and before a run, import, restore or round (identical states are not saved twice; 30 automatic ones kept) |
| **Compare** | Word-level diff per segment between any two revisions or the current article; totals of words added and removed |
| **Restore** | Whole revision or one segment; the current state is snapshotted first |
| **Changes-highlighted export** | DOCX or PDF with insertions green/underlined and deletions red/struck, citations rendered as published |
| **Revision rounds** | Reviewer comments → points (model, with a rule-based fallback) → author accepts / edits / skips → one revision per affected segment through the normal engine → before/after revisions → editable point-by-point response letter (Markdown, DOCX) |
| **Schema versioning** | `schema_version` in `project.json`, upgraded on load |
| **Automated tests** | `backend/tests` (pytest) with a stand-in model; no Ollama or network needed |

---

## 8. User Flow — End to End

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              HOME                                        │
│  • System health indicators (Ollama status, model availability)          │
│  • Project library (existing projects with metadata)                     │
│  • "Begin a new article" CTA                                             │
└───────────────────────────┬──────────────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     STEP 01: SETUP                                       │
│  Configure: Title, Topic, Discipline, Article Type, Citation Style,      │
│             Target Words (2.5K–12K), Authors, Affiliation                │
│  Action: "Create project" → advances to References                       │
└───────────────────────────┬──────────────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     STEP 02: REFERENCES                                  │
│  • Drag-and-drop upload zone (PDF, DOCX, MD, TXT)                        │
│  • Progress ring showing count vs minimum (10) and max (20)              │
│  • File list with parse status, metadata, chunk count                    │
│  • Optional: Upload dataset (CSV/XLSX) for statistical analysis          │
│  Gating: "Choose segments" disabled until min references met             │
└───────────────────────────┬──────────────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     STEP 03: SEGMENTS                                    │
│  • Select from 12 segment types (with dependency tracking)               │
│  • Presets: "Full article", "Core IMRaD", "Literature-focused"           │
│  • Length Plan: Short/Medium/Long presets, Pages, or exact Words         │
│  • Tone Meter: 5 tones × intensity slider (0–100)                        │
│  • Toggles: Web research, Data analysis, Hallucination filter, Style     │
│  • Depth: Thorough vs Quick draft                                        │
│  • Agents: Solo (1), Duo (2), Trio (3)                                   │
│  Action: "Fabricate N segments" → launches pipeline                      │
└───────────────────────────┬──────────────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     STEP 04: PROCESSING                                  │
│  Live pipeline monitor:                                                  │
│  1. Estimating time (speed probe)                                        │
│  2. Reading references (parsing & metadata)                              │
│  3. Online research (scholarly search)                                   │
│  4. Building index (Neural + BM25 + TF-IDF)                              │
│  5. Data analysis (statistics & figures)                                 │
│  6. Writing segments (drafting & reviewing)                              │
│  7. Originality & integrity (overlap & hallucination checks)             │
│  • Dual timer: elapsed + dynamic ETA projection                          │
│  • Auto-scrolling console log (SSE events)                               │
│  • Per-segment status chips with elapsed timers                          │
│  • "Resume from checkpoint" button on failure                            │
│  • "Open studio" once first draft completed                              │
└───────────────────────────┬──────────────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     STEP 05: STUDIO                                      │
│  Three-pane editor:                                                      │
│  [Left: Segment nav] [Centre: Paper view] [Right: Tools & Reports]       │
│  • Typeset reading with hoverable citations                              │
│  • Hallucination flags highlighted in text                               │
│  • Text selection bubble (Revise, Humanize, Polish, Expand)              │
│  • Natural-language revision requests                                    │
│  • 8 text tools (Expand, Condense, Formalize, Simplify, etc.)            │
│  • Integrity, Grounding, Style, Review reports                           │
│  • Version history with rollback                                         │
│  • Front-matter editors (Title, Keywords, Abstract)                      │
│  • Segment approval toggle                                               │
└───────────────────────────┬──────────────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     STEP 06: PUBLISH                                     │
│  • Template picker (5 layouts) with thumbnail previews                   │
│  • Colour palette swatches (7 options)                                   │
│  • Full-screen template preview with real text excerpts                  │
│  • Approval checklist (all segments must be approved)                    │
│  • Export: PDF, DOCX, or Markdown                                        │
│  • Draft preview export (pre-approval)                                   │
│  • Re-import externally edited documents                                 │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Data Models

### Core Models (Pydantic)

#### Project
```
Project
├── id: str (12-char hex UUID)
├── created: float (timestamp)
├── updated: float (timestamp)
├── title: str
├── topic: str
├── discipline: str
├── article_type: str (default "Empirical research article")
├── citation_style: "APA" | "Harvard" | "IEEE" | "Chicago"
├── target_words: int (default 6000)
├── authors: list[str]
├── affiliation: str
├── references: list[Reference]
├── dataset_files: list[str]
├── web_sources: list[WebSource]
├── selected: list[str]              # selected segment keys
├── segments: dict[str, Segment]
├── analysis: AnalysisResult | None
├── options: dict                     # {web_research, data_analysis}
├── segment_lengths: dict[str, int]
├── tone: dict                        # {name, intensity}
├── publish_style: dict               # {template, palette}
├── review: dict                      # article-level consistency review
├── run: RunInfo
├── stage: "setup" | "references" | "segments" | "processing" | "studio" | "published"
└── log: list[dict]                   # rolling event log (last 400)
```

#### Reference
```
Reference
├── id: str
├── filename: str
├── kind: "pdf" | "docx" | "md" | "txt"
├── title, authors, year, venue, doi
├── pages: int, chars: int, chunks: int
├── status: "uploaded" | "parsed" | "failed"
└── error: str
```

#### Segment
```
Segment
├── key: str (e.g., "introduction")
├── title: str
├── status: "pending" | "queued" | "working" | "draft" | "revising" | "approved" | "failed"
├── content: str
├── versions: list[Version]
├── figures: list[Figure]
├── tables: list[Table]
├── quality: QualityReport
├── notes: list[str]
└── error: str
```

#### QualityReport
```
QualityReport
├── words: int, target_words: int
├── ngram_overlap: float
├── flagged_sentences: int, rewritten_sentences: int
├── readability: float | None
├── citations: int
├── unverified_numbers: list[str]
├── checklist: dict[str, bool]
├── grounding: dict         # hallucination filter summary
├── flags: list[dict]       # {sentence, verdict, reason}
├── style: dict             # naturalness metrics & score
├── humanize: dict          # last Humanize run report
└── tool: dict              # report of the last text tool (textops.run)
```

#### RunInfo
```
RunInfo
├── status: "idle" | "running" | "stopped" | "completed"
├── first_started, session_started, elapsed_before, finished
├── sessions: int
├── stages: dict[str, float]           # stage → seconds
├── segment_seconds: dict[str, float]  # segment → seconds
├── agents: int
├── checkpoints: int
└── estimate: dict                      # pre-run time estimate
```

### Persistence

All project data is stored as JSON files on the filesystem:
```
backend/data/projects/<project-id>/
├── project.json        # Full project state (Pydantic → JSON)
├── uploads/            # Uploaded reference files
├── datasets/           # Uploaded CSV/XLSX datasets
├── figures/            # Generated statistical charts (PNG)
├── index/              # Search index, chunks, checkpoints
│   ├── checkpoints.json
│   ├── chunks.json
│   ├── index.pkl
│   ├── style_profile.json
│   └── ref_*.txt / ref_*.tables.json
└── exports/            # Generated DOCX, PDF, Markdown files
```

---

## 10. API Reference

### System & Catalogue

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Service health: Ollama status, model availability, API version, reference limits |
| `GET` | `/api/segments` | Catalogue of blueprint segment types with word limits, shares, dependencies |
| `GET` | `/api/tones` | Available tone presets with intensity level descriptions |
| `GET` | `/api/length-profile` | Suggested word budgets per segment for a given article type and target length |
| `GET` | `/api/publish/styles` | Publishing template and palette catalogue |

### Project CRUD

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/projects` | List all projects with summary statistics |
| `POST` | `/api/projects` | Create a new project |
| `GET` | `/api/projects/{pid}` | Get full project state with busy indicators |
| `PATCH` | `/api/projects/{pid}` | Update project metadata |
| `DELETE` | `/api/projects/{pid}` | Delete project and all data |
| `POST` | `/api/projects/{pid}/stage/{stage}` | Set project workflow stage |

### File Uploads

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/projects/{pid}/references` | Upload reference files (multipart, max 60MB each) |
| `DELETE` | `/api/projects/{pid}/references/{rid}` | Remove a reference |
| `POST` | `/api/projects/{pid}/datasets` | Upload datasets (CSV/TSV/XLSX) |
| `DELETE` | `/api/projects/{pid}/datasets/{name}` | Remove a dataset |

### Configuration

| Method | Path | Description |
|--------|------|-------------|
| `PUT` | `/api/projects/{pid}/lengths` | Set per-segment word targets |
| `PUT` | `/api/projects/{pid}/tone` | Set tone preset and intensity |
| `PUT` | `/api/projects/{pid}/publish-style` | Set template and colour palette |

### Fabrication & Events

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/projects/{pid}/generate` | Launch article fabrication pipeline |
| `GET` | `/api/projects/{pid}/events` | SSE event stream (real-time logs, stages, progress) |

### Studio & Segments

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/projects/{pid}/segments/{key}/revise` | Natural-language revision (full segment or selection) |
| `POST` | `/api/projects/{pid}/segments/{key}/tool` | Apply a text tool: `tool`, optional `selection`, `strength` 1–3 |
| `POST` | `/api/projects/{pid}/segments/{key}/regenerate` | Complete segment re-draft from RAG evidence |
| `PUT` | `/api/projects/{pid}/segments/{key}` | Manual text edit (also creates front-matter if absent) |
| `POST` | `/api/projects/{pid}/segments/{key}/approve` | Approve or un-approve a segment |
| `POST` | `/api/projects/{pid}/segments/{key}/restore/{index}` | Restore a historical version |
| `POST` | `/api/projects/{pid}/review` | Run article-level consistency review |

### Publishing

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/projects/{pid}/export/{fmt}` | Export as PDF, DOCX, or Markdown (`?draft=true` for previews) |
| `POST` | `/api/projects/{pid}/import` | Re-import an externally edited document |
| `GET` | `/api/projects/{pid}/files/{path}` | Serve project assets (e.g., generated figures) |

### Library, History & Revisions (1.5)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/projects/{id}/rename` · `/duplicate` · `/archive` | Library actions |
| GET | `/api/projects/{id}/backup` | Download the project as a `.zip` |
| POST | `/api/projects/restore` | Create a project from a backup |
| GET | `/api/projects/{id}/history` · `/ai-statement` | Event log; disclosure paragraph and its facts |
| GET, POST | `/api/projects/{id}/revisions` | List; save a revision |
| PATCH, DELETE | `/api/projects/{id}/revisions/{n}` | Rename; delete |
| POST | `/api/projects/{id}/revisions/{n}/restore?key=` | Restore the whole revision or one segment |
| GET | `/api/projects/{id}/compare?a=&b=` · `/compare/export/{docx\|pdf}` | Differences; changes-highlighted file |
| GET, POST | `/api/projects/{id}/rounds` | List; start a revision round from pasted comments |
| GET, PUT, DELETE | `/api/projects/{id}/rounds/{rid}` | Read; edit points or letter; discard |
| POST | `/api/projects/{id}/rounds/{rid}/apply` | Apply the accepted points |
| GET | `/api/projects/{id}/rounds/{rid}/letter.docx` | Response letter as Word |

### Developer Tools

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/settings/llm` | Current LLM settings, defaults, presets, Ollama state |
| `PUT` | `/api/settings/llm` | Update LLM parameters |
| `DELETE` | `/api/settings/llm` | Reset to defaults |
| `POST` | `/api/settings/llm/benchmark` | Run speed test |
| `GET` | `/api/settings/llm/keys` | Cloud-model keys without secrets, mode, providers and their rules |
| `POST` | `/api/settings/llm/keys` | Add a key (verified with the provider, stored encrypted) |
| `PATCH` / `DELETE` | `/api/settings/llm/keys/{kid}` | Change model, agents, role, enabled, address / remove |
| `PUT` | `/api/settings/llm/keys-order` | Priority order of the keys |
| `PUT` | `/api/settings/llm/mode` | `local`, `hybrid` or `cloud` |
| `POST` | `/api/settings/llm/keys/{kid}/test` | One very small real request through the key |
| `GET` | `/api/settings/llm/keys/{kid}/models` | Models the key can use, asked from the provider |

---

## 11. Configuration & Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `RAF_OLLAMA_URL` | `http://localhost:11434` | Ollama server URL |
| `RAF_MODEL` | `gemma4:12b` | Writing model |
| `RAF_EMBED_MODEL` | `nomic-embed-text` | Neural embedding model (optional) |
| `RAF_NUM_CTX` | `16384` | Context tokens per LLM call |
| `RAF_NUM_GPU` | `-1` (auto) | GPU layers to offload (0 = CPU only) |
| `RAF_LLM_TIMEOUT` | `900` | Seconds per model response |
| `RAF_OLLAMA_WAIT` | `600` | Seconds to wait for Ollama recovery after crash |
| `RAF_MIN_REFS` / `RAF_MAX_REFS` | `10` / `20` | Reference count limits |
| `RAF_WEB_RESEARCH` | `True` | Default state of the Online research switch for new projects |
| `RAF_RESULTS_PER_SOURCE` | `5` | Results fetched per scholarly API |
| `RAF_HTTP_TIMEOUT` | `25` | Timeout for research HTTP requests |
| `RAF_MAX_NGRAM_OVERLAP` | `0.04` | Originality: max 7-word shingle overlap (4%) |
| `RAF_SENTENCE_SIM_LIMIT` | `82` | Originality: fuzzy sentence similarity threshold |
| `RAF_DATA_DIR` | `backend/data` | Project data directory |
| `RAF_CONTACT_EMAIL` | `raf@example.org` | Polite-pool email for scholarly APIs |
| `RAF_CORS` | `localhost:5173,5173,8080` | Allowed CORS origins |
| `RAF_API` | `http://localhost:8000` | Frontend dev proxy target |
| `OLLAMA_NUM_PARALLEL` | Ollama default | Ollama concurrent request slots (set ≥ agent count) |

---

## 12. Deployment Options

### Option A — Windows Launcher (`start.bat`)
- Creates `.venv`, installs backend and frontend dependencies, opens two terminal windows (API + UI)
- First run: several minutes. Subsequent runs: quick.

### Option B — Manual Start (Cross-platform)
- Two terminals: backend (uvicorn on port 8000) + frontend (Vite dev server on port 5173)
- No virtual environment activation needed — calls `.venv/bin/python` directly

### Option C — Docker Compose
- `docker compose up --build`
- Frontend → port 8080 (Nginx), Backend → port 8000
- Optional `ollama` profile for containerized model serving
- Nginx configured with 1GB upload limit and 1-hour read timeout for SSE

---

## 13. Frontend Architecture

### Routing
- Custom hash router (`#/p/:id/:view`) using `location.hash` parsing
- 6 views: Home, Setup, References, Segments, Processing, Studio, Publish
- Navigation rail with stage gatekeeping (can't skip ahead without prerequisites)

### State Management
- Single source of truth at `App` component level, distributed via props
- Server-reconciled state: API calls return updated project model
- Real-time SSE synchronization (`EventSource` → rolling 600-event log)
- Debounced project reload on critical events (segment, job, done, error, stage, checkpoint)

### Design System
- **Zero external UI libraries** — fully custom CSS (1,397 lines)
- **Dual themes:** Dark (Obsidian Black + Deep Violet) / Light (Sage Alabaster + Electric Lime)
- **Visual effects:** Glassmorphism, ambient cursor-tracking lighting, film grain SVG filter, animated aurora
- **43 SVG icons** built into a pure `Icon` component
- **Custom components:** Button (7 variants), Select, Combo, Toggle, Segmented, Ring, Spinner, Toast notifications

### API Client
- Custom `fetch`-based client with structured error extraction
- Handles JSON, FormData multipart, SSE EventSource, and blob downloads
- Health heartbeat polled every 20 seconds
- API version compatibility check with outdated-server banner

---

## 14. Backend Architecture

### Module Map

| Module | Lines | Responsibility |
|--------|-------|---------------|
| `main.py` | 458 | FastAPI routes, SSE streaming, concurrency guards |
| `writer.py` | 1,271 | Corpus pipeline, segment builders, revision engine, parallel scheduling |
| `publisher.py` | 858 | DOCX/PDF/Markdown export, templates/palettes, document re-import |
| `analysis.py` | 491 | Statistical analysis engine, tables, figures |
| `research.py` | 400 | 8 online scholarly sources with library → REST fallbacks |
| `style.py` | — | Naturalness scoring, field profiling, fact inventory |
| `textops.py` | — | Text-tool engine: diagnose, rules, rewrite, repair, gate, select |
| `factcheck.py` | 344 | 4-layer hallucination filter, article-level review |
| `estimate.py` | 287 | Speed probe, time estimation, self-calibration |
| `blueprints.py` | 258 | 12 segment blueprints, rhetorical moves, tone meter, length profiles |
| `llm.py` | — | Every model call: engine pool (local model + cloud keys), routing, fallbacks, streaming |
| `providers.py` | — | Cloud models: key store, provider rule profiles, Anthropic SDK and OpenAI-compatible calls |
| `vault.py` | — | Encryption of stored API keys (DPAPI / Fernet) |
| `ingest.py` | 255 | Document reading (PDF/DOCX/MD), metadata extraction, chunking |
| `models.py` | 206 | Pydantic data models and request schemas |
| `originality.py` | 196 | Shingle overlap, sentence similarity, automated rephrasing |
| `rag.py` | 163 | Hybrid retrieval: neural + BM25 + TF-IDF, RRF, MMR |
| `citations.py` | 145 | APA/Harvard/Chicago/IEEE formatting |
| `jobs.py` | 132 | Background job runner, SSE event broadcasting |
| `llm_settings.py` | — | Developer Tools settings, presets, benchmark |
| `api/` | — | Route modules: projects, library, fabrication, studio, publishing, record, settings (split out of `main.py` in 1.5) |
| `history.py` | — | Append-only project history, AI-use statement |
| `revisions.py` | — | Whole-article revisions: snapshot, compare, restore, changes export |
| `rounds.py` | — | Revision rounds and the response letter |
| `app_settings.py` | — | RAF settings: theme, new-article defaults, admin lock |
| `structure.py` | — | One article's structure: titles, added segments, order, exclusions |
| `latex.py` | — | LaTeX export |
| `formatter.py` | — | Format an existing article: readers, outline, checks, restyle |
| `live.py` | — | The Window: live sheets and their events |
| `checkpoints.py` | 85 | Durable progress markers, resume from checkpoint |
| `store.py` | 71 | Atomic file-system JSON persistence |
| `config.py` | 66 | Environment variable configuration |

### Concurrency Model
- **Project-level jobs** (fabrication, review, import): exclusive lock — nothing else runs on the project
- **Segment-level jobs** (revisions, tools): up to 3 concurrent, one per distinct segment
- **Agent slots** (1–3): managed by threading Condition variable with automatic degradation
- **Atomic writes:** .tmp → atomic rename to prevent JSON corruption

---

## 15. Performance & Scalability

| Aspect | Details |
|--------|---------|
| **Model Memory** | ~8 GB RAM for gemma4:12b; 16 GB total RAM recommended |
| **Disk Space** | ~10 GB (7.6 GB model + ~1 GB Python packages + project data) |
| **GPU** | Optional NVIDIA GPU recommended; CPU-only is supported but slower |
| **Context Window** | 16,384 tokens per call (default); up to 262,144 tokens with sufficient VRAM |
| **Concurrent Agents** | 1 (Solo), 2 (Duo), or 3 (Trio) parallel model workers |
| **Checkpoint Overhead** | Negligible — JSON writes with atomic replace |
| **Self-Calibration** | Timing accuracy improves over repeated runs |

---

## 16. Security & Privacy

| Aspect | Implementation |
|--------|---------------|
| **Data Locality** | All project data stays on the user's machine. No cloud storage. |
| **API Keys** | None needed. Optional cloud-model keys are stored encrypted (`vault.py`: Windows DPAPI; elsewhere Fernet with an owner-only key file), never returned by the API (last four characters only), scrubbed from error messages and logs, guarded by the admin lock, and kept outside project folders and backups. `http://` addresses are refused except for localhost. |
| **Cloud models** | Opt-in. Prompts for a cloud model contain passages of the references and the draft and go to that provider; the Segments page, the run log, History and the AI-use statement name the providers. Mode *This PC only* or `cloud: false` on a run sends nothing. |
| **No Telemetry** | No analytics, no tracking, no phone-home. |
| **Online Research** | Only optional scholarly database queries are sent externally. Toggleable per project. |
| **CORS** | Configurable allowed origins (default: localhost ports) |
| **File Validation** | Extension checking, size limits (60 MB per file), safe filename sanitization |
| **Atomic Persistence** | Write-to-temp + atomic rename prevents data corruption |

---

## 17. Known Limitations

| Limitation | Details |
|-----------|---------|
| **No OCR** | Scanned PDFs without a text layer cannot be read. Use text-based PDFs or pre-OCR. |
| **Not a plagiarism checker** | The originality guard reduces overlap with the user's corpus. It is not a Turnitin/iThenticate replacement. Run institutional checkers before submission. |
| **12B model quality** | A 12-billion-parameter local model can misread sources. Verify citations and flagged numbers. |
| **No real Results without data** | If no suitable data exists, the Results segment becomes an evidence synthesis (not invented statistics). |
| **AI detection** | Quality features aim for accuracy and readability, not AI-detector evasion. Detectors are unreliable in both directions. |
| **Single machine** | Designed for single-user, single-machine use. No multi-user or multi-tenant support. |
| **Context per call** | 16K tokens default per LLM call (not full 262K window). Raise `RAF_NUM_CTX` with more memory. |

---

## 18. Dependencies

### Backend Python Dependencies

| Category | Packages |
|----------|----------|
| **API Server** | fastapi, uvicorn, python-multipart, pydantic, httpx, truststore |
| **Document I/O** | pymupdf, pypdf, pdfplumber, python-docx, reportlab, markdown-it-py |
| **Retrieval (RAG)** | numpy, scikit-learn, rank-bm25, rapidfuzz |
| **Online Research** | arxiv, pyalex, habanero, semanticscholar, biopython, wikipedia-api, ddgs, trafilatura, beautifulsoup4, lxml, feedparser, wbgapi |
| **Data Analysis** | pandas, scipy, statsmodels, matplotlib, openpyxl, textstat |

### Frontend Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| react | ^18.3.1 | UI framework |
| react-dom | ^18.3.1 | DOM rendering |
| @fontsource-variable/fraunces | ^5.1.0 | Display typography |
| @fontsource-variable/geist | ^5.1.0 | Body typography |
| @fontsource-variable/geist-mono | ^5.1.0 | Monospace typography |
| vite | ^5.4.0 | Build system (dev) |
| @vitejs/plugin-react | ^4.3.1 | React HMR plugin (dev) |

### External Requirements

| Software | Version | Required? |
|----------|---------|-----------|
| Python | 3.12+ | Yes |
| Node.js | 20+ LTS | Yes |
| Ollama | Current | Yes |
| Git | Any recent | Recommended |
| Docker Desktop | Current | Optional (for Docker route) |
| gemma4:12b | — | Yes (7.6 GB download) |
| nomic-embed-text | — | Optional (improves retrieval) |

---

## 19. Project Structure

```
Research_Article_Fabricator-RAF/
├── start.bat                  # Windows launcher
├── docker-compose.yml         # Docker orchestration (3 services)
├── README.md                  # User documentation
├── PRD.md                     # This document
│
├── backend/
│   ├── Dockerfile             # python:3.12-slim image
│   ├── requirements.txt       # 44 Python dependencies
│   └── app/
│       ├── main.py            # FastAPI routes, SSE, guards (458 lines)
│       ├── config.py          # Environment variable settings (66 lines)
│       ├── models.py          # Pydantic data models (206 lines)
│       ├── store.py           # File-system JSON persistence (71 lines)
│       ├── jobs.py            # Background job runner, SSE events (132 lines)
│       ├── writer.py          # Writing engine, pipeline, scheduler (1,271 lines)
│       ├── blueprints.py      # Segment blueprints, moves, tones (258 lines)
│       ├── ingest.py          # Document reading, chunking (255 lines)
│       ├── research.py        # 8 scholarly sources (400 lines)
│       ├── rag.py             # Hybrid retrieval engine (163 lines)
│       ├── analysis.py        # Statistical analysis, figures (491 lines)
│       ├── factcheck.py       # Hallucination filter (344 lines)
│       ├── style.py           # Naturalness engine, humanize (324 lines)
│       ├── originality.py     # Overlap detection, rephrasing (196 lines)
│       ├── citations.py       # Citation formatting (145 lines)
│       ├── publisher.py       # DOCX/PDF/MD export, templates (858 lines)
│       ├── checkpoints.py     # Progress markers, resume (85 lines)
│       ├── estimate.py        # Time estimation, self-calibration (287 lines)
│       ├── llm.py             # Ollama client, agents, fallbacks (255 lines)
│       └── llm_settings.py    # Developer Tools settings
│
├── frontend/
│   ├── Dockerfile             # node:20 → nginx:1.27 multi-stage
│   ├── nginx.conf             # Reverse proxy, SSE streaming config
│   ├── package.json           # React 18.3 + Vite 5.4
│   ├── vite.config.js         # Dev server + API proxy
│   ├── index.html             # SPA entry with zero-FOUC theme script
│   └── src/
│       ├── main.jsx           # React entry (StrictMode + ToastProvider)
│       ├── App.jsx            # Shell, router, nav, SSE consumer, health
│       ├── api.js             # Centralised API client (fetch + SSE)
│       ├── styles.css         # Complete design system (1,397 lines)
│       ├── ui.jsx             # Custom component library (43 icons, 10+ components)
│       ├── DevTools.jsx       # LLM configuration drawer
│       ├── TemplatePreview.jsx # Multi-page A4 typesetting preview
│       └── pages/
│           ├── Home.jsx       # Landing, project library
│           ├── Setup.jsx      # Step 01: Project configuration
│           ├── References.jsx # Step 02: File uploads
│           ├── Segments.jsx   # Step 03: Structure planning
│           ├── Processing.jsx # Step 04: Live fabrication monitor
│           ├── Studio.jsx     # Step 05: Review & revision studio
│           └── Publish.jsx    # Step 06: Export & round-trip
│
└── backend/data/              # Project data (gitignored)
    ├── projects/<id>/         # Per-project storage
    ├── llm_settings.json      # Developer Tools config
    └── timing_history.json    # Self-calibration data
```

---

*This PRD was generated from a comprehensive analysis of the RAF codebase including all backend modules (main.py, writer.py, blueprints.py, rag.py, research.py, analysis.py, factcheck.py, style.py, originality.py, citations.py, publisher.py, ingest.py, llm.py, checkpoints.py, estimate.py, jobs.py, store.py, config.py, models.py) and all frontend files (App.jsx, api.js, ui.jsx, DevTools.jsx, TemplatePreview.jsx, styles.css, and all 7 page components).*

