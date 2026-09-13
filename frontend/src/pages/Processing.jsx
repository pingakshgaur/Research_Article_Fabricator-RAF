import { useEffect, useMemo, useRef } from "react";
import { Button, Icon } from "../ui.jsx";

const STAGES = [
  { key: "parsing", title: "Reading references", sub: "Parse · metadata · chunk" },
  { key: "research", title: "Online research", sub: "Scholarly databases & web" },
  { key: "indexing", title: "Building the index", sub: "Neural + BM25 + TF-IDF fusion" },
  { key: "analysis", title: "Data analysis", sub: "Tests · tables · figures" },
  { key: "writing", title: "Writing segments", sub: "Moves · notes · drafts · review" },
  { key: "guard", title: "Originality & integrity", sub: "Overlap · paraphrase · numbers" },
];

const fmtTime = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

export default function Processing({ project, events, navigate }) {
  const consoleRef = useRef(null);
  const runStart = useMemo(() => {
    for (let i = events.length - 1; i >= 0; i--) if (events[i].kind === "job" && events[i].state === "started" && events[i].job === "Article generation") return i;
    return 0;
  }, [events]);
  const run = events.slice(runStart);
  const seen = new Set(run.filter((e) => e.stage).map((e) => e.stage));
  const current = [...run].reverse().find((e) => e.stage)?.stage;
  const finished = run.some((e) => e.kind === "done") || (!project.busy && run.some((e) => e.kind === "job" && e.state !== "started"));
  const currentMessage = [...run].reverse().find((e) => e.kind === "stage")?.message;

  useEffect(() => {
    const el = consoleRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  const segs = project.selected.map((k) => project.segments[k]).filter(Boolean);
  const doneCount = segs.filter((s) => ["draft", "approved"].includes(s.status)).length;

  return (
    <div className="page wide">
      <div className="row between wrap" style={{ marginBottom: 20 }}>
        <div>
          <div className="eyebrow">Step 04 — Fabrication</div>
          <h1 className="h2" style={{ fontSize: 38, marginTop: 10 }}>{finished ? "The draft is ready." : "RAF is at work."}</h1>
          <p className="muted" style={{ margin: 0 }}>{finished ? "Open the studio to review every segment." : currentMessage || "Preparing…"}</p>
        </div>
        <div className="row">
          <span className="badge accent mono">{doneCount} / {segs.length} segments</span>
          <Button variant="primary" iconRight="arrow" disabled={!doneCount} onClick={() => navigate(project.id, "studio")}>Open studio</Button>
        </div>
      </div>

      <div className="proc">
        <div className="card">
          <div className="stage-list">
            {STAGES.map((s) => {
              const state = finished ? (seen.has(s.key) ? "done" : "") : current === s.key ? "active" : seen.has(s.key) ? "done" : "";
              return (
                <div key={s.key} className={`stage ${state}`}>
                  <span className="s-dot">{state === "done" ? <Icon name="check" size={13} stroke={2.4} /> : null}</span>
                  <span><b>{s.title}</b><small>{s.sub}</small></span>
                </div>
              );
            })}
          </div>
        </div>

        <div>
          <div className="console" ref={consoleRef} aria-live="polite">
            {run.filter((e) => ["log", "stage", "error", "done", "job"].includes(e.kind)).map((e, i) => (
              <div key={i} className={`line ${e.kind === "stage" ? "stage" : ""} ${e.kind === "error" ? "error" : ""}`}>
                <span className="ts">{fmtTime(e.t)}</span>
                <span>{e.kind === "stage" ? "▸ " : ""}{e.message}</span>
              </div>
            ))}
            {!finished && <span className="caret" />}
          </div>
          <div className="seg-progress">
            {segs.map((s) => (
              <div key={s.key} className={`seg-chip ${["working", "revising"].includes(s.status) ? "working" : ""}`}>
                <span className={`status-dot ${s.status}`} />
                <span style={{ flex: 1 }}>{s.title}</span>
                <span className="mono muted" style={{ fontSize: 11 }}>{s.status === "draft" ? `${s.quality.words}w` : s.status}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
