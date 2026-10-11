// Run by test_settings.py with Node. Builds the Custom theme from colours across the whole colour space and checks the
// text / background pairs the interface relies on. The mix() formulas mirror the "Themes" section of styles.css.
import { contrast, deriveTheme, hexToRgb, hslToHex, rgbToHex } from "../../frontend/src/customTheme.js";

const mix = (a, pct, b) => { const [x, y] = [hexToRgb(a), hexToRgb(b)]; return rgbToHex(x.map((v, i) => v * pct / 100 + y[i] * (1 - pct / 100))); };

function pairs(t) {
  const v = t.vars, a = v["--p-a"], l = v["--p-l"];
  // dark mode
  const v5 = mix(a, 50, "#ffffff"), ground = mix(v["--p-tint"], 55, "#6f6f78");
  const [bg, s1, s2] = [3, 9, 13].map((p) => mix(ground, p, "#000000"));
  const ink = mix(a, 6, "#ffffff"), ink2 = mix(a, 14, "#d2d0d6"), muted = mix(a, 22, "#8f8d96"), soft = mix(a, 16, s1);
  // light mode
  const l1 = mix(l, 13, "#ffffff"), l5 = mix(l, 48, "#000000"), l6 = mix(l, 28, "#000000"), lg = mix(l, 40, "#55524c");
  const [lbg, w1, w2] = [7, 3, 9].map((p) => mix(lg, p, "#ffffff"));
  const link = mix(l, 8, "#121212"), link2 = mix(l6, 45, "#3a3a3a"), lmuted = mix(l6, 30, "#6e6e6e"), lsoft = mix(l, 30, w1);
  return {
    "dark: button text": [v["--p-a-ink"], a, 4.5], "dark: button text (hover)": [v["--p-a-ink"], mix(a, 90, v["--p-a-far"]), 4.5],
    "dark: button text (pressed)": [v["--p-a-ink"], mix(a, 80, v["--p-a-far"]), 4.5], "dark: accent on page": [a, bg, 3],
    "dark: text": [ink, bg, 4.5], "dark: secondary text": [ink2, s1, 4.5], "dark: muted text": [muted, s2, 4.5],
    "dark: accent text": [v5, s2, 4.5], "dark: accent text on badge": [v5, soft, 4.5], "dark: contrasting colour": [v["--p-b"], s1, 4.5],
    "light: button text": [v["--p-l-ink"], l, 4.5], "light: button text (hover)": [v["--p-l-ink"], mix(l, 84, v["--p-l-far"]), 4.5],
    "light: button text (pressed)": [v["--p-l-ink"], mix(l, 72, v["--p-l-far"]), 4.5], "light: text on accent fill": [link, l, 4.5],
    "light: text": [link, lbg, 4.5], "light: secondary text": [link2, w1, 4.5], "light: muted text": [lmuted, w2, 4.5],
    "light: accent text": [l6, lbg, 4.5], "light: text on badge": [link, lsoft, 4.5], "light: deep accent": [l5, l1, 4.5],
    "light: contrasting colour": [v["--p-lb"], lbg, 4.5],
  };
}

const colours = ["#000000", "#ffffff", "#808080", "#2f7df6", "#ff0000", "#00ff00", "#0000ff", "#ffff00", "#ff00ff", "#00ffff"];
for (let h = 0; h < 360; h += 10) for (const s of [0, 8, 15, 40, 70, 100]) for (const l of [2, 10, 20, 30, 40, 50, 60, 70, 80, 90, 98]) colours.push(hslToHex(h, s, l));

let failures = 0, worst = 99, worstAt = "";
for (const c of colours) {
  const theme = deriveTheme(c);
  if (theme.ramp.length !== 10 || Object.values(theme.vars).some((x) => !x)) { failures++; console.log(c, "incomplete theme"); continue; }
  for (const [name, [fg, bg, need]] of Object.entries(pairs(theme))) {
    const r = contrast(fg, bg);
    if (need === 4.5 && r < worst) { worst = r; worstAt = `${c} · ${name}`; }
    if (r < need) { failures++; if (failures <= 25) console.log(`${c}  ${name}  ${r.toFixed(2)} < ${need}`); }
  }
}
console.log(`${colours.length} colours · worst text pair ${worst.toFixed(2)} (${worstAt}) · ${failures} failure(s)`);
process.exit(failures ? 1 : 0);
