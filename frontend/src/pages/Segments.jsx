import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Button, Icon, Segmented, Toggle, useToast } from "../ui.jsx";

const PRESETS = {
  full: { label: "Full article", keys: null },
  imrad: { label: "Core IMRaD", keys: ["title", "abstract", "keywords", "introduction", "methodology", "results", "discussion", "conclusion", "references"] },
  review: { label: "Literature-focused", keys: ["abstract", "keywords", "introduction", "literature_review", "conclusion", "limitations", "references"] },
  none: { label: "Clear", keys: [] },
};

export default function Segments({ project, setProject, navigate, health }) {
  const toast = useToast();
  const [catalogue, setCatalogue] = useState([]);
  const [selected, setSelected] = useState(() => new Set(project.selected?.length ? project.selected : []));
  const [web, setWeb] = useState(project.options?.web_research ?? true);
  const [data, setData] = useState(project.options?.data_analysis ?? true);
  const [depth, setDepth] = useState(project.options?.depth ?? "thorough");
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    api.catalogue().then((c) => {
      setCatalogue(c);
      if (!project.selected?.length) setSelected(new Set(c.map((s) => s.key)));
    });
  }, [project.selected]);

  const toggle = (key) => setSelected((s) => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n; });
  const preset = (keys) => setSelected(new Set(keys ?? catalogue.map((c) => c.key)));
  const titleOf = (k) => catalogue.find((c) => c.key === k)?.title || k;

  const start = async () => {
    setStarting(true);
    try {
      const ordered = catalogue.map((c) => c.key).filter((k) => selected.has(k));
      setProject(await api.generate(project.id, { segments: ordered, web_research: web, data_analysis: data, depth }));
      navigate(project.id, "processing");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setStarting(false);
    }
  };

  const engineReady = health?.ollama && health?.model_available;

  return (
    <div className="page">
      <div className="eyebrow rise">Step 03 — Segments</div>
      <h1 className="display rise" style={{ "--i": 1, fontSize: "clamp(34px,4.4vw,56px)" }}>Which parts should RAF <em>write?</em></h1>
      <p className="lede rise" style={{ "--i": 2 }}>
        Every segment has its own blueprint — rhetorical moves, rules and a reviewer checklist. Segments that depend on others
        (like the Abstract) are written after them automatically.
      </p>

      <div className="row wrap rise" style={{ "--i": 3, margin: "26px 0 16px", justifyContent: "space-between" }}>
        <div className="row wrap" style={{ gap: 6 }}>
          {Object.entries(PRESETS).map(([k, p]) => (
            <Button key={k} size="sm" variant={k === "none" ? "ghost" : ""} onClick={() => preset(p.keys)}>{p.label}</Button>
          ))}
        </div>
        <span className="mono muted" style={{ fontSize: 12 }}>{selected.size} / {catalogue.length} selected</span>
      </div>

      <div className="seg-grid">
        {catalogue.map((s, i) => {
          const on = selected.has(s.key);
          const missing = s.depends_on.filter((d) => !selected.has(d));
          return (
            <button key={s.key} type="button" className={`seg-card rise ${on ? "on" : ""}`} style={{ "--i": 4 + i * 0.5 }}
              onClick={() => toggle(s.key)} aria-pressed={on}>
              <span className="check"><Icon name="check" size={14} stroke={2.6} /></span>
              <span className="seg-no">§ {String(s.order + 1).padStart(2, "0")}</span>
              <span className="seg-title">{s.title}</span>
              <span className="seg-desc">{s.description}</span>
              {on && missing.length > 0 && (
                <span className="deps">Works best with: {missing.map(titleOf).join(", ")}</span>
              )}
            </button>
          );
        })}
      </div>

      <div className="card rise" style={{ "--i": 12, marginTop: 26 }}>
        <div className="grid-3" style={{ alignItems: "start" }}>
          <Toggle checked={web} onChange={setWeb} label="Online research" hint="Scholarly databases & the open web" />
          <Toggle checked={data} onChange={setData} label="Data analysis" hint="Statistics, tables & figures" />
          <div className="field">
            <label>Writing depth</label>
            <Segmented value={depth} onChange={setDepth} options={[{ value: "thorough", label: "Thorough" }, { value: "quick", label: "Quick draft" }]} />
            <span className="muted" style={{ fontSize: 12 }}>
              {depth === "thorough" ? "Evidence notes, peer-review and refinement passes. Slower, stronger." : "Single drafting pass per move. Faster."}
            </span>
          </div>
        </div>
      </div>

      <div className="actions-bar">
        <Button variant="ghost" icon="back" onClick={() => navigate(project.id, "references")}>References</Button>
        <div className="row">
          {!engineReady && <span className="badge bad">{health?.ollama ? `Pull ${health.model}` : "Ollama offline"}</span>}
          <Button variant="primary" size="lg" icon="spark" disabled={!selected.size || starting || !engineReady} onClick={start}>
            {starting ? "Starting…" : `Fabricate ${selected.size} segment${selected.size === 1 ? "" : "s"}`}
          </Button>
        </div>
      </div>
    </div>
  );
}
