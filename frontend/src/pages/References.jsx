import { useRef, useState } from "react";
import { api } from "../api.js";
import { Button, Icon, Ring, Spinner, useToast } from "../ui.jsx";

const MODES = [
  { key: "references", name: "My references", blurb: "RAF writes from the 10–20 articles you upload, and may add online sources beside them." },
  { key: "mixed", name: "Mixed", blurb: "Upload what you have, from one file upward. RAF tops it up with a deeper online search and reads the open-access papers in full." },
  { key: "research", name: "Research only", blurb: "No files. RAF builds the reading list itself from scholarly databases and shows it to you before writing." },
];

function Dropzone({ accept, onFiles, title, subtitle, disabled }) {
  const [over, setOver] = useState(false);
  const input = useRef(null);
  return (
    <div className={`dropzone ${over ? "over" : ""}`} role="button" tabIndex={0}
      onClick={() => !disabled && input.current.click()}
      onKeyDown={(e) => e.key === "Enter" && input.current.click()}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => { e.preventDefault(); setOver(false); if (!disabled) onFiles(e.dataTransfer.files); }}>
      <Icon name="upload" size={26} />
      <div className="big">{title}</div>
      <div className="muted">{subtitle}</div>
      <input ref={input} type="file" multiple accept={accept} hidden onChange={(e) => { onFiles(e.target.files); e.target.value = ""; }} />
    </div>
  );
}

export default function References({ project, setProject, navigate, health }) {
  const toast = useToast();
  const [uploading, setUploading] = useState(false);
  const usual = health?.limits?.min_references ?? 10;
  const mode = project.source_mode || "references";
  const min = { references: usual, mixed: 1, research: 0 }[mode];     // how many files this source mode needs
  const max = health?.limits?.max_references ?? 20;
  const count = project.references.length;

  const upload = async (files, kind) => {
    if (!files?.length) return;
    setUploading(true);
    try {
      const p = kind === "data" ? await api.uploadData(project.id, files) : await api.uploadRefs(project.id, files);
      setProject(p);
      toast(`${files.length} file${files.length > 1 ? "s" : ""} added`);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setUploading(false);
    }
  };

  const next = async () => {
    try {
      setProject(await api.stage(project.id, "segments"));
      navigate(project.id, "segments");
    } catch (err) {
      toast(err.message, "error");
    }
  };

  return (
    <div className="page">
      <div className="eyebrow rise">Step 02 — References</div>
      <h1 className="display rise" style={{ "--i": 1, fontSize: "clamp(34px,4.4vw,56px)" }}>Give RAF its <em>reading list.</em></h1>
      <p className="lede rise" style={{ "--i": 2 }}>
        {mode === "research"
          ? <>RAF will find the sources for <b>“{project.title}”</b> itself. You can still add files; each one you upload is read in full.</>
          : <>Upload {mode === "mixed" ? "at least one reference article" : `${min}–${max} reference articles`} for <b>“{project.title}”</b>. RAF reads them in full, extracts
            citation metadata and uses them as {mode === "mixed" ? "the core of" : "the primary"} evidence base.</>}
      </p>

      <div className="mode-grid rise" style={{ "--i": 3 }}>
        {MODES.map((m) => (
          <button key={m.key} type="button" className={`mode-card ${mode === m.key ? "on" : ""}`} aria-pressed={mode === m.key} disabled={!!project.busy}
            onClick={async () => { if (mode !== m.key) try { setProject(await api.setSourceMode(project.id, m.key)); } catch (e) { toast(e.message, "error"); } }}>
            <b>{m.name}</b>
            <span>{m.blurb}</span>
          </button>
        ))}
      </div>
      {mode !== "references" && (
        <p className="muted rise" style={{ fontSize: 12.5, margin: "10px 0 0" }}>
          Sources found online are read from their abstract unless a legal open-access copy exists, and an article built on fewer full texts is thinner.
          RAF says in the Methodology exactly how far its reading went. Online research goes out to public scholarly databases.
        </p>
      )}

      <div className="row rise" style={{ "--i": 3, margin: "30px 0 18px", gap: 26 }}>
        <div className="ref-counter">
          <Ring value={count} max={Math.max(1, min)} label={count} />
          <div>
            <div style={{ fontWeight: 560 }}>{count < min ? `${min - count} more needed` : count >= max ? "Maximum reached" : count === 0 ? "No files — RAF will research the topic" : "Ready — add more if you like"}</div>
            <div className="muted" style={{ fontSize: 12.5 }}>PDF · DOCX · Markdown · TXT, up to {max} files</div>
          </div>
        </div>
      </div>

      <div className="rise" style={{ "--i": 4 }}>
        <Dropzone accept=".pdf,.docx,.md,.markdown,.txt" disabled={uploading || count >= max} onFiles={(f) => upload(f, "refs")}
          title={uploading ? "Uploading…" : "Drop reference articles here"} subtitle="or click to browse your files" />
      </div>

      <div className="file-list" style={{ marginTop: 16 }}>
        {project.references.map((r, i) => (
          <div key={r.id} className="file-item" style={{ animationDelay: `${i * 30}ms` }}>
            <div className="file-kind">{r.kind.toUpperCase()}</div>
            <div style={{ minWidth: 0 }}>
              <div className="file-name">{r.status === "parsed" ? r.title : r.filename}</div>
              <div className="file-meta">
                {r.status === "parsed" ? `${r.authors.slice(0, 3).join(", ")}${r.authors.length > 3 ? " et al." : ""} ${r.year ? "· " + r.year : ""} · ${r.chunks} passages` : r.status === "failed" ? r.error : r.filename}
              </div>
            </div>
            <span className={`badge ${r.status === "parsed" ? "ok" : r.status === "failed" ? "bad" : ""}`}>{r.status}</span>
            <button className="btn ghost icon sm danger" aria-label={`Remove ${r.filename}`} disabled={!!project.busy}
              onClick={async () => { try { setProject(await api.removeRef(project.id, r.id)); } catch (e) { toast(e.message, "error"); } }}>
              <Icon name="x" />
            </button>
          </div>
        ))}
      </div>

      <div className="card rise" style={{ "--i": 5, marginTop: 34 }}>
        <div className="row between wrap" style={{ marginBottom: 14 }}>
          <div>
            <div className="eyebrow" style={{ marginBottom: 6 }}>Optional</div>
            <div className="h2" style={{ fontSize: 22 }}>Your own dataset</div>
            <p className="muted" style={{ margin: 0, maxWidth: 560 }}>
              Upload survey or secondary data (CSV/XLSX) and RAF will analyse it instead of searching open data. Without one, RAF
              looks for matching World Bank indicators or numeric tables inside your references.
            </p>
          </div>
          <Icon name="data" size={30} />
        </div>
        <Dropzone accept=".csv,.tsv,.xlsx,.xls" disabled={uploading} onFiles={(f) => upload(f, "data")} title="Drop a dataset" subtitle="CSV · TSV · XLSX" />
        {project.dataset_files.map((d) => (
          <div key={d} className="file-item" style={{ marginTop: 8 }}>
            <div className="file-kind">DATA</div>
            <div className="file-name">{d}</div>
            <span />
            <button className="btn ghost icon sm danger" aria-label={`Remove ${d}`}
              onClick={async () => setProject(await api.removeData(project.id, d))}><Icon name="x" /></button>
          </div>
        ))}
      </div>

      <div className="actions-bar">
        <Button variant="ghost" icon="back" onClick={() => navigate(project.id, "setup")}>Topic</Button>
        <div className="row">
          {uploading && <Spinner />}
          <Button variant="primary" iconRight="arrow" disabled={count < min || uploading} onClick={next}>Choose segments</Button>
        </div>
      </div>
    </div>
  );
}
