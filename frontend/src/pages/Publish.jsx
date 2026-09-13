import { useRef, useState } from "react";
import { api } from "../api.js";
import { Button, Icon, Spinner, useToast } from "../ui.jsx";

const FORMATS = [
  { fmt: "pdf", title: "PDF document", desc: "Print-ready A4 with cover block, contents, running header, page numbers, tables and figures." },
  { fmt: "docx", title: "Word document", desc: "Fully editable DOCX with real heading styles, live table of contents and styled tables." },
  { fmt: "md", title: "Markdown", desc: "Plain-text source with embedded figures, ideal for Git, Obsidian or conversion." },
];

const ORDER = ["title", "abstract", "keywords", "introduction", "literature_review", "methodology", "results", "discussion", "conclusion", "limitations", "references", "appendices"];

export default function Publish({ project, setProject, navigate }) {
  const toast = useToast();
  const [working, setWorking] = useState("");
  const importRef = useRef(null);
  const keys = ORDER.filter((k) => project.segments[k]);
  const pending = keys.filter((k) => project.segments[k].status !== "approved");
  const ready = pending.length === 0;

  const download = async (fmt, draft = false) => {
    setWorking(fmt + (draft ? "-draft" : ""));
    try {
      await api.download(project.id, fmt, draft);
      toast(`${fmt.toUpperCase()} ${draft ? "preview" : "published"}`);
      if (!draft) setProject(await api.project(project.id));
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setWorking("");
    }
  };

  const importDoc = async (file) => {
    if (!file) return;
    setWorking("import");
    try {
      const res = await api.importDoc(project.id, file);
      setProject(res.project);
      toast(`Imported edits into: ${res.updated.join(", ")}`);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setWorking("");
    }
  };

  return (
    <div className="page">
      <div className="eyebrow rise">Step 06 — Publish</div>
      <h1 className="display rise" style={{ "--i": 1, fontSize: "clamp(34px,4.4vw,56px)" }}>
        {ready ? <>Ready to <em>publish.</em></> : <>Almost <em>there.</em></>}
      </h1>
      <p className="lede rise" style={{ "--i": 2 }}>
        {ready
          ? "Every segment is approved. RAF assembles them in canonical order, converts citations to your chosen style and typesets the document."
          : `Approve the remaining ${pending.length} segment${pending.length > 1 ? "s" : ""} to publish. You can still export a draft preview.`}
      </p>

      <div className="publish-grid" style={{ marginTop: 30 }}>
        <div className="stack" style={{ gap: 12 }}>
          {FORMATS.map((f, i) => (
            <div key={f.fmt} className="format-card rise" style={{ "--i": 3 + i }}>
              <div className="format-icon">.{f.fmt}</div>
              <div>
                <div className="f-title">{f.title}</div>
                <div className="muted" style={{ fontSize: 13 }}>{f.desc}</div>
                {!ready && (
                  <button className="btn ghost sm" style={{ marginTop: 6, paddingLeft: 0 }} disabled={!!working} onClick={() => download(f.fmt, true)}>
                    {working === `${f.fmt}-draft` ? <Spinner size={13} /> : <Icon name="file" size={13} />} Draft preview
                  </button>
                )}
              </div>
              <Button variant="primary" icon={working === f.fmt ? undefined : "download"} disabled={!ready || !!working} onClick={() => download(f.fmt)}>
                {working === f.fmt ? <Spinner /> : null}Publish
              </Button>
            </div>
          ))}

          <div className="card rise" style={{ "--i": 7 }}>
            <div className="row between wrap">
              <div>
                <div style={{ fontWeight: 580 }}>Edited the document elsewhere?</div>
                <div className="muted" style={{ fontSize: 13 }}>Import a DOCX, PDF or Markdown file — RAF matches its headings back to segments.</div>
              </div>
              <Button icon="upload" disabled={!!working} onClick={() => importRef.current.click()}>{working === "import" ? "Importing…" : "Import"}</Button>
              <input ref={importRef} type="file" hidden accept=".docx,.pdf,.md,.markdown,.txt" onChange={(e) => { importDoc(e.target.files[0]); e.target.value = ""; }} />
            </div>
          </div>
        </div>

        <div className="card checklist rise" style={{ "--i": 4 }}>
          <div className="row between" style={{ marginBottom: 6 }}>
            <b>Article structure</b>
            <span className="mono muted" style={{ fontSize: 12 }}>{keys.length - pending.length}/{keys.length}</span>
          </div>
          {keys.map((k) => {
            const s = project.segments[k];
            return (
              <div key={k} className="item">
                <span className={`status-dot ${s.status}`} />
                <span style={{ flex: 1 }}>{s.title}</span>
                {s.status === "approved" ? <span className="badge ok">approved</span> : (
                  <Button size="sm" variant="soft" onClick={() => navigate(project.id, "studio")}>Review</Button>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
