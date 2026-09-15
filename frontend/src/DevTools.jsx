import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Button, Icon, Select, Spinner, Toggle, useToast } from "./ui.jsx";

const GROUPS = [
  {
    title: "Sampling",
    hint: "How the model chooses words. Lower = more predictable and precise; higher = more varied.",
    fields: [
      { key: "temperature", label: "Temperature", step: 0.05, help: "Scales every call. RAF tunes each task relative to this (JSON checks stay low, drafting higher)." },
      { key: "top_p", label: "Top-p (nucleus)", step: 0.01, help: "Sample only from the smallest set of words whose probability adds up to p." },
      { key: "top_k", label: "Top-k", step: 1, help: "Consider only the k most likely next words." },
      { key: "min_p", label: "Min-p", step: 0.01, help: "Drop words less likely than this fraction of the top word. 0 = off." },
      { key: "repeat_penalty", label: "Repeat penalty", step: 0.01, help: "Discourages repeating recent tokens. Too high harms terminology." },
      { key: "repeat_last_n", label: "Repeat window (tokens)", step: 16, help: "How far back the repeat penalty looks." },
      { key: "presence_penalty", label: "Presence penalty", step: 0.05, help: "Pushes toward new topics. 0 = off." },
      { key: "frequency_penalty", label: "Frequency penalty", step: 0.05, help: "Penalises frequently used words. 0 = off." },
      { key: "seed", label: "Seed", step: 1, help: "−1 = random. A fixed seed makes runs reproducible." },
    ],
  },
  {
    title: "Memory & context",
    hint: "Changing these reloads the model once. Bigger context uses more VRAM/RAM.",
    fields: [
      { key: "num_ctx", label: "Context window (tokens)", options: [4096, 8192, 16384, 32768, 65536, 131072, 262144],
        help: "RAF prompts need ~8K; 16K is the safe default. Each doubling roughly doubles KV-cache memory." },
      { key: "max_output_tokens", label: "Max output tokens", step: 256, help: "Upper limit for any single response." },
      { key: "num_batch", label: "Prompt batch size", step: 32, help: "Larger batches read prompts faster but need more memory." },
    ],
  },
  {
    title: "Hardware",
    hint: "Controls where the model runs.",
    fields: [
      { key: "num_gpu", label: "GPU layers", step: 1, help: "−1 = let Ollama decide · 0 = CPU only · 1–48 = layers offloaded to the GPU (gemma4:12b has 48)." },
      { key: "num_thread", label: "CPU threads", step: 1, help: "0 = automatic. Matching physical cores (e.g. 6) is often fastest." },
      { key: "keep_alive", label: "Keep model loaded", text: true, help: "e.g. 30m, 2h, or -1 to keep it loaded until Ollama stops." },
      { key: "request_timeout", label: "Request timeout (s)", step: 30, help: "How long one call may run before it is retried." },
    ],
  },
];

function Field({ f, spec, value, onChange }) {
  const s = spec[f.key] || {};
  return (
    <div className="dev-field">
      <div className="row between">
        <label htmlFor={`dev-${f.key}`}>{f.label}</label>
        {f.options ? null : !f.text && <span className="mono">{value}</span>}
      </div>
      {f.options ? (
        <Select id={`dev-${f.key}`} value={value} onChange={onChange}
          options={f.options.map((o) => ({ value: o, label: `${o.toLocaleString()} tokens` }))} />
      ) : f.text ? (
        <input id={`dev-${f.key}`} className="input" value={value} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <div className="row" style={{ gap: 10 }}>
          <input id={`dev-${f.key}`} type="range" className="range" min={s.min} max={f.key === "seed" ? 9999 : f.key === "num_gpu" ? 48 : f.key === "num_thread" ? 32 : f.key === "request_timeout" ? 3600 : s.max}
            step={f.step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
          <input type="number" className="input dev-num" min={s.min} max={s.max} step={f.step} value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label={f.label} />
        </div>
      )}
      <div className="dev-help">{f.help}</div>
    </div>
  );
}

export default function DevTools({ open, onClose }) {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [bench, setBench] = useState(null);
  const [benching, setBenching] = useState(false);

  const load = () => api.llmSettings().then((d) => { setData(d); setForm(d.settings); }).catch((e) => toast(e.message, "error"));
  useEffect(() => { if (open) load(); }, [open]);
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    if (open) addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  const dirty = form && data && JSON.stringify(form) !== JSON.stringify(data.settings);
  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));

  const save = async () => {
    setSaving(true);
    try {
      const res = await api.saveLlmSettings(form);
      setData((d) => ({ ...d, settings: res.settings }));
      setForm(res.settings);
      toast("Model settings saved — they apply from the next model call");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setSaving(false);
    }
  };

  const runBench = async () => {
    setBenching(true);
    setBench(null);
    try {
      if (dirty) await save();
      setBench(await api.benchmark());
      load();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBenching(false);
    }
  };

  const installed = data?.ollama?.installed || [];
  const loaded = data?.ollama?.loaded || [];

  return (
    <div className="drawer-scrim" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside className="drawer" role="dialog" aria-label="Developer tools">
        <header className="drawer-head">
          <div>
            <div className="eyebrow">Developer tools</div>
            <div className="h2" style={{ fontSize: 24, margin: "6px 0 0" }}>Language model settings</div>
          </div>
          <button className="btn ghost icon" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
        </header>

        {!form ? <div className="empty"><Spinner /> Loading…</div> : (
          <div className="drawer-body">
            <section className="card">
              <h5>Model</h5>
              <Select value={form.model} onChange={set("model")} aria-label="Model"
                options={[...new Set([form.model, ...installed.map((m) => m.name)])].map((name) => {
                  const m = installed.find((x) => x.name === name);
                  return { value: name, label: name, hint: m ? `${m.parameters} · ${m.quantization} · ${m.size_gb} GB` : data.ollama?.error ? "" : "not installed" };
                })} />
              <div className="dev-help" style={{ marginTop: 8 }}>
                {loaded.length ? loaded.map((m) => (
                  <div key={m.name}>Loaded now: <b>{m.name}</b> · {m.size_gb} GB total · {m.vram_gb} GB on GPU ({m.size_gb ? Math.round((m.vram_gb / m.size_gb) * 100) : 0}%) · context {m.context?.toLocaleString?.() || "–"}</div>
                )) : data.ollama?.error ? <span style={{ color: "var(--bad)" }}>Ollama is not reachable — start it to see installed models and run the speed test.</span> : "No model is loaded right now."}
                {data.gpu_fallback != null && <div style={{ color: "var(--warn)" }}>Automatic out-of-memory fallback active: {data.gpu_fallback} GPU layers.</div>}
              </div>
              <div className="row wrap" style={{ marginTop: 12, gap: 6 }}>
                <span className="muted" style={{ fontSize: 12 }}>Presets:</span>
                {Object.entries(data.presets).map(([k, v]) => (
                  <Button key={k} size="sm" onClick={() => setForm((f) => ({ ...f, ...v }))}>{k[0].toUpperCase() + k.slice(1)}</Button>
                ))}
              </div>
              <div style={{ marginTop: 14 }}>
                <Toggle checked={!!form.think} onChange={set("think")} label="Thinking mode" hint="Lets the model reason before answering. Better on hard checks, much slower." />
              </div>
            </section>

            {GROUPS.map((g) => (
              <section key={g.title} className="card">
                <h5>{g.title}</h5>
                <div className="dev-help" style={{ marginTop: -6, marginBottom: 12 }}>{g.hint}</div>
                <div className="dev-grid">
                  {g.fields.map((f) => <Field key={f.key} f={f} spec={data.spec} value={form[f.key]} onChange={set(f.key)} />)}
                </div>
              </section>
            ))}

            <section className="card">
              <h5>Speed test <Icon name="gauge" size={14} /></h5>
              <div className="dev-help">Runs one short generation with the settings above and measures real speed on this PC.</div>
              <Button style={{ marginTop: 10 }} icon={benching ? undefined : "spark"} disabled={benching} onClick={runBench}>{benching ? <><Spinner /> Testing…</> : "Run speed test"}</Button>
              {bench && (
                <div style={{ marginTop: 12 }}>
                  <div className="metric"><span>Reading speed (prompt)</span><span>{bench.prompt_tokens_per_sec} tok/s</span></div>
                  <div className="metric"><span>Writing speed (output)</span><span>{bench.output_tokens_per_sec} tok/s</span></div>
                  <div className="metric"><span>Model load time</span><span>{bench.load_seconds}s</span></div>
                  <div className="metric"><span>Total</span><span>{bench.wall_seconds}s</span></div>
                  {bench.output_tokens_per_sec > 0 && (
                    <div className="dev-help" style={{ marginTop: 8 }}>
                      Estimated full Thorough article (~210K tokens read, ~35K written):{" "}
                      <b>{((210000 / Math.max(1, bench.prompt_tokens_per_sec) + 35000 / bench.output_tokens_per_sec) / 3600).toFixed(1)} h</b>
                      {" "}(the hallucination filter and style pass add roughly 20–30%).
                    </div>
                  )}
                  <p className="serif" style={{ fontSize: 14, marginBottom: 0 }}>{bench.sample}</p>
                </div>
              )}
            </section>
          </div>
        )}

        <footer className="drawer-foot">
          <Button variant="ghost" onClick={async () => { const r = await api.resetLlmSettings(); setForm(r.settings); setData((d) => ({ ...d, settings: r.settings })); toast("Defaults restored"); }}>Reset to defaults</Button>
          <div className="row">
            {dirty && <span className="badge warn">Unsaved</span>}
            <Button variant="primary" icon="check" disabled={!dirty || saving} onClick={save}>{saving ? "Saving…" : "Save settings"}</Button>
          </div>
        </footer>
      </aside>
    </div>
  );
}
