import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { Button, Icon, Spinner, timeAgo, useToast } from "../ui.jsx";
import { fmtDuration } from "./Processing.jsx";

const TOOLS = [
  { key: "expand", label: "Expand", icon: "expand" },
  { key: "condense", label: "Condense", icon: "condense" },
  { key: "formalize", label: "Formalize", icon: "formal" },
  { key: "simplify", label: "Simplify", icon: "simple" },
  { key: "add_citations", label: "Add citations", icon: "cite" },
  { key: "polish", label: "Polish", icon: "polish" },
  { key: "humanize", label: "Humanize", icon: "human", hint: "Paragraph-by-paragraph rewrite; keeps every citation, number and claim or leaves the paragraph unchanged" },
  { key: "strengthen_argument", label: "Strengthen", icon: "target" },
];

const META_KEYS = new Set(["title", "keywords", "abstract"]);
const META_TITLES = { title: "Title", keywords: "Keywords", abstract: "Abstract" };

/** Purpose-built manual editors for the article's front matter. */
function MetaEditor({ segKey, seg, draft, setDraft, project }) {
  const [kwInput, setKwInput] = useState("");
  if (segKey === "title") {
    const alternatives = (seg.notes || []).filter((n) => /^(Alternative|Working title):/.test(n)).map((n) => n.replace(/^[^:]+:\s*/, ""));
    return (
      <div className="paper">
        <div className="field">
          <label htmlFor="title-edit">Article title <span className="opt">use “Title: Subtitle” to add a subtitle</span></label>
          <textarea id="title-edit" className="input title-input" rows={2} value={draft} onChange={(e) => setDraft(e.target.value.replace(/\n/g, " "))} autoFocus />
          <span className="muted mono" style={{ fontSize: 11 }}>{draft.split(/\s+/).filter(Boolean).length} words · 10–20 recommended</span>
        </div>
        {alternatives.length > 0 && (
          <div style={{ marginTop: 22 }}>
            <div className="eyebrow" style={{ marginBottom: 10 }}>Suggestions</div>
            <div className="stack" style={{ gap: 8 }}>
              {alternatives.map((t) => (
                <button key={t} type="button" className="tool" style={{ fontSize: 14 }} onClick={() => setDraft(t)}>
                  <Icon name="arrow" size={14} /> {t}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }
  if (segKey === "keywords") {
    const list = draft.split(/;\s*/).map((k) => k.trim()).filter(Boolean);
    const commit = (items) => setDraft([...new Set(items)].join("; "));
    const add = () => {
      const parts = kwInput.split(/[;,]/).map((k) => k.trim()).filter(Boolean);
      if (parts.length) commit([...list, ...parts]);
      setKwInput("");
    };
    return (
      <div className="paper">
        <div className="field">
          <label>Keywords <span className="opt">{list.length} · 5–7 recommended · press Enter to add</span></label>
          <div className="kw-editor">
            {list.map((k) => (
              <span key={k} className="kw-chip">{k}<button type="button" aria-label={`Remove ${k}`} onClick={() => commit(list.filter((x) => x !== k))}><Icon name="x" size={12} /></button></span>
            ))}
            <input className="kw-input" value={kwInput} autoFocus placeholder="Add a keyword…" onChange={(e) => setKwInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(); }
                if (e.key === "Backspace" && !kwInput && list.length) commit(list.slice(0, -1));
              }} onBlur={add} />
          </div>
        </div>
      </div>
    );
  }
  const words = draft.split(/\s+/).filter(Boolean).length;
  const target = project.segment_lengths?.abstract || seg.quality.target_words || 220;
  return (
    <div className="paper">
      <div className="field">
        <label htmlFor="abstract-edit">Abstract <span className="opt" style={{ color: words > target * 1.25 || words < target * 0.6 ? "var(--warn)" : undefined }}>{words} / ~{target} words</span></label>
        <textarea id="abstract-edit" className="textarea serif" rows={14} value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus spellCheck
          style={{ fontSize: 16, lineHeight: 1.75 }} />
        <span className="muted" style={{ fontSize: 12 }}>One paragraph: context → aim → method → key findings → conclusion → value. No citations.</span>
      </div>
    </div>
  );
}

const ORDER = ["title", "abstract", "keywords", "introduction", "literature_review", "methodology", "results", "discussion", "conclusion", "limitations", "references", "appendices"];

function useSources(project) {
  return useMemo(() => {
    const m = {};
    project.references.filter((r) => r.status === "parsed").forEach((r, i) => { m[`R${i + 1}`] = { ...r, origin: "Uploaded reference" }; });
    project.web_sources.forEach((w, i) => { m[`W${i + 1}`] = { ...w, origin: w.source }; });
    return m;
  }, [project.references, project.web_sources]);
}

function Inline({ text, sources }) {
  const parts = text.split(/(\[(?:[RW]\d+(?:\s*[,;]\s*)?)+\])/g);
  return parts.map((part, i) => {
    if (!/^\[[RW]\d+/.test(part)) return part;
    const labels = part.slice(1, -1).split(/\s*[,;]\s*/);
    return (
      <span key={i} className="cite">
        {labels.join(", ")}
        <span className="tip">
          {labels.map((l) => {
            const s = sources[l];
            return s ? (
              <span key={l} style={{ display: "block", marginBottom: 6 }}>
                <b>{l}</b> · {s.title}<br />
                <span className="muted">{(s.authors || []).slice(0, 3).join(", ")}{s.year ? ` (${s.year})` : ""} — {s.origin}</span>
              </span>
            ) : <span key={l} style={{ display: "block" }}>{l}: unknown source</span>;
          })}
        </span>
      </span>
    );
  });
}

function SegmentBody({ seg, project, sources }) {
  const tables = Object.fromEntries(seg.tables.map((t) => [t.number, t]));
  const figures = Object.fromEntries(seg.figures.map((f) => [f.number, f]));
  const blocks = seg.content.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);

  if (seg.key === "title") return <p className="serif" style={{ fontSize: 30, lineHeight: 1.2, textAlign: "left" }}>{seg.content}</p>;
  if (seg.key === "keywords") return <div className="row wrap">{seg.content.split(/;\s*/).map((k) => <span key={k} className="badge accent" style={{ fontSize: 12 }}>{k}</span>)}</div>;

  return blocks.map((b, i) => {
    const m = b.match(/^\[\[(TABLE|FIGURE) (\d+)\]\]$/);
    if (m && m[1] === "TABLE" && tables[m[2]]) {
      const t = tables[m[2]];
      return (
        <div key={i} className="table-block">
          <div className="caption"><b>{t.number > 100 ? `Table A${t.number - 100}` : `Table ${t.number}`}.</b> {t.caption}</div>
          <table>
            <thead><tr>{t.columns.map((c, j) => <th key={j}>{c}</th>)}</tr></thead>
            <tbody>{t.rows.map((r, j) => <tr key={j}>{r.map((v, k) => <td key={k}>{v}</td>)}</tr>)}</tbody>
          </table>
          {t.note && <div className="table-note"><i>Note.</i> {t.note}</div>}
        </div>
      );
    }
    if (m && m[1] === "FIGURE" && figures[m[2]]) {
      const f = figures[m[2]];
      return (
        <figure key={i} className="figure-block">
          <img src={api.fileUrl(project.id, f.path)} alt={f.caption} loading="lazy" />
          <figcaption className="caption"><b>Figure {f.number}.</b> {f.caption}</figcaption>
        </figure>
      );
    }
    if (m) return null;
    if (seg.key === "references") return b.split("\n").map((line, j) => <p key={`${i}-${j}`} className="ref-entry">{line}</p>);
    if (/^Appendix [A-Z]\./.test(b)) return <h4 key={i}>{b}</h4>;
    return b.split(seg.key === "appendices" ? "\n" : /\n(?!\n)/).map((para, j) => <p key={`${i}-${j}`}><Flagged text={para} flags={seg.quality.flags || []} sources={sources} /></p>);
  });
}

/** Highlights sentences the hallucination filter could not fully verify. */
function Flagged({ text, flags, sources }) {
  const hits = [];
  for (const [n, f] of flags.entries()) {
    const probe = (f.sentence || "").slice(0, 90);
    const at = probe ? text.indexOf(probe) : -1;
    if (at >= 0) {
      const end = text.indexOf(". ", at + Math.min(f.sentence.length, 200) - 2);
      hits.push({ start: at, end: end > 0 ? end + 1 : text.length, flag: f, n });
    }
  }
  if (!hits.length) return <Inline text={text} sources={sources} />;
  hits.sort((a, b) => a.start - b.start);
  const out = [];
  let cursor = 0;
  hits.forEach((h, k) => {
    if (h.start < cursor) return;
    out.push(<Inline key={`t${k}`} text={text.slice(cursor, h.start)} sources={sources} />);
    out.push(
      <mark key={`m${k}`} id={`flag-${h.n}`} className={`flag ${h.flag.verdict}`} title={`${VERDICT_LABEL[h.flag.verdict] || h.flag.verdict}: ${h.flag.reason}`}>
        <Inline text={text.slice(h.start, h.end)} sources={sources} />
      </mark>,
    );
    cursor = h.end;
  });
  out.push(<Inline key="tail" text={text.slice(cursor)} sources={sources} />);
  return out;
}

const VERDICT_LABEL = { partial: "Partly supported", unsupported: "Not supported by the cited source", contradicted: "Contradicted by the source", unverified: "Could not be verified" };

function scoreColor(v) {
  if (v == null) return undefined;
  return v >= 75 ? "var(--ok)" : v >= 50 ? "var(--warn)" : "var(--bad)";
}

export default function Studio({ project, setProject, navigate, events }) {
  const toast = useToast();
  const keys = ORDER.filter((k) => project.segments[k]);
  const [active, setActive] = useState(() => keys.find((k) => project.segments[k].status !== "approved") || keys[0]);
  const [instruction, setInstruction] = useState("");
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [bubble, setBubble] = useState(null);
  const [selection, setSelection] = useState("");
  const paperRef = useRef(null);
  const sources = useSources(project);

  const seg = project.segments[active];
  const busy = !!project.busy;                                   // exclusive project job (fabrication, review, import)
  const jobs = project.busy_segments || {};                      // segment key -> Studio job name
  const jobCount = Object.keys(jobs).length;
  const maxJobs = project.max_segment_jobs || 3;
  const isBusy = (k) => busy || !!jobs[k] || ["working", "revising"].includes(project.segments[k]?.status);
  const segBusy = isBusy(active);
  const atLimit = !segBusy && jobCount >= maxJobs;              // this segment is free, but every job slot is taken
  const limitHint = atLimit ? `RAF is already working on ${maxJobs} segments — wait for one to finish` : undefined;
  const approved = keys.filter((k) => project.segments[k].status === "approved").length;

  useEffect(() => { setEditing(false); setSelection(""); setBubble(null); }, [active]);

  // Tell the author when a background segment job finishes while they are looking at something else.
  const lastEvent = events[events.length - 1];
  const openedAt = useRef(Date.now() / 1000);
  useEffect(() => {
    if (lastEvent?.kind !== "job" || !lastEvent.key || lastEvent.state === "started" || lastEvent.t < openedAt.current) return;
    const title = project.segments[lastEvent.key]?.title || lastEvent.key;
    if (lastEvent.state === "finished") toast(`${title} is ready${lastEvent.key === active ? "" : " — open it to review"}`);
    else toast(`${lastEvent.job} failed`, "error");
  }, [lastEvent]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onUp = () => {
      const sel = window.getSelection();
      const text = sel?.toString().trim();
      if (!text || text.length < 20 || !paperRef.current?.contains(sel.anchorNode)) { setBubble(null); return; }
      const rect = sel.getRangeAt(0).getBoundingClientRect();
      setBubble({ x: rect.left + rect.width / 2, y: rect.top - 10, text });
    };
    document.addEventListener("mouseup", onUp);
    return () => document.removeEventListener("mouseup", onUp);
  }, []);

  if (!seg) return <div className="empty">No segments yet.</div>;

  const run = async (fn, message) => {
    try {
      setProject(await fn());
      if (message) toast(message);
    } catch (err) {
      toast(err.message, "error");
    }
  };

  // Map a rendered selection back to the stored text (citation chips render as "R1, W2" without brackets).
  const sourceExcerpt = (rendered) => {
    const plain = rendered.replace(/\s+/g, " ");
    if (seg.content.includes(plain)) return plain;
    const words = plain.split(" ").filter((w) => !/^[RW]\d+,?$/.test(w));
    const head = words.slice(0, 4).join(" ");
    const tail = words.slice(-3).join(" ");
    const s = seg.content.indexOf(head);
    const e = s >= 0 ? seg.content.indexOf(tail, s) : -1;
    return s >= 0 && e > s ? seg.content.slice(s, e + tail.length) : "";
  };

  const applyTool = (tool, sel = selection) => run(() => api.tool(project.id, active, tool, sel), `RAF is applying “${TOOLS.find((t) => t.key === tool).label}”…`);
  const submitRevision = (e) => {
    e.preventDefault();
    if (instruction.trim().length < 3) return;
    run(() => api.revise(project.id, active, instruction.trim(), selection), "Revision started — RAF will re-display the segment when done.").then(() => setInstruction(""));
  };

  const q = seg.quality;
  const lengthPct = q.target_words ? Math.min(100, (q.words / q.target_words) * 100) : 100;

  return (
    <div className="page wide">
      <div className="row between wrap" style={{ marginBottom: 18 }}>
        <div>
          <div className="eyebrow">Step 05 — Studio</div>
          <h1 className="h2" style={{ fontSize: 30, marginTop: 8, maxWidth: 900 }}>{project.segments.title?.content || project.title}</h1>
        </div>
        <div className="row">
          {project.run?.elapsed_before > 0 && (
            <span className="badge mono" title="Total fabrication time across all sessions">⏱ {fmtDuration(project.run.elapsed_before, true)}</span>
          )}
          {jobCount > 0 && (
            <span className="badge mono jobs-badge" title={Object.values(jobs).join("\n")}>
              <Spinner size={11} /> {jobCount} / {maxJobs} in progress
            </span>
          )}
          <span className="badge accent mono">{approved} / {keys.length} approved</span>
          <Button variant="primary" iconRight="arrow" disabled={!approved} onClick={() => navigate(project.id, "published")}>Publish</Button>
        </div>
      </div>

      <div className="studio">
        <nav className="seg-nav" aria-label="Segments">
          {keys.map((k) => {
            const s = project.segments[k];
            return (
              <button key={k} className={`${k === active ? "on" : ""} ${jobs[k] ? "working" : ""}`} onClick={() => setActive(k)} title={jobs[k]}>
                <span>{s.title}</span>
                {jobs[k] ? <Spinner size={12} /> : <span className={`status-dot ${s.status}`} title={s.status} />}
              </button>
            );
          })}
          {[...META_KEYS].filter((k) => !project.segments[k]).map((k) => (
            <button key={k} className="muted" disabled={busy} title="Write this segment yourself"
              onClick={() => run(() => api.edit(project.id, k, k === "title" ? project.title : ""), `${META_TITLES[k]} added — edit it below`).then(() => setActive(k))}>
              <span>+ Add {META_TITLES[k].toLowerCase()}</span>
              <Icon name="plus" size={13} />
            </button>
          ))}
        </nav>

        <section>
          <div className="approve-bar">
            <div className="row">
              <span className={`badge ${seg.status === "approved" ? "ok" : seg.status === "failed" ? "bad" : "accent"}`}>{seg.status}</span>
              {seg.error && <span className="muted" style={{ fontSize: 12 }}>{seg.error}</span>}
            </div>
            <div className="row">
              {editing ? (
                <>
                  <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
                  <Button size="sm" variant="primary" icon="check" onClick={() => run(() => api.edit(project.id, active, draft), "Edit saved").then(() => setEditing(false))}>Save edit</Button>
                </>
              ) : (
                <>
                  <Button size="sm" variant="ghost" icon="edit" disabled={segBusy} onClick={() => { setDraft(seg.content); setEditing(true); }}>Edit</Button>
                  <Button size="sm" variant="ghost" icon="refresh" disabled={segBusy || atLimit} title={limitHint}
                    onClick={() => confirm(`Rewrite “${seg.title}” from scratch?`) && run(() => api.regenerate(project.id, active),
                      `Regenerating ${seg.title} — you can keep working on other segments meanwhile`)}>Regenerate</Button>
                  {seg.status === "approved" ? (
                    <Button size="sm" onClick={() => run(() => api.approve(project.id, active, false))}>Unapprove</Button>
                  ) : (
                    <Button size="sm" variant="primary" icon="check" disabled={segBusy || !seg.content}
                      onClick={() => run(() => api.approve(project.id, active, true), `${seg.title} approved`).then(() => {
                        const next = keys.find((k) => k !== active && project.segments[k].status !== "approved");
                        if (next) setActive(next);
                      })}>Approve</Button>
                  )}
                </>
              )}
            </div>
          </div>

          {editing && META_KEYS.has(active) ? (
            <MetaEditor segKey={active} seg={seg} draft={draft} setDraft={setDraft} project={project} />
          ) : editing ? (
            <textarea className="editor" value={draft} onChange={(e) => setDraft(e.target.value)} spellCheck
              aria-label={`Edit ${seg.title}`} />
          ) : (
            <article ref={paperRef} className={`paper fade ${segBusy ? "busy" : ""}`} key={active + seg.versions.length}>
              {segBusy && (
                <div className="busy-veil"><div className="card"><Spinner size={18} /><span>{project.busy || jobs[active] || "RAF is working on this segment…"}</span></div></div>
              )}
              <div className="row between">
                <div className="mono muted" style={{ fontSize: 11, letterSpacing: ".14em", textTransform: "uppercase" }}>§ {seg.title}</div>
                {META_KEYS.has(active) && !segBusy && (
                  <Button size="sm" variant="soft" icon="edit" onClick={() => { setDraft(seg.content); setEditing(true); }}>Edit {seg.title.toLowerCase()}</Button>
                )}
              </div>
              <h2 className="seg-heading">{seg.title}</h2>
              <div className="prose">
                {seg.content ? <SegmentBody seg={seg} project={project} sources={sources} /> : <p className="muted">Not written yet.</p>}
              </div>
            </article>
          )}
        </section>

        <aside className="side">
          <div className="card">
            <h5>Request changes {selection && <span className="badge accent" style={{ letterSpacing: 0 }}>on selection</span>}</h5>
            <form onSubmit={submitRevision} className="stack" style={{ gap: 10 }}>
              {selection && (
                <div className="muted" style={{ fontSize: 12, borderLeft: "2px solid var(--accent)", paddingLeft: 10, maxHeight: 80, overflow: "hidden" }}>
                  “{selection.slice(0, 180)}{selection.length > 180 ? "…" : ""}”
                  <button type="button" className="btn ghost sm" style={{ height: 22, padding: "0 6px", marginLeft: 6 }} onClick={() => setSelection("")}>clear</button>
                </div>
              )}
              <textarea className="textarea" rows={4} value={instruction} onChange={(e) => setInstruction(e.target.value)}
                placeholder={`What should change in the ${seg.title.toLowerCase()}? e.g. “Add a paragraph contrasting developing and developed economies.”`}
                onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submitRevision(e); }} />
              <Button variant="primary" icon="send" disabled={segBusy || atLimit || instruction.trim().length < 3} title={limitHint}>Revise segment</Button>
              {atLimit && <span className="muted" style={{ fontSize: 11.5 }}>{limitHint}.</span>}
            </form>
          </div>

          <div className="card">
            <h5>Text tools</h5>
            <div className="tools">
              {TOOLS.map((t) => (
                <button key={t.key} className="tool" title={limitHint || t.hint} disabled={segBusy || atLimit || ["title", "keywords", "references"].includes(active)} onClick={() => applyTool(t.key)}>
                  <Icon name={t.icon} size={15} />{t.label}
                </button>
              ))}
            </div>
            <p className="muted" style={{ fontSize: 11.5, margin: "10px 0 0" }}>Select text in the page to apply a tool to just that passage.</p>
          </div>

          <div className="card">
            <h5>Integrity report</h5>
            <div className="metric"><span>Words</span><span>{q.words}{q.target_words ? ` / ${q.target_words}` : ""}</span></div>
            {q.target_words > 0 && <div className="meter"><i style={{ width: `${lengthPct}%` }} /></div>}
            <div className="metric"><span>Source overlap (7-gram)</span><span style={{ color: q.ngram_overlap > 0.04 ? "var(--warn)" : "var(--ok)" }}>{(q.ngram_overlap * 100).toFixed(1)}%</span></div>
            <div className="metric"><span>Sentences re-expressed</span><span>{q.rewritten_sentences}</span></div>
            <div className="metric"><span>Still close to a source</span><span style={{ color: q.flagged_sentences ? "var(--warn)" : "var(--ok)" }}>{q.flagged_sentences}</span></div>
            <div className="metric"><span>Citations</span><span>{q.citations}</span></div>
            {q.readability != null && <div className="metric"><span>Flesch reading ease</span><span>{q.readability}</span></div>}
            {q.unverified_numbers?.length > 0 && (
              <div style={{ marginTop: 10, fontSize: 12, color: "var(--warn)" }}>
                Numbers not found in the evidence — please verify: <span className="mono">{q.unverified_numbers.join(", ")}</span>
              </div>
            )}
            {seg.notes?.length > 0 && (
              <div style={{ marginTop: 12, fontSize: 12 }} className="muted">
                {seg.notes.map((n) => <div key={n}>{n}</div>)}
              </div>
            )}
          </div>

          {q.grounding?.checked > 0 && (
            <div className="card">
              <h5>Hallucination filter <Icon name="shield" size={14} /></h5>
              <div className="score-row">
                <span className="score-big mono" style={{ color: scoreColor(q.grounding.grounding_score) }}>{q.grounding.grounding_score}</span>
                <span className="muted" style={{ fontSize: 12 }}>grounding score<br />claims backed by their sources</span>
              </div>
              <div className="metric"><span>Claims checked</span><span>{q.grounding.checked}</span></div>
              <div className="metric"><span>Supported</span><span style={{ color: "var(--ok)" }}>{q.grounding.supported}{q.grounding.partial ? ` + ${q.grounding.partial} partly` : ""}</span></div>
              <div className="metric"><span>Corrected from evidence</span><span>{q.grounding.corrected || 0}</span></div>
              <div className="metric"><span>Removed as unsupported</span><span>{q.grounding.removed || 0}</span></div>
              {q.grounding.auto_cited > 0 && <div className="metric"><span>Citations added</span><span>{q.grounding.auto_cited}</span></div>}
              {q.grounding.sanitised > 0 && <div className="metric"><span>Artefacts cleaned</span><span>{q.grounding.sanitised}</span></div>}
              {q.grounding.paragraphs_repaired > 0 && <div className="metric"><span>Incoherent paragraphs repaired</span><span>{q.grounding.paragraphs_repaired}</span></div>}
              {q.flags?.length > 0 ? (
                <div className="flag-list">
                  <div style={{ fontSize: 12, fontWeight: 600, margin: "10px 0 6px" }}>Needs your review ({q.flags.length})</div>
                  {q.flags.map((f, n) => (
                    <button key={n} className={`flag-item ${f.verdict}`} onClick={() => document.getElementById(`flag-${n}`)?.scrollIntoView({ behavior: "smooth", block: "center" })}>
                      <b>{VERDICT_LABEL[f.verdict] || f.verdict}</b>
                      <span>“{f.sentence.slice(0, 110)}{f.sentence.length > 110 ? "…" : ""}”</span>
                      {f.reason && <span className="muted">{f.reason}</span>}
                    </button>
                  ))}
                </div>
              ) : <div style={{ fontSize: 12, color: "var(--ok)", marginTop: 8 }}>No unverified claims remain.</div>}
            </div>
          )}

          {q.style?.score != null && (
            <div className="card">
              <h5>Style & naturalness</h5>
              <div className="score-row">
                <span className="score-big mono" style={{ color: scoreColor(q.style.score) }}>{q.style.score}</span>
                <span className="muted" style={{ fontSize: 12 }}>varied, specific,<br />non-formulaic prose</span>
              </div>
              <div className="metric"><span>Avg sentence length</span><span>{q.style.mean_sentence_words} w</span></div>
              <div className="metric"><span>Sentence-length variation</span><span>{q.style.sentence_length_variation}</span></div>
              <div className="metric"><span>Stock connectors</span><span>{Math.round(q.style.stock_connector_share * 100)}%</span></div>
              <div className="metric"><span>Formulaic phrases /100 w</span><span>{q.style.generic_phrases_per_100_words}</span></div>
              <div className="metric"><span>Lexical diversity</span><span>{q.style.lexical_diversity}</span></div>
              {q.humanize?.attempted > 0 && (
                <div className="humanize-report">
                  <b>Last Humanize</b> · {timeAgo(q.humanize.at)}<br />
                  Rewrote {q.humanize.rewritten}/{q.humanize.attempted} paragraphs · score {q.humanize.score_before} → {q.humanize.score_after}<br />
                  Citations kept {q.humanize.citations_preserved} · numbers kept {q.humanize.numbers_preserved}
                  {q.humanize.kept?.length > 0 && (
                    <div className="muted" style={{ marginTop: 4 }}>
                      {q.humanize.kept.length} paragraph(s) left unchanged because a rewrite would have lost content
                      {q.humanize.kept[0]?.reasons?.[0] ? ` (e.g. ${q.humanize.kept[0].reasons[0]})` : ""}.
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="card">
            <h5>Article review</h5>
            {project.review?.issues?.length ? project.review.issues.map((it, n) => (
              <div key={n} className="review-issue">
                <div className="row between"><b>{project.segments[it.segment]?.title || it.segment}</b><span className="badge">{it.type}</span></div>
                <div style={{ fontSize: 12.5, margin: "4px 0" }}>{it.issue}</div>
                {it.applied ? <span className="badge ok">fixed automatically</span> : project.segments[it.segment] && (
                  <Button size="sm" variant="soft" disabled={isBusy(it.segment) || jobCount >= maxJobs}
                    onClick={() => { setActive(it.segment); run(() => api.revise(project.id, it.segment, it.instruction), "Applying the review fix…"); }}>Apply fix</Button>
                )}
              </div>
            )) : <div className="muted" style={{ fontSize: 12 }}>{project.review?.at ? "No cross-segment inconsistencies found." : "Checks that research questions are answered, numbers match across sections and nothing contradicts."}</div>}
            <Button size="sm" style={{ marginTop: 10 }} icon="refresh" disabled={busy || jobCount > 0} title={jobCount ? "Available once the segments in progress finish" : undefined}
              onClick={() => run(() => api.review(project.id), "Reviewing the whole article…")}>Run article review</Button>
          </div>

          <div className="card">
            <h5>Version history <Icon name="history" size={14} /></h5>
            <div className="versions">
              {[...seg.versions].map((v, i) => ({ v, i })).reverse().map(({ v, i }) => (
                <div key={i} className="version">
                  <span><b className="mono">v{i + 1}</b> <span className="muted">{v.reason.slice(0, 38)} · {timeAgo(v.created)}</span></span>
                  {i !== seg.versions.length - 1 && (
                    <button className="btn ghost sm" style={{ height: 24 }} disabled={segBusy} onClick={() => run(() => api.restore(project.id, active, i), `Restored v${i + 1}`)}>Restore</button>
                  )}
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>

      {bubble && !segBusy && !editing && (
        <div className="selection-bubble" style={{ left: bubble.x, top: bubble.y }} onMouseDown={(e) => e.preventDefault()}>
          <Button size="sm" variant="primary" icon="edit" onClick={() => {
            const ex = sourceExcerpt(bubble.text);
            if (!ex) { toast("Couldn't map that selection — try selecting whole sentences.", "error"); return; }
            setSelection(ex); setBubble(null);
          }}>Revise selection</Button>
          {["humanize", "polish", "expand"].map((t) => (
            <Button key={t} size="sm" variant="ghost" disabled={atLimit} title={limitHint} onClick={() => { const ex = sourceExcerpt(bubble.text); setBubble(null); if (ex) applyTool(t, ex); }}>
              {TOOLS.find((x) => x.key === t).label}
            </Button>
          ))}
        </div>
      )}
    </div>
  );
}
