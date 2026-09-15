import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { Button, Icon, Spinner, useToast } from "../ui.jsx";
import TemplatePreview from "../TemplatePreview.jsx";

/** Miniature page illustrating each template's structure. */
function TemplateThumb({ t, accent, fill }) {
  const lines = (n, w = "100%") => Array.from({ length: n }, (_, i) => <i key={i} style={{ width: i === n - 1 ? "62%" : w }} />);
  const center = t.key !== "modern_report" && t.key !== "minimal_monograph";
  return (
    <div className={`thumb thumb-${t.key}`} aria-hidden="true">
      {t.cover === "band" && <div className="thumb-band" style={{ background: accent }} />}
      {t.cover === "title_page" ? (
        <div className="thumb-titlepage"><i className="thumb-title" style={{ width: "70%" }} /><i style={{ width: "40%" }} /><i style={{ width: "30%" }} /></div>
      ) : (
        <>
          <i className="thumb-title" style={{ background: t.key === "minimal_monograph" ? "#222" : "#111", margin: center ? "0 auto" : 0 }} />
          <i className="thumb-sub" style={{ margin: center ? "4px auto 0" : "4px 0 0" }} />
          {t.cover === "rule" && <div className="thumb-rule" style={{ background: accent }} />}
          <div className={`thumb-abstract ${t.key}`} style={t.key === "modern_report" ? { background: fill, borderLeftColor: accent } : { borderColor: accent }}>{lines(3)}</div>
          <div className="thumb-h" style={{ background: accent, margin: t.key === "conference" ? "6px auto 4px" : "6px 0 4px" }} />
          <div className={t.columns === 2 ? "thumb-cols" : "thumb-body"}>
            {t.columns === 2 ? <><div>{lines(9)}</div><div>{lines(9)}</div></> : lines(t.key === "minimal_monograph" ? 5 : 8)}
          </div>
        </>
      )}
    </div>
  );
}

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

  const [catalogue, setCatalogue] = useState(null);
  const [style, setStyle] = useState(project.publish_style || { template: "modern_report", palette: "violet" });
  useEffect(() => { api.publishStyles().then(setCatalogue).catch(() => {}); }, []);
  const activeTemplate = catalogue?.templates.find((t) => t.key === style.template);
  const palette = catalogue?.palettes.find((p) => p.key === style.palette);

  const choose = async (patch) => {
    const next = { ...style, ...patch };
    setStyle(next);
    try { setProject(await api.setPublishStyle(project.id, next)); } catch (err) { toast(err.message, "error"); }
  };

  const [previewing, setPreviewing] = useState(null);   // template key shown in the floating preview

  const download = async (fmt, draft = false) => {
    setWorking(fmt + (draft ? "-draft" : ""));
    try {
      await api.download(project.id, fmt, draft, fmt === "md" ? null : style);
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

      <section className="card rise style-picker" style={{ "--i": 3, marginTop: 30 }}>
        <div className="row between wrap">
          <div>
            <div className="eyebrow" style={{ marginBottom: 6 }}>Step 1 · Template</div>
            <div className="h2" style={{ fontSize: 22 }}>Choose a layout</div>
          </div>
          <Button icon="eye" disabled={!catalogue} onClick={() => setPreviewing(style.template)}>Preview layout</Button>
        </div>
        <div className="template-grid">
          {catalogue?.templates.map((t) => (
            <div key={t.key} className="template-card-wrap">
              <button type="button" className={`template-card ${style.template === t.key ? "on" : ""}`} aria-pressed={style.template === t.key}
                onClick={() => choose({ template: t.key })}>
                <TemplateThumb t={t} accent={t.color ? `#${palette?.accent}` : "#111"} fill={t.color ? `#${palette?.fill}` : "#fff"} />
                <b>{t.name}</b>
                <span>{t.description}</span>
              </button>
              <button type="button" className="template-peek" onClick={() => setPreviewing(t.key)} aria-label={`Preview ${t.name}`}>
                <Icon name="eye" size={14} /> Preview
              </button>
            </div>
          ))}
        </div>
        {previewing && catalogue && (
          <TemplatePreview project={project} catalogue={catalogue} current={style}
            initial={{ template: previewing, palette: style.palette }} onApply={choose} onClose={() => setPreviewing(null)} />
        )}
        <div className="eyebrow" style={{ margin: "22px 0 10px" }}>Step 2 · Colour style</div>
        <div className="row wrap" style={{ gap: 10 }}>
          {catalogue?.palettes.map((p) => (
            <button key={p.key} type="button" className={`swatch ${style.palette === p.key ? "on" : ""}`} disabled={!activeTemplate?.color}
              aria-pressed={style.palette === p.key} onClick={() => choose({ palette: p.key })} title={p.name}>
              <span className="swatch-dot" style={{ background: `#${p.accent}`, boxShadow: `inset 0 0 0 5px #${p.fill}` }} />
              {p.name}
            </button>
          ))}
          {activeTemplate && !activeTemplate.color && <span className="muted" style={{ fontSize: 12 }}>This template is monochrome by convention.</span>}
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 12 }}>Charts keep the colours they were generated with.</div>
      </section>

      <div className="eyebrow rise" style={{ "--i": 4, margin: "28px 0 12px" }}>Step 3 · Format</div>
      <div className="publish-grid">
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
