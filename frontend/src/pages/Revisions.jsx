import { Fragment, useCallback, useEffect, useState } from "react";
import { api, saveBlob } from "../api.js";
import { Button, Icon, Segmented, Select, Spinner, timeAgo, useToast } from "../ui.jsx";

const when = (t) => new Date(t * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const STATE = { applied: ["ok", "applied"], failed: ["bad", "could not be applied"], skipped: ["", "skipped"] };

/** Word-level differences of one segment: removed text struck through, added text underlined. */
function Diff({ diff }) {
  return (
    <div className="diff-text serif">
      {diff.map(([op, text], i) => {
        const El = op === "+" ? "ins" : op === "-" ? "del" : "span";
        return <Fragment key={i}><El>{text}</El>{" "}</Fragment>;
      })}
    </div>
  );
}

function Compare({ project, revisions, pair, setPair, onRestored }) {
  const toast = useToast();
  const [cmp, setCmp] = useState(null);
  const [open, setOpen] = useState({});
  const [working, setWorking] = useState("");

  useEffect(() => {
    setCmp(null);
    if (pair.a === pair.b) return;
    api.compare(project.id, pair.a, pair.b).then(setCmp).catch((err) => toast(err.message, "error"));
  }, [project.id, pair.a, pair.b, project.updated]); // eslint-disable-line react-hooks/exhaustive-deps

  const options = [{ value: "current", label: "Current article" }, ...revisions.map((r) => ({ value: String(r.n), label: r.name, hint: when(r.created) }))];
  const changed = cmp?.segments.filter((s) => s.status !== "same") || [];
  const run = async (name, fn) => {
    setWorking(name);
    try { await fn(); } catch (err) { toast(err.message, "error"); } finally { setWorking(""); }
  };

  return (
    <div className="card">
      <div className="row between wrap" style={{ alignItems: "flex-end", gap: 12 }}>
        <div className="row wrap" style={{ alignItems: "flex-end" }}>
          <div className="field" style={{ width: 250 }}><label>From</label><Select value={pair.a} onChange={(a) => setPair({ ...pair, a })} options={options} /></div>
          <Icon name="arrow" />
          <div className="field" style={{ width: 250 }}><label>To</label><Select value={pair.b} onChange={(b) => setPair({ ...pair, b })} options={options} /></div>
        </div>
        <div className="row">
          {["docx", "pdf"].map((fmt) => (
            <Button key={fmt} size="sm" icon={working === fmt ? undefined : "download"} disabled={!changed.length || !!working} title="A document with every change highlighted"
              onClick={() => run(fmt, () => api.exportChanges(project.id, fmt, pair.a, pair.b))}>
              {working === fmt && <Spinner size={13} />}Changes as {fmt.toUpperCase()}
            </Button>
          ))}
        </div>
      </div>

      {pair.a === pair.b && <p className="muted" style={{ marginBottom: 0 }}>Choose two different versions to compare.</p>}
      {pair.a !== pair.b && !cmp && <div className="empty"><Spinner /> Comparing…</div>}
      {cmp && (
        <>
          <div className="row wrap" style={{ margin: "16px 0 6px" }}>
            <span className="badge ok">+{cmp.totals.added.toLocaleString()} words</span>
            <span className="badge bad">−{cmp.totals.removed.toLocaleString()} words</span>
            <span className="badge">{cmp.totals.changed_segments} of {cmp.segments.length} segments changed</span>
            <span className="muted" style={{ fontSize: 12 }}>{cmp.a.stats.words.toLocaleString()} → {cmp.b.stats.words.toLocaleString()} body words · {cmp.a.stats.citations} → {cmp.b.stats.citations} citations</span>
          </div>
          {!changed.length && <p className="muted" style={{ marginBottom: 0 }}>These two versions are identical.</p>}
          {cmp.segments.map((s) => {
            const shown = open[s.key] ?? (s.status !== "same" && changed.length <= 3);
            return (
              <div key={s.key} className={`diff-seg ${s.status}`}>
                <button className="diff-head" disabled={s.status === "same"} onClick={() => setOpen({ ...open, [s.key]: !shown })} aria-expanded={shown}>
                  <b>{s.title}</b>
                  {s.status === "same" ? <span className="muted">unchanged</span> : (
                    <span className="row" style={{ gap: 8 }}>
                      {s.status !== "changed" && <span className="badge">{s.status === "added" ? "new in “To”" : "only in “From”"}</span>}
                      <span className="mono" style={{ color: "var(--ok)" }}>+{s.added}</span>
                      <span className="mono" style={{ color: "var(--bad)" }}>−{s.removed}</span>
                      <Icon name="chevron" size={14} />
                    </span>
                  )}
                </button>
                {shown && s.status !== "same" && (
                  <>
                    <Diff diff={s.diff} />
                    {pair.b === "current" && pair.a !== "current" && s.in_a && (
                      <Button size="sm" variant="soft" icon="history" disabled={!!project.busy || !!working}
                        onClick={() => confirm(`Put “${s.title}” back to how it was in “${cmp.a.name}”? The current article is saved as a revision first.`) &&
                          run("restore", async () => { onRestored(await api.restoreRevision(project.id, pair.a, s.key)); toast(`${s.title} restored`); })}>
                        Restore this segment from “{cmp.a.name}”
                      </Button>
                    )}
                  </>
                )}
              </div>
            );
          })}
        </>
      )}
    </div>
  );
}

function Round({ project, round, engineReady, reload, showChanges }) {
  const toast = useToast();
  const [points, setPoints] = useState(round.points);
  const [letter, setLetter] = useState(round.letter);
  const [working, setWorking] = useState("");
  useEffect(() => { setPoints(round.points); setLetter(round.letter); }, [round]);

  const keys = Object.keys(project.segments).filter((k) => project.segments[k].content && !["references", "appendices"].includes(k));
  const segOptions = keys.map((k) => ({ value: k, label: project.segments[k].title }));
  const set = (i, patch) => setPoints((list) => list.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  const accepted = points.filter((p) => p.decision === "accept").length;
  const run = async (name, fn) => {
    setWorking(name);
    try { await fn(); } catch (err) { toast(err.message, "error"); } finally { setWorking(""); }
  };
  const apply = () => run("apply", async () => {
    await api.updateRound(project.id, round.id, { points });
    await api.applyRound(project.id, round.id);
    toast("Revision round started — RAF is revising the segments");
    reload();
  });

  if (round.status === "analysing") return <div className="card"><Spinner /> RAF is reading the comments of “{round.name}”…</div>;
  if (round.status === "applying") return <div className="card"><Spinner /> RAF is applying “{round.name}”: {project.busy || "revising the segments"}. You can leave this page; the round continues.</div>;

  if (round.status === "ready") return (
    <div className="card">
      <div className="row between wrap">
        <div>
          <div className="h2" style={{ fontSize: 20 }}>{round.name} · {points.length} point{points.length === 1 ? "" : "s"}</div>
          <p className="muted" style={{ margin: "4px 0 0", maxWidth: 640 }}>
            {round.analysed_by === "plain"
              ? "The model was not available, so the comments were split by paragraph and numbering. Check the segment and the instruction of each point."
              : "Check each point: the segment it concerns and the instruction RAF will follow. Nothing is changed until you apply."}
          </p>
        </div>
        <Button size="sm" variant="ghost" icon="trash" className="danger" onClick={() => confirm("Discard this round?") && run("delete", async () => { await api.deleteRound(project.id, round.id); reload(); })}>Discard</Button>
      </div>
      {points.map((p, i) => (
        <div key={i} className={`point ${p.decision}`}>
          <div className="point-n mono">{i + 1}</div>
          <div className="stack" style={{ gap: 8 }}>
            <blockquote>{p.comment}</blockquote>
            <div className="row wrap" style={{ alignItems: "flex-start" }}>
              <div style={{ width: 230 }}><Select value={p.segment} onChange={(segment) => set(i, { segment })} options={segOptions} aria-label={`Segment for point ${i + 1}`} /></div>
              <Segmented value={p.decision} onChange={(decision) => set(i, { decision })} options={[{ value: "accept", label: "Apply" }, { value: "skip", label: "Skip" }]} />
            </div>
            {p.decision === "accept" && (
              <textarea className="textarea" rows={2} value={p.instruction} onChange={(e) => set(i, { instruction: e.target.value })} aria-label={`Instruction for point ${i + 1}`} />
            )}
          </div>
        </div>
      ))}
      <div className="row between wrap" style={{ marginTop: 16 }}>
        <span className="muted" style={{ fontSize: 12.5 }}>
          The article is saved as a revision before and after, so the round can be undone. Revised segments go back to “draft” for your approval.
        </span>
        <div className="row">
          {!engineReady && <span className="badge bad">No model available</span>}
          <Button variant="primary" icon="spark" disabled={!accepted || !engineReady || !!project.busy || !!working} onClick={apply}>
            {working === "apply" ? "Starting…" : `Apply ${accepted} point${accepted === 1 ? "" : "s"}`}
          </Button>
        </div>
      </div>
    </div>
  );

  const name = `${project.title.replace(/[^A-Za-z0-9]+/g, "_").slice(0, 40)}_response`;
  return (
    <div className="card">
      <div className="row between wrap">
        <div className="h2" style={{ fontSize: 20 }}>{round.name} · finished {timeAgo(round.finished || round.created)}</div>
        {round.before && round.after && <Button size="sm" icon="eye" onClick={() => showChanges(String(round.before), String(round.after))}>See what changed</Button>}
      </div>
      {round.error && <p style={{ color: "var(--bad)", fontSize: 13 }}>{round.error}</p>}
      <div className="stack" style={{ gap: 6, margin: "12px 0 18px" }}>
        {round.points.map((p) => (
          <div key={p.n} className="row" style={{ alignItems: "flex-start", fontSize: 13 }}>
            <span className={`badge ${STATE[p.state]?.[0] || ""}`}>{STATE[p.state]?.[1] || p.state}</span>
            <span><b>{project.segments[p.segment]?.title || p.segment}</b> — {p.comment.slice(0, 160)}{p.comment.length > 160 ? "…" : ""}</span>
          </div>
        ))}
      </div>
      <div className="field">
        <label htmlFor={`letter-${round.id}`}>Response to reviewers <span className="opt">edit freely — the downloads use this text</span></label>
        <textarea id={`letter-${round.id}`} className="textarea" rows={16} value={letter} onChange={(e) => setLetter(e.target.value)}
          onBlur={() => letter !== round.letter && run("save", async () => { await api.updateRound(project.id, round.id, { letter }); reload(); })} style={{ fontSize: 13.5, lineHeight: 1.6 }} />
      </div>
      <div className="row wrap" style={{ marginTop: 10 }}>
        <Button size="sm" variant="primary" icon="download" disabled={!!working}
          onClick={() => run("docx", async () => { await api.updateRound(project.id, round.id, { letter }); await api.letterDocx(project.id, round.id); })}>Letter as Word</Button>
        <Button size="sm" icon="download" onClick={() => saveBlob(new Blob([letter], { type: "text/markdown" }), `${name}.md`)}>Letter as Markdown</Button>
        {round.before && round.after && ["docx", "pdf"].map((fmt) => (
          <Button key={fmt} size="sm" icon="download" disabled={!!working} onClick={() => run(fmt, () => api.exportChanges(project.id, fmt, round.before, round.after))}>
            Manuscript with changes highlighted ({fmt.toUpperCase()})
          </Button>
        ))}
      </div>
    </div>
  );
}

export default function Revisions({ project, setProject, health }) {
  const toast = useToast();
  const [revisions, setRevisions] = useState(null);
  const [rounds, setRounds] = useState([]);
  const [name, setName] = useState("");
  const [pair, setPair] = useState(null);             // { a, b } being compared
  const [comments, setComments] = useState("");
  const [roundName, setRoundName] = useState("");
  const [working, setWorking] = useState("");
  const [renaming, setRenaming] = useState(null);

  const reload = useCallback(() => {
    api.revisions(project.id).then(setRevisions).catch(() => setRevisions([]));
    api.rounds(project.id).then(setRounds).catch(() => {});
  }, [project.id]);
  // project.updated moves on every save and project.busy when a job starts or ends, so both lists follow background work
  useEffect(reload, [reload, project.updated, project.busy]);

  const written = Object.values(project.segments).some((s) => s.content);
  const engineReady = health?.ready ?? (health?.ollama && health?.model_available);   // the local model, or a cloud model with a key
  const run = async (key, fn) => {
    setWorking(key);
    try { await fn(); } catch (err) { toast(err.message, "error"); } finally { setWorking(""); }
  };
  const save = (e) => {
    e.preventDefault();
    run("save", async () => { const r = await api.saveRevision(project.id, name); setName(""); toast(`Saved “${r.name}”`); reload(); });
  };
  const restore = (r) => confirm(`Replace the whole article with “${r.name}”? The current article is saved as a revision first, so you can come back to it.`) &&
    run(`restore-${r.n}`, async () => { setProject(await api.restoreRevision(project.id, r.n)); toast(`Article restored from “${r.name}”`); reload(); });
  const startRound = (e) => {
    e.preventDefault();
    run("round", async () => { await api.createRound(project.id, comments, roundName); setComments(""); setRoundName(""); toast("RAF is reading the comments…"); reload(); });
  };

  return (
    <div className="page wide" style={{ maxWidth: 1180 }}>
      <div className="eyebrow">Revisions</div>
      <h1 className="h2" style={{ fontSize: 34, marginTop: 10 }}>Saved states of the whole article</h1>
      <p className="muted" style={{ maxWidth: 760, marginTop: 0 }}>
        A revision keeps every segment exactly as it stood. RAF saves one by itself at each publish and before anything that replaces a lot of text at once.
        Compare any two, bring one back, or work through a reviewer's comments as a revision round.
      </p>

      {!written && <div className="empty card">Nothing has been written yet. Revisions become available after the first fabrication run.</div>}
      {written && (
        <div className="rev-grid">
          <div className="stack" style={{ gap: 12 }}>
            <form className="card" onSubmit={save}>
              <div className="field">
                <label htmlFor="rev-name">Save the article as it is now</label>
                <div className="row">
                  <input id="rev-name" className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. First full draft, Submitted, R1" maxLength={120} />
                  <Button variant="primary" icon="check" disabled={working === "save" || !!project.busy}>Save</Button>
                </div>
              </div>
            </form>
            {!revisions && <div className="empty"><Spinner /></div>}
            {revisions?.length === 0 && <div className="muted" style={{ fontSize: 13, padding: "0 6px" }}>No revisions saved yet.</div>}
            {revisions?.map((r) => (
              <div key={r.n} className={`rev-item ${pair && [pair.a, pair.b].includes(String(r.n)) ? "on" : ""}`}>
                <div className="row between">
                  {renaming?.n === r.n ? (
                    <input className="input" autoFocus value={renaming.name} onChange={(e) => setRenaming({ n: r.n, name: e.target.value })} aria-label="Revision name"
                      onKeyDown={(e) => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") setRenaming(null); }}
                      onBlur={() => { const v = renaming.name.trim(); setRenaming(null); if (v && v !== r.name) run("rename", async () => { await api.renameRevision(project.id, r.n, v); reload(); }); }} />
                  ) : <b className="rev-name">{r.name}</b>}
                  {r.auto && <span className="badge" title="Saved by RAF. Only the 30 most recent automatic revisions are kept; rename one to keep it for good.">auto</span>}
                </div>
                <div className="muted" style={{ fontSize: 12 }}>
                  {when(r.created)} · {r.stats.words.toLocaleString()} words · {r.stats.approved}/{r.stats.segments} approved
                </div>
                <div className="row wrap" style={{ gap: 4, marginTop: 8 }}>
                  <Button size="sm" variant="soft" icon="eye" onClick={() => setPair({ a: String(r.n), b: "current" })}>Compare</Button>
                  <Button size="sm" variant="ghost" icon="history" disabled={!!project.busy || !!working} onClick={() => restore(r)}>Restore</Button>
                  <button className="btn ghost icon sm" title="Rename" aria-label={`Rename ${r.name}`} onClick={() => setRenaming({ n: r.n, name: r.name })}><Icon name="edit" /></button>
                  <button className="btn ghost icon sm danger" title="Delete this revision" aria-label={`Delete ${r.name}`}
                    onClick={() => confirm(`Delete the revision “${r.name}”? The article itself is not changed.`) &&
                      run("delete", async () => { await api.deleteRevision(project.id, r.n); if (pair && [pair.a, pair.b].includes(String(r.n))) setPair(null); reload(); })}><Icon name="trash" /></button>
                </div>
              </div>
            ))}
          </div>

          <div className="stack" style={{ gap: 16 }}>
            {pair && revisions
              ? <Compare project={project} revisions={revisions} pair={pair} setPair={setPair} onRestored={(p) => { setProject(p); reload(); }} />
              : <div className="card muted">Press <b>Compare</b> on a revision to see what changed since then, word by word.</div>}

            <div className="eyebrow" style={{ marginTop: 14 }}>Revision rounds</div>
            {rounds.map((r) => (
              <Round key={r.id} project={project} round={r} engineReady={engineReady} reload={reload}
                showChanges={(a, b) => { setPair({ a, b }); window.scrollTo?.(0, 0); document.querySelector(".main")?.scrollTo({ top: 0, behavior: "smooth" }); }} />
            ))}
            <form className="card" onSubmit={startRound}>
              <div className="h2" style={{ fontSize: 20 }}>Start a revision round</div>
              <p className="muted" style={{ margin: "4px 0 12px", maxWidth: 680 }}>
                Paste the comments of a reviewer, editor or supervisor. RAF splits them into separate points, links each to the segment it concerns and proposes
                how to revise it. You decide point by point, and RAF drafts the response letter from what actually changed.
              </p>
              <div className="stack" style={{ gap: 10 }}>
                <input className="input" value={roundName} onChange={(e) => setRoundName(e.target.value)} placeholder={`Name (optional) — e.g. Reviewer 2, Supervisor, Round ${rounds.length + 1}`} maxLength={80} aria-label="Name of the round" />
                <textarea className="textarea" rows={7} value={comments} onChange={(e) => setComments(e.target.value)} aria-label="Comments received"
                  placeholder={"1. The research gap is not stated clearly in the Introduction.\n2. The Discussion overstates causality — these are correlations.\n3. …"} />
                <div className="row between wrap">
                  <span className="muted" style={{ fontSize: 12 }}>{comments.trim() ? `${comments.trim().split(/\s+/).length} words` : ""}</span>
                  <Button variant="primary" icon="send" disabled={comments.trim().split(/\s+/).length < 5 || !!project.busy || working === "round"}>
                    {working === "round" ? "Starting…" : "Read the comments"}
                  </Button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
