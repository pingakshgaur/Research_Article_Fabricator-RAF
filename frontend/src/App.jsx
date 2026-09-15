import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api.js";
import { AmbientLight, Icon } from "./ui.jsx";
import DevTools from "./DevTools.jsx";
import Home from "./pages/Home.jsx";
import Setup from "./pages/Setup.jsx";
import References from "./pages/References.jsx";
import Segments from "./pages/Segments.jsx";
import Processing from "./pages/Processing.jsx";
import Studio from "./pages/Studio.jsx";
import Publish from "./pages/Publish.jsx";

// Must match API_VERSION in backend/app/main.py.
const EXPECTED_API = "1.4.0";

const STEPS = [
  { key: "setup", label: "Topic & title", hint: "What are we writing?" },
  { key: "references", label: "References", hint: "10–20 source articles" },
  { key: "segments", label: "Segments", hint: "Choose what RAF writes" },
  { key: "processing", label: "Fabrication", hint: "Research · analyse · write" },
  { key: "studio", label: "Studio", hint: "Review, revise, approve" },
  { key: "published", label: "Publish", hint: "DOCX · PDF · Markdown" },
];

const readHash = () => {
  const m = location.hash.match(/^#\/p\/([a-z0-9]+)(?:\/(\w+))?/);
  if (m) return { id: m[1], view: m[2] };
  return { id: null, view: location.hash === "#/new" ? "new" : null };
};

function applyTheme(next) {
  const set = () => {
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("raf-theme", next); } catch { /* storage unavailable */ }
  };
  // Circular reveal from the toggle when the View Transitions API is available.
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) document.startViewTransition(set);
  else set();
}

export default function App() {
  const [route, setRoute] = useState(readHash);
  const [project, setProject] = useState(null);
  const [health, setHealth] = useState(null);
  const [events, setEvents] = useState([]);
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || "dark");
  const mainRef = useRef(null);
  const [devOpen, setDevOpen] = useState(false);

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
    location.hash = id ? `#/p/${id}${view ? "/" + view : ""}` : view === "new" ? "#/new" : "#/";
    mainRef.current?.scrollTo({ top: 0 });
  };

  const view = project ? route.view || (project.stage === "processing" && !project.busy && Object.values(project.segments).every((s) => s.content) && Object.keys(project.segments).length ? "studio" : project.stage) : null;
  const reached = project ? STEPS.findIndex((s) => s.key === project.stage) : -1;
  const hasDrafts = project && Object.values(project.segments).some((s) => s.content);

  const stepEnabled = (key, i) => {
    if (!project) return false;
    if (project.busy && key !== "processing" && key !== "studio") return false;
    if (key === "studio" || key === "published") return hasDrafts;
    if (key === "processing") return project.busy || reached >= 3;
    return i <= Math.max(reached, 2);
  };

  const pageProps = { project, setProject, refresh, navigate, events, health };
  const segmentJobs = Object.values(project?.busy_segments || {});

  return (
    <div className="shell">
      <AmbientLight />
      <header className="topbar">
        <button className="brand" onClick={() => navigate(null)} aria-label="RAF home">
          <span className="brand-mark">RAF</span>
          <span className="brand-sub">Research Article Fabricator</span>
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
        <button className={`btn icon dev-button ${devOpen ? "on" : ""}`} aria-label="Developer tools: language model settings" title="Developer tools"
          onClick={() => setDevOpen(true)}>
          <Icon name="sliders" size={16} />
        </button>
        <button className="theme-switch" aria-label="Toggle colour theme"
          onClick={() => { const next = theme === "dark" ? "light" : "dark"; setTheme(next); applyTheme(next); }}>
          <span className="knob"><Icon name={theme === "dark" ? "moon" : "sun"} size={13} stroke={2} /></span>
        </button>
      </header>

      <DevTools open={devOpen} onClose={() => { setDevOpen(false); api.health().then(setHealth).catch(() => {}); }} />

      <nav className="rail" aria-label="Workflow">
        <div className="rail-title">{project ? "Workflow" : "Start"}</div>
        {STEPS.map((s, i) => (
          <button key={s.key} disabled={!stepEnabled(s.key, i)}
            className={`rail-step ${view === s.key ? "active" : ""} ${i < reached ? "done" : ""}`}
            onClick={() => navigate(project.id, s.key)}>
            <span className="num">{String(i + 1).padStart(2, "0")}</span>
            <span className="label">{s.label}</span>
            <span className="hint">{s.hint}</span>
          </button>
        ))}
        <div className="rail-foot">
          Everything runs on this machine — your documents never leave it, except for public research queries.
        </div>
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
        {!route.id && route.view !== "new" && <Home navigate={navigate} health={health} />}
        {!route.id && route.view === "new" && <Setup {...pageProps} project={null} />}
        {route.id && !project && <div className="empty">Loading project…</div>}
        {project && view === "setup" && <Setup {...pageProps} />}
        {project && view === "references" && <References {...pageProps} />}
        {project && view === "segments" && <Segments {...pageProps} />}
        {project && view === "processing" && <Processing {...pageProps} />}
        {project && view === "studio" && <Studio {...pageProps} />}
        {project && view === "published" && <Publish {...pageProps} />}
      </main>
    </div>
  );
}
