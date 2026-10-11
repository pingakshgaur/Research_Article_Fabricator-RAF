import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { Button, Icon, Segmented, Spinner, useToast } from "../ui.jsx";
import StructureEditor from "../StructureEditor.jsx";
import TemplatePreview from "../TemplatePreview.jsx";

/** Miniature page illustrating each template's structure. */
const VERDICT = (score) => (score >= 75 ? "ok" : score >= 50 ? "warn" : "bad");

/** For an article brought in with "Format an existing article": checks that only run when asked for. */
function FormatChecks({ project, setProject }) {
  const toast = useToast();
  const [report, setReport] = useState(null);
  const [working, setWorking] = useState("");
  const [target, setTarget] = useState(["APA", "Harvard", "Chicago"].find((s) => s !== project.citation_style) || "APA");
  const run = async (name, fn) => {
    setWorking(name);
    try { await fn(); } catch (err) { toast(err.message, "error"); } finally { setWorking(""); }
  };
  const refs = report?.references;
  return (
    <div className="card rise" style={{ marginTop: 12 }}>
      <div className="row between wrap">
        <div style={{ maxWidth: 520 }}>
          <div style={{ fontWeight: 580 }}>Checks</div>
          <div className="muted" style={{ fontSize: 13 }}>Compares the citations in the text with the reference list, and reports on the writing style of each section. Nothing is changed.</div>
        </div>
        <Button icon={working === "checks" ? undefined : "shield"} disabled={!!working} onClick={() => run("checks", async () => setReport(await api.formatChecks(project.id)))}>
          {working === "checks" && <Spinner size={13} />}{report ? "Run again" : "Run the checks"}
        </Button>
      </div>
      {report && (
        <div style={{ marginTop: 14 }}>
          <div className="metric"><span>Reference list</span><span>{refs.references} entries · {refs.style}</span></div>
          <div className="metric"><span>Cited in the text but not in the list</span><span style={{ color: refs.missing.length ? "var(--warn)" : "var(--ok)" }}>{refs.missing.length}</span></div>
          {refs.missing.length > 0 && <p className="muted" style={{ fontSize: 12.5, margin: "4px 0 8px" }}>{refs.missing.join(" · ")}</p>}
          <div className="metric"><span>In the list but never cited</span><span style={{ color: refs.uncited.length ? "var(--warn)" : "var(--ok)" }}>{refs.uncited.length}</span></div>
          {refs.uncited.map((u) => <p key={u} className="muted" style={{ fontSize: 12.5, margin: "4px 0" }}>{u}</p>)}
          {report.style.length > 0 && <div style={{ fontWeight: 580, margin: "14px 0 4px" }}>Writing style by section</div>}
          {report.style.map((s) => (
            <div key={s.key} style={{ padding: "6px 0", borderTop: "1px dashed var(--line)" }}>
              <div className="row between"><span>{s.title}</span><span className={`badge ${VERDICT(s.score)}`}>{s.score} / 100</span></div>
              {s.issues.map((issue) => <div key={issue} className="muted" style={{ fontSize: 12.5 }}>{issue}</div>)}
            </div>
          ))}
          <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>The citation check reads author–date and numbered citations by pattern, so treat it as a list to look through, not a verdict.</p>
        </div>
      )}
      {project.segments.references && (
        <div className="row between wrap" style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--line)" }}>
          <div style={{ maxWidth: 480 }}>
            <div style={{ fontWeight: 580 }}>Restyle the reference list <span className="badge warn">experimental</span></div>
            <div className="muted" style={{ fontSize: 13 }}>
              Looks each entry up in Crossref (this goes online) and re-formats the ones it can identify. The rest stay exactly as they are. Citations in the text are not changed.
            </div>
          </div>
          <div className="row">
            <Segmented value={target} onChange={setTarget} options={["APA", "Harvard", "Chicago"].map((v) => ({ value: v, label: v }))} />
            <Button disabled={!!working} onClick={() => confirm(`Look up ${project.segments.references.content.split("\n").filter(Boolean).length} references in Crossref and restyle them to ${target}?`) &&
              run("restyle", async () => {
                const out = await api.restyleReferences(project.id, target);
                setProject(out.project);
                toast(out.restyled ? `${out.restyled} of ${out.total} entries restyled to ${target}; ${out.unchanged.length} left as they were` : "No entry could be identified; the list is unchanged", out.restyled ? "info" : "error");
              })}>{working === "restyle" ? "Looking up…" : "Restyle"}</Button>
          </div>
        </div>
      )}
    </div>
  );
}

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
  { fmt: "tex", title: "LaTeX", desc: "A .zip with main.tex, references.bib and the figures. Real citation commands; opens in Overleaf as it is." },
  { fmt: "md", title: "Markdown", desc: "Plain-text source with embedded figures, ideal for Git, Obsidian or conversion." },
];

export default function Publish({ project, setProject, navigate, health }) {
  const toast = useToast();
  const [working, setWorking] = useState("");
  const importRef = useRef(null);
  // the article as arranged by the author; segments left out do not have to be approved, nor does an empty one they write themselves
  const rows = project.structure.filter((r) => project.segments[r.key]);
  const keys = rows.map((r) => r.key);
  const inDocument = rows.filter((r) => r.included && (r.written || r.kind !== "manual"));
  const pending = inDocument.filter((r) => project.segments[r.key].status !== "approved").map((r) => r.key);
  const [arranging, setArranging] = useState(false);
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
      toast(["bib", "ris"].includes(fmt) ? `Reference list saved as ${fmt.toUpperCase()}` : `${fmt === "tex" ? "LaTeX" : fmt.toUpperCase()} ${draft ? "preview" : "published"}`);
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

          {project.mode === "format" ? <FormatChecks project={project} setProject={setProject} /> : project.references.length > 0 && (
            <div className="card rise" style={{ "--i": 6 }}>
              <div className="row between wrap">
                <div>
                  <div style={{ fontWeight: 580 }}>Reference list on its own</div>
                  <div className="muted" style={{ fontSize: 13 }}>For Zotero, Mendeley, EndNote or your own .bib file. Does not need approval.</div>
                </div>
                <div className="row">
                  {[["bib", "BibTeX"], ["ris", "RIS"]].map(([fmt, label]) => (
                    <Button key={fmt} icon={working === `${fmt}-draft` ? undefined : "download"} disabled={!!working} onClick={() => download(fmt, true)}>
                      {working === `${fmt}-draft` && <Spinner size={13} />}{label}
                    </Button>
                  ))}
                </div>
              </div>
            </div>
          )}

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
            <span className="mono muted" style={{ fontSize: 12 }}>{inDocument.length - pending.length}/{inDocument.length}</span>
          </div>
          {rows.map((r) => {
            const s = project.segments[r.key];
            return (
              <div key={r.key} className="item" style={r.included ? undefined : { opacity: 0.55 }}>
                <span className={`status-dot ${r.included ? s.status : "pending"}`} />
                <span style={{ flex: 1 }}>{s.title}</span>
                {!r.included ? <span className="badge">left out</span> : s.status === "approved" ? <span className="badge ok">approved</span>
                  : !r.written && r.kind === "manual" ? <span className="badge">empty</span> : (
                    <Button size="sm" variant="soft" onClick={() => navigate(project.id, "studio")}>Review</Button>
                  )}
              </div>
            );
          })}
          <Button size="sm" icon="edit" style={{ marginTop: 12 }} onClick={() => setArranging(true)}>Arrange, rename or leave out</Button>
          <StructureEditor project={project} setProject={setProject} health={health} open={arranging} onClose={() => setArranging(false)} />
        </div>
      </div>
    </div>
  );
}
