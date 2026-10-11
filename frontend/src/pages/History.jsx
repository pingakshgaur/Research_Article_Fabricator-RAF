import { useEffect, useMemo, useState } from "react";
import { api, saveBlob } from "../api.js";
import { Button, Icon, Segmented, Select, Spinner, useToast } from "../ui.jsx";

const GROUPS = [
  { value: "all", label: "Everything", test: () => true },
  { value: "writing", label: "Writing", test: (k) => k.startsWith("segment.") },
  { value: "runs", label: "Fabrication", test: (k) => k.startsWith("run.") || k.startsWith("review.") },
  { value: "revisions", label: "Revisions", test: (k) => k.startsWith("revision.") || k.startsWith("round.") },
  { value: "publishing", label: "Publishing", test: (k) => k.startsWith("article.") },
  { value: "project", label: "Project", test: (k) => /^(project|references|datasets|settings|stage)\./.test(k) },
];
const ICONS = { segment: "edit", run: "spark", review: "shield", revision: "history", round: "send", article: "download", project: "file", references: "upload",
  datasets: "data", settings: "sliders", stage: "arrow" };

const day = (t) => new Date(t * 1000).toLocaleDateString([], { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
const stamp = (t) => new Date(t * 1000).toISOString().slice(0, 19).replace("T", " ");

export default function History({ project }) {
  const toast = useToast();
  const [events, setEvents] = useState(null);
  const [group, setGroup] = useState("all");
  const [segment, setSegment] = useState("all");
  const [actor, setActor] = useState("all");
  const [statement, setStatement] = useState(null);
  const [drafting, setDrafting] = useState(false);

  // project.updated changes whenever anything is saved, so the timeline follows live work
  useEffect(() => { api.history(project.id).then(setEvents).catch(() => setEvents([])); }, [project.id, project.updated]);

  const titleOf = (key) => project.segments[key]?.title || key;
  const segments = useMemo(() => [...new Set((events || []).map((e) => e.segment).filter(Boolean))], [events]);
  const shown = useMemo(() => {
    const test = GROUPS.find((g) => g.value === group).test;
    return (events || []).filter((e) => test(e.kind) && (segment === "all" || e.segment === segment) && (actor === "all" || e.actor === actor));
  }, [events, group, segment, actor]);
  const days = useMemo(() => {
    const out = [];
    for (const e of shown) {
      const d = day(e.t);
      if (out[out.length - 1]?.day !== d) out.push({ day: d, items: [] });
      out[out.length - 1].items.push(e);
    }
    return out;
  }, [shown]);

  const exportAs = (fmt) => {
    const rows = [...shown].reverse();
    const name = `${project.title.replace(/[^A-Za-z0-9]+/g, "_").slice(0, 50)}_history.${fmt}`;
    if (fmt === "csv") {
      const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
      const lines = [["time", "who", "event", "segment", "summary"].join(","),
        ...rows.map((e) => [stamp(e.t), e.actor, e.kind, e.segment ? titleOf(e.segment) : "", e.summary].map(cell).join(","))];
      saveBlob(new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv" }), name);
    } else {
      const lines = [`# History — ${project.title}`, ""];
      let last = "";
      for (const e of rows) {
        if (day(e.t) !== last) { last = day(e.t); lines.push("", `## ${last}`, ""); }
        lines.push(`- ${clock(e.t)} · **${e.actor}** · ${e.summary}`);
      }
      saveBlob(new Blob([lines.join("\n")], { type: "text/markdown" }), name);
    }
  };

  const draft = async () => {
    setDrafting(true);
    try { setStatement(await api.aiStatement(project.id)); } catch (err) { toast(err.message, "error"); } finally { setDrafting(false); }
  };
  const f = statement?.facts;

  return (
    <div className="page">
      <div className="eyebrow rise">History</div>
      <h1 className="display rise" style={{ "--i": 1, fontSize: "clamp(30px,3.8vw,48px)" }}>What happened to <em>this article.</em></h1>
      <p className="lede rise" style={{ "--i": 2 }}>
        Every step is recorded here from the day the project was created: what RAF wrote, what you changed, and when. Nothing is ever removed from this list.
      </p>

      <div className="row between wrap rise" style={{ "--i": 3, margin: "26px 0 12px", gap: 12 }}>
        <Segmented value={group} onChange={setGroup} options={GROUPS.map(({ value, label }) => ({ value, label }))} />
        <div className="row">
          <Button size="sm" icon="download" disabled={!shown.length} onClick={() => exportAs("csv")}>CSV</Button>
          <Button size="sm" icon="download" disabled={!shown.length} onClick={() => exportAs("md")}>Markdown</Button>
        </div>
      </div>
      <div className="row wrap rise" style={{ "--i": 4, marginBottom: 18 }}>
        <div style={{ width: 240 }}>
          <Select value={segment} onChange={setSegment} aria-label="Filter by segment"
            options={[{ value: "all", label: "All segments" }, ...segments.map((s) => ({ value: s, label: titleOf(s) }))]} />
        </div>
        <Segmented value={actor} onChange={setActor} options={[{ value: "all", label: "You and RAF" }, { value: "you", label: "You" }, { value: "RAF", label: "RAF" }]} />
        <span className="mono muted" style={{ fontSize: 12 }}>{events ? `${shown.length} of ${events.length} events` : ""}</span>
      </div>

      {!events && <div className="empty"><Spinner /> Loading…</div>}
      {events && !shown.length && <div className="empty card">Nothing recorded matches these filters.</div>}
      <div className="timeline">
        {days.map((d) => (
          <section key={d.day}>
            <h3 className="tl-day">{d.day}</h3>
            {d.items.map((e, i) => (
              <div key={`${e.t}-${i}`} className={`tl-item ${e.actor === "RAF" ? "raf" : "you"}`}>
                <span className="tl-time mono">{clock(e.t)}</span>
                <span className="tl-icon"><Icon name={ICONS[e.kind.split(".")[0]] || "file"} size={14} /></span>
                <div>
                  <div className="tl-summary">{e.summary}</div>
                  <div className="tl-meta muted">
                    <span className={`badge ${e.actor === "RAF" ? "accent" : ""}`}>{e.actor === "RAF" ? "RAF" : "You"}</span>
                    {e.segment && <span>{titleOf(e.segment)}</span>}
                    {e.meta?.version && <span>version {e.meta.version}</span>}
                    {e.meta?.reconstructed && <span title="This project was made before RAF kept a history. The entry was rebuilt from the project's saved versions.">rebuilt from saved versions</span>}
                  </div>
                </div>
              </div>
            ))}
          </section>
        ))}
      </div>

      <div className="card rise" style={{ marginTop: 34 }}>
        <div className="row between wrap" style={{ alignItems: "flex-start" }}>
          <div style={{ maxWidth: 620 }}>
            <div className="eyebrow" style={{ marginBottom: 6 }}>For your submission</div>
            <div className="h2" style={{ fontSize: 22 }}>AI-use statement</div>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              Many journals ask authors to declare how AI tools were used. RAF drafts that paragraph from the facts recorded above, and from nothing else.
              Read it, correct it, and follow your journal's own wording rules.
            </p>
          </div>
          <Button icon="spark" disabled={drafting} onClick={draft}>{drafting ? "Drafting…" : statement ? "Draft again" : "Draft the statement"}</Button>
        </div>
        {statement && !statement.statement && <p className="muted" style={{ marginBottom: 0 }}>RAF has not drafted any part of this article, so there is nothing to declare yet.</p>}
        {statement?.statement && (
          <>
            <textarea className="textarea serif" rows={7} style={{ marginTop: 16, fontSize: 15, lineHeight: 1.65 }} value={statement.statement}
              onChange={(e) => setStatement({ ...statement, statement: e.target.value })} aria-label="AI-use statement" />
            <div className="row between wrap" style={{ marginTop: 10 }}>
              <span className="muted" style={{ fontSize: 12 }}>
                Based on: {f.drafted_by_raf.length} segment{f.drafted_by_raf.length === 1 ? "" : "s"} drafted by RAF · {f.manual_edits} manual edit{f.manual_edits === 1 ? "" : "s"} ·
                {" "}{f.revisions_requested} revision{f.revisions_requested === 1 ? "" : "s"} · {f.tools_used.length} text tool{f.tools_used.length === 1 ? "" : "s"} · model {f.models.join(", ")}
              </span>
              <Button size="sm" icon="copy" onClick={() => navigator.clipboard.writeText(statement.statement).then(() => toast("Copied"), () => toast("Could not copy — select the text and copy it by hand", "error"))}>Copy</Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
