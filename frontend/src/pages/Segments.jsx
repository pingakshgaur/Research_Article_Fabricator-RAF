import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { Button, Icon, Segmented, Toggle, useToast } from "../ui.jsx";

const PRESETS = {
  full: { label: "Full article", keys: null },
  imrad: { label: "Core IMRaD", keys: ["title", "abstract", "keywords", "introduction", "methodology", "results", "discussion", "conclusion", "references"] },
  review: { label: "Literature-focused", keys: ["abstract", "keywords", "introduction", "literature_review", "conclusion", "limitations", "references"] },
  none: { label: "Clear", keys: [] },
};

const AGENTS = [
  { value: 1, label: "Solo", hint: "One agent does everything in order. Lowest memory use." },
  { value: 2, label: "Duo", hint: "Two agents: independent segments and evidence notes run side by side. Needs OLLAMA_NUM_PARALLEL ≥ 2." },
  { value: 3, label: "Trio", hint: "Three agents in parallel. Fastest on GPUs with plenty of memory. Needs OLLAMA_NUM_PARALLEL ≥ 3." },
];

export const defaultWords = (seg, project) => (seg.key === "abstract" ? 220 : Math.round((project.target_words * seg.word_share) / 10) * 10);

export default function Segments({ project, setProject, navigate, health }) {
  const toast = useToast();
  const [catalogue, setCatalogue] = useState([]);
  const [selected, setSelected] = useState(() => new Set(project.selected?.length ? project.selected : []));
  const [web, setWeb] = useState(project.options?.web_research ?? true);
  const [data, setData] = useState(project.options?.data_analysis ?? true);
  const [depth, setDepth] = useState(project.options?.depth ?? "thorough");
  const [agents, setAgents] = useState(project.options?.agents ?? 1);
  const [lengths, setLengths] = useState(() => ({ ...(project.segment_lengths || {}) }));
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

  const lengthRows = catalogue.filter((c) => c.lengthable && selected.has(c.key));
  const wordsFor = (c) => lengths[c.key] ?? defaultWords(c, project);
  const totalWords = useMemo(() => lengthRows.reduce((sum, c) => sum + (c.key === "abstract" ? 0 : wordsFor(c)), 0), [lengthRows, lengths]);
  const setWords = (key, value) => setLengths((l) => ({ ...l, [key]: value }));

  const start = async () => {
    setStarting(true);
    try {
      const ordered = catalogue.map((c) => c.key).filter((k) => selected.has(k));
      const planned = Object.fromEntries(lengthRows.map((c) => [c.key, wordsFor(c)]));
      setProject(await api.generate(project.id, { segments: ordered, web_research: web, data_analysis: data, depth, agents, lengths: planned, resume: false }));
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
              <span className="seg-no">§ {String(s.order + 1).padStart(2, "0")}{on && s.lengthable ? ` · ≈ ${wordsFor(s).toLocaleString()} words` : ""}</span>
              <span className="seg-title">{s.title}</span>
              <span className="seg-desc">{s.description}</span>
              {on && missing.length > 0 && (
                <span className="deps">Works best with: {missing.map(titleOf).join(", ")}</span>
              )}
            </button>
          );
        })}
      </div>

      {lengthRows.length > 0 && (
        <div className="card rise" style={{ "--i": 11, marginTop: 26 }}>
          <div className="row between wrap" style={{ marginBottom: 6 }}>
            <div>
              <div className="eyebrow" style={{ marginBottom: 6 }}>Length plan</div>
              <div className="h2" style={{ fontSize: 22 }}>How long should each segment be?</div>
              <p className="muted" style={{ margin: "4px 0 0", maxWidth: 620 }}>
                RAF sizes its research and drafting to these targets. Segments that haven't started can still be changed during fabrication.
              </p>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="mono" style={{ fontSize: 22 }}>{totalWords.toLocaleString()}</div>
              <div className="muted" style={{ fontSize: 12 }}>body words · target {project.target_words.toLocaleString()}</div>
              <Button size="sm" variant="ghost" icon="refresh" onClick={() => setLengths({})}>Reset to defaults</Button>
            </div>
          </div>
          <div className="length-plan">
            {lengthRows.map((c) => {
              const w = wordsFor(c);
              return (
                <div key={c.key} className="length-row">
                  <span className="length-name">{c.title}</span>
                  <input type="range" className="range" min={c.min_words} max={Math.min(c.max_words, c.key === "abstract" ? 400 : 3000)} step={10}
                    value={w} onChange={(e) => setWords(c.key, Number(e.target.value))} aria-label={`${c.title} length`} />
                  <input type="number" className="input length-input" min={c.min_words} max={c.max_words} step={10} value={w}
                    onChange={(e) => setWords(c.key, Number(e.target.value))} aria-label={`${c.title} words`} />
                  <span className="muted mono" style={{ fontSize: 11 }}>words</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="card rise" style={{ "--i": 12, marginTop: 16 }}>
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
        <div className="field" style={{ marginTop: 18, paddingTop: 18, borderTop: "1px solid var(--line)" }}>
          <label>Agents working in parallel</label>
          <div className="row wrap">
            <Segmented value={agents} onChange={setAgents} options={AGENTS.map((a) => ({ value: a.value, label: `${a.label} · ${a.value}` }))} />
            <span className="muted" style={{ fontSize: 12, maxWidth: 520 }}>{AGENTS.find((a) => a.value === agents).hint}</span>
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
