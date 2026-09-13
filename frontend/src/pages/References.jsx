import { useRef, useState } from "react";
import { api } from "../api.js";
import { Button, Icon, Ring, Spinner, useToast } from "../ui.jsx";

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
  const min = health?.limits?.min_references ?? 10;
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
        Upload {min}–{max} reference articles for <b>“{project.title}”</b>. RAF reads them in full, extracts citation metadata and uses
        them as the primary evidence base.
      </p>

      <div className="row rise" style={{ "--i": 3, margin: "30px 0 18px", gap: 26 }}>
        <div className="ref-counter">
          <Ring value={count} max={min} label={count} />
          <div>
            <div style={{ fontWeight: 560 }}>{count < min ? `${min - count} more needed` : count >= max ? "Maximum reached" : "Ready — add more if you like"}</div>
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
