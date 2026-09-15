import { createContext, useCallback, useContext, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

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
  sliders: "M4 6h10m4 0h2M4 12h4m4 0h8M4 18h12m4 0h0M14 4v4M8 10v4M16 16v4",
  shield: "M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6l-8-3Zm-3 9 2 2 4-4",
  palette: "M12 3a9 9 0 1 0 0 18c1.1 0 1.5-.8 1.2-1.6-.4-1 .3-2.4 1.6-2.4H17a4 4 0 0 0 4-4c0-5.5-4-10-9-10ZM7.5 11.5h.01M10 7.5h.01M15 7.5h.01",
  gauge: "M12 14l4-4M4 18a9 9 0 1 1 16 0",
  data: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  eye: "M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7Zm9.5 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  chevron: "m6 9 6 6 6-6",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-13v4l3 2",
  zoomIn: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm9 2-4-4M8 11h6m-3-3v6",
  zoomOut: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm9 2-4-4M8 11h6",
  left: "m15 18-6-6 6-6",
  right: "m9 18 6-6-6-6",
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

/* ---------------------------------------------------------------- glass dropdowns */

/** Positions a floating menu under (or above, when there is no room) its anchor. Re-measures on scroll and resize. */
function useFloating(anchorRef, open) {
  const [pos, setPos] = useState(null);
  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const r = anchorRef.current?.getBoundingClientRect();
      if (!r) return;
      const below = innerHeight - r.bottom;
      const up = below < 260 && r.top > below;
      setPos({ left: r.left, width: r.width, top: up ? undefined : r.bottom + 6, bottom: up ? innerHeight - r.top + 6 : undefined,
        maxHeight: Math.max(160, Math.min(320, (up ? r.top : below) - 18)), up });
    };
    place();
    addEventListener("resize", place);
    addEventListener("scroll", place, true);
    return () => { removeEventListener("resize", place); removeEventListener("scroll", place, true); };
  }, [open, anchorRef]);
  return pos;
}

function GlassMenu({ id, anchorRef, open, options, activeIndex, selected, onPick, onHover, onClose }) {
  const pos = useFloating(anchorRef, open);
  const listRef = useRef(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e) => {
      if (!listRef.current?.contains(e.target) && !anchorRef.current?.contains(e.target)) onClose();
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open, onClose, anchorRef]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${activeIndex}"]`)?.scrollIntoView({ block: "nearest" });
  }, [activeIndex]);
  if (!open || !pos || !options.length) return null;
  return createPortal(
    <ul id={id} ref={listRef} role="listbox" className={`glass-menu ${pos.up ? "up" : ""}`}
      style={{ left: pos.left, width: pos.width, top: pos.top, bottom: pos.bottom, maxHeight: pos.maxHeight }}>
      {options.map((o, i) => (
        <li key={String(o.value)} id={`${id}-${i}`} data-index={i} role="option" aria-selected={o.value === selected}
          className={`glass-option ${i === activeIndex ? "active" : ""} ${o.value === selected ? "selected" : ""}`}
          onPointerEnter={() => onHover(i)} onPointerDown={(e) => e.preventDefault()} onClick={() => onPick(o)}>
          <span className="glass-option-label">{o.label}</span>
          {o.hint && <span className="glass-option-hint">{o.hint}</span>}
          {o.value === selected && <Icon name="check" size={14} stroke={2.2} />}
        </li>
      ))}
    </ul>,
    document.body,
  );
}

/** Glass-styled replacement for <select>. options: [{ value, label, hint? }] */
export function Select({ value, options, onChange, id, placeholder = "Choose…", className = "", ...aria }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const ref = useRef(null);
  const menuId = useId();
  const current = options.find((o) => o.value === value);
  const close = useCallback(() => setOpen(false), []);
  const openMenu = () => { setActive(Math.max(0, options.findIndex((o) => o.value === value))); setOpen(true); };
  const pick = (o) => { onChange(o.value); setOpen(false); ref.current?.focus(); };

  const onKeyDown = (e) => {
    if (!open && ["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) { e.preventDefault(); openMenu(); return; }
    if (!open) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((i) => Math.min(options.length - 1, i + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(0, i - 1)); }
    else if (e.key === "Home") { e.preventDefault(); setActive(0); }
    else if (e.key === "End") { e.preventDefault(); setActive(options.length - 1); }
    else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); if (options[active]) pick(options[active]); }
    else if (e.key === "Escape" || e.key === "Tab") { e.stopPropagation(); setOpen(false); }
    else if (e.key.length === 1) {
      const i = options.findIndex((o) => String(o.label).toLowerCase().startsWith(e.key.toLowerCase()));
      if (i >= 0) setActive(i);
    }
  };

  return (
    <>
      <button ref={ref} id={id} type="button" className={`glass-select ${open ? "open" : ""} ${className}`} role="combobox"
        aria-haspopup="listbox" aria-expanded={open} aria-controls={menuId} aria-activedescendant={open && active >= 0 ? `${menuId}-${active}` : undefined}
        onClick={() => (open ? setOpen(false) : openMenu())} onKeyDown={onKeyDown} {...aria}>
        <span className={current ? "" : "muted"}>{current ? current.label : placeholder}</span>
        <Icon name="chevron" size={15} stroke={2} />
      </button>
      <GlassMenu id={menuId} anchorRef={ref} open={open} options={options} activeIndex={active} selected={value}
        onPick={pick} onHover={setActive} onClose={close} />
    </>
  );
}

/** Free-text input with a glass suggestion list (replacement for <input list> + <datalist>). */
export function Combo({ value, suggestions, onChange, id, placeholder, className = "" }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const ref = useRef(null);
  const menuId = useId();
  const q = value.trim().toLowerCase();
  const options = suggestions.filter((s) => !q || s.toLowerCase().includes(q)).map((s) => ({ value: s, label: s }));
  const close = useCallback(() => setOpen(false), []);
  const pick = (o) => { onChange(o.value); setOpen(false); };

  const onKeyDown = (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setActive((i) => Math.min(options.length - 1, i + 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((i) => Math.max(0, i - 1)); }
    else if (e.key === "Enter" && open && options[active]) { e.preventDefault(); pick(options[active]); }
    else if (e.key === "Escape") { e.stopPropagation(); setOpen(false); }
  };

  return (
    <div ref={ref} className="combo">
      <input id={id} className={`input ${className}`} value={value} placeholder={placeholder} autoComplete="off" role="combobox"
        aria-expanded={open} aria-controls={menuId} aria-autocomplete="list" aria-activedescendant={open && active >= 0 ? `${menuId}-${active}` : undefined}
        onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onKeyDown={onKeyDown}
        onChange={(e) => { onChange(e.target.value); setOpen(true); setActive(-1); }} />
      <Icon name="chevron" size={15} stroke={2} />
      <GlassMenu id={menuId} anchorRef={ref} open={open} options={options} activeIndex={active} selected={value}
        onPick={pick} onHover={setActive} onClose={close} />
    </div>
  );
}

/* ---------------------------------------------------------------- shine & ambient light */

const SHINE = ".card, .btn, .tool, .seg-card, .template-card, .format-card, .tone-option, .file-item, .timer-card, .seg-chip, .swatch, .glass-select, .stage-card";

/**
 * One document-level pointer listener drives every light effect:
 *  - `--mx/--my` on the hovered surface (spotlight + lit border in CSS)
 *  - a soft ambient glow that eases after the cursor on the page background
 * Disabled for touch-only devices and reduced-motion users.
 */
export function AmbientLight() {
  const glow = useRef(null);
  useEffect(() => {
    if (matchMedia("(prefers-reduced-motion: reduce)").matches || !matchMedia("(pointer: fine)").matches) return;
    let x = innerWidth / 2, y = innerHeight / 3, tx = x, ty = y, raf = 0, lit = null;
    const tick = () => {
      x += (tx - x) * 0.12;
      y += (ty - y) * 0.12;
      if (glow.current) glow.current.style.transform = `translate3d(${x}px, ${y}px, 0)`;
      raf = Math.abs(tx - x) + Math.abs(ty - y) > 0.5 ? requestAnimationFrame(tick) : 0;
    };
    const onMove = (e) => {
      tx = e.clientX;
      ty = e.clientY;
      if (!raf) raf = requestAnimationFrame(tick);
      const el = e.target.closest?.(SHINE);
      if (lit && lit !== el) lit.removeAttribute("data-lit");
      lit = el;
      if (el) {
        const r = el.getBoundingClientRect();
        el.style.setProperty("--mx", `${e.clientX - r.left}px`);
        el.style.setProperty("--my", `${e.clientY - r.top}px`);
        if (!el.hasAttribute("data-lit")) el.setAttribute("data-lit", "");
      }
    };
    const onLeave = () => { lit?.removeAttribute("data-lit"); lit = null; };
    addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("pointerleave", onLeave);
    return () => { removeEventListener("pointermove", onMove); document.removeEventListener("pointerleave", onLeave); cancelAnimationFrame(raf); };
  }, []);
  return (
    <div className="ambient" aria-hidden="true">
      <div className="ambient-blob a" />
      <div className="ambient-blob b" />
      <div className="ambient-grid" />
      <div className="cursor-glow" ref={glow} />
    </div>
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
