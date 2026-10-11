/* The Custom theme: the whole interface worked out from ONE colour the user picks.
 *
 * deriveTheme(hex) returns the same seven named colours a built-in ramp theme defines by hand in styles.css
 * (--p-a, --p-b, --p-l …); the shared color-mix() formulas there turn them into every shade the interface uses.
 * What is decided here:
 *   - the accent for dark mode and for light mode, nudged lighter or darker only as far as needed to stay readable
 *   - whether text on the accent is white or dark
 *   - the contrasting colour: the opposite hue, used sparingly as a highlight
 *   - a ten-colour ramp for the signature strokes and the theme card
 *
 * Pure functions, no DOM: backend/tests/custom_theme_check.mjs runs them over the whole colour space with Node and
 * checks every text / background pair at WCAG AA.
 */
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export const validHex = (hex) => /^#[0-9a-f]{6}$/i.test(hex || "");
export const hexToRgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
export const rgbToHex = (rgb) => "#" + rgb.map((v) => clamp(Math.round(v), 0, 255).toString(16).padStart(2, "0")).join("");

export function rgbToHsl([r, g, b]) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2, d = max - min;
  if (!d) return [0, 0, l * 100];
  const s = d / (1 - Math.abs(2 * l - 1));
  const h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [(h * 60 + 360) % 360, s * 100, l * 100];
}

export function hslToHex(h, s, l) {
  s = clamp(s, 0, 100) / 100; l = clamp(l, 0, 100) / 100;
  const c = (1 - Math.abs(2 * l - 1)) * s, x = c * (1 - Math.abs(((((h % 360) + 360) % 360) / 60) % 2 - 1)), m = l - c / 2;
  const i = Math.floor((((h % 360) + 360) % 360) / 60);
  const [r, g, b] = [[c, x, 0], [x, c, 0], [0, c, x], [0, x, c], [x, 0, c], [c, 0, x]][i];
  return rgbToHex([(r + m) * 255, (g + m) * 255, (b + m) * 255]);
}

export function luminance(hex) {
  const [r, g, b] = hexToRgb(hex).map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const WHITE = "#ffffff", BLACK = "#000000", DARK_INK = "#0b0b12", LIGHT_INK = "#15130f";
const DARK_GROUND = "#0c0c0e", DARK_CARD = "#16161a", LIGHT_GROUND = "#f4f4f2";   // roughly the page and a raised card in dark mode, the page in light mode
const mix = (a, pct, b) => { const [x, y] = [hexToRgb(a), hexToRgb(b)]; return rgbToHex(x.map((v, i) => (v * pct + y[i] * (100 - pct)) / 100)); };

/** Move the lightness of (h, s, l) one step at a time in `direction` until `ok(hex)` holds. */
function until(h, s, l, direction, ok) {
  let hex = hslToHex(h, s, l);
  for (let i = 0; i < 100 && !ok(hex); i++) hex = hslToHex(h, s, (l = clamp(l + direction, 0, 100)));
  return hex;
}

export function deriveTheme(picked) {
  const [h, s, l] = rgbToHsl(hexToRgb(validHex(picked) ? picked.toLowerCase() : "#2f7df6"));
  const grey = s < 10;
  const opposite = grey ? 38 : h + 180;                 // a grey has no opposite hue: pair it with a warm amber
  const oppositeS = grey ? 70 : Math.max(s, 55);

  // dark mode: the accent has to stand out from a near-black page, and carry readable text
  let a = until(h, s, Math.max(l, 18), +1, (c) => contrast(c, DARK_GROUND) >= 3.2);
  let aInk = WHITE;
  if (contrast(WHITE, a) < 4.6) {
    if (contrast(DARK_INK, a) >= 4.6) aInk = DARK_INK;
    else a = until(...rgbToHsl(hexToRgb(a)), -1, (c) => contrast(WHITE, c) >= 4.6);   // in the narrow band where neither works: a touch darker
  }
  const b = until(opposite, oppositeS, 68, +1, (c) => contrast(c, DARK_CARD) >= 4.8);

  // light mode: the interface writes dark text on accent fills, so the accent is kept light enough for that
  let lAccent = until(h, s, clamp(l, 44, 62), +1, (c) => contrast(LIGHT_INK, c) >= 5);
  // … and its deep shade (small accent-coloured text) has to read on its pale tint; very bright yellows need a touch less light
  const deepReads = (c) => contrast(mix(c, 48, BLACK), mix(c, 13, WHITE)) >= 4.7;
  if (!deepReads(lAccent)) lAccent = until(...rgbToHsl(hexToRgb(lAccent)), -1, (c) => deepReads(c) || contrast(LIGHT_INK, c) < 4.7);
  const lb = until(opposite, oppositeS, 36, -1, (c) => contrast(c, LIGHT_GROUND) >= 4.6);

  const rampS = grey ? s : Math.max(s, 45);
  const ramp = Array.from({ length: 10 }, (_, i) => hslToHex(h + (grey ? 0 : i * 7), rampS, 20 + i * 6.4));
  return {
    vars: {
      "--p-a": a, "--p-a-ink": aInk, "--p-a-far": aInk === WHITE ? BLACK : WHITE, "--p-b": b, "--p-tint": a,
      "--p-l": lAccent, "--p-l-ink": LIGHT_INK, "--p-l-far": WHITE, "--p-lb": lb,
      "--ramp": `linear-gradient(90deg, ${ramp.join(", ")})`,
    },
    ramp, accent: a, accentInk: aInk, contrasting: b, lightAccent: lAccent, lightContrasting: lb,
  };
}
