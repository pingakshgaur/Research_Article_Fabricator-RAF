import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../api.js";
import DevTools from "../DevTools.jsx";
import { deriveTheme, hexToRgb, rgbToHex, validHex } from "../customTheme.js";
import { THEMES, applyAppearance } from "../theme.js";
import { Button, Combo, Icon, Segmented, Select, Spinner, Toggle, useToast } from "../ui.jsx";
import { DISCIPLINES, TYPES } from "./Setup.jsx";

const TABS = [
  { value: "appearance", label: "Appearance" },
  { value: "articles", label: "New articles" },
  { value: "model", label: "Language model" },
  { value: "admin", label: "Admin lock" },
  { value: "about", label: "About" },
];
const AGENTS = [{ value: 1, label: "Solo · 1" }, { value: 2, label: "Duo · 2" }, { value: 3, label: "Trio · 3" }];

/**
 * The floating colour button of the Custom theme. Pick with the system colour dialog, the R / G / B sliders or a hex
 * code; the page previews the result as you go, and nothing is saved until "Use this colour".
 */
function ColourPicker({ value, disabled, onPreview, onUse, onCancel }) {
  const [open, setOpen] = useState(false);
  const [hex, setHex] = useState(value);
  const [text, setText] = useState(value);
  useEffect(() => { if (!open) { setHex(value); setText(value); } }, [value, open]);
  const pick = (c) => { setHex(c); setText(c); onPreview(c); };
  const close = (keep) => { setOpen(false); if (keep) onUse(hex); else onCancel(); };
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => e.key === "Escape" && close(false);
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }); // eslint-disable-line react-hooks/exhaustive-deps
  const rgb = hexToRgb(hex);
  const made = deriveTheme(hex);
  const swatches = [
    ["Accent", made.accent, made.accentInk], ["Contrast", made.contrasting, "#0b0b12"],
    ["Light accent", made.lightAccent, "#15130f"], ["Light contrast", made.lightContrasting, "#ffffff"],
  ];
  // Rendered on <body>. Inside the page it belonged to the Theme card, so the cards below it (and their lighting
  // effects) were painted over the panel.
  return createPortal(
    <>
      <button type="button" className="rgb-fab" disabled={disabled} aria-expanded={open} aria-label="Custom theme: pick a colour"
        title={disabled ? "Unlock Settings to change the theme" : "Custom theme — pick any colour"}
        onClick={() => (open ? close(false) : (setOpen(true), onPreview(hex)))}>
        <i style={{ background: hex }} />
      </button>
      {open && (
        <div className="rgb-pop" role="dialog" aria-label="Custom theme colour">
          <h5>Custom theme</h5>
          <div className="rgb-well">
            <input type="color" value={hex} onChange={(e) => pick(e.target.value.toLowerCase())} aria-label="Colour" />
            <div className="stack" style={{ gap: 6, justifyContent: "center" }}>
              {["R", "G", "B"].map((channel, i) => {
                const set = (v) => pick(rgbToHex(rgb.map((old, j) => (j === i ? Math.min(255, Math.max(0, Number(v) || 0)) : old))));
                return (
                  <div key={channel} className="rgb-row">
                    <span>{channel}</span>
                    <input type="range" className="range" min={0} max={255} value={rgb[i]} onChange={(e) => set(e.target.value)} aria-label={`${channel} slider`} />
                    <input type="number" className="input" min={0} max={255} value={rgb[i]} onChange={(e) => set(e.target.value)} aria-label={`${channel} value`} />
                  </div>
                );
              })}
            </div>
          </div>
          <input className="input mono" value={text} maxLength={7} spellCheck={false} aria-label="Hex colour" placeholder="#2f7df6"
            onChange={(e) => { const v = e.target.value.trim(); setText(v); if (validHex(v)) { setHex(v.toLowerCase()); onPreview(v.toLowerCase()); } }} />
          <div className="rgb-made">
            {swatches.map(([label, bg, ink]) => <div key={label} style={{ background: bg, color: ink }} title={bg}>Aa</div>)}
            {swatches.map(([label]) => <span key={label}>{label}</span>)}
          </div>
          <div className="theme-ramp" style={{ background: made.vars["--ramp"], height: 22 }} />
          <p className="muted" style={{ fontSize: 12, margin: 0 }}>
            Every shade, the text colour on buttons and the contrasting colour are worked out from this one colour, for dark and light mode,
            and adjusted where needed so text stays readable.
          </p>
          <div className="row between">
            <Button size="sm" variant="ghost" onClick={() => close(false)}>Cancel</Button>
            <Button size="sm" variant="primary" icon="check" onClick={() => close(true)}>Use this colour</Button>
          </div>
        </div>
      )}
    </>,
    document.body,
  );
}

/** Shown on every tab while a passcode is set and this session has not entered it. */
function Unlock({ onDone }) {
  const toast = useToast();
  const [passcode, setPasscode] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try { await api.unlock(passcode); setPasscode(""); await onDone(); toast("Settings unlocked"); } catch (err) { toast(err.message, "error"); } finally { setBusy(false); }
  };
  return (
    <div className="lock-note" role="status">
      <Icon name="lock" size={18} />
      <span>Settings are locked. You can look, but changing them needs the admin passcode.</span>
      <form onSubmit={submit}>
        <input className="input" type="password" autoComplete="current-password" value={passcode} onChange={(e) => setPasscode(e.target.value)} placeholder="Admin passcode" aria-label="Admin passcode" />
        <Button size="sm" variant="primary" icon="unlock" disabled={busy || !passcode}>Unlock</Button>
      </form>
    </div>
  );
}

function AdminLock({ app, locked, reload }) {
  const toast = useToast();
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const run = async (fn, message) => {
    setBusy(true);
    try { await fn(); setNext(""); setAgain(""); await reload(); toast(message); } catch (err) { toast(err.message, "error"); } finally { setBusy(false); }
  };
  const mismatch = again.length > 0 && next !== again;
  return (
    <div className="settings-panel">
      <div className="card">
        <h5>Admin lock <Icon name={app.locked ? "lock" : "unlock"} size={14} /></h5>
        <p style={{ marginTop: 0, maxWidth: 680 }}>
          {app.locked
            ? "A passcode is set. Everything on this page can be read by anyone using RAF, but only someone who enters the passcode can change it."
            : "No passcode is set, so anyone using RAF on this computer can change these settings. Set one to keep the theme, the defaults and the model settings as you chose them."}
        </p>
        <p className="muted" style={{ fontSize: 12.5, maxWidth: 680 }}>
          The lock covers this Settings page only. It does not hide your articles, and it does not stop someone who can open RAF's data folder:
          a forgotten passcode is removed by deleting the “admin” entry in <span className="mono">app_settings.json</span> there.
          An unlocked session stays unlocked for 12 hours or until RAF's server restarts.
        </p>
        {locked ? <p className="muted" style={{ marginBottom: 0 }}>Unlock above to change or remove the passcode.</p> : (
          <form className="stack" style={{ gap: 12, maxWidth: 420, marginTop: 16 }} onSubmit={(e) => { e.preventDefault(); run(() => api.setPasscode(next), app.locked ? "Passcode changed" : "Admin lock is on"); }}>
            <div className="field">
              <label htmlFor="pc-new">{app.locked ? "New passcode" : "Passcode"} <span className="opt">at least 4 characters</span></label>
              <input id="pc-new" className="input" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="pc-again">Type it again {mismatch && <span className="opt" style={{ color: "var(--bad)" }}>does not match</span>}</label>
              <input id="pc-again" className="input" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} />
            </div>
            <div className="row wrap">
              <Button variant="primary" icon="lock" disabled={busy || next.length < 4 || next !== again}>{app.locked ? "Change passcode" : "Turn the lock on"}</Button>
              {app.locked && (
                <>
                  <Button type="button" icon="lock" disabled={busy} onClick={() => run(() => api.lock(), "Settings locked")}>Lock now</Button>
                  <Button type="button" variant="ghost" className="danger" disabled={busy}
                    onClick={() => confirm("Remove the admin lock? Anyone using RAF will be able to change the settings.") && run(() => api.setPasscode(""), "Admin lock removed")}>Remove the lock</Button>
                </>
              )}
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

export default function Settings({ app, reload, mode, setMode, navigate, onModelChange }) {
  const toast = useToast();
  const [tab, setTab] = useState("appearance");
  const [form, setForm] = useState(null);       // editable copy of app.settings
  const [tones, setTones] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => { if (app?.settings) setForm(app.settings); }, [app]);
  useEffect(() => { api.tones().then(setTones).catch(() => {}); }, []);
  const saved = useRef(app?.settings);
  saved.current = app?.settings;
  useEffect(() => () => applyAppearance(saved.current), []);   // leaving the page drops a preview that was not saved

  if (!app) return <div className="empty"><Spinner /> Loading…</div>;
  if (!app.settings || !form) return <div className="empty card">RAF's settings could not be loaded. Is the API server running?</div>;

  const locked = app.locked && !app.unlocked;
  const save = async (patch, message = "Saved") => {
    setSaving(true);
    try {
      await api.saveAppSettings(patch);
      await reload();
      if (message) toast(message);
    } catch (err) {
      toast(err.message, "error");
      applyAppearance(app.settings);
      setForm(app.settings);
    } finally {
      setSaving(false);
    }
  };
  const look = (patch) => {   // appearance changes show at once and are saved straight away
    const next = { ...form, ...patch };
    setForm(next);
    applyAppearance(next);
    save(patch, "");
  };
  const set = (group, key) => (value) => setForm((f) => ({ ...f, [group]: { ...f[group], [key]: value?.target ? value.target.value : value } }));
  const authors = Array.isArray(form.article.authors) ? form.article.authors.join(", ") : form.article.authors;
  const articleDirty = JSON.stringify([form.article, form.run, form.tone]) !== JSON.stringify([app.settings.article, app.settings.run, app.settings.tone]);
  const tone = tones.find((t) => t.key === form.tone.name);
  const level = form.tone.intensity <= 33 ? 0 : form.tone.intensity <= 66 ? 1 : 2;

  return (
    <div className="page">
      <div className="eyebrow rise">Settings</div>
      <h1 className="display rise" style={{ "--i": 1, fontSize: "clamp(34px,4.4vw,56px)" }}>Make RAF <em>yours.</em></h1>
      <div className="settings-tabs rise" style={{ "--i": 2 }}>
        <Segmented value={tab} onChange={(t) => { if (tab === "model") onModelChange?.(); setTab(t); }} options={TABS} />
      </div>
      {locked && <Unlock onDone={reload} />}

      {tab === "appearance" && (
        <div className="settings-panel">
          <div className="card">
            <h5>Theme <Icon name="palette" size={14} /></h5>
            <div className="theme-grid">
              {THEMES.map((t) => {
                const ramp = t.ramp || deriveTheme(form.custom_color).ramp;      // the Custom theme draws its ramp from the picked colour
                return (
                  <button key={t.key} type="button" className={`theme-card ${form.palette === t.key ? "on" : ""}`} aria-pressed={form.palette === t.key}
                    disabled={locked || saving} onClick={() => form.palette !== t.key && look({ palette: t.key })}>
                    <div className="theme-ramp" style={{ background: `linear-gradient(90deg, ${ramp.join(", ")})` }} />
                    <div className="theme-chips">{ramp.map((c, i) => <i key={i} style={{ background: c }} title={c} />)}</div>
                    <b>{t.name}{t.key === "custom" && <span className="mono" style={{ marginLeft: 8 }}>{form.custom_color}</span>}</b>
                    <span>{t.blurb}</span>
                  </button>
                );
              })}
            </div>
            <p className="muted" style={{ fontSize: 12.5, margin: "14px 0 0" }}>
              The theme colours the interface for everyone using this RAF. Published documents keep the colour style you pick on the Publish page.
              For a theme of your own, use the round colour button at the bottom right.
            </p>
            <ColourPicker value={form.custom_color} disabled={locked || saving}
              onPreview={(c) => applyAppearance({ ...form, palette: "custom", custom_color: c })}
              onUse={(c) => look({ palette: "custom", custom_color: c })} onCancel={() => applyAppearance(form)} />
          </div>
          <div className="card">
            <div className="grid-2" style={{ alignItems: "start" }}>
              <div className="field">
                <label>Mode <span className="opt">this browser only</span></label>
                <Segmented value={mode} onChange={setMode} options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }]} />
                <span className="muted" style={{ fontSize: 12 }}>Every theme has a dark and a light version. The switch in the top bar does the same.</span>
              </div>
              <div style={{ pointerEvents: locked ? "none" : undefined, opacity: locked ? 0.55 : 1 }}>
                <Toggle checked={form.effects} onChange={(effects) => look({ effects })} label="Background effects"
                  hint="Ambient light, paper grain and the glow that follows the cursor. Turn off for a calmer, flatter page." />
              </div>
            </div>
          </div>
          <div className="card">
            <div className="field" style={{ maxWidth: 460 }}>
              <label htmlFor="workspace">Workspace name <span className="opt">optional — shown under the RAF mark</span></label>
              <input id="workspace" className="input" maxLength={60} disabled={locked} value={form.workspace} placeholder="Research Article Fabricator"
                onChange={(e) => setForm({ ...form, workspace: e.target.value })}
                onBlur={() => form.workspace !== app.settings.workspace && save({ workspace: form.workspace }, "Workspace name saved")}
                onKeyDown={(e) => e.key === "Enter" && e.target.blur()} />
              <span className="muted" style={{ fontSize: 12 }}>For example a lab, department or team name.</span>
            </div>
          </div>
        </div>
      )}

      {tab === "articles" && (
        <form className="settings-panel" onSubmit={(e) => {
          e.preventDefault();
          save({ article: { ...form.article, authors: String(authors).split(",").map((a) => a.trim()).filter(Boolean) }, run: form.run, tone: form.tone }, "Defaults saved — they apply to articles you create from now on");
        }}>
          <fieldset disabled={locked} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }} className="settings-panel">
            <div className="card">
              <h5>What a new article starts with</h5>
              <div className="stack">
                <div className="grid-2">
                  <div className="field"><label htmlFor="d-authors">Author(s) <span className="opt">comma separated</span></label>
                    <input id="d-authors" className="input" value={authors} onChange={set("article", "authors")} placeholder="Jane Doe, John Smith" /></div>
                  <div className="field"><label htmlFor="d-aff">Affiliation</label>
                    <input id="d-aff" className="input" value={form.article.affiliation} onChange={set("article", "affiliation")} placeholder="Department, University" /></div>
                </div>
                <div className="grid-2">
                  <div className="field"><label htmlFor="d-disc">Discipline</label>
                    <Combo id="d-disc" value={form.article.discipline} onChange={set("article", "discipline")} suggestions={DISCIPLINES} placeholder="Choose or type a field" /></div>
                  <div className="field"><label>Article type</label>
                    <Select value={form.article.article_type} onChange={set("article", "article_type")} options={TYPES.map((t) => ({ value: t, label: t }))} /></div>
                </div>
                <div className="grid-2">
                  <div className="field"><label>Citation style</label>
                    <Segmented value={form.article.citation_style} onChange={set("article", "citation_style")} options={["APA", "Harvard", "Chicago", "IEEE"].map((v) => ({ value: v, label: v }))} /></div>
                  <div className="field"><label htmlFor="d-words">Target length <span className="mono">{Number(form.article.target_words).toLocaleString()} words</span></label>
                    <input id="d-words" type="range" className="range" min={2500} max={12000} step={500} value={form.article.target_words}
                      onChange={(e) => set("article", "target_words")(Number(e.target.value))} /></div>
                </div>
              </div>
            </div>
            <div className="card">
              <h5>How RAF writes it</h5>
              <div className="grid-2" style={{ alignItems: "start" }}>
                <Toggle checked={form.run.web_research} onChange={set("run", "web_research")} label="Online research" hint="Scholarly databases & the open web" />
                <Toggle checked={form.run.data_analysis} onChange={set("run", "data_analysis")} label="Data analysis" hint="Statistics, tables & figures" />
                <Toggle checked={form.run.hallucination_filter} onChange={set("run", "hallucination_filter")} label="Hallucination filter" hint="Checks every claim against its cited source" />
                <Toggle checked={form.run.style_pass} onChange={set("run", "style_pass")} label="Style & naturalness pass" hint="Thorough mode only" />
              </div>
              <div className="grid-2" style={{ marginTop: 18 }}>
                <div className="field"><label>Writing depth</label>
                  <Segmented value={form.run.depth} onChange={set("run", "depth")} options={[{ value: "thorough", label: "Thorough" }, { value: "quick", label: "Quick draft" }]} /></div>
                <div className="field"><label>Agents working in parallel</label>
                  <Segmented value={form.run.agents} onChange={set("run", "agents")} options={AGENTS} /></div>
              </div>
              <div className="grid-2" style={{ marginTop: 18 }}>
                <div className="field"><label>Tone</label>
                  <Select value={form.tone.name} onChange={set("tone", "name")} options={tones.map((t) => ({ value: t.key, label: t.label, hint: t.summary }))} /></div>
                <div className="field"><label htmlFor="d-tone">Intensity <span className="mono">{form.tone.intensity} · {["subtle", "balanced", "strong"][level]}</span></label>
                  <input id="d-tone" type="range" className="range" min={0} max={100} value={form.tone.intensity} onChange={(e) => set("tone", "intensity")(Number(e.target.value))} /></div>
              </div>
              {tone && <p className="muted" style={{ fontSize: 12.5, marginBottom: 0 }}>Instruction given to RAF: {tone.levels[level]}</p>}
            </div>
          </fieldset>
          <div className="settings-foot">
            <span className="muted" style={{ fontSize: 12.5 }}>Projects you already have keep their own choices; each can still be changed on its own pages.</span>
            <div className="row">
              {articleDirty && <span className="badge warn">Unsaved</span>}
              <Button variant="primary" icon="check" disabled={!articleDirty || saving || locked}>{saving ? "Saving…" : "Save defaults"}</Button>
            </div>
          </div>
        </form>
      )}

      {tab === "model" && <DevTools inline locked={locked} />}

      {tab === "admin" && <AdminLock app={app} locked={locked} reload={reload} />}

      {tab === "about" && (
        <div className="settings-panel">
          <div className="card">
            <h5>This installation</h5>
            <dl className="about-grid">
              <dt>RAF version</dt><dd className="mono">{app.info.version}</dd>
              <dt>Language model</dt><dd className="mono">{app.info.model}</dd>
              <dt>Theme</dt><dd>{THEMES.find((t) => t.key === app.settings.palette)?.name} · {mode}</dd>
              <dt>Projects</dt><dd>{app.info.projects} <button className="btn ghost sm" style={{ marginLeft: 8 }} onClick={() => navigate(null, "library")}>Open the Library</button></dd>
              <dt>Data folder</dt><dd className="mono">{app.info.data_dir}</dd>
              <dt>Admin lock</dt><dd>{app.locked ? (locked ? "On — locked" : "On — unlocked in this session") : "Off"}</dd>
            </dl>
            <p className="muted" style={{ fontSize: 12.5, marginBottom: 0 }}>
              Everything RAF stores lives in the data folder: projects, settings and backups. Copy it to move RAF to another computer.
            </p>
          </div>
          <div className="card">
            <div className="row between wrap">
              <div style={{ maxWidth: 560 }}>
                <b>Reset RAF's settings</b>
                <div className="muted" style={{ fontSize: 13 }}>Back to the original theme and the built-in defaults for new articles. Projects, the language-model settings and the admin lock are not touched.</div>
              </div>
              <Button icon="refresh" disabled={locked || saving}
                onClick={async () => { if (!confirm("Reset the theme and the defaults for new articles?")) return; try { await api.resetAppSettings(); await reload(); toast("Settings reset"); } catch (err) { toast(err.message, "error"); } }}>Reset</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
