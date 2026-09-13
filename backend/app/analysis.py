"""Data analysis engine.

Data comes from (in priority order): datasets the user uploads (CSV/XLSX), World Bank open data matched to the
topic, and numeric tables found inside the reference documents. The engine decides which statistical procedures
are valid for the data (assumption checks first), runs them, and curates a SMALL set of tables and figures that
carry the conclusions. Every number that reaches the article is produced here — the language model never invents
statistics; it only narrates the findings below.
"""
from __future__ import annotations

import itertools
import json
import logging
import math
import re
from pathlib import Path
from typing import Callable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402

from . import llm  # noqa: E402
from .models import AnalysisResult, Figure, Table  # noqa: E402

log = logging.getLogger("raf.analysis")

INK, ACCENT, ACCENT2, GRID = "#16121f", "#6a2fd6", "#9ccc1f", "#d9d4e3"
plt.rcParams.update({
    "font.family": "DejaVu Serif", "font.size": 9.5, "axes.edgecolor": INK, "axes.labelcolor": INK,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "xtick.color": INK, "ytick.color": INK, "figure.dpi": 200, "savefig.bbox": "tight",
})


def fmt(x: float, digits: int = 2) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "–"
    if abs(x) >= 1e6:
        return f"{x:,.0f}"
    if abs(x) >= 100:
        return f"{x:,.1f}"
    return f"{x:.{digits}f}"


def fmt_p(p: float) -> str:
    return "< .001" if p < 0.001 else f"= {p:.3f}".replace("0.", ".")


# ================================================================== data acquisition
def load_user_datasets(paths: list[Path]) -> list[tuple[str, pd.DataFrame, dict]]:
    out = []
    for p in paths:
        try:
            df = pd.read_excel(p) if p.suffix.lower() in {".xlsx", ".xls"} else pd.read_csv(p, sep=None, engine="python")
            out.append((p.stem, df, {"origin": "user-supplied dataset", "file": p.name, "rows": len(df)}))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read dataset %s: %s", p.name, exc)
    return out


def world_bank_datasets(title: str, topic: str, progress: Callable[[str], None]) -> list[tuple[str, pd.DataFrame, dict]]:
    try:
        import wbgapi as wb
    except ImportError:
        progress("World Bank library not installed; skipping open data")
        return []

    plan = llm.generate_json(
        "You are a quantitative research planner. Reply with JSON only.",
        f"Article title: {title}\nTopic: {topic}\n\n"
        "Would country-level secondary statistics (World Bank World Development Indicators) meaningfully support "
        "this article? If yes, list up to 6 short search phrases for indicators (e.g. 'GDP per capita', "
        "'internet users', 'health expenditure'). JSON: {\"relevant\": true|false, \"phrases\": [..]}",
        default={"relevant": False, "phrases": []}, max_tokens=300,
    )
    if not plan.get("relevant") or not plan.get("phrases"):
        progress("Topic is not suited to country-level open data; skipping World Bank retrieval")
        return []

    candidates: dict[str, str] = {}
    for phrase in plan["phrases"][:6]:
        try:
            for item in list(wb.series.list(q=str(phrase)))[:6]:
                candidates[item["id"]] = item["value"]
        except Exception as exc:  # noqa: BLE001
            progress(f"World Bank search failed for “{phrase}”: {exc}")
    if not candidates:
        return []

    listing = "\n".join(f"{k}: {v}" for k, v in list(candidates.items())[:40])
    chosen = llm.generate_json(
        "You select statistical indicators for a research article. Reply with JSON only.",
        f"Article: {title}\nTopic: {topic}\n\nCandidate indicators:\n{listing}\n\n"
        "Choose 3 to 5 indicator ids that together allow a meaningful analysis (one plausible outcome and "
        "several plausible explanatory variables). JSON: {\"outcome\": \"id\", \"predictors\": [\"id\", ...]}",
        default={}, max_tokens=300,
    )
    ids = [i for i in [chosen.get("outcome"), *(chosen.get("predictors") or [])] if i in candidates][:5]
    if len(ids) < 2:
        ids = list(candidates)[:4]

    datasets = []
    try:
        progress(f"Downloading World Bank indicators: {', '.join(ids)}")
        economies = [e["id"] for e in wb.economy.list() if not e.get("aggregate")]
        panel = wb.data.DataFrame(ids, economies, time=range(2010, 2024), labels=False, columns="series", numericTimeKeys=True)
        panel = panel.reset_index().rename(columns={"economy": "Country", "time": "Year"})
        rename = {i: _short(candidates[i]) for i in ids if i in panel.columns}
        panel = panel.rename(columns=rename)
        cross = panel.groupby("Country")[list(rename.values())].mean().dropna(thresh=2).reset_index()
        meta = {"origin": "World Bank World Development Indicators", "indicators": {rename[i]: f"{candidates[i]} ({i})" for i in rename},
                "years": "2010–2023", "outcome": rename.get(ids[0], "")}
        datasets.append(("Cross-country averages, 2010–2023", cross, {**meta, "rows": len(cross), "unit": "country"}))

        world = wb.data.DataFrame(ids, "WLD", time=range(2000, 2024), labels=False, columns="series", numericTimeKeys=True)
        world = world.reset_index().rename(columns={"time": "Year"}).rename(columns=rename)
        if "economy" in world.columns:
            world = world.drop(columns=["economy"])
        world = world.sort_values("Year")
        datasets.append(("World aggregate time series, 2000–2023", world, {**meta, "rows": len(world), "unit": "year", "years": "2000–2023"}))
    except Exception as exc:  # noqa: BLE001
        progress(f"World Bank download failed ({exc}); continuing without it")
    return datasets


def reference_tables(tables: list[list[list[str]]]) -> list[tuple[str, pd.DataFrame, dict]]:
    """Numeric tables printed in the reference documents, kept only when they are genuinely tabular data."""
    out = []
    for i, rows in enumerate(tables):
        if len(rows) < 6 or len(rows[0]) < 3:
            continue
        header, body = rows[0], rows[1:]
        width = len(header)
        body = [r for r in body if len(r) == width]
        df = pd.DataFrame(body, columns=[h or f"col{j}" for j, h in enumerate(header)])
        numeric = df.apply(lambda s: pd.to_numeric(s.astype(str).str.replace(r"[,%$€£]", "", regex=True), errors="coerce"))
        good = [c for c in numeric.columns if numeric[c].notna().mean() > 0.8]
        if len(good) >= 2 and len(df) >= 5:
            df[good] = numeric[good]
            out.append((f"Table extracted from reference material #{i + 1}", df, {"origin": "table in uploaded reference", "rows": len(df)}))
    return out[:2]


def _short(label: str) -> str:
    label = re.sub(r"\(.*?\)", "", label).strip()
    return label if len(label) <= 48 else label[:45].rsplit(" ", 1)[0] + "…"


# ================================================================== analysis
class Analyzer:
    def __init__(self, fig_dir: Path, progress: Callable[[str], None]) -> None:
        self.fig_dir = fig_dir
        self.progress = progress
        self.result = AnalysisResult()
        self._fig_budget = 4
        self._table_budget = 4
        self._group = ""

    # ----------------------------------------------------------- entry
    def run(self, datasets: list[tuple[str, pd.DataFrame, dict]], topic: str) -> AnalysisResult:
        for name, df, meta in datasets[:3]:
            df = self._clean(df)
            numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and not _is_time(c) and df[c].nunique() > 3]
            if len(numeric) < 1 or len(df) < 8:
                continue
            self._group = name
            self.result.datasets.append({"name": name, **meta, "variables": numeric[:10]})
            self.progress(f"Analysing “{name}” ({len(df)} rows, {len(numeric)} numeric variables)")
            numeric = self._rank_variables(numeric, topic)[:8]
            outcome = meta.get("outcome") if meta.get("outcome") in numeric else choose_outcome(numeric, topic)
            numeric = [outcome, *[c for c in numeric if c != outcome]]
            time_col = next((c for c in df.columns if _is_time(c)), None)

            self._descriptives(name, df, numeric)
            if time_col and df[time_col].nunique() >= 8 and len(df) == df[time_col].nunique():
                self._trends(name, df, time_col, numeric)
            else:
                normal = self._normality(df, numeric)
                if len(numeric) >= 3:
                    self._correlations(name, df, numeric, normal)
                self._group_comparison(name, df, numeric, normal)
                if len(numeric) >= 3 and len(df.dropna(subset=numeric[:4])) >= 20:
                    self._regression(name, df, numeric)
        return self.result

    # ----------------------------------------------------------- helpers
    def _clean(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.columns = [str(c).strip() for c in df.columns]
        for c in df.columns:
            if df[c].dtype == object:
                conv = pd.to_numeric(df[c].astype(str).str.replace(r"[,%$€£\s]", "", regex=True), errors="coerce")
                if conv.notna().mean() > 0.85:
                    df[c] = conv
        return df.dropna(axis=1, how="all")

    def _rank_variables(self, cols: list[str], topic: str) -> list[str]:
        words = set(re.findall(r"[a-z]{4,}", topic.lower()))
        return sorted(cols, key=lambda c: -len(words & set(re.findall(r"[a-z]{4,}", c.lower()))))

    def _add_table(self, caption: str, columns: list[str], rows: list[list[str]], note: str = "") -> None:
        if self._table_budget <= 0:
            return
        self._table_budget -= 1
        t = Table(number=len(self.result.tables) + 1, caption=caption, columns=columns, rows=rows, note=note, group=self._group)
        self.result.tables.append(t)

    def _save_fig(self, fig, caption: str, note: str = "") -> None:
        if self._fig_budget <= 0:
            plt.close(fig)
            return
        self._fig_budget -= 1
        number = len(self.result.figures) + 1
        path = self.fig_dir / f"figure_{number}.png"
        fig.savefig(path)
        plt.close(fig)
        self.result.figures.append(Figure(number=number, caption=caption, path=f"figures/{path.name}", note=note, group=self._group))

    # ----------------------------------------------------------- procedures
    def _descriptives(self, name: str, df: pd.DataFrame, cols: list[str]) -> None:
        rows = []
        for c in cols:
            s = df[c].dropna()
            if len(s) < 3:
                continue
            skew = stats.skew(s)
            rows.append([c, str(len(s)), fmt(s.mean()), fmt(s.std()), fmt(s.median()), fmt(s.min()), fmt(s.max()), fmt(skew)])
            cv = s.std() / s.mean() * 100 if s.mean() else float("nan")
            self.result.findings.append(
                f"[{name}] {c}: mean {fmt(s.mean())} (SD {fmt(s.std())}, median {fmt(s.median())}, n = {len(s)}); "
                f"coefficient of variation {fmt(cv, 1)}%; skewness {fmt(skew)}."
            )
        if rows:
            self.result.methods.append("Descriptive statistics (mean, standard deviation, median, range, skewness)")
            self._add_table(f"Descriptive statistics — {name}", ["Variable", "n", "Mean", "SD", "Median", "Min", "Max", "Skew"], rows)

    def _normality(self, df: pd.DataFrame, cols: list[str]) -> bool:
        results = []
        for c in cols:
            s = df[c].dropna()
            if 8 <= len(s) <= 5000:
                results.append(stats.shapiro(s).pvalue > 0.05)
        normal = bool(results) and sum(results) / len(results) >= 0.5
        self.result.methods.append(
            "Shapiro–Wilk normality tests, used to choose between parametric and rank-based procedures "
            f"(majority {'approximately normal → parametric' if normal else 'non-normal → rank-based'})"
        )
        return normal

    def _trends(self, name: str, df: pd.DataFrame, t: str, cols: list[str]) -> None:
        import statsmodels.api as sm

        rows, plotted = [], []
        for c in cols:
            d = df[[t, c]].dropna()
            if len(d) < 8:
                continue
            model = sm.OLS(d[c], sm.add_constant(d[t].astype(float))).fit()
            slope, p, r2 = model.params.iloc[1], model.pvalues.iloc[1], model.rsquared
            first, last = d[c].iloc[0], d[c].iloc[-1]
            years = d[t].iloc[-1] - d[t].iloc[0]
            cagr = ((last / first) ** (1 / years) - 1) * 100 if first > 0 and last > 0 and years > 0 else float("nan")
            rho, rho_p = stats.spearmanr(d[t], d[c])
            rows.append([c, f"{int(d[t].iloc[0])}–{int(d[t].iloc[-1])}", fmt(first), fmt(last), fmt(slope, 3), fmt(r2), f"p {fmt_p(p)}", fmt(cagr, 2)])
            direction = "increased" if slope > 0 else "decreased"
            sig = "statistically significant" if p < 0.05 else "not statistically significant"
            self.result.findings.append(
                f"[{name}] {c} {direction} from {fmt(first)} in {int(d[t].iloc[0])} to {fmt(last)} in {int(d[t].iloc[-1])}; "
                f"linear trend slope {fmt(slope, 3)} per year (R² = {fmt(r2)}, p {fmt_p(p)}, {sig}); "
                f"compound annual growth {fmt(cagr, 2)}%; monotonic trend Spearman ρ = {fmt(rho)} (p {fmt_p(rho_p)})."
            )
            plotted.append(c)
        if rows:
            self.result.methods.append("Ordinary least squares trend regression on time, compound annual growth rate, Spearman monotonic trend test")
            self._add_table(f"Trend estimates — {name}", ["Indicator", "Period", "Start", "End", "Slope / yr", "R²", "Sig.", "CAGR %"], rows,
                            note="Slopes from OLS regression of each indicator on year.")
        if plotted:
            k = min(len(plotted), 4)
            fig, axes = plt.subplots(1, k, figsize=(3.2 * k, 2.6), squeeze=False)
            for ax, c in zip(axes[0], plotted[:k]):
                d = df[[t, c]].dropna()
                ax.plot(d[t], d[c], color=ACCENT, lw=1.8, marker="o", ms=2.5)
                z = np.polyfit(d[t].astype(float), d[c], 1)
                ax.plot(d[t], np.polyval(z, d[t].astype(float)), color=ACCENT2, lw=1.2, ls="--")
                ax.set_title(_wrap(c), fontsize=8.5)
                ax.set_xlabel(t)
            fig.tight_layout()
            self._save_fig(fig, f"Temporal evolution of key indicators with fitted linear trends ({name})")

    def _correlations(self, name: str, df: pd.DataFrame, cols: list[str], normal: bool) -> None:
        method = "pearson" if normal else "spearman"
        test = stats.pearsonr if normal else stats.spearmanr
        pairs = []
        for a, b in itertools.combinations(cols[:7], 2):
            d = df[[a, b]].dropna()
            if len(d) < 10:
                continue
            r, p = test(d[a], d[b])
            pairs.append((a, b, float(r), float(p), len(d)))
        if not pairs:
            return
        # Holm–Bonferroni correction for multiple comparisons
        order = sorted(range(len(pairs)), key=lambda i: pairs[i][3])
        m = len(pairs)
        adjusted = [0.0] * m
        running = 0.0
        for rank, i in enumerate(order):
            running = max(running, min(1.0, (m - rank) * pairs[i][3]))
            adjusted[i] = running
        sym = "r" if normal else "ρ"
        strongest = sorted(zip(pairs, adjusted), key=lambda x: -abs(x[0][2]))[:6]
        rows = [[a, b, str(n), fmt(r), f"p {fmt_p(p_adj)}", _strength(r)] for (a, b, r, _, n), p_adj in strongest]
        self._add_table(f"Strongest bivariate associations ({'Pearson' if normal else 'Spearman'}) — {name}",
                        ["Variable A", "Variable B", "n", sym, "Holm-adj.", "Strength"], rows,
                        note="p-values adjusted for multiple comparisons with the Holm–Bonferroni procedure.")
        for (a, b, r, _, n), p_adj in strongest[:4]:
            self.result.findings.append(
                f"[{name}] {a} and {b}: {method} {sym} = {fmt(r)} (n = {n}, Holm-adjusted p {fmt_p(p_adj)}), a {_strength(r).lower()} "
                f"{'positive' if r > 0 else 'negative'} association{'' if p_adj < 0.05 else ' that is not statistically significant'}."
            )
        self.result.methods.append(f"{'Pearson' if normal else 'Spearman rank'} correlation matrix with Holm–Bonferroni correction")

        if len(cols) >= 3:
            sub = df[cols[:7]].corr(method=method)
            fig, ax = plt.subplots(figsize=(5.2, 4.2))
            cmap = matplotlib.colors.LinearSegmentedColormap.from_list("raf", ["#9ccc1f", "#ffffff", "#6a2fd6"])
            im = ax.imshow(sub.values, cmap=cmap, vmin=-1, vmax=1)
            ax.set_xticks(range(len(sub)), [_wrap(c, 14) for c in sub.columns], rotation=45, ha="right", fontsize=7)
            ax.set_yticks(range(len(sub)), [_wrap(c, 18) for c in sub.columns], fontsize=7)
            ax.grid(False)
            for i in range(len(sub)):
                for j in range(len(sub)):
                    ax.text(j, i, f"{sub.values[i, j]:.2f}", ha="center", va="center", fontsize=6.5, color=INK)
            fig.colorbar(im, ax=ax, shrink=0.75)
            self._save_fig(fig, f"{'Pearson' if normal else 'Spearman'} correlation matrix of study variables ({name})")

    def _group_comparison(self, name: str, df: pd.DataFrame, cols: list[str], normal: bool) -> None:
        cats = [c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c]) and 2 <= df[c].nunique() <= 8 and df[c].value_counts().min() >= 3]
        if not cats:
            return
        g = cats[0]
        y = cols[0]
        d = df[[g, y]].dropna()
        groups = [s[y].values for _, s in d.groupby(g)]
        labels = [str(k) for k, _ in d.groupby(g)]
        if len(groups) == 2:
            if normal:
                stat, p = stats.ttest_ind(*groups, equal_var=False)
                pooled = math.sqrt((np.var(groups[0], ddof=1) + np.var(groups[1], ddof=1)) / 2) or 1
                eff, eff_name, test = (np.mean(groups[0]) - np.mean(groups[1])) / pooled, "Cohen's d", "Welch's t-test"
            else:
                stat, p = stats.mannwhitneyu(*groups)
                eff = 1 - 2 * stat / (len(groups[0]) * len(groups[1]))
                eff_name, test = "rank-biserial r", "Mann–Whitney U test"
        else:
            if normal:
                stat, p = stats.f_oneway(*groups)
                grand = d[y].mean()
                ss_b = sum(len(x) * (x.mean() - grand) ** 2 for x in groups)
                ss_t = ((d[y] - grand) ** 2).sum() or 1
                eff, eff_name, test = ss_b / ss_t, "η²", "one-way ANOVA"
            else:
                stat, p = stats.kruskal(*groups)
                eff = (stat - len(groups) + 1) / (len(d) - len(groups)) if len(d) > len(groups) else float("nan")
                eff_name, test = "ε²", "Kruskal–Wallis H test"
        self.result.methods.append(f"{test} comparing {y} across levels of {g}, with {eff_name} effect size")
        rows = [[lab, str(len(x)), fmt(np.mean(x)), fmt(np.std(x, ddof=1)), fmt(np.median(x))] for lab, x in zip(labels, groups)]
        self._add_table(f"{y} by {g} ({test}, statistic = {fmt(stat)}, p {fmt_p(p)}, {eff_name} = {fmt(eff)})", [g, "n", "Mean", "SD", "Median"], rows)
        self.result.findings.append(
            f"[{name}] {test}: {y} {'differs significantly' if p < 0.05 else 'does not differ significantly'} across {g} groups "
            f"(statistic = {fmt(stat)}, p {fmt_p(p)}, {eff_name} = {fmt(eff)}); highest mean in “{labels[int(np.argmax([np.mean(x) for x in groups]))]}”."
        )
        fig, ax = plt.subplots(figsize=(5, 3))
        bp = ax.boxplot(groups, patch_artist=True, widths=0.55)
        ax.set_xticks(range(1, len(labels) + 1), [_wrap(l, 12) for l in labels])
        for patch in bp["boxes"]:
            patch.set(facecolor="#e7dcfb", edgecolor=ACCENT)
        for med in bp["medians"]:
            med.set(color=INK, lw=1.5)
        ax.set_ylabel(_wrap(y, 30))
        self._save_fig(fig, f"Distribution of {y} across {g} groups")

    def _regression(self, name: str, df: pd.DataFrame, cols: list[str]) -> None:
        import statsmodels.api as sm
        from statsmodels.stats.outliers_influence import variance_inflation_factor

        y, xs = cols[0], cols[1:5]
        d = df[[y, *xs]].dropna()
        # Log-transform strongly right-skewed positive variables so OLS assumptions hold better.
        transformed = []
        for c in [y, *xs]:
            if (d[c] > 0).all() and stats.skew(d[c]) > 1.5:
                d[c] = np.log(d[c])
                transformed.append(c)
        X = sm.add_constant(d[xs])
        model = sm.OLS(d[y], X).fit(cov_type="HC3")
        vif = {c: variance_inflation_factor(X.values, i) for i, c in enumerate(X.columns) if c != "const"}
        bp_p = sm.stats.diagnostic.het_breuschpagan(model.resid, X)[1]
        rows = [[c, fmt(model.params[c], 3), fmt(model.bse[c], 3), fmt(model.tvalues[c]), f"{fmt_p(model.pvalues[c])}", fmt(vif.get(c, float("nan")))] for c in xs]
        note = (f"Dependent variable: {y}{' (log)' if y in transformed else ''}. n = {int(model.nobs)}, R² = {fmt(model.rsquared)}, "
                f"adjusted R² = {fmt(model.rsquared_adj)}, F p {fmt_p(model.f_pvalue)}. Robust (HC3) standard errors. "
                f"Breusch–Pagan p {fmt_p(bp_p)}." + (f" Log-transformed: {', '.join(transformed)}." if transformed else ""))
        self._add_table(f"Multiple regression predicting {y}", ["Predictor", "B", "SE", "z", "p", "VIF"], rows, note=note)
        self.result.methods.append("Multiple OLS regression with heteroskedasticity-robust (HC3) errors, VIF multicollinearity check and Breusch–Pagan test")
        sig = [c for c in xs if model.pvalues[c] < 0.05]
        self.result.findings.append(
            f"[{name}] Regression of {y} on {', '.join(xs)} explains {fmt(model.rsquared * 100, 1)}% of variance "
            f"(adjusted R² = {fmt(model.rsquared_adj)}, n = {int(model.nobs)}). Significant predictors: "
            + (", ".join(f"{c} (B = {fmt(model.params[c], 3)}, p {fmt_p(model.pvalues[c])})" for c in sig) if sig else "none at α = .05")
            + (f". Maximum VIF {fmt(max(vif.values()))}." if vif else ".")
        )
        if sig:
            x = sig[0]
            fig, ax = plt.subplots(figsize=(4.6, 3.2))
            ax.scatter(d[x], d[y], s=12, color=ACCENT, alpha=0.65, edgecolor="none")
            z = np.polyfit(d[x], d[y], 1)
            xx = np.linspace(d[x].min(), d[x].max(), 50)
            ax.plot(xx, np.polyval(z, xx), color=ACCENT2, lw=2)
            ax.set_xlabel(_wrap(x + (" (log)" if x in transformed else ""), 40))
            ax.set_ylabel(_wrap(y + (" (log)" if y in transformed else ""), 30))
            self._save_fig(fig, f"Relationship between {x} and {y} with fitted regression line")


_OUTCOME_HINTS = ("performance", "productivity", "outcome", "growth", "satisfaction", "score", "income", "profit", "return",
                  "expectancy", "mortality", "rate", "intention", "yield", "output", "wellbeing", "well-being", "success")


def choose_outcome(cols: list[str], topic: str) -> str:
    """Pick the dependent variable: ask the SLM, fall back to outcome-like names."""
    data = llm.generate_json(
        "You are a research methodologist. Reply with JSON only.",
        f"Research topic: {topic}\nNumeric variables: {json.dumps(cols)}\n"
        "Which ONE variable is the most plausible dependent (outcome) variable for this topic? JSON: {\"outcome\": \"exact name\"}",
        default={}, max_tokens=80,
    )
    if isinstance(data, dict) and data.get("outcome") in cols:
        return data["outcome"]
    for c in cols:
        if any(h in c.lower() for h in _OUTCOME_HINTS):
            return c
    return cols[0]


def _is_time(col: str) -> bool:
    return str(col).strip().lower() in {"year", "yr", "date", "time", "period"}


def _strength(r: float) -> str:
    a = abs(r)
    return "Very strong" if a >= 0.8 else "Strong" if a >= 0.6 else "Moderate" if a >= 0.4 else "Weak" if a >= 0.2 else "Negligible"


def _wrap(text: str, width: int = 22) -> str:
    import textwrap

    return "\n".join(textwrap.wrap(str(text), width, break_long_words=False)[:3])


def run_analysis(project_dir: Path, title: str, topic: str, dataset_paths: list[Path], ref_tables: list, progress: Callable[[str], None]) -> AnalysisResult:
    datasets = load_user_datasets(dataset_paths)
    if datasets:
        progress(f"Using {len(datasets)} user-supplied dataset(s)")
    else:
        datasets = world_bank_datasets(title, topic, progress) + reference_tables(ref_tables)
    if not datasets:
        progress("No suitable quantitative data found; Results will be a structured synthesis of the evidence")
        return AnalysisResult()
    fig_dir = project_dir / "figures"
    fig_dir.mkdir(exist_ok=True)
    return Analyzer(fig_dir, progress).run(datasets, f"{title} {topic}")
