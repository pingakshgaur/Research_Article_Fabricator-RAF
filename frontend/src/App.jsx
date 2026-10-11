import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { AmbientLight, Icon } from "./ui.jsx";
import { applyAppearance, applyMode, currentMode } from "./theme.js";
import Home from "./pages/Home.jsx";
import Setup from "./pages/Setup.jsx";
import References from "./pages/References.jsx";
import Segments from "./pages/Segments.jsx";
import Processing from "./pages/Processing.jsx";
import Studio from "./pages/Studio.jsx";
import Publish from "./pages/Publish.jsx";
import Library from "./pages/Library.jsx";
import History from "./pages/History.jsx";
import Revisions from "./pages/Revisions.jsx";
import Settings from "./pages/Settings.jsx";
import Format from "./pages/Format.jsx";

// Must match API_VERSION in backend/app/main.py.
const EXPECTED_API = "1.7.0";

const STEPS = [
  { key: "setup", label: "Topic & title", hint: "What are we writing?" },
  { key: "references", label: "References", hint: "10–20 source articles" },
  { key: "segments", label: "Segments", hint: "Choose what RAF writes" },
  { key: "processing", label: "Fabrication", hint: "Research · analyse · write" },
  { key: "studio", label: "Studio", hint: "Review, revise, approve" },
  { key: "published", label: "Publish", hint: "DOCX · PDF · Markdown" },
];

// Views of a project that are not steps of the workflow.
const RECORD = [
  { key: "history", label: "History", hint: "Everything that happened", icon: "clock" },
  { key: "revisions", label: "Revisions", hint: "Saved states · reviewer rounds", icon: "history" },
];

/**
 * Addresses: #/raf (RAF home) · #/raf/library · #/raf/settings · #/raf/new · #/raf/format · #/raf/p/{id}/{view}.
 * RAF lives under /raf so that a suite home page can take over "#/" later; addresses from before 1.5 are redirected.
 */
const RAIL = { min: 64, max: 420, usual: 216, compactBelow: 132 };

/** Width of the sidebar: dragged with the mouse (or set with the arrow keys), remembered by this browser. */
function useRail() {
  const [width, setWidth] = useState(() => {
    let saved = 0;
    try { saved = Number(localStorage.getItem("raf-rail")); } catch { /* storage unavailable */ }
    return saved >= RAIL.min && saved <= RAIL.max ? saved : RAIL.usual;
  });
  const apply = useCallback((w) => {
    const next = Math.round(Math.min(RAIL.max, Math.max(RAIL.min, w)));
    setWidth(next);
    document.documentElement.style.setProperty("--rail-w", `${next}px`);
    try { localStorage.setItem("raf-rail", String(next)); } catch { /* ignore */ }
  }, []);
  useEffect(() => { document.documentElement.style.setProperty("--rail-w", `${width}px`); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const startDrag = (e) => {
    e.preventDefault();
    const handle = e.currentTarget;
    const left = handle.parentElement.getBoundingClientRect().left;
    const move = (ev) => apply(ev.clientX - left);
    const stop = () => { removeEventListener("pointermove", move); removeEventListener("pointerup", stop); document.body.classList.remove("resizing"); };
    document.body.classList.add("resizing");
    addEventListener("pointermove", move);
    addEventListener("pointerup", stop);
  };
  const onKey = (e) => {
    const step = e.shiftKey ? 40 : 12;
    if (e.key === "ArrowLeft") { e.preventDefault(); apply(width - step); }
    if (e.key === "ArrowRight") { e.preventDefault(); apply(width + step); }
    if (e.key === "Home") { e.preventDefault(); apply(RAIL.min); }
    if (e.key === "End") { e.preventDefault(); apply(RAIL.max); }
  };
  return { width, compact: width < RAIL.compactBelow, startDrag, onKey, reset: () => apply(RAIL.usual) };
}

const readHash = () => {
  let h = location.hash.replace(/^#\/?/, "");
  if (!h.startsWith("raf")) {
    h = h === "new" || h.startsWith("p/") ? `raf/${h}` : "raf";
    history.replaceState(null, "", `#/${h}`);
  }
  const m = h.match(/^raf\/p\/([a-z0-9]+)(?:\/(\w+))?/);
  if (m) return { id: m[1], view: m[2] };
  return { id: null, view: ["new", "library", "settings", "format"].find((v) => h === `raf/${v}`) || null };
};

export default function App() {
  const [route, setRoute] = useState(readHash);
  const [project, setProject] = useState(null);
  const [health, setHealth] = useState(null);
  const [events, setEvents] = useState([]);
  const [theme, setTheme] = useState(currentMode);
  const [app, setApp] = useState(null);     // RAF settings from the server: { settings, palettes, locked, unlocked, info }
  const mainRef = useRef(null);
  const rail = useRail();

  useEffect(() => {
    const onHash = () => setRoute(readHash());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    const load = () => api.health().then(setHealth).catch(() => setHealth({ status: "down", ollama: false }));
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, []);

  const loadApp = useCallback(() => api.appSettings().then((a) => { setApp(a); applyAppearance(a.settings); return a; }).catch(() => setApp((a) => a || { settings: null })), []);
  useEffect(() => { loadApp(); }, [loadApp]);
  const setMode = (next) => { setTheme(next); applyMode(next); };

  const refresh = useCallback(async () => {
    if (!route.id) return null;
    const p = await api.project(route.id);
    setProject(p);
    return p;
  }, [route.id]);

  useEffect(() => {
    setProject(null);
    setEvents([]);
    if (!route.id) return;
    refresh().then((p) => p && setEvents(p.log || [])).catch(() => navigate(null));
    let timer;
    const stop = api.events(route.id, (ev) => {
      if (ev.kind === "hello") return;
      setEvents((list) => [...list.slice(-600), ev]);
      if (["segment", "job", "done", "error", "stage", "checkpoint"].includes(ev.kind)) {
        clearTimeout(timer);
        timer = setTimeout(() => refresh().catch(() => {}), 250);
      }
    });
    return () => { stop(); clearTimeout(timer); };
  }, [route.id, refresh]);

  const navigate = (id, view) => {
    location.hash = id ? `#/raf/p/${id}${view ? "/" + view : ""}` : view ? `#/raf/${view}` : "#/raf";
    mainRef.current?.scrollTo({ top: 0 });
  };

  const view = project ? route.view || (project.stage === "processing" && !project.busy && Object.values(project.segments).every((s) => s.content) && Object.keys(project.segments).length ? "studio" : project.stage) : null;
  const reached = project ? STEPS.findIndex((s) => s.key === project.stage) : -1;
  const hasDrafts = project && Object.values(project.segments).some((s) => s.content);

  const stepEnabled = (key, i) => {
    if (!project) return false;
    if (project.mode === "format") return key === "studio" || key === "published";   // an article brought in for typesetting has no writing steps
    if (project.busy && key !== "processing" && key !== "studio") return false;
    if (key === "studio" || key === "published") return hasDrafts;
    if (key === "processing") return project.busy || reached >= 3;
    return i <= Math.max(reached, 2);
  };

  const pageProps = { project, setProject, refresh, navigate, events, health };
  const segmentJobs = Object.values(project?.busy_segments || {});

  return (
    <div className="shell">
      {app?.settings?.effects !== false && <AmbientLight />}
      <header className="topbar">
        <button className="brand" onClick={() => navigate(null)} aria-label="RAF home">
          <span className="brand-mark">RAF</span>
          <span className="brand-sub">{app?.settings?.workspace || "Research Article Fabricator"}</span>
        </button>
        <div className="topbar-spacer" />
        {project?.busy && (
          <span className="status-pill fade"><span className="dot live" />{project.busy}</span>
        )}
        {!project?.busy && segmentJobs.length > 0 && (
          <span className="status-pill fade" title={segmentJobs.join("\n")}>
            <span className="dot live" />
            {segmentJobs.length === 1 ? segmentJobs[0] : `Studio · ${segmentJobs.length} segments in progress`}
          </span>
        )}
        <span className="status-pill" title={health?.error || ""}>
          <span className={`dot ${health?.ollama && health?.model_available ? "ok" : health ? "bad" : ""}`} />
          {!health ? "Checking engine…" : health.ollama ? (health.model_available ? `${health.model} · local` : `${health.model} not pulled`) : "Ollama offline"}
        </span>
        <button className={`btn icon dev-button ${!route.id && route.view === "settings" ? "on" : ""}`} aria-label="Settings" title="Settings"
          onClick={() => navigate(null, "settings")}>
          <Icon name="gear" size={16} />
        </button>
        <button className="theme-switch" aria-label="Toggle colour theme"
          onClick={() => setMode(theme === "dark" ? "light" : "dark")}>
          <span className="knob"><Icon name={theme === "dark" ? "moon" : "sun"} size={13} stroke={2} /></span>
        </button>
      </header>

      <nav className={`rail ${rail.compact ? "compact" : ""}`} aria-label="Navigation">
        <button className={`rail-step ${!route.id && route.view === "library" ? "active" : ""}`} title="Library — every article project" onClick={() => navigate(null, "library")}>
          <span className="num"><Icon name="books" size={15} /></span>
          <span className="label">Library</span>
        </button>
        <div className="rail-rule" role="separator" />
        {STEPS.map((s, i) => (
          <button key={s.key} disabled={!stepEnabled(s.key, i)} title={`${s.label} — ${s.hint}`}
            className={`rail-step ${view === s.key ? "active" : ""} ${i < reached ? "done" : ""}`}
            onClick={() => navigate(project.id, s.key)}>
            <span className="num">{String(i + 1).padStart(2, "0")}</span>
            <span className="label">{s.label}</span>
          </button>
        ))}
        <div className="rail-rule" role="separator" />
        {RECORD.map((s) => (
          <button key={s.key} disabled={!project} title={`${s.label} — ${s.hint}`} className={`rail-step ${view === s.key ? "active" : ""}`} onClick={() => navigate(project.id, s.key)}>
            <span className="num"><Icon name={s.icon} size={15} /></span>
            <span className="label">{s.label}</span>
          </button>
        ))}
        <div className="rail-resize" role="separator" aria-orientation="vertical" aria-label="Sidebar width — drag, or use the arrow keys; double-click to reset"
          aria-valuenow={rail.width} aria-valuemin={RAIL.min} aria-valuemax={RAIL.max} tabIndex={0} title="Drag to resize · double-click to reset"
          onPointerDown={rail.startDrag} onDoubleClick={rail.reset} onKeyDown={rail.onKey} />
      </nav>

      <main className="main" ref={mainRef}>
        {health?.status === "ok" && health.api_version !== EXPECTED_API && (
          <div className="stale-banner" role="alert">
            <span className="dot bad" />
            <span>
              <b>The API server is running older code</b> ({health.api_version || "before 1.2"}; this interface expects {EXPECTED_API}).
              Restart it so the latest fixes apply: press <span className="mono">Ctrl+C</span> in the API window and start it again.
            </span>
          </div>
        )}
        {!route.id && !route.view && <Home navigate={navigate} health={health} />}
        {!route.id && route.view === "library" && <Library navigate={navigate} />}
        {!route.id && route.view === "format" && <Format navigate={navigate} />}
        {!route.id && route.view === "settings" && (
          <Settings app={app} reload={loadApp} mode={theme} setMode={setMode} navigate={navigate} onModelChange={() => api.health().then(setHealth).catch(() => {})} />
        )}
        {!route.id && route.view === "new" && (app ? <Setup {...pageProps} project={null} defaults={app.settings?.article} /> : <div className="empty">Loading…</div>)}
        {route.id && !project && <div className="empty">Loading project…</div>}
        {project && view === "setup" && <Setup {...pageProps} />}
        {project && view === "references" && <References {...pageProps} />}
        {project && view === "segments" && <Segments {...pageProps} />}
        {project && view === "processing" && <Processing {...pageProps} />}
        {project && view === "studio" && <Studio {...pageProps} />}
        {project && view === "published" && <Publish {...pageProps} />}
        {project && view === "history" && <History {...pageProps} />}
        {project && view === "revisions" && <Revisions {...pageProps} />}
      </main>
    </div>
  );
}
