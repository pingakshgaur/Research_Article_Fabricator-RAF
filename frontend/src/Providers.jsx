import { useEffect, useState } from "react";
import { api } from "./api.js";
import { Button, Icon, Segmented, Select, Spinner, Toggle, useToast } from "./ui.jsx";

/* Cloud language models: the marks that stand for each provider, the team shown on the Segments page,
 * and the key manager of Settings → Language model.
 * The marks are simple drawings in each provider's colour, made for RAF — they are not the official logos. */

const MARKS = {
  ollama: { bg: "#1f2430", fg: "#ffffff", draw: <><rect x="5" y="6" width="14" height="9.5" rx="1.6" fill="none" stroke="currentColor" strokeWidth="1.7" /><path d="M9 19h6m-3-3.5V19" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" /></> },
  anthropic: { bg: "#d97757", fg: "#ffffff", draw: <g stroke="currentColor" strokeWidth="2.1" strokeLinecap="round">{[0, 45, 90, 135].map((a) => <path key={a} d="M12 5.2v13.6" transform={`rotate(${a} 12 12)`} />)}</g> },
  openai: { bg: "#0f0f0f", fg: "#ffffff", draw: <g fill="none" stroke="currentColor" strokeWidth="1.6">{[0, 60, 120].map((a) => <ellipse key={a} cx="12" cy="12" rx="3.1" ry="6.6" transform={`rotate(${a} 12 12)`} />)}</g> },
  gemini: { bg: "#1b1f3b", fg: "#8ab4ff", draw: <path d="M12 4c.6 4.4 3.6 7.4 8 8-4.4.6-7.4 3.6-8 8-.6-4.4-3.6-7.4-8-8 4.4-.6 7.4-3.600 8-8Z" fill="currentColor" /> },
  nvidia: { bg: "#76b900", fg: "#0b1400", draw: <><path d="M4.500 12S7.5 7 12 7s7.5 5 7.500 5-3 5-7.500 5-7.500-5-7.500-5Z" fill="none" stroke="currentColor" strokeWidth="1.8" /><circle cx="12" cy="12" r="2.3" fill="currentColor" /></> },
  groq: { bg: "#f55036", fg: "#ffffff", text: "g" },
  mistral: { bg: "#ff8205", fg: "#1a0d00", draw: <g fill="currentColor"><rect x="5" y="6" width="3" height="12" /><rect x="16" y="6" width="3" height="12" /><rect x="8" y="8.500" width="3" height="3" /><rect x="13" y="8.500" width="3" height="3" /><rect x="10.500" y="11.500" width="3" height="3" /></g> },
  deepseek: { bg: "#4d6bfe", fg: "#ffffff", text: "d" },
  openrouter: { bg: "#6467f2", fg: "#ffffff", draw: <path d="M4 9h6c3 0 3 6 6 6h4M4 15h6c3 0 3-6 6-6h4m-3-2.500L20 9l-3 2.500M17 12.500l3 2.500-3 2.500" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" /> },
  custom: { bg: "#5b6472", fg: "#ffffff", draw: <path d="M9 4v4m6-4v4M7 8h10v3a5 5 0 0 1-10 0V8Zm5 8v4" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" /> },
};

export function ProviderLogo({ provider, size = 22, title }) {
  const m = MARKS[provider] || MARKS.custom;
  return (
    <svg className="provider-logo" width={size} height={size} viewBox="0 0 24 24" role="img" aria-label={title || provider} style={{ color: m.fg }}>
      <title>{title || provider}</title>
      <rect width="24" height="24" rx="6.500" fill={m.bg} />
      {m.text ? <text x="12" y="16.600" textAnchor="middle" fontSize="13" fontWeight="700" fill="currentColor" fontFamily="system-ui, sans-serif">{m.text}</text> : m.draw}
    </svg>
  );
}

/** Who will do the writing: this PC's model and every cloud model with a key, each with its mark and its number of agents. */
export function Team({ health, agents, cloud }) {
  const c = health?.cloud || { mode: "local", engines: [], agents: 0 };
  const engines = cloud ? c.engines : [];
  const pc = !(cloud && c.mode === "cloud" && engines.length);     // in cloud-only mode this PC is on standby
  const total = Math.min(8, (pc ? agents : 0) + engines.reduce((n, e) => n + e.parallel, 0));
  return (
    <div className="team">
      <div className="team-row">
        <span className={`team-chip ${pc ? "" : "standby"}`} title={pc ? "Runs on this computer. Nothing leaves it." : "On standby: steps in only if no cloud model is left"}>
          <ProviderLogo provider="ollama" title="This PC" />
          <span><b>{health?.model || "local model"}</b><small>{pc ? `this PC · ${agents} agent${agents > 1 ? "s" : ""}` : "this PC · standby"}</small></span>
        </span>
        {engines.map((e) => (
          <span key={e.id} className="team-chip" title={`${e.name} — ${e.model}${e.role !== "all" ? ` · ${e.role} only` : ""}`}>
            <ProviderLogo provider={e.provider} title={e.name} />
            <span><b>{e.label || e.name}</b><small>{e.model} · {e.parallel} agent{e.parallel > 1 ? "s" : ""}{e.role !== "all" ? ` · ${e.role}` : ""}</small></span>
          </span>
        ))}
        <span className="team-total mono">{total} agent{total > 1 ? "s" : ""} in all</span>
      </div>
      {engines.length > 0 && (
        <div className="team-note">
          <Icon name="globe" size={12} /> Passages of your reference files and the draft are sent to {[...new Set(engines.map((e) => (e.provider === "custom" ? e.label || "your own server" : e.name)))].join(", ")} while they write.
          Their use is billed to your key.
        </div>
      )}
    </div>
  );
}

const STATUS = { ok: ["ok", "working"], unchecked: ["warn", "not tested"], rejected: ["bad", "rejected"] };

function KeyRow({ k, spec, data, locked, first, act }) {
  const [model, setModel] = useState(k.model);
  const [offered, setOffered] = useState(null);
  const [busy, setBusy] = useState("");
  const [result, setResult] = useState(null);
  useEffect(() => setModel(k.model), [k.model]);
  const run = (name, fn) => async () => {
    setBusy(name);
    try { await fn(); } finally { setBusy(""); }
  };
  const [tone, word] = STATUS[k.status] || STATUS.unchecked;
  return (
    <div className={`key-row ${k.enabled ? "" : "off"}`}>
      <div className="key-head">
        <ProviderLogo provider={k.provider} size={30} title={k.name} />
        <div className="key-name">
          <b>{k.label || k.name}</b>
          <span className="mono muted">{k.company} · ••••{k.tail}</span>
        </div>
        <span className={`badge ${tone}`}>{word}</span>
        <Toggle checked={k.enabled} onChange={(v) => !locked && act(() => api.changeKey(k.id, { enabled: v }))} label="" />
      </div>
      <div className="key-grid">
        <div className="field">
          <label htmlFor={`model-${k.id}`}>Model</label>
          <div className="row" style={{ gap: 6 }}>
            <input id={`model-${k.id}`} className="input" list={`models-${k.id}`} value={model} disabled={locked} spellCheck={false}
              onChange={(e) => setModel(e.target.value)} onBlur={() => model.trim() && model !== k.model && act(() => api.changeKey(k.id, { model: model.trim() }))}
              onKeyDown={(e) => e.key === "Enter" && e.target.blur()} />
            <datalist id={`models-${k.id}`}>{(offered || spec?.models || []).map((m) => <option key={m} value={m} />)}</datalist>
            <Button size="sm" disabled={locked || !!busy} title="Ask the provider which models this key can use"
              onClick={run("models", async () => { try { setOffered((await api.keyModels(k.id)).models); } catch (e) { act(() => Promise.reject(e)); } })}>
              {busy === "models" ? <Spinner size={12} /> : "List"}
            </Button>
          </div>
          {offered && <span className="dev-help">{offered.length} models offered — type or pick one above.</span>}
        </div>
        <div className="field">
          <label>Agents on this key</label>
          <Segmented value={k.parallel} onChange={(v) => !locked && act(() => api.changeKey(k.id, { parallel: v }))}
            options={Array.from({ length: data.max_parallel }, (_, i) => ({ value: i + 1, label: String(i + 1) }))} />
        </div>
        <div className="field">
          <label>Used for</label>
          <Select value={k.role} onChange={(v) => !locked && act(() => api.changeKey(k.id, { role: v }))} aria-label="Used for"
            options={Object.entries(data.roles).map(([value, label]) => ({ value, label, hint: { all: "writing and checks", writing: "drafting and revising prose", checks: "fact checks, plans and other short JSON tasks" }[value] }))} />
        </div>
      </div>
      {(k.note || result || k.usage.calls > 0 || k.usage.errors > 0) && (
        <div className="dev-help">
          {k.note && <div style={{ color: "var(--warn)" }}>{k.note}</div>}
          {result && <div style={{ color: result.ok ? "var(--ok)" : "var(--bad)" }}>{result.ok ? `Answered in ${result.seconds} s: “${result.sample}”` : `Test failed — ${result.error}`}</div>}
          {(k.usage.calls > 0 || k.usage.errors > 0) && <div>Since RAF started: {k.usage.calls} request{k.usage.calls === 1 ? "" : "s"} answered{k.usage.errors ? `, ${k.usage.errors} failed (last: ${k.usage.last_error})` : ""}.</div>}
        </div>
      )}
      <div className="row between wrap">
        <details className="key-rules">
          <summary>How RAF drives {k.name}</summary>
          <ul>{(spec?.rules || []).map((r) => <li key={r}>{r}</li>)}</ul>
        </details>
        <div className="row" style={{ gap: 6 }}>
          {!first && <Button size="sm" variant="ghost" disabled={locked} title="Higher in the list = asked first" onClick={() => act(() => api.orderKeys([k.id]))}>Make first</Button>}
          <Button size="sm" disabled={locked || !!busy} title="Sends one very small request (a few tokens)"
            onClick={run("test", async () => { try { const r = await api.testKey(k.id); setResult(r.result); act(() => Promise.resolve(r)); } catch (e) { act(() => Promise.reject(e)); } })}>
            {busy === "test" ? <><Spinner size={12} /> Testing…</> : "Test"}
          </Button>
          <Button size="sm" variant="ghost" icon="trash" disabled={locked} aria-label={`Remove the ${k.name} key`}
            onClick={() => confirm(`Remove this ${k.name} key from RAF?`) && act(() => api.removeKey(k.id))} />
        </div>
      </div>
    </div>
  );
}

/** Settings → Language model → Cloud models. Changes are saved at once; `locked` shows everything read-only. */
export function KeyManager({ locked = false, onChange }) {
  const toast = useToast();
  const [data, setData] = useState(null);
  const [form, setForm] = useState({ key: "", provider: "", label: "", model: "", base_url: "" });
  const [adding, setAdding] = useState(false);

  useEffect(() => { api.keys().then(setData).catch((e) => toast(e.message, "error")); }, []);
  const act = async (fn) => {
    try {
      const next = await fn();
      if (next?.keys) setData(next);
      onChange?.();
    } catch (e) {
      toast(e.message, "error");
    }
  };
  if (!data) return <section className="card"><h5>Cloud models</h5><div className="empty"><Spinner /> Loading…</div></section>;

  const specs = Object.fromEntries(data.providers.map((p) => [p.key, p]));
  const guessed = [...data.providers].filter((p) => p.prefix && form.key.trim().startsWith(p.prefix)).sort((a, b) => b.prefix.length - a.prefix.length)[0]?.key || "";
  const provider = form.provider || guessed;
  const spec = specs[provider];
  const add = async () => {
    setAdding(true);
    try {
      setData(await api.addKey({ key: form.key.trim(), provider, label: form.label, model: form.model.trim(), base_url: form.base_url.trim() }));
      setForm({ key: "", provider: "", label: "", model: "", base_url: "" });
      toast("Key saved, encrypted. Its model now works beside the local one.");
      onChange?.();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setAdding(false);
    }
  };
  const cloudAgents = data.mode === "local" ? 0 : data.keys.filter((k) => k.enabled && k.status !== "rejected").reduce((n, k) => n + k.parallel, 0);

  return (
    <section className="card key-manager">
      <h5>Cloud models <Icon name="globe" size={14} /></h5>
      <div className="dev-help" style={{ marginTop: -6 }}>
        Add the API key of any language model you have — Claude, GPT, Gemini, NVIDIA and others. Each key becomes extra agents that write
        beside the local model, so the article is finished sooner, and a stronger model can take over the writing. Several keys can work at once.
      </div>
      <div className="key-facts">
        <span><Icon name="lock" size={13} /> Keys are stored encrypted on this computer ({data.protection}) and are never shown again — only the last four characters.</span>
        <span><Icon name="globe" size={13} /> A cloud model receives the prompts RAF writes for it, which contain passages of your reference files and the draft. Its use is billed to your key by the provider.</span>
      </div>

      <div className="field" style={{ marginTop: 14 }}>
        <label>Who writes</label>
        <div className="row wrap">
          <Segmented value={data.mode} onChange={(v) => !locked && act(() => api.setLlmMode(v))}
            options={[{ value: "local", label: "This PC only" }, { value: "hybrid", label: "This PC + cloud" }, { value: "cloud", label: "Cloud only" }]} />
          <span className="muted" style={{ fontSize: 12, maxWidth: 460 }}>
            {{ local: "The keys stay saved but are not used. Nothing leaves this computer.",
               hybrid: "Cloud models are asked first; the local model takes what is left over and everything if they fail.",
               cloud: "Only the cloud models write. The local model steps in only when none of them is left." }[data.mode]}
            {cloudAgents > 0 && ` ${cloudAgents} cloud agent${cloudAgents > 1 ? "s" : ""} ready (RAF runs at most ${data.max_agents} agents at once).`}
          </span>
        </div>
      </div>

      {data.keys.length > 0 && (
        <div className="key-list">
          {data.keys.map((k, i) => <KeyRow key={k.id} k={k} spec={specs[k.provider]} data={data} locked={locked} first={i === 0} act={act} />)}
        </div>
      )}

      <div className="key-add">
        <div className="field-label" style={{ marginBottom: 8 }}>{data.keys.length ? "Add another key" : "Add a key"}</div>
        <div className="key-grid">
          <div className="field">
            <label htmlFor="new-key">API key</label>
            <input id="new-key" className="input mono" type="password" autoComplete="off" spellCheck={false} placeholder="Paste the key here" value={form.key} disabled={locked}
              onChange={(e) => setForm((f) => ({ ...f, key: e.target.value }))} onKeyDown={(e) => e.key === "Enter" && form.key.trim() && provider && add()} />
          </div>
          <div className="field">
            <label>Provider {guessed && !form.provider && <span className="opt">recognised from the key</span>}</label>
            <Select value={provider} onChange={(v) => setForm((f) => ({ ...f, provider: v, model: "" }))} placeholder="Choose…" aria-label="Provider"
              options={data.providers.map((p) => ({ value: p.key, label: p.name, hint: p.company }))} />
          </div>
          <div className="field">
            <label htmlFor="new-model">Model <span className="opt">optional</span></label>
            <input id="new-model" className="input" list="new-models" spellCheck={false} placeholder={spec?.model || "model name"} value={form.model} disabled={locked}
              onChange={(e) => setForm((f) => ({ ...f, model: e.target.value }))} />
            <datalist id="new-models">{(spec?.models || []).map((m) => <option key={m} value={m} />)}</datalist>
          </div>
        </div>
        <div className="key-grid" style={{ marginTop: 10 }}>
          <div className="field">
            <label htmlFor="new-label">Name <span className="opt">optional</span></label>
            <input id="new-label" className="input" maxLength={40} placeholder="e.g. Lab account" value={form.label} disabled={locked} onChange={(e) => setForm((f) => ({ ...f, label: e.target.value }))} />
          </div>
          {(spec?.needs_address || form.base_url) && (
            <div className="field" style={{ gridColumn: "span 2" }}>
              <label htmlFor="new-url">Server address</label>
              <input id="new-url" className="input" spellCheck={false} placeholder="https://api.example.com/v1" value={form.base_url} disabled={locked} onChange={(e) => setForm((f) => ({ ...f, base_url: e.target.value }))} />
            </div>
          )}
        </div>
        <div className="row between wrap" style={{ marginTop: 12 }}>
          <span className="dev-help" style={{ margin: 0, maxWidth: 520 }}>
            {spec ? `RAF asks ${spec.name} for its model list to check the key (free), then saves it encrypted.` : "The provider is recognised from the key where possible."}
          </span>
          <Button variant="primary" icon={adding ? undefined : "plus"} disabled={locked || adding || !form.key.trim() || !provider} onClick={add}>{adding ? <><Spinner /> Checking…</> : "Add key"}</Button>
        </div>
      </div>
    </section>
  );
}
