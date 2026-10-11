# RAF Roadmap — versions 1.4.1 to 2.0

This plan takes the sixteen requested features and improvements and places each one in a release. It was written
against the code as it stood at **version 1.4.0**, so every item names the files it touches and the reason it sits
where it does.

Sizes are relative: **S** is a few focused changes, **M** is a new module or page, **L** changes how several modules
work together. No dates are given, because speed depends on how much time goes into each release.

**Jump to:** [The plan at a glance](#the-plan-at-a-glance) · [Where each request went](#where-each-request-went) ·
[Why this order](#why-this-order) · [1.4.1](#version-141--fix-up) · [1.5](#version-15--project-memory) ·
[1.6](#version-16--segment-freedom) · [1.7](#version-17--publishing) · [1.8](#version-18--open-research-and-the-window) ·
[1.9](#version-19--quality) · [2.0](#version-20--the-suite) · [Rules for every release](#rules-for-every-release) ·
[Decisions that are yours](#decisions-that-are-yours)

---

## The plan at a glance

| Version | Theme | What ships | Size |
|---|---|---|---|
| **1.4.1** ✅ released | Fix-up | DOCX Contents fix, Resume fix, small corrections | S |
| **1.5** ✅ released | Project memory | Library page, Project History, Article Revisions; added on request: Settings page, four new themes, admin lock | M + M + L + M |
| **1.6** ✅ released | Segment freedom | Rename segments, custom segments, add / remove / reorder segments later; added on request: Custom theme from one colour, resizable and tidied sidebar | S + L + M + M |
| **1.7** ✅ released | Publishing | LaTeX export, Format an existing article | M + L |
| **1.8** ✅ released (1.8.1 adds cloud models) | Open research and the Window | Articles without reference files, live view of the writing; add-on: cloud models through your own API keys | L + L |
| **1.9** | Quality | Article level Q1–Q4, Humanize 2 (engine delivered early in 1.8.2), Integrity Report image | M + L + M |
| **2.0** | The suite | New Hub home page, TextAI Tools, Data Analyzer | S + L + L |

## Where each request went

| # | Request | Version |
|---|---|---|
| 1 | Article Revisions | 1.5 |
| 2 | A separate page for the history of all article projects | 1.5 |
| 3 | Create an article without reference articles | 1.8 |
| 4 | Export the final article in LaTeX | 1.7 |
| 5 | Better Humanize layers | 1.9 |
| 6 | DOCX exporter does not write the Contents section properly | 1.4.1 |
| 7 | Better Fabrication page: watch the text being written, like looking through a window | 1.8 |
| 8 | Home page shows three products; RAF's own menu opens after choosing RAF | 2.0 |
| 9 | Two new products: TextAI Tools and Data Analyzer | 2.0 |
| 10 | One-click image export of the plagiarism report and AI-detection meter | 1.9 |
| 11 | Edit the title of the default segments | 1.6 |
| 12 | Add custom segments | 1.6 |
| 13 | Add or remove segments from the final document later | 1.6 |
| 14 | A history of each project: every stage, change and addition | 1.5 |
| 15 | Apply formatting to an already existing article | 1.7 |
| 16 | Choose the article level (Q1–Q4) at creation | 1.9 |

## Why this order

1. **Bugs first.** The DOCX Contents problem affects every article published today, so it ships as a patch and does
   not wait for a feature release.
2. **History before everything that should be recorded.** Once the History log exists (1.5), every later feature
   writes into it from its first day: renamed segments, LaTeX exports, revision rounds.
3. **Structure before new outputs.** Custom segments (1.6) change what an article *is*. LaTeX export and the
   formatter (1.7) are built afterwards, so they handle any structure from the start and are not reworked.
4. **Streaming before the suite.** The live Window (1.8) needs the model's output to arrive word by word. TextAI Tools
   (2.0) uses the same plumbing to show results as they are written.
5. **Humanize 2 before TextAI Tools.** Humanize is the headline tool of TextAI Tools, so the better engine (1.9) must
   exist first. The Integrity Report image uses the same new measurements, so it ships with it.
6. **The Hub arrives with the products it links to.** A home page with two "coming soon" cards is a worse home page
   than today's. From 1.5 on, RAF's own addresses are written as `#/raf/…`, so the Hub can take over `#/` in 2.0
   without breaking any link.

---

## Version 1.4.1 — Fix-up

**Status: done.** Checked by `.scratch/v141_test.py` and by opening the generated files in Word.

**Goal:** published files are correct, and resuming a run keeps your choices.

### DOCX Contents fix (request 6)

* **What is wrong today.** `to_docx` in `backend/app/publisher.py` inserts a Word "TOC field" with the placeholder
  result `1` and a note asking the reader to right-click and update it. Word only builds the list when the field is
  updated, and LibreOffice, Google Docs and file previews never do. So the Contents page shows a stray "1" instead of
  the headings. The PDF builds a real list (ReportLab `TableOfContents`). The Markdown export has no Contents list at
  all.
* **The fix.**
  1. Give every level-1 and level-2 heading a bookmark.
  2. Write the Contents entries into the file as real text, each one a link to its bookmark, inside the TOC field. The
     list is then visible in every program, even when nothing updates it.
  3. Switch on "update fields on open" in the document settings, so Word rebuilds the list with page numbers when
     the file is opened. (As built: the stored entries carry no page numbers of their own, because RAF cannot know
     where Word will break pages, and a wrong number is worse than none.)
  4. Remove the "(Right-click → Update Field…)" note.
  5. Add a linked Contents list to the Markdown export, which had none.
  6. Teach the importer that a heading can now appear twice (once in the Contents list, once above its section), so
     re-importing a published file still recovers every section.
* **Done when:** the same article opened in Word, LibreOffice and Google Docs shows every section and appendix
  heading under Contents, in the same order as the PDF.

### Resume fix

"Resume from checkpoint" in `frontend/src/pages/Processing.jsx` does not send the hallucination-filter and style-pass
choices, so `generate_article` in `backend/app/writer.py` switches both back on. Resume will send the options the run
started with, and the backend will fall back to the stored options when a resume request leaves them out.

### Small corrections

* The "model is not installed" message in `main.py` names the model from the environment variable, not the one chosen
  in Developer Tools.
* `RAF_WEB_RESEARCH` in `config.py` was read by nothing. It now sets whether the Online research switch starts on for
  new projects.
* `originality.destyle` replaces "Moreover," with "In addition," — which `style.py` then counts as a stock connector.
  Those connectors are now dropped instead of swapped.

### Sequence

1. DOCX Contents → 2. Markdown Contents → 3. Resume fix → 4. small corrections → 5. publish one test article in all
   five templates and open each DOCX in three programs.

---

## Version 1.5 — Project memory

**Status: done.** Covered by the automated tests in `backend/tests` and checked in the browser, including one revision
round run with the real model.

**Added to 1.5 on request (not in the original plan):** a **Settings** page behind a gear button, replacing the
Developer Tools button. It holds the theme picker with four new themes (Rosewood, Aurora, Solar, Ember, each in dark
and light), the defaults new articles start with, the language-model controls that used to be Developer Tools, and an
optional **admin lock** (a passcode needed to change settings). Version 2.0's Hub will reuse this page for the whole
suite.

Built differently from the plan in four places:

* The Library is kept fast by remembering each project's summary in memory until its file changes, not by a
  `projects/index.json` file. Same effect, and no second file that could disagree with the first.
* A copy made with **Duplicate** inherits the original's history and then continues its own.
* In a revision round, all accepted points for one segment go to the model as a single revision, so two comments on
  the same segment cannot undo each other. Segments are revised side by side, as many at once as the project's
  agent setting allows.
* The comments are still split into points when Ollama is not running (by paragraph and numbering), so a round can
  be prepared offline. Applying it needs the model.

**Goal:** RAF remembers what happened to an article, lets you find every project, and lets you go back to any earlier
state of the whole article.

### Groundwork (done first, invisible to the user)

* **Automated tests.** Add `pytest` with a stand-in model server, so tests run in seconds without Ollama. The scratch
  scripts in `.scratch/` are the starting material. Every later release adds tests for what it ships.
* **Split `main.py` into routers** (system, projects, studio, publishing, settings). It is 457 lines now and every
  release below adds routes.
* **`schema_version` in `project.json`**, with a small upgrade step on load. Releases 1.5–1.9 all add fields.
* **New address scheme in the interface:** `#/raf`, `#/raf/library`, `#/raf/new`, `#/raf/p/{id}/{view}`. Old
  addresses (`#/new`, `#/p/{id}`) redirect.

### Project History (request 14) — M

* **What you get.** A **History** tab in every project: a timeline of everything that happened, newest first. Each
  line says when, who (you or RAF), what, and to which segment. Examples: "Project created", "3 references added",
  "Fabrication started · Thorough · 2 agents", "Introduction drafted (812 words)", "You edited the Abstract (+14
  words)", "Polish applied to Discussion", "Methodology approved", "Published as PDF · Classic Journal · Emerald".
  Filter by segment or by kind of event, and export the timeline as CSV or Markdown.
* **How.** A new `backend/app/history.py` writes one line per event to an append-only file,
  `projects/<id>/history.jsonl`. It never trims, unlike `project.log`, which keeps only the last 400 lines and stays
  as the Fabrication console. Calls are added in the route handlers and in `writer.finalize`, `manual_edit`,
  `humanize_segment` and the export and import routes. Route: `GET /api/projects/{id}/history`.
* **Extra:** an **AI-use statement** button that drafts the disclosure paragraph many journals ask for, from the
  recorded facts (which segments RAF drafted, which tools were used, how much you edited by hand).

### Library page (request 2) — M

* **What you get.** A page of its own, **Library**, listing every project with search, filters by stage, and sorting
  by last activity, title or progress. Each row shows segments approved, word count, time spent and last activity.
  Actions: open, rename, duplicate, archive, delete, and **back up / restore** a project as one `.zip` file. The home
  page keeps only the five most recent projects and a "See all" link.
* **How.** New `frontend/src/pages/Library.jsx`. `GET /api/projects` gains the extra fields. `store.list_all` loads
  every `project.json` in full today; a small `projects/index.json` cache keeps the page fast with many projects. New
  routes: duplicate, archive, export-zip, import-zip.

### Article Revisions (request 1) — L

I have read this as two connected things: saved states of the **whole article**, and a guided **revision round** when
a supervisor or reviewer sends comments. Today RAF only keeps versions per segment.

* **Snapshots.** Save the whole article as a named revision ("First draft", "Submitted", "R1"). RAF also saves one
  automatically at each publish, before each new fabrication run, and before each import. Stored in
  `projects/<id>/revisions/`.
* **Compare.** Pick any two revisions and see the differences segment by segment, with words added and removed
  highlighted, plus a summary (words, citations, integrity scores then and now).
* **Restore.** Bring back a whole revision or a single segment from it. Restoring never deletes anything; it creates a
  new state.
* **Revision round.** Paste the comments you received. RAF splits them into separate points, links each point to the
  segment it concerns, and proposes a revision instruction for each. You accept, edit or skip each one. RAF then
  applies them through the existing `revise_segment` jobs, up to three segments at a time.
* **Response letter.** When the round is done, RAF drafts a point-by-point "Response to reviewers" from what actually
  changed, and exports a **changes-highlighted** PDF or DOCX (insertions and deletions in colour).
* **How.** New `backend/app/revisions.py`; a `Revisions.jsx` page; the comment-splitting step uses `llm.generate_json`
  the way `factcheck.review_article` already does.

### Sequence

1. Groundwork (tests, routers, schema version, addresses).
2. History log and its hooks.
3. History tab.
4. Library page with backup and restore.
5. Snapshots, compare and restore.
6. Revision round and response letter.
7. AI-use statement.

---

## Version 1.6 — Segment freedom

**Status: done.** Covered by `backend/tests/test_structure.py` and checked in the browser (structure drawer, Studio,
Publish, Segments and Fabrication pages).

**Added to 1.6 on request (not in the original plan):**

* **Custom theme.** A round colour button in Settings → Appearance opens a picker (system dialog, R / G / B sliders,
  hex). From the one colour picked, RAF works out every shade, the text colour on buttons, and a contrasting colour,
  for dark and light mode, with a live preview. A test runs the engine over 2,386 colours and checks every text pair.
* **Resizable sidebar.** Drag its right edge (or use the arrow keys); double-click resets. Below 132 px it shows
  numbers and icons only. Remembered per browser.
* **Tidier sidebar.** The captions under each button, the group titles and the footer sentence are gone; bold rules
  separate the groups; Library moved to the top. The whole sidebar now fits without scrolling. Captions remain as
  hover tooltips.

**Changes to the look made in this version** (as invited): only the sidebar, described above, and the new Structure
drawer and colour picker, which follow the existing card and drawer style. No other page was restyled.

**Built differently from the plan:**

* Reordering works by dragging *and* by up / down buttons, so it is usable from the keyboard.
* The reference list is rebuilt automatically, except when you edited it by hand; then it is yours until you press
  Regenerate. Without this exception, every automatic rebuild would have thrown away hand corrections.
* "Leave out" and "delete" are separate: built-in segments can only be left out, segments you added can also be
  deleted.
* A fabrication run never touches a segment you write yourself.

**Not done in 1.6:**

* The purpose and parts of an added segment cannot be edited in the interface after it is created (the API route
  exists; for now, delete the segment and add it again).
* Title, Abstract and Keywords cannot be renamed or moved: the templates typeset them as the title block.
* Writing an added segment was tested with the stand-in model only, not with a real run.

**Goal:** the article's structure belongs to the author. RAF's twelve segments become a starting point, not a limit.

### Groundwork: one structure, read from one place

The twelve segments are fixed in many places today: the global `BLUEPRINTS` dictionary, `EVIDENCE_SEGMENTS` in
`writer.py`, the `ORDER` lists in `Studio.jsx` and `Publish.jsx`, `BODY_ORDER` in `TemplatePreview.jsx`, `LENGTHABLE`
in `Processing.jsx`, and the cost table in `estimate.py`. This release replaces all of them with one per-project
structure:

* `Project.structure`: an ordered list of entries `{key, title, kind, included, position}`.
* `blueprint_for(project, key)`: returns the built-in blueprint or the project's custom one. Every `BLUEPRINTS[key]`
  lookup goes through it.
* The interface reads order, titles and capabilities from the project, not from its own lists.

### Rename segments (request 11) — S

Click a segment title in the Segments page, the Studio or the Publish checklist and type a new one ("Review of
Literature" → "Theoretical Background"). The new title is used in the Studio, in every export and in the Contents
list. The importer matches headings against your titles as well as the default ones. RAF's writing rules for the
segment stay the same; only the name changes.

### Custom segments (request 12) — L

* **What you get.** **Add a segment** on the Segments page. You give it a title, say in a sentence or two what it
  should do, choose where it goes, and set its length. Two kinds:
  * **Written by RAF.** RAF proposes the parts the segment should contain (its "moves"), which you can edit, and then
    writes it with the same pipeline as every other body segment: evidence, notes, draft, peer review, filters.
    Examples: Theoretical Framework, Hypothesis Development, Case Description, Policy Context.
  * **Written by you.** A plain segment RAF does not touch, with a ready-made starter text. Examples:
    Acknowledgements, Funding, Conflict of Interest, Data Availability, Author Contributions, AI-use statement.
* **A small gallery** of common custom segments, so the usual ones are one click.
* **How.** `Project.custom_segments` holds each one's blueprint. `build_generic` in `writer.py` already writes any
  blueprint that has moves, so custom segments reuse it. The proposal of moves is one `generate_json` call.
  `estimate.py` uses its existing default cost for unknown segments. Dependencies are set from position: a custom
  segment may read the segments placed before it.

### Add, remove and reorder later (request 13) — M

* **Include / exclude.** A switch on every segment in the Publish checklist and the Studio list. An excluded segment
  stays in the project but is left out of the document, and it no longer blocks publishing when it is not approved.
* **Add after fabrication.** "Add a segment" also works in the Studio. It writes just that segment as a background
  job. (Today `generate` would overwrite the list of selected segments.)
* **Reorder.** Drag segments into a new order. Section numbers follow automatically, because `publisher.assemble`
  already numbers sections as it goes.
* **References stay correct.** The References segment is a fixed text written at the end of a run today, so it can go
  stale when you add, remove or edit citing text. From this release it is rebuilt at publish time and whenever a body
  segment changes.

### Sequence

1. Structure model and `blueprint_for`, with tests proving the twelve built-in segments behave exactly as before.
2. Interface reads the structure from the project.
3. Rename.
4. Include / exclude and reorder.
5. References rebuilt automatically.
6. Custom segments written by you.
7. Custom segments written by RAF, with proposed moves.
8. Add a segment after fabrication.
9. Gallery.

---

## Version 1.7 — Publishing

**Status: done.** Covered by `backend/tests/test_latex_format.py` and checked in the browser.

**Fixed along the way:**

* The Custom-theme colour picker opened underneath the cards of the Settings page. It is now drawn above everything.
* RAF's punctuation clean-up removed the space in statistics, turning "p = .05" into "p =.05" in exports and in stored
  drafts. A space before punctuation is now only removed when no digit follows. Text already stored that way is not
  corrected automatically.
* Superscript was lost in Word exports of formatted articles (found by the new tests).

**Built differently from the plan:**

* **RAF does not compile the LaTeX.** The plan said it would when a LaTeX program is installed. None is installed
  on the development machine, so that path could not be tested and was left out. The generated source is checked by
  tests for balanced braces and environments, escaped special characters, a `.bib` entry for every citation and a
  file for every figure. **It has not been built with a real LaTeX engine**; the first compile on Overleaf is the
  real test.
* Long tables are continued in a second float after 30 rows; `longtable` does not work in two-column layouts.
* A formatted article opens on the Publish page with its outline, not on a separate three-step page; the existing
  Structure drawer does the renaming, reordering and leaving out.

**Not done in 1.7:**

* LaTeX files cannot be brought in for formatting (Word, Markdown, plain text and PDF can).
* Sections of a formatted article cannot be merged or split in the interface.
* Converting in-text citations between author–date and numbered styles (as planned, not attempted).
* The Crossref lookups (reference restyle, BibTeX completion) were tested with stand-in replies, not against the
  live service.

**Goal:** RAF's output goes wherever an article needs to go, and RAF's typesetting works on articles it did not write.

### LaTeX export (request 4) — M

* **What you get.** A fourth format on the Publish page. It downloads a `.zip` containing `main.tex`,
  `references.bib`, a `figures/` folder and a short read-me. It opens directly in Overleaf.
* **Templates.** Each of the five templates maps to a LaTeX setup: Modern Report and Minimal Monograph use the
  standard `article` class with a RAF preamble, Classic Journal a serif `article` setup, APA 7 Manuscript the `apa7`
  class, and Two-Column Conference `IEEEtran`. The colour style becomes the accent colour.
* **Real citations.** In the Word and PDF exports citations are converted to plain text. In LaTeX they become
  `\cite{…}` commands with a proper BibTeX file, so the journal's own style can restyle them. Citation style maps to
  `biblatex`: APA, author-year (Harvard), Chicago author-date, IEEE.
* **Also:** download the reference list alone as BibTeX or RIS, for Zotero, Mendeley or EndNote.
* **How.** New `to_latex` in `publisher.py`, working from the same `Article` model as the other three exporters, plus
  a variant of `assemble` that keeps citation markers. Special characters are escaped; tables become `booktabs`
  tables. RAF stores only title, authors, year, venue and DOI for a source, so entries with a DOI are completed from
  Crossref (volume, issue, pages) when online research is on. If a LaTeX program is installed on the machine, RAF also
  compiles the PDF as a check; if not, it just delivers the `.zip`.

### Format an existing article (request 15) — L

* **What you get.** A new entry in RAF's menu: **Format an existing article**. Upload a finished article, check the
  outline RAF detected, pick a template, colour style and output format, and download. RAF changes the layout. It
  does not rewrite your text.
* **Steps for the user.**
  1. Upload DOCX, Markdown or LaTeX. PDF is accepted, with a warning that structure and tables may be lost.
  2. Review the detected outline: title, authors, abstract, keywords, sections, references. Rename, merge, split or
     reorder.
  3. Choose template, colour style and format (PDF, DOCX, LaTeX, Markdown).
  4. Optional checks, on request only: a style report, and a reference check that lists works cited but missing from
     the reference list, and listed but never cited.
* **How.**
  * A general outline detector. Today `import_document` only recognises headings that match RAF's own segment titles;
    the new one accepts any headings (Word heading styles first, then numbering and typography).
  * Tables and images are carried over from DOCX.
  * Bold, italic, superscript and subscript survive. RAF's own text is plain today, so the `Block` model in
    `publisher.py` gains light inline formatting.
  * A project created this way has `mode = "format"` and skips References, Segments and Fabrication.
* **Reference restyling, marked experimental.** Reformatting the reference list into another citation style means
  recognising each entry. RAF looks each one up in Crossref and reformats the ones it can identify with
  `citations.format_reference`, and leaves the rest unchanged and flagged. Converting in-text citations between
  author-year and numbered styles is not attempted in this release.

### Sequence

1. `assemble` variant that keeps citation markers; BibTeX writer.
2. `to_latex` for the `article`-based templates, then `apa7`, then `IEEEtran`.
3. BibTeX / RIS download.
4. Outline detector and inline formatting.
5. Format-only project mode and its three-step page.
6. Tables and images from DOCX.
7. Optional checks.
8. Experimental reference restyling.

---

## Version 1.8 — Open research and the Window

**Status: done.** Covered by `backend/tests/test_research_window.py`. Checked live as well: text streaming from the
real model, the Window filling in the browser during a real revision (and when the page is opened mid-run), a real
OpenAlex search, and a real open-access paper downloaded and read in full.

**Built differently from the plan:**

* In a Research-only article, Wikipedia and general web pages are left out altogether. The plan let them "inform
  background"; keeping them out is the only way to be sure they are never cited.
* The label on each sheet is the step RAF already reports in the Console, not a fixed list of phase names.
* The Window also shows revisions started in the Studio.
* The estimate was not refined with the number of words written; it still works by stage and segment.

**Not done or not checked in 1.8:**

* A complete Research-only article has not been written with the real model. The pipeline was run end to end with
  stand-ins for the model and the databases, and each real piece was checked on its own.
* Unpaywall returned nothing in the live check, most likely because the default contact address is a placeholder.
  Set `RAF_CONTACT_EMAIL` to a real address.
* The second research round and the reading-list page were checked in tests, not in the browser.
* Corrections appearing struck through on a sheet were not seen live; the revision used for the live check made none.

**Added on request after 1.8 (released as 1.8.1): cloud models through your own API keys.**

What was asked for: a place in the language-model settings to enter the API key of any LLM (Gemini, NVIDIA, GPT,
Claude and others), stored encrypted; several keys at once for more agents and more speed; the models shown with a
logo under the agents box on the Segments page; and rules so that each model is used in the way that suits it.

What was built:

* **Settings → Language model → Cloud models.** Add, test, switch off and remove keys. The provider is recognised from
  the key. Each key has a model (with the provider's real model list one click away), 1 to 4 agents, and a role:
  everything, writing only or checks only. Up to 12 keys; RAF runs at most 8 agents at once.
* **Encrypted storage** (`vault.py`): Windows data protection on Windows, an AES key file elsewhere. The key is never
  sent back to the browser, is removed from error messages, and is covered by the admin lock.
* **Who writes:** This PC only, This PC + cloud, or Cloud only.
* **Routing and failover** (`llm.py`): cloud keys are extra agents; a rejected key is switched off, a rate-limited one
  rests, a declined request goes to another model, and the local model takes over when no cloud model is left.
* **Rules per provider** (`providers.py`): one output contract for all; Claude through Anthropic's SDK with effort
  instead of temperature and Anthropic's refusal fallback; the other providers through their OpenAI-compatible API,
  with parameters a model rejects dropped or renamed on the fly and remembered.
* **Segments page:** the team that will write, a mark per provider, the number of agents, a notice that text is sent to
  those providers, and a switch to leave them out of a run.
* **Record:** the run log and History name the models; the AI-use statement says which ran locally and which online.

Covered by `backend/tests/test_providers.py` (10 tests, no real provider involved). Checked live against a stand-in
server on this PC that speaks the OpenAI chat API and rejects `max_tokens` like a reasoning model: adding a key in the
browser, listing its models, the Test button, the team on the Segments page, and a real Studio revision written by the
stand-in through its key, streamed.

**Built differently from what was asked:**

* "Neural network layers" cannot be added to a model that is reached through an API: its weights are not ours to
  change. What was built instead is the layer RAF does control: the rules for how each model is called, which work it
  gets, and what happens when it fails.
* The marks on the Segments page are simple drawings in each provider's colour, made for RAF. They are not the
  official logos, which are trademarks and could not be redrawn faithfully.
* This goes against rule 7 below ("everything still runs on the machine itself") on purpose and only when you add a
  key. As that rule requires, it is named in the interface and can be switched off (mode *This PC only*, or per run).

**Not done or not checked in 1.8.1:**

* **No real provider was called.** No real API key was available, and entering one is yours to do. The Claude path was
  tested against a stand-in for Anthropic's SDK, the others against stand-in servers. The first real call to each
  provider is therefore the real test: use the **Test** button after adding a key.
* The default model names for OpenAI, Gemini, NVIDIA, Groq, Mistral, DeepSeek and OpenRouter come from memory and may
  be out of date. Use **List** to pick a model the key really offers.
* A complete article has not been written with cloud agents, and the mix of local and cloud agents was not timed. The
  time estimate assumes a speed for cloud models; it is rough.
* RAF does not show what a run costs, only how many requests each key answered.
* Embeddings for retrieval still come from Ollama only (or TF-IDF + BM25 without it).
* The encryption was exercised on Windows only. The macOS / Linux path (AES key file) is written but was not run.
* Azure OpenAI, Amazon Bedrock and Google Vertex use other sign-in schemes and are not supported; a gateway that
  speaks the OpenAI chat API in front of them works as *Other*.

**Goal:** RAF can start from a title alone, and you can watch it think.

### Articles without reference files (request 3) — L

Today RAF refuses to start with fewer than ten uploaded references, and for online sources it only reads the title
and abstract. Removing the limit alone would produce thin, weakly supported articles. So this feature is mostly about
making online research strong enough to stand on its own.

* **Three source modes**, chosen on the References page:
  * **My references** — today's behaviour (10–20 files).
  * **Mixed** — any number of files from 1 upward, topped up by research.
  * **Research only** — no files at all.
* **Deeper research.** In Mixed and Research-only modes RAF plans more queries, searches in two rounds (the second
  round follows up on what the first found), and keeps more sources.
* **Full text where it is legally open.** For open-access sources RAF downloads the full paper (through OpenAlex,
  arXiv, Europe PMC and Unpaywall links) and reads it with the same pipeline as an uploaded reference. Everything else
  stays abstract-only and is labelled as such.
* **You approve the reading list.** A new pause between research and writing: RAF shows the sources it found, with
  venue, year and whether it has the full text. You remove what does not belong, pin what must be used, and can drop
  in a file of your own. Writing starts when you confirm.
* **Scholarly sources only for citations.** In Research-only mode Wikipedia and general web pages may inform
  background but are not cited as evidence.
* **Honest wording.** The Methodology segment describes what really happened ("a structured search of these
  databases; N sources screened; M read in full"), and the integrity report states how much of the evidence was
  abstract-only.
* **How.** `Project.source_mode`; the minimum check in `main.generate` and `References.jsx` depends on it;
  `research.py` gains the second round and the open-access fetch; fabrication splits into a "find sources" job and the
  writing job; `analysis_protocol` in `writer.py` gets mode-aware wording.

### The Window: live view of the writing (request 7) — L

* **What you get.** The Fabrication page gets a second view next to the console, **Window**. Every segment is a small
  sheet of paper. The ones being written fill with text as the model produces it, word by word. A label on each sheet
  shows what is happening to it: *Reading evidence → Taking notes → Drafting part 2 of 4 → Peer review → Checking
  claims → Style pass → Originality check → Done*.
* **You see the corrections too.** When the hallucination filter removes or corrects a sentence, or the originality
  guard re-expresses one, the sheet shows it: the sentence is highlighted, struck through, and replaced.
* **Look, don't touch.** The view is read-only: no editing, no buttons that change the run. You can choose which
  segment to enlarge and switch between Window and Console. Editing still happens in the Studio.
* **With two or three agents** you see two or three sheets being written at once.
* **How.**
  * `llm.chat` learns to stream (`"stream": true` on Ollama's chat endpoint) and hands each piece of text to a
    callback. Checks that return JSON are not streamed; they show as a status label.
  * `writer.py` tells each call which segment and step it belongs to.
  * `jobs.emit` gets two new event kinds: `delta` (new text) and `edit` (a correction). Neither is saved to the log.
    They are grouped into a few updates per second so the page stays smooth.
  * The server keeps the current text of each active sheet in memory, so opening the page in the middle of a run shows
    the sheet as it is, not an empty one.
  * A retry or fallback clears the sheet and starts it again.
  * Animations are switched off for people who have reduced motion set on their system, as the rest of the interface
    already does.
* **Bonus:** the estimate improves, because RAF now knows how many words have been written, not just which step is
  running.

### Sequence

1. Streaming in `llm.chat`, with tests for retries and out-of-memory fallbacks while streaming.
2. `delta` and `edit` events and the in-memory sheets.
3. Window view.
4. Source modes and the relaxed minimum.
5. Two-round research and open-access full text.
6. Reading-list approval step.
7. Mode-aware Methodology wording and integrity labels.

---

## Version 1.9 — Quality

**Goal:** the article is written to a chosen standard, reads like a specialist wrote it, and its checks can be shown
to someone else in one image.

### Article level Q1–Q4 (request 16) — M

A quartile belongs to a journal, not to an article, and no tool can promise acceptance. What RAF can do is write to
the standard that journals of a given tier usually expect. The setting is called **Target journal tier** and says so.

* **Where.** A four-way choice on the Topic & title page, with one sentence under each option.
* **What it changes.**

  | | Q4 | Q3 | Q2 | Q1 |
  |---|---|---|---|---|
  | Sources kept from research | fewer | standard | more | most |
  | Share of recent sources expected | low | medium | high | highest |
  | Citations per 1,000 words | light | standard | dense | densest |
  | Peer-review passes per segment | 1 | 1 | 2 | 2, with a stricter checklist |
  | Extra reviewer questions | — | — | contribution stated | contribution, alternative explanations, robustness |
  | Suggested lengths | shorter | standard | longer | longest |
  | Suggested extra segments | — | — | Limitations | Limitations, Data Availability, Theoretical Contribution |

  The exact numbers are tuned on test articles during the release.
* **How.** `Project.target_tier`; a `TIER_PROFILES` table in `blueprints.py` next to the existing tone and length
  profiles; `critique_and_refine` in `writer.py` reads the number of passes and the extra questions; `research.py`
  reads the breadth; `estimate.py` gets a tier factor, because Q1 runs take longer.
* **In the report.** The integrity report shows which of the tier's expectations the article meets.

### Humanize 2 (request 5) — L

**Status: the engine was built early, in 1.8.2, together with the other text tools, after you reported that Humanize
and the tools did not work on long text.** What is done and what is still open is listed first; the original plan
follows unchanged for reference.

*Why they failed.* The text tools sent the whole section to the model in one request. The answer was cut off at the
output limit, or the model summarised, and nothing checked the result. Humanize had the opposite fault: its gate
(length within ±15 %, the style score must rise, 70 % of key terms kept, propositions extracted by the model) rejected
most rewrites, so most paragraphs were returned unchanged.

*Done in 1.8.2* (`backend/app/textops.py`, 26 tests in `backend/tests/test_textops.py`):

* One engine for all eight tools, working paragraph by paragraph, in parallel, on text of any length.
* Diagnosis that points at the sentence (points 1 and 2 of the plan, word and sentence level).
* A rule layer that always produces a result; citation repair; a gate with hard checks and a fidelity check by the
  model (point 7); retries that carry the reason; selection of the best passing rewrite.
* A check for the replacement habit (point 5): a rewrite that brings in new stock wording is rejected.
* Cutting is allowed (point 6): the length window is per tool, and filler is removed by rule.
* Three strengths in the Studio, and a report of what the last tool did.

Checked with the real local model (`gemma4:12b`) on a 230-word sample: all eight tools changed the text and kept every
citation and number; Humanize was also run from the Studio in the browser. Reading those results by hand found three
faults that the first version of the gate let through, and each now has a check and a test: a sentence whose meaning
was reversed, plain words replaced by heavy ones in Formalize, and text copied in from the neighbouring paragraph.

*Asked for and not built, with the reason:*

* **"ChatGPT's and Claude's humanizing algorithms."** Neither company publishes one, so there is nothing to add. What
  those models have is writing ability, and RAF uses it when you add their API key (1.8.1): the rewriting step is then
  done by that model, inside the same checks.
* **"Open-source algorithms and ML layers."** The measures used are the ones from the open literature: sentence-length
  variation, moving-average type–token ratio, reading ease, a catalogue of formulaic patterns, fuzzy sentence
  matching, and embedding similarity when an embedding model is installed. I did not add a downloaded paraphrasing
  network: such models rewrite without regard to citations, numbers or claims, which is the opposite of what a
  research article needs, and they would add gigabytes to the install.
* **No promise about AI detectors.** Humanize improves how the text reads. It was not tested against any detector and
  makes no claim about one.

*Still open from the plan below (stays in 1.9):* habits across paragraphs and across the article (points 1 and 3 at
paragraph and article level), edits smaller than a paragraph (point 4), the fuller field profile (point 8), the
before-and-after view with accept and reject per change, and the fixed test set of paragraphs scored on every change.

*Not checked in 1.8.2:* a long real section end to end with the real model (long text was tested with a stand-in
model, the real model on two paragraphs per tool); the tools with a cloud model; a quality comparison beyond my own
reading of the outputs. On the test PC a paragraph took about 40 seconds with most tools, about a minute with Expand and over two minutes with
Strengthen, so long sections take many minutes.

*The original plan:*

I know of no published "Claude humanizing algorithm", so I have read this as: make Humanize work the way a careful
human editor works. That means finding the specific habits that make text sound machine-written, fixing each by
restructuring the sentence rather than swapping a word, and checking the result again. This matches RAF's stated
position in the README: the aim is better writing, not beating detection tools.

* **What is weak today** (`backend/app/style.py`):
  * It looks at one paragraph at a time, so it cannot see habits that repeat *across* paragraphs: every paragraph
    with the same shape, the same closing move, the same kind of opener.
  * It measures eight numbers and gives the model general advice ("vary sentence openings"). It does not point at the
    sentence that has the problem.
  * It rewrites a whole paragraph to fix one sentence, which is how content gets lost and why many rewrites are
    rejected.
  * A rewrite must stay within 78–130% of the original length, so pure filler cannot be cut.
* **What changes.**
  1. **A catalogue of habits, in families:** word level (stock vocabulary, stacked hedges, intensifiers), sentence
     level ("not X but Y" framings, lists of three, a short quotable line closing the paragraph, signposting that
     announces content), paragraph level (identical shape, every paragraph ending on a summary), and article level
     (the same arc in every segment). Each habit has a detector.
  2. **Diagnosis that points.** Each finding names the sentence and the habit. Detectors are rules where rules are
     reliable, plus one model pass per segment for the habits rules cannot see.
  3. **A plan for the whole segment** before anything is rewritten: which sentences to restructure, which to merge,
     which to cut.
  4. **Small edits.** Change the sentence that has the problem, not the paragraph around it.
  5. **Check for the replacement habit.** Suppressing one habit tends to produce its nearest relative. The edited
     text is diagnosed again, and an edit that trades one habit for another is rejected.
  6. **Cutting is allowed** when the claim inventory shows the sentence carries no claim, citation or number.
  7. **The safety gate stays and gets stricter.** Every citation, number, name and claim must survive, as today, and a
     judge now compares each changed sentence with its original for meaning.
  8. **A fuller field profile** from your references: how often authors hedge, whether they write "Smith (2020)
     argues" or "(Smith, 2020)", how much first person they use, how long their paragraphs run.
* **In the Studio.** Three strengths (Light, Standard, Deep), and a before-and-after view where every change shows the
  habit it fixed and can be accepted or rejected one by one.
* **Kept honest by a test set.** A fixed collection of paragraphs is scored before and after on every change to the
  engine, so an "improvement" that makes results worse is caught.

### Integrity Report image (request 10) — M

* **What you get.** One button, **Export report image**, in the Studio's integrity card and on the Publish page. It
  saves a single PNG (PDF also offered) for the whole article, or for one segment.
* **What is on it.**
  * **Header:** article title, date, RAF version, model used, target tier.
  * **Source overlap** (the plagiarism screen): overall percentage, a bar per segment, sentences still close to a
    source, sentences re-expressed.
  * **Grounding:** score, claims checked, supported, corrected, removed, still flagged.
  * **AI-likeness meter:** one dial from 0 to 100, with every parameter listed under it and its own score: sentence
    rhythm, repeated openers, stock connectors, formulaic phrases, lists of three, vocabulary variety, paragraph
    uniformity, and the new habit families from Humanize 2.
  * **Readability and length** against targets.
  * **Footer, always printed:** the overlap figure is measured against this project's own sources and is not a
    Turnitin or iThenticate result; the AI-likeness figure is RAF's own estimate from measurable writing features and
    does not predict what any detection service will say.
* **How.** A new `backend/app/report.py` draws the image with Matplotlib, which RAF already uses for figures. Scores
  exist per segment today (`QualityReport`); article-level figures are added by re-running the overlap check on the
  full text and weighting the rest by word count. Route: `GET /api/projects/{id}/report.{png|pdf}`.

### Sequence

1. Habit catalogue and detectors, with the test set.
2. Pointing diagnosis and segment plan.
3. Sentence-level edits, replacement-habit check, stricter gate.
4. Studio before-and-after view and strengths.
5. Tier profiles and their effect on research, review passes and lengths.
6. Article-level integrity figures.
7. Report image.

---

## Version 2.0 — The suite

**Goal:** RAF becomes one of three tools that share one home, one engine and one look. This is a major version because
the home page, the addresses and the layout of the code all change.

### The Hub (request 8) — S

* **What you get.** The first screen shows three large cards:
  * **Research Article Fabricator** — from a title and sources to a publishable article.
  * **TextAI Tools** — improve, check and reshape any text.
  * **Data Analyzer** — from a spreadsheet to statistics, charts and a written results section.

  Each card shows what the tool does and your most recent work in it. Choosing RAF opens **RAF's own menu**: New
  article, Format an existing article, Library, and recent projects.
* **Shared by all three:** the top bar, the engine status pill, Developer Tools, light and dark themes.
* **How.** `#/` becomes the Hub; RAF already lives under `#/raf` since 1.5. New `Hub.jsx`; today's `Home.jsx` becomes
  the RAF menu. The logo files in the project root finally get used, as the browser icon and in the top bar.

### TextAI Tools (request 9) — L

A workbench for text that was not written in RAF. Paste text or upload a file, pick a tool, see the result appear as
it is written.

* **Rewrite tools:** Expand, Condense, Formalize, Simplify, Polish, Strengthen argument, Humanize (the 1.9 engine),
  Paraphrase, and Change tone (the five tones of the tone meter).
* **Check tools:** Style and AI-likeness report, grammar and clarity check, readability, and an originality check
  against documents you upload.
* **Academic helpers:** suggest a title, write an abstract, pick keywords, convert a reference list between APA,
  Harvard, Chicago and IEEE, and write a summary.
* **Every result** shows a before-and-after view with changes highlighted, can be accepted in whole or in part, and
  can be exported. Sessions are saved, so earlier work is still there.
* **Hand-over:** "Send to RAF" places the text into a segment of a RAF project.
* **How.** Almost everything exists already: `TOOL_INSTRUCTIONS` and `revise_segment` in `writer.py`, `style.py`,
  `originality.py`, `citations.py`, `build_title`, `build_abstract`, `build_keywords`. The work is to make these
  callable without a project and its evidence index, and to build the page. Tools that need evidence (Add citations)
  only appear when sources are uploaded. New `backend/app/textai/` and routes under `/api/text`.

### Data Analyzer (request 9) — L

* **What you get.**
  1. **Upload** CSV, TSV or Excel. See a profile of every column: type, missing values, distribution.
  2. **Auto-analysis.** One click runs what RAF runs today: descriptives, normality checks, then the correlation,
     group-comparison, regression or trend analysis the data supports.
  3. **Your own analysis.** Choose the outcome, the predictors and the grouping variable yourself, and pick the test.
     RAF still checks assumptions first and says so when a test is not appropriate.
  4. **Chart builder.** Histogram, box plot, scatter with fitted line, bar, line, correlation heat-map. Titles, labels
     and colours are editable.
  5. **Plain-language results.** RAF writes up the findings, using only the computed numbers, the same rule the
     Results segment follows.
  6. **Export.** Tables as CSV, DOCX or LaTeX; charts as PNG or SVG; the whole analysis as a PDF report.
* **Hand-over:** "Send to RAF" attaches the dataset and the finished analysis to a RAF project, so its Methodology and
  Results segments are written from it.
* **How.** `analysis.py` is fully automatic today and limited to four tables and four figures. Its `Analyzer` is
  split into separately callable procedures with the limits lifted. New `backend/app/datalab/`, routes under
  `/api/data`, and analyses stored under `<data_dir>/analyses/`.

### Code layout

`backend/app/` is reorganised into `core/` (model client, settings, jobs, storage, configuration), `raf/`,
`textai/` and `datalab/`. Existing RAF routes keep their addresses (`/api/projects/…`), so nothing that calls the API
breaks.

### Sequence

1. Reorganise the backend into `core/` and `raf/`, with the test suite proving nothing changed.
2. Hub and RAF menu.
3. TextAI Tools: rewrite tools, then check tools, then academic helpers, then Send to RAF.
4. Data Analyzer: upload and profile, auto-analysis, own analysis, chart builder, written results, exports, Send to
   RAF.
5. Rewrite `README.md` and `PRD.md` for the suite.

If the release has to be cut down, the Data Analyzer moves to **2.1** and its Hub card says so. The Hub and TextAI
Tools do not depend on it.

---

## Rules for every release

A release is finished when all of these are true:

1. `API_VERSION` in `backend/app/main.py` and `EXPECTED_API` in `frontend/src/App.jsx` both carry the new number.
2. Projects created in every earlier version still open, and a run interrupted before the update still resumes.
3. New behaviour has automated tests, and the whole suite passes.
4. Every new action writes a line to the project's History (from 1.5).
5. The same test article has been published in all templates and formats, and each file opened and checked.
6. `README.md` and `PRD.md` describe the release, and the "Honest limits" section is updated when a feature adds a
   new limit.
7. Everything still runs on the machine itself. Anything new that goes online is named in the interface and can be
   switched off.

## Decisions that are yours

These are the places where I chose for you. Each one can be changed without disturbing the rest of the plan.

1. **What "Article Revisions" means.** I planned whole-article snapshots plus a guided round for reviewer comments.
   If you meant something narrower (for example only a "revise the whole article with one instruction" button), 1.5
   gets smaller.
2. **What "like Claude's Humanizing algorithm" means.** I planned an editor-style engine: diagnose specific habits,
   restructure, re-check. If you have a specific reference in mind, the catalogue in 1.9 can be built from it.
3. **What the AI-detection meter claims.** I planned it as RAF's own local estimate, clearly labelled, and not as a
   prediction of what commercial detectors will report. Calling an outside detection service would need an account
   and would send the article off the machine, which goes against how RAF works today.
4. **A patch release, 1.4.1,** ahead of 1.5, so the DOCX fix does not wait.
5. **2.0, not 1.10,** for the suite, because the home page, the addresses and the code layout all change.
6. **Names.** "Library", "Window", "Hub", "Target journal tier" and "Data Analyzer" are working names.
7. **Order of 1.7 and 1.8.** They do not depend on each other. If writing without references matters more to you than
   LaTeX, they can swap.
