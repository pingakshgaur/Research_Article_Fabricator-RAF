# RAF — Research Article Fabricator

RAF is a local, private web app that turns **a title plus 10–20 reference articles** into a structured research
article. It reads your references, researches the topic across scholarly databases, runs real statistics, writes
each segment you select with its own writing blueprint, lets you revise every segment, and publishes the approved
article as **DOCX, PDF or Markdown**.

All text generation runs on your own machine through **Ollama + `gemma4:12b`**. RAF uses no API keys and has no cloud LLM.

---

## Workflow

| Step | What happens |
|---|---|
| **01 Topic & title** | Title, research focus, discipline, article type, citation style (APA / Harvard / Chicago / IEEE), target length, authors. |
| **02 References** | Upload 10–20 PDF / DOCX / Markdown / TXT articles. You can also upload your own dataset (CSV/XLSX). |
| **03 Segments** | Choose any of: Title, Abstract, Keywords, Introduction, Review of Literature, Methodology, Results/Analysis, Discussion, Conclusion & Implications, Limitations & Future Research, References, Appendices. |
| **04 Fabrication** | A live pipeline view streams every step: parsing, research, indexing, analysis, writing, and integrity checks. |
| **05 Studio** | Read each segment on a paper-style page with hoverable citations, tables and figures. Request changes in plain language, apply text tools (Expand, Condense, Formalize, Simplify, Add citations, Polish, Humanize, Strengthen) to a whole segment or a selected passage, edit by hand, restore versions, and approve. |
| **06 Publish** | Once every segment is approved, download a typeset PDF or DOCX (or Markdown). You can also re-import an edited DOCX, PDF or Markdown file, and RAF splits it back into segments. |

## Reliability & speed features

* **Timer.** The Fabrication screen shows the total time, the time for each stage and the time for each segment. Time adds up across resumed sessions.
* **Checkpoints.** RAF saves progress as it goes: each reference it reads, the online research, the index, the analysis, the literature themes, and every evidence note, drafted part and refinement of a segment. **Resume from checkpoint** continues at the exact step that was interrupted. This also works after the API server was closed or crashed.
* **Fallbacks.** Problems don't stop the whole run:
  * If research or analysis fails, RAF continues without it.
  * If a segment fails, RAF retries it in Quick mode, then with a single-pass emergency draft.
  * If the model runs out of memory, RAF reduces the number of agents, then lowers GPU offload step by step down to CPU only.
  * If Ollama crashes or restarts, RAF waits up to `RAF_OLLAMA_WAIT` seconds for it to come back.
* **Agents.** Solo, Duo or Trio model workers. Segments that don't depend on each other are written side by side, and evidence notes are prepared ahead of drafting. Set `OLLAMA_NUM_PARALLEL` to at least the number of agents before running `ollama serve`, otherwise Ollama queues the requests and there is no speed-up.
* **Per-segment lengths.** Set a word target for each segment on the Segments page. Segments that haven't started can still be changed during fabrication.
* **Front matter editing.** The Studio has dedicated editors for the Title (with suggestions), Keywords (chips) and Abstract (live word count). You can also add any of these by hand if they weren't generated.
* **Outdated-server warning.** The UI shows a banner when the API process is running older code than the interface. Restart the API after you update RAF.

## How RAF writes

```
references ─► parse (PyMuPDF → pypdf → pdfplumber) ─► metadata (layout + SLM) ─► chunk
title/topic ─► SLM search plan ─► OpenAlex · Crossref · Semantic Scholar · arXiv · PubMed/Europe PMC · DOAJ · Wikipedia · web
                                          │
                     hybrid index: neural embeddings (optional) + BM25 + TF-IDF ─► Reciprocal Rank Fusion ─► MMR diversity
                                          │
data ─► user dataset │ World Bank indicators │ tables inside references ─► assumption checks ─► tests ─► ≤4 tables, ≤4 figures
                                          │
for each segment (dependency order) ─► blueprint moves ─► retrieve ─► paraphrased evidence notes ─► draft
                                    ─► peer-review checklist ─► refine ─► de-cliché ─► originality guard ─► number verification
```

* **Blueprints** (`backend/app/blueprints.py`): each segment has its own rhetorical moves, rules and reviewer checklist.
  Introductions follow Swales' CARS model. The literature review is organised by theme: RAF clusters the corpus with
  k-means, and the model names each theme. Methodology describes *only* the procedures RAF actually ran. Results
  reports statistics verbatim and does not interpret them. Discussion compares the findings with the literature.
* **Statistics** (`backend/app/analysis.py`): descriptive statistics and Shapiro–Wilk normality tests. Depending on the
  normality result, RAF then chooses Pearson or Spearman correlations with Holm–Bonferroni correction, Welch's t-test
  or Mann–Whitney U, and ANOVA or Kruskal–Wallis, each with effect sizes. It also fits OLS regression with HC3 robust
  errors, VIF and Breusch–Pagan checks, and runs trend analysis with CAGR. The engine keeps only the most informative
  tables and figures.
* **Integrity** (`backend/app/originality.py`): every draft is compared against the full source corpus. The check uses
  7-word shingle overlap plus fuzzy sentence similarity. Sentences that are too close to a source are rewritten and
  checked again. Every number in the prose is checked against the evidence, and numbers RAF cannot verify are flagged
  in the Studio.

### Honest limits

* The originality guard **reduces and measures** overlap with *your corpus and retrieved sources*. It is not a
  Turnitin/iThenticate replacement. Run your institution's checker before submission.
* A 12B local model can still misread a source. Check citations and flagged numbers in the Integrity report, and
  follow your target journal's policy on disclosing AI assistance.
* Results come only from data RAF actually analysed. If no suitable data exists, the Results segment becomes a
  clearly labelled evidence synthesis instead of invented statistics.
* `gemma4:12b` has **12 billion parameters** and a **262K-token context window** (it does not have a 12-billion-token
  window). RAF uses 16K tokens per call by default because it builds focused evidence packs for each part of a
  segment. Raise `RAF_NUM_CTX` if you have more memory.

---

## Requirements

* Windows / macOS / Linux, Python 3.12+ (tested on 3.14), Node 20+
* [Ollama](https://ollama.com) with `ollama pull gemma4:12b`
* Optional, for better retrieval: `ollama pull nomic-embed-text`. Without it RAF uses BM25 + TF-IDF.

## Run locally (Windows)

Double-click **`start.bat`**, or run it manually:

```bash
python -m venv .venv
.venv\Scripts\python -m pip install --cache-dir .scratch\pip-cache -r backend\requirements.txt
cd backend && ..\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

```bash
cd frontend && npm.cmd install --cache ..\.scratch\npm-cache && npm.cmd run dev
```

Open http://localhost:5173.

## Run with Docker

```bash
docker compose up --build
```

UI → http://localhost:8080, API → http://localhost:8000. By default the backend uses Ollama running on the host.
To run Ollama in a container instead, use `docker compose --profile ollama up -d` and set `RAF_OLLAMA_URL=http://ollama:11434`.
Docker Desktop keeps its images on C: by default. To keep everything on D:, change *Settings → Resources → Disk image location*.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `RAF_OLLAMA_URL` | `http://localhost:11434` | Ollama server |
| `RAF_MODEL` | `gemma4:12b` | Writing model |
| `RAF_EMBED_MODEL` | `nomic-embed-text` | Optional neural retrieval model |
| `RAF_NUM_CTX` | `16384` | Context tokens per call |
| `RAF_NUM_GPU` | `-1` (auto) | GPU layers to offload. `0` = CPU only. Use a small number (e.g. `12`) on 4 GB GPUs. |
| `RAF_MIN_REFS` / `RAF_MAX_REFS` | `10` / `20` | Reference count limits |
| `RAF_DATA_DIR` | `backend/data` | Projects, uploads, indexes, figures, exports |
| `RAF_CONTACT_EMAIL` | `raf@example.org` | Sent to OpenAlex, Crossref and NCBI so requests use their polite pool |

### Small-GPU note

On a 4 GB laptop GPU, Ollama may fail to load the 7.6 GB model with `CUDA error: shared object initialization failed`
or an out-of-memory error. If that happens:

1. Close memory-heavy apps (the model needs about 8 GB of free RAM).
2. Update the NVIDIA driver and Ollama.
3. Start the API with `set RAF_NUM_GPU=0` (CPU only, slower but stable) or a partial offload such as `set RAF_NUM_GPU=12`.

## API overview

`GET /api/health` · `GET /api/segments` · `POST /api/projects` · `POST /api/projects/{id}/references` ·
`POST /api/projects/{id}/datasets` · `POST /api/projects/{id}/generate` · `GET /api/projects/{id}/events` (SSE) ·
`POST …/segments/{key}/revise | tool | regenerate | approve | restore/{n}` · `PUT …/segments/{key}` ·
`GET /api/projects/{id}/export/{pdf|docx|md}` · `POST /api/projects/{id}/import`

Interactive docs: http://localhost:8000/docs

## Project layout

```
backend/app/
  main.py          FastAPI routes + SSE
  writer.py        corpus pipeline, segment builders, revision engine
  blueprints.py    per-segment writing rules, moves and checklists
  rag.py           hybrid retrieval (embeddings + BM25 + TF-IDF, RRF, MMR)
  research.py      8 online sources with library → REST fallbacks, throttling
  analysis.py      statistics engine, tables, figures
  originality.py   overlap detection, paraphrase enforcement, number verification
  citations.py     APA / Harvard / Chicago / IEEE formatting
  publisher.py     DOCX + PDF + Markdown publishing, document re-import
  ingest.py        PDF / DOCX / Markdown reading, metadata, chunking
frontend/src/      React UI (App, pages/, ui.jsx, styles.css)
```
