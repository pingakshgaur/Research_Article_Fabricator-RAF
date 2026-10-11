import { useEffect, useRef, useState } from "react";
import { Icon, Spinner } from "./ui.jsx";

/* The Window: every segment as a sheet of paper, filling with text while RAF writes it.
 * Read-only by design — nothing here changes the run; editing happens in the Studio.
 * `sheets` comes from the event stream (see live.py): { key: { text, live, edits, marks } }. */

const CHANGE = {
  corrected: "corrected from the source", removed: "removed — not supported by its source", cited: "citation added",
  rewritten: "paragraph rewritten — it did not hold together", "re-expressed": "re-expressed — too close to a source", polished: "polished",
};

/** Text with RAF's citation markers shown as small chips. */
function Marked({ text }) {
  return text.split(/(\[(?:[RW]\d+(?:\s*[,;]\s*)?)+\])/g).map((part, i) => (/^\[[RW]\d/.test(part) ? <span key={i} className="w-cite">{part.slice(1, -1)}</span> : part));
}

/** The sheet's text with the sentences a filter just changed struck through (and their replacement beside them). */
function Body({ sheet }) {
  let pieces = [{ text: sheet.text }];
  for (const mark of sheet.marks || []) {
    pieces = pieces.flatMap((piece) => {
      if (piece.mark || !mark.before) return [piece];
      const at = piece.text.indexOf(mark.before.slice(0, 120));
      if (at < 0) return [piece];
      const end = at + Math.min(mark.before.length, piece.text.length - at);
      return [{ text: piece.text.slice(0, at) }, { text: piece.text.slice(at, end), mark }, { text: piece.text.slice(end) }];
    });
  }
  return (
    <>
      {pieces.map((piece, i) => (piece.mark ? (
        <span key={i} title={CHANGE[piece.mark.change] || piece.mark.change}>
          <del><Marked text={piece.text} /></del>{piece.mark.after && <ins> <Marked text={piece.mark.after} /></ins>}
        </span>
      ) : <Marked key={i} text={piece.text} />))}
      {sheet.live && <span className="w-live"><Marked text={sheet.live} /></span>}
      <span className="caret" />
    </>
  );
}

function Sheet({ row, seg, sheet, phase, waitingFor, focused, onFocus }) {
  const body = useRef(null);
  const active = !!sheet;
  useEffect(() => {     // follow the writing
    if (active && body.current) body.current.scrollTop = body.current.scrollHeight;
  }, [active, sheet?.text, sheet?.live, sheet?.marks?.length]);
  const state = active ? "active" : seg?.content ? "done" : seg?.status === "failed" ? "failed" : "waiting";
  const last = sheet?.edits?.[sheet.edits.length - 1];
  return (
    <button type="button" className={`sheet ${state} ${focused ? "focused" : ""}`} onClick={onFocus} aria-pressed={focused}
      title={focused ? "Back to all segments" : "Look closer"}>
      <span className="sheet-head">
        <b>{row.title}</b>
        {state === "active" && <span className="sheet-phase"><Spinner size={11} />{phase || "Writing"}</span>}
        {state === "done" && <span className="sheet-phase done"><Icon name="check" size={12} stroke={2.4} />{seg.quality.words} words</span>}
        {state === "failed" && <span className="sheet-phase bad">could not be written</span>}
        {state === "waiting" && <span className="sheet-phase muted">{waitingFor ? `after ${waitingFor}` : "waiting"}</span>}
      </span>
      <span className="sheet-body" ref={body}>
        {state === "active" && <Body sheet={sheet} />}
        {state === "done" && <Marked text={seg.content.replace(/\[\[(TABLE|FIGURE) (\d+)\]\]/g, (_, kind, n) => `▦ ${kind === "TABLE" ? "Table" : "Figure"} ${n}`)} />}
        {state === "waiting" && <span className="sheet-empty">{row.kind === "manual" ? "You write this one, in the Studio." : "Not started yet."}</span>}
        {state === "failed" && <span className="sheet-empty">{seg.error}</span>}
      </span>
      {state === "active" && last && <span className="sheet-note"><Icon name="shield" size={12} />{CHANGE[last.change] || last.change}</span>}
    </button>
  );
}

export default function Window({ project, sheets, events }) {
  const [focus, setFocus] = useState(null);
  const rows = project.structure.filter((r) => project.selected.includes(r.key));
  const title = Object.fromEntries(project.structure.map((r) => [r.key, r.title]));

  // what is happening to each segment: the latest stage message that names it ("Introduction · move 2/4: Establishing the niche")
  const phase = {};
  for (let i = events.length - 1; i >= 0 && Object.keys(phase).length < rows.length; i--) {
    const e = events[i];
    if (e.kind === "stage" && e.key && !(e.key in phase)) {
      phase[e.key] = e.message.replace(/^\[Agent \d\] /, "").replace(new RegExp(`^(Writing: )?${title[e.key]?.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*[·:]?\\s*`), "")
        .replace(/^(Hallucination filter|Style & naturalness pass|Originality & integrity checks): .*$/, "$1") || "Writing";
    }
  }
  const shown = focus && rows.some((r) => r.key === focus) ? rows.filter((r) => r.key === focus) : rows;
  const writing = Object.keys(sheets).filter((k) => rows.some((r) => r.key === k));

  return (
    <div className={`window ${focus ? "one" : ""}`} aria-live="off">
      <div className="window-bar">
        <span className="muted">
          {writing.length ? `Writing now: ${writing.map((k) => title[k]).join(" · ")}` : project.busy ? "Preparing — the sheets fill in once writing begins." : "Nothing is being written at the moment."}
        </span>
        <span className="muted">Look, don’t touch: this view never changes the run. {focus ? "Click the sheet to see them all." : "Click a sheet to look closer."}</span>
      </div>
      <div className="window-grid">
        {shown.map((row) => (
          <Sheet key={row.key} row={row} seg={project.segments[row.key]} sheet={sheets[row.key]} phase={phase[row.key]} focused={focus === row.key}
            waitingFor={row.depends_on.filter((d) => project.selected.includes(d) && !project.segments[d]?.content).map((d) => title[d])[0]}
            onFocus={() => setFocus(focus === row.key ? null : row.key)} />
        ))}
      </div>
    </div>
  );
}
