import { useRef, useState } from "react";
import { api } from "../api.js";
import { Button, Icon, Spinner, useToast } from "../ui.jsx";

const STEPS = [
  ["01", "Bring it in", "Word keeps the most: headings, bold and italic, tables and pictures. Markdown and plain text work too. A PDF gives text and headings only."],
  ["02", "Check the outline", "RAF shows the title, abstract, sections and reference list it found. Rename, reorder or leave out anything."],
  ["03", "Typeset", "Pick a template and colour style, then download PDF, Word, LaTeX or Markdown."],
];

/** "Format an existing article": a finished document goes in, RAF typesets it. Nothing is rewritten. */
export default function Format({ navigate }) {
  const toast = useToast();
  const input = useRef(null);
  const [over, setOver] = useState(false);
  const [working, setWorking] = useState("");

  const bring = async (file) => {
    if (!file || working) return;
    setWorking(file.name);
    try {
      const { project, found } = await api.formatUpload(file);
      const parts = [`${found.sections.length} section${found.sections.length === 1 ? "" : "s"}`, found.abstract && "an abstract",
        found.references && `${found.references} references`, found.tables && `${found.tables} table${found.tables === 1 ? "" : "s"}`,
        found.figures && `${found.figures} picture${found.figures === 1 ? "" : "s"}`].filter(Boolean);
      toast(`Found ${parts.join(", ")}.${found.lossy ? " A PDF gives text and headings only — check the outline." : ""}`);
      navigate(project.id, "published");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setWorking("");
    }
  };

  return (
    <div className="page">
      <div className="eyebrow rise">Format an existing article</div>
      <h1 className="display rise" style={{ "--i": 1, fontSize: "clamp(34px,4.4vw,56px)" }}>Your words, <em>typeset.</em></h1>
      <p className="lede rise" style={{ "--i": 2 }}>
        Already have a finished article? Bring it in and RAF lays it out in any of its templates. RAF does not rewrite a word of it.
      </p>

      <div className={`dropzone rise ${over ? "over" : ""}`} style={{ "--i": 3, marginTop: 30 }} role="button" tabIndex={0}
        onClick={() => !working && input.current.click()} onKeyDown={(e) => e.key === "Enter" && input.current.click()}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); bring(e.dataTransfer.files[0]); }}>
        {working ? <Spinner size={26} /> : <Icon name="upload" size={26} />}
        <div className="big">{working ? `Reading ${working}…` : "Drop your article here"}</div>
        <div className="muted">DOCX · Markdown · TXT · PDF, up to 60 MB — or click to browse</div>
        <input ref={input} type="file" hidden accept=".docx,.md,.markdown,.txt,.pdf" onChange={(e) => { bring(e.target.files[0]); e.target.value = ""; }} />
      </div>

      <div className="pipeline-strip rise" style={{ "--i": 4, gridTemplateColumns: "repeat(3, 1fr)" }}>
        {STEPS.map(([n, t, d]) => <div key={n}><span className="mono">{n}</span><b>{t}</b><p>{d}</p></div>)}
      </div>

      <div className="actions-bar">
        <Button variant="ghost" icon="back" onClick={() => navigate(null)}>RAF home</Button>
        <span className="muted" style={{ fontSize: 12.5 }}>The file stays on this computer. A scanned PDF has to go through OCR first.</span>
      </div>
    </div>
  );
}
