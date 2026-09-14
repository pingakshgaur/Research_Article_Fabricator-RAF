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

const TONE_ICONS = { academic: "formal", analytical: "target", persuasive: "send", explanatory: "simple", reflective: "human" };
const TONE_SAMPLES = {
  academic: "Crowd density above four persons per square metre is associated with a marked rise in crush risk.",
  analytical: "Although density thresholds are widely cited, most derive from a handful of post-incident studies, which limits their predictive value.",
  persuasive: "Density thresholds alone cannot prevent crushes; what matters is whether authorities act on them in real time.",
  explanatory: "Crowd density is the number of people per square metre. Above about four, people can no longer move freely.",
  reflective: "At the stadium's single entrance ramp, stewards watched the queue thicken for an hour before anyone opened the side gates.",
};
const WORDS_PER_PAGE = 500;

export const defaultWords = (seg, project) => (seg.key === "abstract" ? 220 : Math.round((project.target_words * seg.word_share) / 10) * 10);
const pagesOf = (w) => Math.round((w / WORDS_PER_PAGE) * 10) / 10;

function sizeOf(words, entry) {
  if (!entry) return null;
  const opts = ["short", "medium", "long"];
  return opts.reduce((best, o) => (Math.abs(entry[o] - words) < Math.abs(entry[best] - words) ? o : best), "medium");
}

export default function Segments({ project, setProject, navigate, health }) {
  const toast = useToast();
  const [catalogue, setCatalogue] = useState([]);
  const [selected, setSelected] = useState(() => new Set(project.selected?.length ? project.selected : []));
  const [web, setWeb] = useState(project.options?.web_research ?? true);
  const [data, setData] = useState(project.options?.data_analysis ?? true);
  const [depth, setDepth] = useState(project.options?.depth ?? "thorough");
  const [agents, setAgents] = useState(project.options?.agents ?? 1);
  const [filter, setFilter] = useState(project.options?.hallucination_filter ?? true);
  const [stylePass, setStylePass] = useState(project.options?.style_pass ?? true);
  const [lengths, setLengths] = useState(() => ({ ...(project.segment_lengths || {}) }));
  const [unit, setUnit] = useState("size");
  const [profile, setProfile] = useState(null);
  const [tones, setTones] = useState([]);
  const [tone, setTone] = useState(project.tone || { name: "academic", intensity: 50 });
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    api.catalogue().then((c) => {
      setCatalogue(c);
      if (!project.selected?.length) setSelected(new Set(c.map((s) => s.key)));
    });
    api.tones().then(setTones).catch(() => {});
  }, [project.selected]);

  useEffect(() => {
    api.lengthProfile(project.article_type, project.target_words).then(setProfile).catch(() => {});
  }, [project.article_type, project.target_words]);

  const toggle = (key) => setSelected((s) => { const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n; });
  const preset = (keys) => setSelected(new Set(keys ?? catalogue.map((c) => c.key)));
  const titleOf = (k) => catalogue.find((c) => c.key === k)?.title || k;

  const lengthRows = catalogue.filter((c) => c.lengthable && selected.has(c.key));
  const suggestion = (key) => profile?.segments?.[key];
  const wordsFor = (c) => lengths[c.key] ?? suggestion(c.key)?.suggested ?? defaultWords(c, project);
  const totalWords = useMemo(() => lengthRows.reduce((sum, c) => sum + (c.key === "abstract" ? 0 : wordsFor(c)), 0), [lengthRows, lengths, profile]);
  const setWords = (key, value) => setLengths((l) => ({ ...l, [key]: Math.max(100, Math.round(value / 10) * 10) }));
  const applyAll = (size) => setLengths(Object.fromEntries(lengthRows.map((c) => [c.key, suggestion(c.key)?.[size] ?? wordsFor(c)])));

  const start = async () => {
    setStarting(true);
    try {
      const ordered = catalogue.map((c) => c.key).filter((k) => selected.has(k));
      const planned = Object.fromEntries(lengthRows.map((c) => [c.key, wordsFor(c)]));
      setProject(await api.generate(project.id, {
        segments: ordered, web_research: web, data_analysis: data, depth, agents, lengths: planned, resume: false,
        tone, hallucination_filter: filter, style_pass: stylePass,
      }));
      navigate(project.id, "processing");
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setStarting(false);
    }
  };

  const engineReady = health?.ollama && health?.model_available;
  const activeTone = tones.find((t) => t.key === tone.name);
  const level = tone.intensity <= 33 ? 0 : tone.intensity <= 66 ? 1 : 2;

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
              <span className="seg-no">§ {String(s.order + 1).padStart(2, "0")}{on && s.lengthable ? ` · ≈ ${pagesOf(wordsFor(s))} p` : ""}</span>
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
          <div className="row between wrap" style={{ marginBottom: 10, alignItems: "flex-start" }}>
            <div style={{ maxWidth: 560 }}>
              <div className="eyebrow" style={{ marginBottom: 6 }}>Length plan</div>
              <div className="h2" style={{ fontSize: 22 }}>How long should each segment be?</div>
              <p className="muted" style={{ margin: "4px 0 0" }}>
                Suggestions follow the usual proportions of a <b>{profile?.article_type || project.article_type}</b> (typically about {profile?.typical_pages ?? "–"} pages).
                One page ≈ {WORDS_PER_PAGE} words (A4, single-spaced).
              </p>
            </div>
            <div style={{ textAlign: "right" }}>
              <div className="mono" style={{ fontSize: 24 }}>{pagesOf(totalWords)} <span style={{ fontSize: 13 }}>pages</span></div>
              <div className="muted" style={{ fontSize: 12 }}>{totalWords.toLocaleString()} body words</div>
            </div>
          </div>
          <div className="row between wrap" style={{ margin: "8px 0 12px" }}>
            <Segmented value={unit} onChange={setUnit} options={[{ value: "size", label: "Short · Medium · Long" }, { value: "pages", label: "Pages" }, { value: "words", label: "Words" }]} />
            <div className="row wrap" style={{ gap: 6 }}>
              <span className="muted" style={{ fontSize: 12 }}>Set all:</span>
              {["short", "medium", "long"].map((s) => <Button key={s} size="sm" onClick={() => applyAll(s)}>{s[0].toUpperCase() + s.slice(1)}</Button>)}
              <Button size="sm" variant="ghost" icon="refresh" onClick={() => setLengths({})}>Suggested</Button>
            </div>
          </div>
          <div className="length-plan">
            {lengthRows.map((c) => {
              const w = wordsFor(c);
              const sug = suggestion(c.key);
              const size = sizeOf(w, sug);
              return (
                <div key={c.key} className="length-row v2">
                  <div>
                    <div className="length-name">{c.title}</div>
                    <div className="muted" style={{ fontSize: 11.5 }}>
                      Suggested: {sug ? `${pagesOf(sug.suggested)} p · ${sug.suggested} w` : "–"}
                    </div>
                  </div>
                  <div className="length-control">
                    {unit === "size" && (
                      <Segmented value={Math.abs((sug?.[size] ?? w) - w) <= 20 ? size : ""} onChange={(v) => setWords(c.key, sug?.[v] ?? w)}
                        options={["short", "medium", "long"].map((o) => ({ value: o, label: o[0].toUpperCase() + o.slice(1) }))} />
                    )}
                    {unit === "pages" && (
                      <div className="row" style={{ gap: 6 }}>
                        <button className="btn sm icon" aria-label="Fewer pages" onClick={() => setWords(c.key, w - WORDS_PER_PAGE / 4)}>−</button>
                        <input type="number" className="input length-input" min={0.2} step={0.25} value={pagesOf(w)} aria-label={`${c.title} pages`}
                          onChange={(e) => setWords(c.key, Number(e.target.value) * WORDS_PER_PAGE)} />
                        <button className="btn sm icon" aria-label="More pages" onClick={() => setWords(c.key, w + WORDS_PER_PAGE / 4)}>+</button>
                      </div>
                    )}
                    {unit === "words" && (
                      <input type="number" className="input length-input" min={c.min_words} max={c.max_words} step={10} value={w}
                        onChange={(e) => setWords(c.key, Number(e.target.value))} aria-label={`${c.title} words`} />
                    )}
                  </div>
                  <span className="mono muted length-readout">{unit === "words" ? `${pagesOf(w)} p` : `${w} w`}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      <div className="card rise tone-card" style={{ "--i": 12, marginTop: 16 }}>
        <div className="row between wrap" style={{ alignItems: "flex-start" }}>
          <div>
            <div className="eyebrow" style={{ marginBottom: 6 }}>Tone meter</div>
            <div className="h2" style={{ fontSize: 22 }}>How should the article sound?</div>
          </div>
          <span className="badge accent">{activeTone?.label} · {["Subtle", "Balanced", "Strong"][level]}</span>
        </div>
        <div className="tone-grid">
          {tones.map((t) => (
            <button key={t.key} type="button" className={`tone-option ${tone.name === t.key ? "on" : ""}`} aria-pressed={tone.name === t.key}
              onClick={() => setTone((x) => ({ ...x, name: t.key }))}>
              <Icon name={TONE_ICONS[t.key] || "spark"} size={18} />
              <b>{t.label}</b>
              <span>{t.summary}</span>
            </button>
          ))}
        </div>
        <div className="tone-meter">
          <div className="row between"><label htmlFor="tone-intensity">Intensity</label><span className="mono">{tone.intensity}</span></div>
          <input id="tone-intensity" type="range" className="range tone-range" min={0} max={100} step={1} value={tone.intensity}
            style={{ "--pct": `${tone.intensity}%` }} onChange={(e) => setTone((x) => ({ ...x, intensity: Number(e.target.value) }))} />
          <div className="row between muted" style={{ fontSize: 11.5 }}><span>Subtle</span><span>Balanced</span><span>Strong</span></div>
        </div>
        {activeTone && (
          <div className="tone-preview">
            <div className="muted" style={{ fontSize: 12, marginBottom: 6 }}>Instruction given to RAF: {activeTone.levels[level]}</div>
            <p className="serif">“{TONE_SAMPLES[tone.name]}”</p>
          </div>
        )}
      </div>

      <div className="card rise" style={{ "--i": 13, marginTop: 16 }}>
        <div className="grid-3" style={{ alignItems: "start" }}>
          <Toggle checked={web} onChange={setWeb} label="Online research" hint="Scholarly databases & the open web" />
          <Toggle checked={data} onChange={setData} label="Data analysis" hint="Statistics, tables & figures" />
          <div className="field">
            <label>Writing depth</label>
            <Segmented value={depth} onChange={setDepth} options={[{ value: "thorough", label: "Thorough" }, { value: "quick", label: "Quick draft" }]} />
            <span className="muted" style={{ fontSize: 12 }}>
              {depth === "thorough" ? "Evidence notes, peer review, refinement and article review. Slower, stronger." : "Single drafting pass per move. Faster."}
            </span>
          </div>
        </div>
        <div className="grid-2" style={{ marginTop: 18, paddingTop: 18, borderTop: "1px solid var(--line)" }}>
          <Toggle checked={filter} onChange={setFilter} label="Hallucination filter"
            hint="Checks every claim against its cited source; corrects or removes what isn't supported. Adds ~15–20% time." />
          <Toggle checked={stylePass} onChange={setStylePass} label="Style & naturalness pass"
            hint="Thorough mode: rewrites weak paragraphs with verified content preservation. Adds ~5–10% time." />
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
