# RAF — Research Article Fabricator

RAF is a local, private web app that turns **a title plus 10–20 reference articles** into a structured research
article. It reads your references, researches the topic across scholarly databases, runs real statistics, writes
each segment you select with its own writing blueprint, lets you revise every segment, and publishes the approved
article as **DOCX, PDF or Markdown**.

All text generation runs on your own machine through **Ollama + `gemma4:12b`**, a 12-billion-parameter small language
model (SLM). RAF uses no API keys and has no cloud LLM.

**Jump to:** [Quick start](#quick-start-windows) · [What you need](#what-you-need) ·
[1. Prerequisites](#1-install-the-prerequisites) · [2. Get the code](#2-get-the-code) ·
[3. Ollama and models](#3-install-ollama-and-download-the-models) · [4. Run RAF](#4-run-raf) ·
[5. Check it works](#5-check-that-everything-works) · [Configuration](#configuration-environment-variables) ·
[Troubleshooting](#troubleshooting)

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
* **Agents.** Solo, Duo or Trio model workers. Segments that don't depend on each other are written side by side, and evidence notes are prepared ahead of drafting. Set `OLLAMA_NUM_PARALLEL` to at least the number of agents before running `ollama serve`, otherwise Ollama queues the requests and there is no speed-up (see [Speed up with multiple agents](#speed-up-with-multiple-agents)).
* **Per-segment lengths.** Set a word target for each segment on the Segments page. Segments that haven't started can still be changed during fabrication.
* **Front matter editing.** The Studio has dedicated editors for the Title (with suggestions), Keywords (chips) and Abstract (live word count). You can also add any of these by hand if they weren't generated.
* **Outdated-server warning.** The UI shows a banner when the API process is running older code than the interface. Restart the API after you update RAF.

## Quality, tone & publishing features (v1.3)

* **Hallucination filter** (`backend/app/factcheck.py`). Runs on every drafted segment in four layers:
  1. Cleans up model artefacts: commentary, placeholders, citations to sources that don't exist, repeated and unfinished sentences.
  2. A coherence review repairs paragraphs that are off-topic or don't make sense.
  3. Every claim is checked against the passages of the source it cites; unclear cases go to a judge model.
  4. Unsupported claims are corrected from the evidence or removed.
  Anything still unverified is highlighted in the Studio. A whole-article review then checks that research questions are answered and numbers match across sections.
* **Style engine** (`backend/app/style.py`). Measures sentence variation, repeated openers, stock connectors and formulaic phrases, and gives a naturalness score. It also profiles how your reference articles are written, so drafts follow your field's conventions. **Humanize** rewrites one paragraph at a time and keeps a rewrite only if every citation, number, name, key term and claim is preserved and the style metrics improve. Otherwise the paragraph stays unchanged.
* **Tone meter**. Five tones (Formal academic, Critical-analytical, Argumentative, Explanatory, Reflective/narrative), each with an intensity slider.
* **Length plan**. Short / Medium / Long, pages or words for each segment. Suggestions follow the usual proportions of the selected article type.
* **Publishing templates**. Modern Report, Classic Journal, APA 7 Manuscript, Two-Column Conference and Minimal Monograph, in 7 colour styles, for both PDF and DOCX, with a PDF preview.
* **Developer Tools** (sliders button in the top bar). Choose the model and set temperature, top-p/top-k/min-p, repeat, presence and frequency penalties, seed, context window, output limit, batch size, GPU layers, CPU threads, keep-alive, thinking mode and timeout. Includes presets and a real speed test. Settings are stored in `<data_dir>/llm_settings.json` and apply from the next model call.

A note on AI detectors: these features aim to make articles accurate, well-sourced and well-written. They are not built to beat AI-detection tools, which are unreliable in both directions. Review the text yourself and follow your venue's rules on disclosing AI assistance.

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
* RAF does not run OCR. A scanned PDF with no text layer can't be read; use a text-based PDF or run OCR on it first.
* `gemma4:12b` has **12 billion parameters** and a **262K-token context window** (it does not have a 12-billion-token
  window). RAF uses 16K tokens per call by default because it builds focused evidence packs for each part of a
  segment. Raise `RAF_NUM_CTX` if you have more memory.

---

# Getting started

## Quick start (Windows)

Once the four programs from [step 1](#1-install-the-prerequisites) are installed (Git, Python 3.12+, Node.js 20+, Ollama):

```bash
# 1. Get the code
git clone https://github.com/pingakshgaur/Research_Article_Fabricator-RAF.git
cd Research_Article_Fabricator-RAF

# 2. Download the models (about 8 GB in total, one-time)
ollama pull gemma4:12b
ollama pull nomic-embed-text

# 3. Start RAF (creates the virtual environment and installs everything on first run)
start.bat            # in PowerShell use: .\start.bat
```

Then open **http://localhost:5173**. On macOS or Linux, follow [Option B](#option-b--manual-start-windows-macos-linux) in step 4.

---

## What you need

| | Requirement |
|---|---|
| **Operating system** | Windows 10/11, macOS or Linux |
| **Memory** | The model needs about **8 GB of free RAM** while it runs. 16 GB of total RAM is a comfortable target. |
| **Disk space** | About **10 GB free**: the `gemma4:12b` download is 7.6 GB, and the Python packages take roughly 1 GB. |
| **GPU** | Optional. An NVIDIA GPU speeds things up a lot. CPU-only works, just more slowly (see [Small-GPU note](#small-gpu-note)). |
| **Internet** | Needed for the one-time installs and model downloads, and for the online research step. Writing itself runs offline. |
| **Accounts / API keys** | None. RAF has no cloud LLM and needs no `.env` file. |

| Software | Version | Why it is needed |
|---|---|---|
| [Git](https://git-scm.com/downloads) | any recent | Clone the repository (or download the ZIP instead) |
| [Python](https://www.python.org/downloads/) | **3.12 or newer** (tested on 3.14) | Runs the API server and the writing pipeline |
| [Node.js](https://nodejs.org) | **20 or newer** (LTS), includes `npm` | Builds and serves the web interface |
| [Ollama](https://ollama.com/download) | current (Gemma 4 models need a recent release; update if an old copy can't pull `gemma4:12b`) | Runs the language models locally |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | current | Only for the optional [Docker route](#option-c--docker) |

| Model (pulled with Ollama) | Required? | What it does | Download |
|---|---|---|---|
| `gemma4:12b` | **Yes** | The writing model. It plans searches, reads reference metadata, drafts, reviews and fact-checks every segment. | 7.6 GB |
| `nomic-embed-text` | Optional | Neural embeddings for better retrieval. Without it RAF falls back to BM25 + TF-IDF. | small |

## 1. Install the prerequisites

**Windows.** Download and run each installer from the links above. Two details matter:

* **Python:** on the first installer screen, tick **"Add python.exe to PATH"** before clicking *Install Now*.
* **Git, Node.js, Ollama:** the default options are fine.

If you prefer the command line, `winget` (built into Windows 10/11) can install all four:

```bash
winget install --id Git.Git -e
winget install --id Python.Python.3.12 -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id Ollama.Ollama -e
```

**macOS** (with [Homebrew](https://brew.sh)):

```bash
brew install git python@3.12 node ollama
```

**Linux** (Debian/Ubuntu shown; use your distribution's package manager otherwise):

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip nodejs npm
curl -fsSL https://ollama.com/install.sh | sh
```

Make sure the versions you get meet the table above. If your distribution ships an older Node.js, install the LTS
build from [nodejs.org](https://nodejs.org).

**Verify.** Close every terminal, open a **new** one (the installers only update the PATH for new windows) and run:

```bash
git --version
python --version      # 3.12 or newer. On macOS/Linux use: python3 --version
node --version        # v20 or newer
npm --version
ollama --version
```

Every command must print a version number. If one says "not recognized", see [Troubleshooting](#troubleshooting).

## 2. Get the code

**With Git (recommended, because it makes updating easy):**

```bash
git clone https://github.com/pingakshgaur/Research_Article_Fabricator-RAF.git
cd Research_Article_Fabricator-RAF
```

Choose a short, simple folder for it, such as `C:\RAF` or `D:\RAF`. RAF keeps its virtual environment, caches and data
inside this folder.

**Without Git:** on the repository page choose **Code → Download ZIP**, unzip it, and open a terminal in the unzipped
folder. You will not be able to `git pull` updates this way.

## 3. Install Ollama and download the models

1. **Start Ollama.** On Windows and macOS the installer starts it for you and leaves an icon in the system tray or menu
   bar. On Linux the install script sets it up as a background service. If it is not running, start it manually in a
   separate terminal with `ollama serve` and leave that window open.
2. **Download the models** (one-time, about 8 GB):

   ```bash
   ollama pull gemma4:12b
   ollama pull nomic-embed-text
   ```

3. **Check** that both are installed:

   ```bash
   ollama list
   ```

   The list should show `gemma4:12b` and `nomic-embed-text`. Ollama answers on `http://localhost:11434`.

## 4. Run RAF

Choose **one** of the three options.

### Option A — Windows launcher

Double-click **`start.bat`** in the project folder, or run it from a terminal opened there.

On the first run it:

1. creates a Python virtual environment in `.venv`,
2. installs the backend packages from `backend\requirements.txt`,
3. installs the frontend packages into `frontend\node_modules`,
4. opens two windows: **RAF API** (port 8000) and **RAF UI** (port 5173).

The first run takes several minutes. Later runs are much quicker. Everything (virtual environment, pip and npm caches
in `.scratch`, and your data) stays inside the project folder, so nothing is spread across other drives. Keep both
windows open while you use RAF; closing a window stops that part.

Open **http://localhost:5173**.

### Option B — Manual start (Windows, macOS, Linux)

Use two terminals, both opened in the project folder.

**Windows** (Command Prompt or PowerShell):

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements.txt
```

Terminal 1, the API:

```bash
cd backend
..\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Terminal 2, the web interface:

```bash
cd frontend
npm.cmd install
npm.cmd run dev
```

(`npm.cmd` avoids the PowerShell "running scripts is disabled" error that `npm` can trigger. In Command Prompt plain
`npm` works too.)

**macOS / Linux:**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
```

Terminal 1, the API:

```bash
cd backend
../.venv/bin/python -m uvicorn app.main:app --port 8000
```

Terminal 2, the web interface:

```bash
cd frontend
npm install
npm run dev
```

The commands call the virtual environment's Python directly, so you never need to "activate" it. Open
**http://localhost:5173**. The dev server forwards `/api` requests to the API on port 8000.

### Option C — Docker

Install Docker Desktop (or Docker Engine with the Compose plugin on Linux), start it, then from the project folder:

```bash
docker compose up --build
```

UI → http://localhost:8080, API → http://localhost:8000. By default the backend uses **Ollama running on the host**,
so complete [step 3](#3-install-ollama-and-download-the-models) first. Your projects are stored in `backend/data`.

To run Ollama in a container instead, use `docker compose --profile ollama up -d`, set
`RAF_OLLAMA_URL=http://ollama:11434`, and pull the model inside the container with
`docker compose exec ollama ollama pull gemma4:12b`. The bundled Ollama container has no GPU passthrough configured, so
it runs on the CPU unless you add that to `docker-compose.yml`.

On Linux, if the backend container cannot reach Ollama on the host, start Ollama with `OLLAMA_HOST=0.0.0.0`.

Docker Desktop keeps its images on C: by default. To keep everything on D:, change *Settings → Resources → Disk image
location*.

## 5. Check that everything works

1. Open **http://localhost:8000/api/health** in a browser. A healthy setup shows `"status":"ok"`, `"ollama":true` and
   `"model_available":true`. If `ollama` is `false`, Ollama is not running. If `model_available` is `false`, run
   `ollama pull gemma4:12b`.
2. Open **http://localhost:5173** (or **8080** with Docker). The RAF home page should load.
3. Interactive API documentation is at **http://localhost:8000/docs**.
4. Start a project: enter a title, upload 10–20 references, pick your segments and press *Fabricate*.

## Speed up with multiple agents

RAF can run Solo, Duo or Trio model workers in parallel. For Duo or Trio to actually help, tell Ollama to serve that
many requests at once **before** it starts:

```bash
# Windows: set it once, then quit Ollama from the tray icon and start it again
setx OLLAMA_NUM_PARALLEL 3

# macOS / Linux: stop the background service first, then
OLLAMA_NUM_PARALLEL=3 ollama serve
```

More agents use more memory. If your machine has little RAM, stay on Solo.

## Use a different model

RAF reads the model name from `RAF_MODEL` (default `gemma4:12b`), and you can also switch it in **Developer Tools**
inside the app. Pull the model first, then start the API with the new name (see
[Configuration](#configuration-environment-variables) for how to set variables on each system):

```bash
ollama pull <model-name>
# then start the API with RAF_MODEL=<model-name>
```

Check the download size on [ollama.com/library/gemma4](https://ollama.com/library/gemma4) before pulling, because a
smaller-sounding tag is not always a smaller download (for example `gemma4:e4b` is about 9.6 GB, larger than
`gemma4:12b` at 7.6 GB). RAF is developed and tested with `gemma4:12b`, so a different or smaller model may write
noticeably weaker text. Check its output carefully.

## Update, stop and back up

* **Update:** run `git pull` in the project folder, then restart the API. On Windows `start.bat` reinstalls the Python
  packages automatically, but if `frontend\package.json` changed, also run `npm.cmd install` inside `frontend`. On
  other systems re-run the `pip install` and `npm install` commands from Option B.
* **Stop:** press `Ctrl+C` in (or close) the API and UI windows. Ollama keeps the model in memory for a while after the
  last request; free the memory at once with `ollama stop gemma4:12b`.
* **Your data:** projects, uploads, indexes, figures and exports live in `backend/data` (or the folder in
  `RAF_DATA_DIR`). Copy that folder to back it up or to move your projects to another computer.
* **Privacy:** the writing model runs entirely on your machine. The online research step sends search queries to public
  scholarly databases; turn it off with the **Web research** option on the Segments page before you start a run.
* **Uninstall:** delete the project folder, then remove the models with `ollama rm gemma4:12b` and
  `ollama rm nomic-embed-text`.

---

## Configuration (environment variables)

Set variables **before** starting the API, in the same terminal:

| System | Command |
|---|---|
| Windows Command Prompt | `set RAF_NUM_GPU=0` |
| Windows PowerShell | `$env:RAF_NUM_GPU = "0"` |
| macOS / Linux | `export RAF_NUM_GPU=0` |

On Windows you can set a variable and then run `start.bat` from the same Command Prompt; the API window it opens
inherits the variable. With Docker, `docker-compose.yml` passes only `RAF_OLLAMA_URL`, `RAF_MODEL`, `RAF_NUM_CTX` and
`RAF_NUM_GPU` through (from your shell or a `.env` file next to it). Add any other variable under `environment:` for the
`backend` service.

| Variable | Default | Purpose |
|---|---|---|
| `RAF_OLLAMA_URL` | `http://localhost:11434` | Ollama server |
| `RAF_MODEL` | `gemma4:12b` | Writing model |
| `RAF_EMBED_MODEL` | `nomic-embed-text` | Optional neural retrieval model |
| `RAF_NUM_CTX` | `16384` | Context tokens per call |
| `RAF_NUM_GPU` | `-1` (auto) | GPU layers to offload. `0` = CPU only. Use a small number (e.g. `12`) on 4 GB GPUs. |
| `RAF_LLM_TIMEOUT` | `900` | Seconds to wait for one model response |
| `RAF_OLLAMA_WAIT` | `600` | Seconds to wait for Ollama to come back after a crash or restart |
| `RAF_MIN_REFS` / `RAF_MAX_REFS` | `10` / `20` | Reference count limits |
| `RAF_RESULTS_PER_SOURCE` | `5` | Results fetched from each research source |
| `RAF_HTTP_TIMEOUT` | `25` | Seconds before an online research request times out |
| `RAF_MAX_NGRAM_OVERLAP` | `0.04` | Originality guard: maximum 7-word shingle overlap with a source |
| `RAF_SENTENCE_SIM_LIMIT` | `82` | Originality guard: fuzzy sentence-similarity limit |
| `RAF_DATA_DIR` | `backend/data` | Projects, uploads, indexes, figures, exports |
| `RAF_CONTACT_EMAIL` | `raf@example.org` | Sent to OpenAlex, Crossref and NCBI so requests use their polite pool. Set it to your own address. |
| `RAF_CORS` | `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:8080` | Browser origins allowed to call the API (comma-separated) |
| `RAF_API` | `http://localhost:8000` | Read by the web UI dev server: where to forward `/api` requests |
| `OLLAMA_NUM_PARALLEL` | Ollama default | Read by Ollama itself, not RAF. Set to at least the number of agents. |

### Small-GPU note

On a 4 GB laptop GPU, Ollama may fail to load the 7.6 GB model with `CUDA error: shared object initialization failed`
or an out-of-memory error. If that happens:

1. Close memory-heavy apps (the model needs about 8 GB of free RAM).
2. Update the NVIDIA driver and Ollama.
3. Start the API with `set RAF_NUM_GPU=0` (CPU only, slower but stable) or a partial offload such as `set RAF_NUM_GPU=12`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `python` or `git` "is not recognized" | Open a **new** terminal after installing. For Python, re-run the installer and tick *Add python.exe to PATH*. |
| `python` opens the Microsoft Store | Turn off the Python entries under *Settings → Apps → Advanced app settings → App execution aliases*, then open a new terminal. |
| `npm.ps1 cannot be loaded because running scripts is disabled` | Use `npm.cmd` instead of `npm`, or run the command in Command Prompt. |
| A package fails to install with a build error | Use Python 3.12, the version the Docker image is built on. |
| The UI reports that Ollama is not reachable, or the API returns 503 | Start Ollama (tray icon, or `ollama serve`) and check http://localhost:11434 answers. |
| `Model gemma4:12b is not installed` | Run `ollama pull gemma4:12b`. |
| `ollama pull gemma4:12b` fails and says the model needs a newer version of Ollama | Install the latest Ollama from https://ollama.com/download, restart it, and pull again. |
| Very slow generation | Expected on CPU-only machines. Use Solo agent mode, keep `RAF_NUM_CTX` at 16384 or lower, close other apps, or try a smaller model. |
| `CUDA error` or out-of-memory when the model loads | See the [Small-GPU note](#small-gpu-note). |
| Port 8000 or 5173 is already in use | Close the other program. Or run the API on another port, e.g. `--port 8001`, set `RAF_API=http://localhost:8001`, and start the UI with `npm run dev -- --port 5180`. |
| A reference PDF is rejected with "no extractable text" | It is probably a scan. RAF does not OCR; use a text-based PDF or run OCR on it first. |
| Banner about an outdated server | Restart the API window so it picks up the new code. |
| Online research returns nothing | Check your internet connection or proxy. RAF carries on without research; you can also switch off **Web research** on the Segments page. |
| Docker backend cannot reach Ollama | Make sure Ollama is running on the host. On Linux start it with `OLLAMA_HOST=0.0.0.0`. |

## API overview

`GET /api/health` · `GET /api/segments` · `POST /api/projects` · `POST /api/projects/{id}/references` ·
`POST /api/projects/{id}/datasets` · `POST /api/projects/{id}/generate` · `GET /api/projects/{id}/events` (SSE) ·
`POST …/segments/{key}/revise | tool | regenerate | approve | restore/{n}` · `PUT …/segments/{key}` ·
`GET /api/projects/{id}/export/{pdf|docx|md}` · `POST /api/projects/{id}/import`

Interactive docs: http://localhost:8000/docs

## Project layout

```
start.bat            Windows launcher: sets up and starts the API and the UI
docker-compose.yml   Docker setup (backend, frontend, optional Ollama)
backend/
  requirements.txt   Python dependencies
  Dockerfile
  app/
    main.py          FastAPI routes + SSE
    writer.py        corpus pipeline, segment builders, revision engine
    blueprints.py    per-segment writing rules, moves and checklists
    rag.py           hybrid retrieval (embeddings + BM25 + TF-IDF, RRF, MMR)
    research.py      8 online sources with library → REST fallbacks, throttling
    analysis.py      statistics engine, tables, figures
    originality.py   overlap detection, paraphrase enforcement, number verification
    factcheck.py     hallucination filter
    style.py         style engine and naturalness score
    citations.py     APA / Harvard / Chicago / IEEE formatting
    publisher.py     DOCX + PDF + Markdown publishing, document re-import
    ingest.py        PDF / DOCX / Markdown reading, metadata, chunking
    llm.py           Ollama client, agent slots, out-of-memory fallbacks
    llm_settings.py  Developer Tools settings
    checkpoints.py   save and resume
    config.py        environment-variable settings
frontend/
  package.json       Node dependencies (React + Vite)
  Dockerfile, nginx.conf
  src/               React UI (App, pages/, ui.jsx, styles.css)
```
