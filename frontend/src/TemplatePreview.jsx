import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Button, Icon } from "./ui.jsx";

/* In-page template preview: a floating panel that typesets excerpts of the author's own article in each layout. */

const BODY_ORDER = ["introduction", "literature_review", "methodology", "results", "discussion", "conclusion", "limitations"];

const PLACEHOLDER = {
  title: "Adaptive Crowd Management in Mass Gatherings: Evidence from Urban Event Venues",
  abstract: "Mass gatherings concentrate risk in narrow spaces and short time windows. This article synthesises operational evidence from urban venues to examine how density monitoring, staged ingress and communication protocols shape crowd safety outcomes. Drawing on published incident analyses and venue case material, it identifies the conditions under which early intervention reduces crush risk and outlines implications for planners and regulators.",
  keywords: ["crowd safety", "mass gatherings", "density monitoring", "event management", "risk governance"],
  sections: [
    { title: "Introduction", paras: [
      "Large public events have grown in scale and frequency, and with them the operational burden placed on organisers and emergency services (Smith, 2021). Despite advances in monitoring, serious incidents continue to occur where density rises faster than staff can respond.",
      "This article asks which organisational practices allow venues to anticipate dangerous density before it becomes unmanageable, and how those practices can be evaluated consistently across contexts.",
    ] },
    { title: "Methodology", paras: [
      "The study follows a structured evidence synthesis. Peer-reviewed articles and official incident reports were screened against predefined criteria, coded for intervention type and outcome, and compared across venue categories (Garcia & Lee, 2019).",
    ] },
    { title: "Results", paras: [
      "Venues that combined real-time density estimates with pre-agreed intervention thresholds reported fewer escalations than venues relying on steward observation alone. Staged ingress was associated with lower peak density at entry points.",
    ] },
    { title: "Discussion", paras: [
      "The findings suggest that technology is most effective when it is embedded in clear decision rights. Monitoring without authority to act produced little measurable benefit, echoing earlier work on command structures (Okafor, 2020).",
    ] },
  ],
  table: { caption: "Intervention types and reported outcomes", columns: ["Intervention", "Venues", "Escalations", "Change"], rows: [["Density sensors", "14", "3", "−41%"], ["Staged ingress", "11", "4", "−28%"], ["Steward patrols", "18", "9", "−9%"]] },
  references: [
    "Garcia, M., & Lee, J. (2019). Evidence synthesis for event safety. Journal of Risk Research, 22(4), 455–472.",
    "Okafor, C. (2020). Command structures in crowd emergencies. Safety Science, 128, 104–118.",
    "Smith, A. (2021). Mass gatherings and public health. The Lancet Public Health, 6(2), e80–e88.",
  ],
};

const words = (text, n) => {
  const w = text.split(/\s+/).filter(Boolean);
  return w.length > n ? `${w.slice(0, n).join(" ")}…` : w.join(" ");
};

/** Turns RAF's stored segments into short, publication-styled excerpts (citations rendered in the chosen style). */
function buildSample(project) {
  const refs = project.references.filter((r) => r.status === "parsed");
  const sources = {};
  refs.forEach((r, i) => { sources[`R${i + 1}`] = r; });
  project.web_sources.forEach((w, i) => { sources[`W${i + 1}`] = w; });
  const order = Object.keys(sources);
  const ieee = project.citation_style === "IEEE";
  const cite = (text) => text.replace(/\[((?:[RW]\d+(?:\s*[,;]\s*)?)+)\]/g, (_, inner) => {
    const labels = inner.split(/\s*[,;]\s*/);
    if (ieee) return `[${labels.map((l) => order.indexOf(l) + 1 || "?").join(", ")}]`;
    return `(${labels.map((l) => {
      const s = sources[l];
      const surname = (s?.authors?.[0] || s?.title || "Author").split(",")[0].split(" ").slice(-1)[0];
      return `${surname}${(s?.authors?.length || 0) > 2 ? " et al." : ""}, ${s?.year || "n.d."}`;
    }).join("; ")})`;
  });
  const seg = (k) => project.segments[k]?.content?.trim() || "";
  const paragraphs = (k) => seg(k).split(/\n\s*\n/).map((b) => b.trim()).filter((b) => b && !/^\[\[(TABLE|FIGURE)/.test(b) && !/^Appendix/.test(b));

  const sections = BODY_ORDER.filter((k) => seg(k)).map((k) => ({
    title: project.segments[k].title.replace(" / Analysis", ""),
    paras: paragraphs(k).slice(0, 2).map((p) => words(cite(p), 70)),
  }));
  const tableSrc = BODY_ORDER.map((k) => project.segments[k]?.tables?.[0]).find(Boolean);
  const table = tableSrc && {
    caption: tableSrc.caption,
    columns: tableSrc.columns.slice(0, 4),
    rows: tableSrc.rows.slice(0, 4).map((r) => r.slice(0, 4).map((v) => words(String(v), 4))),
  };
  const refLines = seg("references").split("\n").map((l) => l.trim()).filter(Boolean).slice(0, 4);
  const [title, subtitle] = (seg("title") || project.title).split(/:\s+(.+)/);

  const real = sections.length > 0;
  return {
    real,
    title: real ? title : PLACEHOLDER.title.split(":")[0],
    subtitle: real ? subtitle : PLACEHOLDER.title.split(": ")[1],
    authors: project.authors?.length ? project.authors : ["A. Author", "B. Author"],
    affiliation: project.affiliation || "Department of Research, University",
    abstract: words(cite(seg("abstract")) || PLACEHOLDER.abstract, 95),
    keywords: seg("keywords") ? seg("keywords").split(/;\s*/).slice(0, 6) : PLACEHOLDER.keywords,
    sections: real ? sections : PLACEHOLDER.sections,
    table: table || PLACEHOLDER.table,
    references: refLines.length ? refLines.map((l) => words(l, 26)) : PLACEHOLDER.references,
  };
}

const ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"];

function Heading({ t, n, children }) {
  const label = t.key === "conference" ? `${ROMAN[n]}. ${children}` : t.key === "apa_manuscript" ? children : `${n + 1}. ${children}`;
  return <h3 className="tp-h">{label}</h3>;
}

function Table({ table, n }) {
  return (
    <figure className="tp-table">
      <figcaption><b>Table {n}.</b> {words(table.caption, 12)}</figcaption>
      <table>
        <thead><tr>{table.columns.map((c, i) => <th key={i}>{words(c, 3)}</th>)}</tr></thead>
        <tbody>{table.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{v}</td>)}</tr>)}</tbody>
      </table>
    </figure>
  );
}

function Body({ t, s, from = 0, to = 99, withTable = false }) {
  return s.sections.slice(from, to).map((sec, i) => (
    <section key={sec.title}>
      <Heading t={t} n={from + i}>{sec.title}</Heading>
      {sec.paras.map((p, j) => <p key={j}>{p}</p>)}
      {withTable && i === 1 && <Table table={s.table} n={1} />}
    </section>
  ));
}

function Header({ t, s, page }) {
  if (t.key === "conference") return null;
  return (
    <div className="tp-running">
      <span>{t.key === "apa_manuscript" ? words(s.title, 6).toUpperCase() : words(s.title, 8)}</span>
      <span>{page}</span>
    </div>
  );
}

/** A page set per template, mirroring the structure of the PDF renderer. */
function Pages({ t, s }) {
  const authorLine = s.authors.join(", ");
  const kw = <p className="tp-keywords"><b>{t.key === "conference" ? "Index Terms" : "Keywords"}</b>{t.key === "conference" ? "—" : ": "}{s.keywords.join(t.key === "conference" ? ", " : "; ")}</p>;

  if (t.cover === "title_page") {
    return [
      <div className="tp-page" key="1">
        <Header t={t} s={s} page={1} />
        <div className="tp-titlepage">
          <h1 className="tp-title">{s.title}{s.subtitle ? `: ${s.subtitle}` : ""}</h1>
          <p>{authorLine}</p>
          <p>{s.affiliation}</p>
          <div className="tp-note"><b>Author Note</b><p>Correspondence concerning this article should be addressed to {s.authors[0]}, {s.affiliation}.</p></div>
        </div>
      </div>,
      <div className="tp-page" key="2">
        <Header t={t} s={s} page={2} />
        <h2 className="tp-abstract-h">Abstract</h2>
        <p className="tp-abstract">{s.abstract}</p>
        {kw}
      </div>,
      <div className="tp-page" key="3">
        <Header t={t} s={s} page={3} />
        <h2 className="tp-abstract-h">{s.title}</h2>
        <Body t={t} s={s} to={2} />
      </div>,
    ];
  }

  const front = (
    <>
      {t.cover === "band" && <div className="tp-band"><span>RESEARCH ARTICLE</span></div>}
      <h1 className="tp-title">{s.title}</h1>
      {s.subtitle && <p className="tp-subtitle">{s.subtitle}</p>}
      <p className="tp-authors">{authorLine}</p>
      <p className="tp-aff">{s.affiliation}</p>
      {t.cover === "rule" && <div className="tp-rule" />}
      <div className="tp-abstract-box">
        {t.key === "conference"
          ? <p className="tp-abstract"><b><i>Abstract</i>—</b>{s.abstract}</p>
          : <><h2 className="tp-abstract-h">Abstract</h2><p className="tp-abstract">{s.abstract}</p></>}
        {kw}
      </div>
    </>
  );

  if (t.columns === 2) {
    return [
      <div className="tp-page" key="1">
        {front}
        <div className="tp-cols"><Body t={t} s={s} to={3} withTable /></div>
      </div>,
      <div className="tp-page" key="2">
        <div className="tp-cols">
          <Body t={t} s={s} from={3} />
          <section className="tp-refs"><h3 className="tp-h">References</h3>{s.references.map((r, i) => <p key={i}>[{i + 1}] {r}</p>)}</section>
        </div>
      </div>,
    ];
  }

  // Modern Report opens with a contents list (as the PDF does); the other layouts start the body on page 1.
  const toc = t.toc ?? t.key === "modern_report";
  const firstBody = toc ? 0 : 1;
  return [
    <div className="tp-page" key="1">
      <Header t={t} s={s} page={1} />
      {front}
      {toc
        ? <div className="tp-toc"><b>Contents</b>{s.sections.slice(0, 5).map((x, i) => <span key={x.title}><i>{i + 1}. {x.title}</i><i>{i + 2}</i></span>)}</div>
        : <Body t={t} s={s} to={1} />}
    </div>,
    <div className="tp-page" key="2">
      <Header t={t} s={s} page={2} />
      <Body t={t} s={s} from={firstBody} to={firstBody + 2} withTable />
    </div>,
    <div className="tp-page" key="3">
      <Header t={t} s={s} page={3} />
      <Body t={t} s={s} from={firstBody + 2} to={firstBody + 4} />
      <section className="tp-refs"><h3 className="tp-h">References</h3>{s.references.map((r, i) => <p key={i}>{r}</p>)}</section>
    </div>,
  ];
}

export default function TemplatePreview({ project, catalogue, initial, current, onApply, onClose }) {
  const [templateKey, setTemplateKey] = useState(initial.template);
  const [paletteKey, setPaletteKey] = useState(initial.palette);
  const [zoom, setZoom] = useState(1);
  const [page, setPage] = useState(0);
  const stageRef = useRef(null);
  const panelRef = useRef(null);
  const [fit, setFit] = useState(0.6);

  const sample = useMemo(() => buildSample(project), [project]);
  const t = catalogue.templates.find((x) => x.key === templateKey) || catalogue.templates[0];
  const pal = t.color ? catalogue.palettes.find((p) => p.key === paletteKey) : { accent: "111111", fill: "FFFFFF", rule: "000000" };
  const pages = Pages({ t, s: sample });
  const scale = fit * zoom;
  const isCurrent = current.template === templateKey && (current.palette === paletteKey || !t.color);

  // Fit an A4 page (595 × 842 CSS px) to the stage height.
  useEffect(() => {
    const measure = () => {
      const h = stageRef.current?.clientHeight || 700;
      setFit(Math.max(0.35, Math.min(1.1, (h - 56) / 842)));
    };
    measure();
    addEventListener("resize", measure);
    return () => removeEventListener("resize", measure);
  }, []);

  useEffect(() => { setPage(0); stageRef.current?.scrollTo({ left: 0, behavior: "smooth" }); }, [templateKey]);
  useEffect(() => { panelRef.current?.focus(); }, []);

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") goto(page + 1);
      if (e.key === "ArrowLeft") goto(page - 1);
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  });

  const goto = (n) => {
    const next = Math.max(0, Math.min(pages.length - 1, n));
    setPage(next);
    stageRef.current?.querySelectorAll(".tp-sheet")[next]?.scrollIntoView({ behavior: "smooth", inline: "center", block: "nearest" });
  };

  return createPortal(
    <div className="preview-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="preview-panel" role="dialog" aria-modal="true" aria-label={`Preview of the ${t.name} template`} tabIndex={-1} ref={panelRef}>
        <aside className="preview-side">
          <div>
            <div className="eyebrow">Template preview</div>
            <div className="h2" style={{ fontSize: 24, margin: "8px 0 4px" }}>{t.name}</div>
            <p className="muted" style={{ fontSize: 12.5, margin: 0 }}>{t.description}</p>
          </div>

          <div className="preview-templates" role="radiogroup" aria-label="Templates">
            {catalogue.templates.map((x) => (
              <button key={x.key} type="button" role="radio" aria-checked={x.key === templateKey}
                className={`preview-template ${x.key === templateKey ? "on" : ""}`} onClick={() => setTemplateKey(x.key)}>
                <span className={`preview-mini mini-${x.key}`} aria-hidden="true"><i /><i /><i /></span>
                <span>{x.name}</span>
                {current.template === x.key && <span className="badge accent">current</span>}
              </button>
            ))}
          </div>

          <div>
            <div className="field-label">Colour style</div>
            <div className="preview-swatches">
              {catalogue.palettes.map((p) => (
                <button key={p.key} type="button" className={`preview-swatch ${paletteKey === p.key ? "on" : ""}`} disabled={!t.color}
                  title={p.name} aria-label={p.name} aria-pressed={paletteKey === p.key} onClick={() => setPaletteKey(p.key)}
                  style={{ "--sw": `#${p.accent}`, "--sw-fill": `#${p.fill}` }} />
              ))}
            </div>
            {!t.color && <p className="muted" style={{ fontSize: 11.5, margin: "8px 0 0" }}>Monochrome by convention.</p>}
          </div>

          <p className="muted preview-note">
            {sample.real
              ? "Typeset with excerpts of your own article — citations shown in your chosen style. The exported file contains the full text."
              : "Your segments are not written yet, so sample academic text shows how the layout will look."}
          </p>

          <div className="preview-actions">
            <Button variant="primary" icon="check" disabled={isCurrent} onClick={() => { onApply({ template: templateKey, palette: paletteKey }); onClose(); }}>
              {isCurrent ? "Current layout" : "Use this layout"}
            </Button>
            <Button variant="ghost" onClick={onClose}>Close</Button>
          </div>
        </aside>

        <div className="preview-main">
          <div className="preview-toolbar">
            <div className="row" style={{ gap: 6 }}>
              <button className="btn icon sm ghost" aria-label="Previous page" disabled={page === 0} onClick={() => goto(page - 1)}><Icon name="left" /></button>
              <span className="mono muted" style={{ fontSize: 12, minWidth: 64, textAlign: "center" }}>Page {page + 1} / {pages.length}</span>
              <button className="btn icon sm ghost" aria-label="Next page" disabled={page === pages.length - 1} onClick={() => goto(page + 1)}><Icon name="right" /></button>
            </div>
            <div className="row" style={{ gap: 6 }}>
              <button className="btn icon sm ghost" aria-label="Zoom out" disabled={zoom <= 0.6} onClick={() => setZoom((z) => Math.max(0.6, +(z - 0.2).toFixed(1)))}><Icon name="zoomOut" /></button>
              <button className="btn sm ghost mono" style={{ minWidth: 58 }} onClick={() => setZoom(1)} title="Fit to height">{Math.round(zoom * 100)}%</button>
              <button className="btn icon sm ghost" aria-label="Zoom in" disabled={zoom >= 1.8} onClick={() => setZoom((z) => Math.min(1.8, +(z + 0.2).toFixed(1)))}><Icon name="zoomIn" /></button>
              <button className="btn icon sm ghost" aria-label="Close preview" onClick={onClose}><Icon name="x" /></button>
            </div>
          </div>
          <div className="preview-stage" ref={stageRef}>
            {pages.map((pg, i) => (
              <div key={`${templateKey}-${i}`} className={`tp-sheet ${i === page ? "current" : ""}`} style={{ width: 595 * scale, height: 842 * scale, "--d": `${i * 70}ms` }}
                onClick={() => setPage(i)}>
                <div className={`tp tpl-${t.key}`} style={{ transform: `scale(${scale})`, "--tp-accent": `#${pal.accent}`, "--tp-fill": `#${pal.fill}`, "--tp-rule": `#${pal.rule}` }}>
                  {pg}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
