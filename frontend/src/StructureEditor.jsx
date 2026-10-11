import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "./api.js";
import { Button, Icon, Segmented, Select, Spinner, Toggle, useToast } from "./ui.jsx";

/* The structure of one article, in a drawer that opens from the Segments page, the Studio and the Publish page:
 * rename segments, drag them into another order, leave them out of the document, add your own, delete the ones you added,
 * and ask RAF to write a segment that has no text yet. Everything shown comes from project.structure (see structure.py). */

const EMPTY = { title: "", kind: "generated", purpose: "", after: "", words: 400, cites: true, moves: null };

function AddSegment({ project, setProject, engineReady, onAdded }) {
  const toast = useToast();
  const [gallery, setGallery] = useState([]);
  const [form, setForm] = useState(EMPTY);
  const [busy, setBusy] = useState("");
  useEffect(() => { api.gallery().then(setGallery).catch(() => {}); }, []);

  const taken = new Set(project.structure.map((r) => r.title.toLowerCase()));
  const places = [{ value: "", label: "Just before the references" }, ...project.structure.filter((r) => !r.front).map((r) => ({ value: r.key, label: `After ${r.title}` }))];
  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value?.target ? value.target.value : value, ...(key === "title" || key === "purpose" ? { moves: null } : {}) }));
  const add = async (body, name) => {
    setBusy(name);
    try {
      const out = await api.addSegment(project.id, body);
      setProject(out.project);
      setForm(EMPTY);
      toast(`“${out.project.structure.find((r) => r.key === out.key).title}” added`);
      onAdded?.(out.key);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy("");
    }
  };
  const propose = async () => {
    setBusy("propose");
    try {
      const out = await api.proposeParts(project.id, form.title, form.purpose);
      setForm((f) => ({ ...f, moves: out.moves }));
      toast(out.by === "model" ? "RAF proposed the parts — edit them if you like" : "The model is not available; these are RAF's usual three parts");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setBusy("");
    }
  };
  const setMove = (i, key, value) => setForm((f) => ({ ...f, moves: f.moves.map((m, j) => (j === i ? { ...m, [key]: value } : m)) }));
  const ready = form.title.trim().length >= 2 && (form.kind === "manual" || form.purpose.trim().length >= 15);

  return (
    <section className="card">
      <h5>Add a segment</h5>
      <div className="row wrap" style={{ gap: 6 }}>
        {gallery.filter((g) => !taken.has(g.title.toLowerCase())).map((g) => (
          <button key={g.id} type="button" className="tool" disabled={!!busy} title={g.purpose || g.starter || "Written by you"} onClick={() => add({ gallery: g.id }, g.id)}>
            {busy === g.id ? <Spinner size={13} /> : <Icon name="plus" size={13} />}{g.title}
            <span className="muted" style={{ fontSize: 11 }}>{g.kind === "manual" ? "you write" : "RAF writes"}</span>
          </button>
        ))}
      </div>
      <form className="stack" style={{ gap: 12, marginTop: 16 }} onSubmit={(e) => { e.preventDefault(); add({ ...form, moves: form.moves || [] }, "form"); }}>
        <div className="field">
          <label htmlFor="ns-title">Or one of your own</label>
          <input id="ns-title" className="input" value={form.title} onChange={set("title")} maxLength={90} placeholder="Title, e.g. Regional Context" />
        </div>
        <Segmented value={form.kind} onChange={set("kind")} options={[{ value: "generated", label: "RAF writes it" }, { value: "manual", label: "I write it" }]} />
        {form.kind === "generated" && (
          <>
            <div className="field">
              <label htmlFor="ns-purpose">What should it do? <span className="opt">a sentence or two — RAF writes from this</span></label>
              <textarea id="ns-purpose" className="textarea" rows={3} value={form.purpose} onChange={set("purpose")} maxLength={600}
                placeholder="Describe the regional setting of the study and why it matters for the research question." />
            </div>
            <div className="grid-2">
              <div className="field">
                <label htmlFor="ns-words">Length <span className="mono">{form.words} words</span></label>
                <input id="ns-words" type="range" className="range" min={100} max={2000} step={50} value={form.words} onChange={(e) => set("words")(Number(e.target.value))} />
              </div>
              <Toggle checked={form.cites} onChange={set("cites")} label="Use the sources" hint="Draw on the references and cite them" />
            </div>
            {form.moves && (
              <div className="stack" style={{ gap: 8 }}>
                {form.moves.map((m, i) => (
                  <div key={i} className="part">
                    <input className="input" value={m.name} onChange={(e) => setMove(i, "name", e.target.value)} aria-label={`Name of part ${i + 1}`} />
                    <textarea className="textarea" rows={2} value={m.instruction} onChange={(e) => setMove(i, "instruction", e.target.value)} aria-label={`What part ${i + 1} does`} />
                  </div>
                ))}
              </div>
            )}
          </>
        )}
        <div className="field"><label>Where</label><Select value={form.after} onChange={set("after")} options={places} /></div>
        <div className="row between wrap">
          {form.kind === "generated"
            ? <Button type="button" size="sm" icon={busy === "propose" ? undefined : "spark"} disabled={!ready || !!busy} onClick={propose}
                title={engineReady ? "RAF suggests which parts the segment should have" : "The model is not available — RAF will show its usual three parts"}>
                {busy === "propose" && <Spinner size={13} />}{form.moves ? "Propose the parts again" : "Let RAF propose its parts"}
              </Button>
            : <span className="muted" style={{ fontSize: 12 }}>It appears in the Studio at once, ready for you to type.</span>}
          <Button variant="primary" icon="plus" disabled={!ready || !!busy}>{busy === "form" ? "Adding…" : "Add segment"}</Button>
        </div>
        {form.kind === "generated" && !form.moves && <span className="muted" style={{ fontSize: 12 }}>Without a proposal RAF uses three parts: purpose and context, core content, link to the article.</span>}
      </form>
    </section>
  );
}

export default function StructureEditor({ project, setProject, open, onClose, health, onAdded }) {
  const toast = useToast();
  const [renaming, setRenaming] = useState(null);   // { key, title }
  const [drag, setDrag] = useState(null);           // { from, over } while a row is being dragged
  const [working, setWorking] = useState("");
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && !renaming && onClose();
    if (open) addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [open, onClose, renaming]);
  if (!open) return null;

  const rows = project.structure;
  const body = rows.filter((r) => !r.front);
  const engineReady = health?.ready ?? (health?.ollama && health?.model_available);   // the local model, or a cloud model with a key
  const fabricated = Object.values(project.segments).some((s) => s.content);
  const busyAll = !!project.busy;
  const run = async (key, fn, message) => {
    setWorking(key);
    try { setProject(await fn()); if (message) toast(message); } catch (err) { toast(err.message, "error"); } finally { setWorking(""); }
  };
  const move = (from, to) => {
    if (to < 0 || to >= body.length || from === to) return;
    const keys = body.map((r) => r.key);
    keys.splice(to, 0, keys.splice(from, 1)[0]);
    run("order", () => api.setOrder(project.id, keys));
  };
  const saveName = (r) => {
    const title = renaming.title.trim();
    setRenaming(null);
    if (title !== r.title) run(r.key, () => api.renameSegment(project.id, r.key, title), title ? "Renamed" : "Back to the usual title");
  };

  const row = (r, i) => {
    const seg = project.segments[r.key];
    const status = !r.written ? (r.kind === "manual" ? "empty" : "not written") : seg.status;
    return (
      <div key={r.key} className={`struct-row ${r.included ? "" : "out"} ${drag?.over === i && !r.front ? "over" : ""}`}
        draggable={!r.front && !renaming && !busyAll} onDragStart={(e) => { e.dataTransfer.effectAllowed = "move"; setDrag({ from: i, over: i }); }}
        onDragOver={(e) => { if (drag && !r.front) { e.preventDefault(); if (drag.over !== i) setDrag({ ...drag, over: i }); } }}
        onDrop={(e) => { e.preventDefault(); if (drag) move(drag.from, i); setDrag(null); }} onDragEnd={() => setDrag(null)}>
        <span className="struct-grip" aria-hidden="true">{r.front ? "" : "⋮⋮"}</span>
        <div style={{ minWidth: 0 }}>
          {renaming?.key === r.key ? (
            <input className="input" autoFocus value={renaming.title} maxLength={90} aria-label="Segment title" onChange={(e) => setRenaming({ key: r.key, title: e.target.value })}
              onBlur={() => saveName(r)} onKeyDown={(e) => { if (e.key === "Enter") saveName(r); if (e.key === "Escape") { e.stopPropagation(); setRenaming(null); } }} />
          ) : r.front ? <b>{r.title}</b> : (
            <button type="button" className="struct-title" title="Rename" onClick={() => setRenaming({ key: r.key, title: r.title })}>
              {r.numbered && r.included && r.written ? <span className="mono muted">{body.filter((x, j) => j <= i && x.numbered && x.included && x.written).length}.</span> : null}
              <b>{r.title}</b><Icon name="edit" size={12} />
            </button>
          )}
          <div className="struct-meta muted">
            <span>{r.kind === "builtin" ? "built-in" : r.kind === "manual" ? "added · you write" : "added · RAF writes"}</span>
            <span>{status}</span>
            {!r.custom && r.title !== r.default_title && (
              <button type="button" className="link" onClick={() => run(r.key, () => api.renameSegment(project.id, r.key, ""), "Back to the usual title")}>use “{r.default_title}”</button>
            )}
            {!r.written && r.kind !== "manual" && fabricated && (
              <button type="button" className="link" disabled={!engineReady || busyAll} title={engineReady ? undefined : "Start Ollama or add a cloud model key to write"}
                onClick={() => run(r.key, () => api.writeSegment(project.id, r.key), `RAF is writing ${r.title}`)}>write it now</button>
            )}
          </div>
        </div>
        {working === r.key ? <Spinner /> : (
          <div className="row" style={{ gap: 2 }}>
            {!r.front && (
              <>
                <button className="btn ghost icon sm" disabled={i === 0 || busyAll} aria-label={`Move ${r.title} up`} title="Move up" onClick={() => move(i, i - 1)}><Icon name="chevron" size={14} /></button>
                <button className="btn ghost icon sm down" disabled={i === body.length - 1 || busyAll} aria-label={`Move ${r.title} down`} title="Move down" onClick={() => move(i, i + 1)}><Icon name="chevron" size={14} /></button>
              </>
            )}
            {r.custom && (
              <button className="btn ghost icon sm danger" disabled={busyAll} aria-label={`Delete ${r.title}`} title="Delete this segment"
                onClick={() => confirm(`Delete “${r.title}”${r.written ? " and its text" : ""}? Save a revision first if you may want it back.`) &&
                  run(r.key, () => api.deleteSegment(project.id, r.key), "Segment deleted")}><Icon name="trash" /></button>
            )}
          </div>
        )}
        <label className="struct-in" title={r.included ? "In the document — switch off to leave it out" : "Left out of the document — its text is kept"}>
          <input type="checkbox" checked={r.included} aria-label={`${r.title} in the document`}
            onChange={(e) => run(r.key, () => api.setIncluded(project.id, r.key, e.target.checked), e.target.checked ? `${r.title} is back in the document` : `${r.title} left out of the document`)} />
          <span className="track" />
        </label>
      </div>
    );
  };

  // rendered on <body>: inside the page it would sit under the top bar
  return createPortal(
    <div className="drawer-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer struct-drawer" role="dialog" aria-label="Article structure">
        <header className="drawer-head">
          <div>
            <div className="eyebrow">Article structure</div>
            <div className="h2" style={{ fontSize: 24, margin: "6px 0 0" }}>Arrange, rename, add</div>
          </div>
          <button className="btn ghost icon" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </header>
        <div className="drawer-body">
          <section className="card">
            <h5>Front matter <span className="muted" style={{ letterSpacing: 0, textTransform: "none" }}>always first</span></h5>
            {rows.filter((r) => r.front).map((r) => row(r, -1))}
          </section>
          <section className="card">
            <h5>Body <span className="muted" style={{ letterSpacing: 0, textTransform: "none" }}>drag to reorder · click a title to rename · switch off to leave out</span></h5>
            {body.map(row)}
            <p className="muted" style={{ fontSize: 12, margin: "12px 0 0" }}>
              Section numbers and the reference list follow whatever you arrange here. A segment that is left out keeps its text and can come back any time.
            </p>
          </section>
          <AddSegment project={project} setProject={setProject} engineReady={engineReady} onAdded={onAdded} />
        </div>
      </aside>
    </div>,
    document.body,
  );
}
