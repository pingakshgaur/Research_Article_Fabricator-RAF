/* Appearance: the theme (a colour ramp), dark or light mode, and background effects.
 *
 * The theme and effects are RAF settings saved by the server (Settings → Appearance). Dark / light is a choice of this
 * browser. All three are also kept in localStorage so index.html can apply them before the first paint.
 * The colours of each theme are defined in styles.css (section "Themes"); the ramps here only draw the picker.
 */
import { deriveTheme } from "./customTheme.js";

export const THEMES = [
  { key: "violet", name: "Violet & Lime", blurb: "The original: violet on black, lime on sage.",
    ramp: ["#1d0b3d", "#3a1680", "#5b24c4", "#7f3aed", "#9b64f2", "#bc96f6", "#e3d3fc", "#e1f79f", "#c9ff2e", "#b8f400"] },
  { key: "rosewood", name: "Rosewood", blurb: "Dusty rose warming into sand and pale leaf.",
    ramp: ["#aa5378", "#ba5e73", "#c66b6f", "#cf7a6c", "#d58a6b", "#d89b6d", "#d8ac72", "#d7bd7c", "#d4ce8a", "#d0de9b"] },
  { key: "aurora", name: "Aurora", blurb: "Magenta through electric blue to sea green.",
    ramp: ["#e029c6", "#b35ef4", "#6580ff", "#009aff", "#00adff", "#00bbff", "#00c6f3", "#00ced2", "#00d4b1", "#46d895"] },
  { key: "solar", name: "Solar", blurb: "Deep indigo burning up to orange and yellow.",
    ramp: ["#200299", "#800090", "#b8007f", "#e10069", "#fd0051", "#ff4437", "#ff7a12", "#ffa700", "#ffd200", "#e8f921"] },
  { key: "ember", name: "Ember", blurb: "Burnt orange cooling through wine to midnight.",
    ramp: ["#cd6430", "#ca513a", "#c43f44", "#ba2e4e", "#ac2058", "#9b1762", "#861569", "#6e196f", "#511e73", "#2b2173"] },
  // no fixed ramp: every colour is worked out from the one the user picks (customTheme.js)
  { key: "custom", name: "Custom", blurb: "Pick one colour; RAF works out every shade and a contrasting colour.", ramp: null },
];
const CUSTOM_VARS = ["--p-a", "--p-a-ink", "--p-a-far", "--p-b", "--p-tint", "--p-l", "--p-l-ink", "--p-l-far", "--p-lb", "--ramp"];

const root = document.documentElement;
const remember = (key, value) => { try { localStorage.setItem(key, value); } catch { /* storage unavailable */ } };

/** Apply the saved RAF appearance settings to the page. */
export function applyAppearance(settings) {
  if (!settings) return;
  root.dataset.palette = THEMES.some((t) => t.key === settings.palette) ? settings.palette : "violet";
  root.dataset.effects = settings.effects === false ? "off" : "on";
  if (root.dataset.palette === "custom") {
    const { vars } = deriveTheme(settings.custom_color);
    Object.entries(vars).forEach(([name, value]) => root.style.setProperty(name, value));
    remember("raf-custom", JSON.stringify(vars));
  } else CUSTOM_VARS.forEach((name) => root.style.removeProperty(name));
  remember("raf-palette", root.dataset.palette);
  remember("raf-effects", root.dataset.effects);
}

/** Switch between dark and light, with a circular reveal where the browser supports it. */
export function applyMode(next) {
  const set = () => {
    root.dataset.theme = next;
    remember("raf-theme", next);
  };
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) document.startViewTransition(set);
  else set();
}

export const currentMode = () => root.dataset.theme || "dark";
