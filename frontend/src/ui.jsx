import { createContext, useCallback, useContext, useState } from "react";

const PATHS = {
  sun: "M12 4V2m0 20v-2m8-8h2M2 12h2m13.66-5.66 1.41-1.41M4.93 19.07l1.41-1.41m0-11.32L4.93 4.93m14.14 14.14-1.41-1.41M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z",
  arrow: "M5 12h14m-6-6 6 6-6 6",
  back: "M19 12H5m6 6-6-6 6-6",
  plus: "M12 5v14M5 12h14",
  check: "m5 12.5 4.5 4.5L19 7",
  x: "M6 6l12 12M18 6 6 18",
  upload: "M12 16V4m0 0-5 5m5-5 5 5M4 17v2a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-2",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Zm0 0v5h5",
  spark: "M12 3v4m0 10v4M3 12h4m10 0h4M6.3 6.3l2.5 2.5m6.4 6.4 2.5 2.5m0-11.4-2.5 2.5m-6.4 6.4-2.5 2.5",
  expand: "M4 9V4h5M20 15v5h-5M4 4l6 6m10 10-6-6",
  condense: "M10 4v6H4m10 10v-6h6M4 10l6-6m10 10-6 6",
  formal: "M4 20h16M6 16V9m4 7V9m4 7V9m4 7V9M3 9l9-5 9 5",
  simple: "M4 6h16M4 12h10M4 18h6",
  cite: "M7 7h4v4c0 3-2 5-4 6m8-10h4v4c0 3-2 5-4 6",
  polish: "m15 4 5 5L9 20H4v-5L15 4Z",
  human: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 9a7 7 0 0 1 14 0",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-5a4 4 0 1 0 0-8 4 4 0 0 0 0 8Z",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  edit: "M4 20h4L19 9l-4-4L4 16v4Z",
  history: "M3 12a9 9 0 1 0 3-6.7L3 8m0-5v5h5m4-1v5l3 2",
  trash: "M4 7h16m-10 4v6m4-6v6M6 7l1 13h10l1-13M9 7V4h6v3",
  download: "M12 4v12m0 0 5-5m-5 5-5-5M4 20h16",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-9-9h18M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3Z",
  chart: "M4 20V10m6 10V4m6 16v-7m4 7H2",
  send: "M4 12 20 4l-6 16-3-7-7-1Z",
  data: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
};

export function Icon({ name, size = 16, stroke = 1.7 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name]} />
    </svg>
  );
}

export function Button({ variant = "", size = "", icon, iconRight, children, className = "", ...rest }) {
  return (
    <button className={`btn ${variant} ${size} ${className}`} {...rest}>
      {icon && <Icon name={icon} />}
      {children}
      {iconRight && <Icon name={iconRight} />}
    </button>
  );
}

export function Toggle({ checked, onChange, label, hint }) {
  return (
    <label className="toggle">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" />
      <span>
        <div className="t-label">{label}</div>
        {hint && <div className="t-hint">{hint}</div>}
      </span>
    </label>
  );
}

export function Segmented({ value, options, onChange }) {
  return (
    <div className="segmented" role="radiogroup">
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} className={value === o.value ? "on" : ""} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Ring({ value, max, label }) {
  const r = 36;
  const c = 2 * Math.PI * r;
  const pct = Math.min(1, value / max);
  return (
    <div className="ring">
      <svg width="84" height="84">
        <circle cx="42" cy="42" r={r} stroke="var(--surface-3)" strokeWidth="6" fill="none" />
        <circle cx="42" cy="42" r={r} stroke="var(--accent)" strokeWidth="6" fill="none" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - pct)} style={{ transition: "stroke-dashoffset .8s cubic-bezier(.2,.8,.2,1)" }} />
      </svg>
      <div className="ring-label">{label ?? value}</div>
    </div>
  );
}

export function Spinner({ size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" style={{ animation: "spin .8s linear infinite" }} aria-label="working">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity=".25" strokeWidth="3" fill="none" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
    </svg>
  );
}

const ToastCtx = createContext(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const push = useCallback((message, kind = "info") => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, message, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "error" ? 7000 : 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            <span className={`dot ${t.kind === "error" ? "bad" : "ok"}`} style={{ marginTop: 6 }} />
            <span>{t.message}</span>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function timeAgo(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString();
}
