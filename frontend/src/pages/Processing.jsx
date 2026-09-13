import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { Button, Icon, useToast } from "../ui.jsx";

const STAGES = [
  { key: "parsing", title: "Reading references", sub: "Parse · metadata · chunk" },
  { key: "research", title: "Online research", sub: "Scholarly databases & web" },
  { key: "indexing", title: "Building the index", sub: "Neural + BM25 + TF-IDF fusion" },
  { key: "analysis", title: "Data analysis", sub: "Tests · tables · figures" },
  { key: "writing", title: "Writing segments", sub: "Moves · notes · drafts · review" },
  { key: "guard", title: "Originality & integrity", sub: "Overlap · paraphrase · numbers" },
];
const LENGTHABLE = new Set(["abstract", "introduction", "literature_review", "methodology", "results", "discussion", "conclusion", "limitations"]);

const fmtTime = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

export function fmtDuration(seconds, compact = false) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  if (compact) return h ? `${h}h ${m}m` : m ? `${m}m ${sec}s` : `${sec}s`;
  return [h, m, sec].map((v) => String(v).padStart(2, "0")).join(":");
}

/** Seconds elapsed for the whole run, including earlier (resumed) sessions. */
export function runElapsed(run, now) {
  if (!run) return 0;
  return (run.elapsed_before || 0) + (run.status === "running" && run.session_started ? now - run.session_started : 0);
}

function useNow(active) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

function LengthChip({ project, seg, setProject }) {
  const [editing, setEditing] = useState(false);
  const current = project.segment_lengths?.[seg.key] ?? seg.quality.target_words;
  const [value, setValue] = useState(current || "");
  if (!LENGTHABLE.has(seg.key)) return <span className="mono muted" style={{ fontSize: 11 }}>{seg.status}</span>;
  if (!editing)
    return (
      <button className="btn ghost sm" style={{ height: 22, padding: "0 6px", fontSize: 11 }} title="Change the length before this segment starts"
        onClick={() => { setValue(current || ""); setEditing(true); }}>
        {current ? `${current}w` : "set length"} ✎
      </button>
    );
  const save = async () => {
    try { setProject(await api.setLengths(project.id, { [seg.key]: Number(value) })); } catch { /* ignore */ }
    setEditing(false);
  };
  return (
    <input className="input length-input" autoFocus type="number" min={100} step={10} value={value} style={{ height: 26, width: 78, padding: "0 6px", fontSize: 12 }}
      onChange={(e) => setValue(e.target.value)} onBlur={save} onKeyDown={(e) => e.key === "Enter" && save()} />
  );
}

export default function Processing({ project, setProject, events, navigate }) {
  const consoleRef = useRef(null);
  const toast = useToast();
  const run = project.run || {};
  const working = !!project.busy;
  const now = useNow(working || run.status === "running");

  const runStart = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) if (events[i].kind === "job" && events[i].state === "started" && events[i].job === "Article generation") return i;
    return 0;
  }, [events]);
  const runEvents = events.slice(runStart);
  const seen = new Set(runEvents.filter((e) => e.stage).map((e) => e.stage));
  const current = [...runEvents].reverse().find((e) => e.stage)?.stage;
  const currentMessage = [...runEvents].reverse().find((e) => e.kind === "stage")?.message;

  useEffect(() => {
    const el = consoleRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  const segs = project.selected.map((k) => project.segments[k]).filter(Boolean);
  const doneCount = segs.filter((s) => ["draft", "approved"].includes(s.status)).length;
  const lastError = [...runEvents].reverse().find((e) => e.kind === "error");
  const finished = !working && (run.status === "completed" || (segs.length > 0 && doneCount === segs.length));
  const stopped = !working && !finished;
  const [resuming, setResuming] = useState(false);

  const total = runElapsed(run, now);
  const stageSeconds = (key) => (run.stages?.[key] || 0) + (run.stage_started?.[key] && run.status === "running" ? now - run.stage_started[key] : 0);
  const segSeconds = (key) => (run.segment_seconds?.[key] || 0) + (run.segment_started?.[key] && run.status === "running" ? now - run.segment_started[key] : 0);

  const resume = async () => {
    setResuming(true);
    try {
      const o = project.options || {};
      setProject(await api.generate(project.id, {
        segments: project.selected, web_research: o.web_research ?? true, data_analysis: o.data_analysis ?? true,
        depth: o.depth ?? "thorough", agents: o.agents ?? 1, resume: true,
      }));
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setResuming(false);
    }
  };

  return (
    <div className="page wide">
      <div className="row between wrap" style={{ marginBottom: 20, alignItems: "flex-start" }}>
        <div style={{ flex: 1, minWidth: 320 }}>
          <div className="eyebrow">Step 04 — Fabrication</div>
          <h1 className="h2" style={{ fontSize: 38, marginTop: 10 }}>
            {working ? "RAF is at work." : finished ? "The draft is ready." : "Fabrication stopped."}
          </h1>
          <p className="muted" style={{ margin: 0, maxWidth: 760, color: stopped && lastError ? "var(--bad)" : undefined }}>
            {working ? currentMessage || "Preparing…" : finished ? "Open the studio to review every segment."
              : lastError ? `${lastError.message} — Resume continues from the last checkpoint.` : "The run is paused. Resume continues from the last checkpoint."}
          </p>
          <div className="row wrap" style={{ marginTop: 16 }}>
            {stopped && (
              <Button variant="primary" icon="refresh" disabled={resuming} onClick={resume}>{resuming ? "Resuming…" : "Resume from checkpoint"}</Button>
            )}
            <span className="badge accent mono">{doneCount} / {segs.length} segments</span>
            <span className="badge mono" title="Progress markers saved so far">⚑ {run.checkpoints || 0} checkpoints</span>
            {(run.agents || 1) > 1 && <span className="badge mono">{run.agents} agents</span>}
            <Button variant={finished ? "primary" : ""} iconRight="arrow" disabled={!doneCount} onClick={() => navigate(project.id, "studio")}>Open studio</Button>
          </div>
        </div>
        <div className="timer-card">
          <div className="timer-label"><span className={`dot ${working ? "live" : finished ? "ok" : ""}`} /> {working ? "Fabricating" : finished ? "Completed in" : "Time so far"}</div>
          <div className="timer-value mono">{fmtDuration(total)}</div>
          <div className="timer-sub muted">
            {working && current && run.stage_started?.[current === "guard" ? "writing" : current] !== undefined
              ? `this stage ${fmtDuration(stageSeconds(current === "guard" ? "writing" : current), true)}`
              : `${run.sessions || 0} session${run.sessions === 1 ? "" : "s"}`}
          </div>
        </div>
      </div>

      <div className="proc">
        <div className="card">
          <div className="stage-list">
            {STAGES.map((s) => {
              const state = current === s.key && !finished ? (working ? "active" : "failed") : seen.has(s.key) || run.stages?.[s.key] ? "done" : "";
              const secs = stageSeconds(s.key);
              return (
                <div key={s.key} className={`stage ${state}`}>
                  <span className="s-dot">{state === "done" ? <Icon name="check" size={13} stroke={2.4} /> : state === "failed" ? <Icon name="x" size={13} stroke={2.4} /> : null}</span>
                  <span style={{ display: "flex", justifyContent: "space-between", gap: 10 }}>
                    <span><b>{s.title}</b><small>{s.sub}</small></span>
                    {secs > 0 && <span className="mono muted" style={{ fontSize: 11, whiteSpace: "nowrap" }}>{fmtDuration(secs, true)}</span>}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div>
          <div className="console" ref={consoleRef} aria-live="polite">
            {runEvents.filter((e) => ["log", "stage", "error", "done", "job", "checkpoint"].includes(e.kind)).map((e, i) => (
              <div key={i} className={`line ${e.kind === "stage" ? "stage" : ""} ${e.kind === "error" ? "error" : ""} ${e.kind === "checkpoint" ? "checkpoint" : ""}`}>
                <span className="ts">{fmtTime(e.t)}</span>
                <span>{e.kind === "stage" ? "▸ " : ""}{e.message}</span>
              </div>
            ))}
            {working && <span className="caret" />}
          </div>
          <div className="seg-progress">
            {segs.map((s) => {
              const secs = segSeconds(s.key);
              return (
                <div key={s.key} className={`seg-chip ${["working", "revising"].includes(s.status) ? "working" : ""}`}>
                  <span className={`status-dot ${s.status}`} />
                  <span style={{ flex: 1 }}>{s.title}</span>
                  {s.status === "draft" || s.status === "approved"
                    ? <span className="mono muted" style={{ fontSize: 11 }}>{s.quality.words}w{secs ? ` · ${fmtDuration(secs, true)}` : ""}</span>
                    : s.status === "working"
                      ? <span className="mono muted" style={{ fontSize: 11 }}>{fmtDuration(secs, true)}</span>
                      : s.status === "failed" && !working
                        ? <span className="mono" style={{ fontSize: 11, color: "var(--bad)" }}>failed</span>
                        : <LengthChip project={project} seg={s} setProject={setProject} />}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
