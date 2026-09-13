import { useState } from "react";
import { api } from "../api.js";
import { Button, Segmented, useToast } from "../ui.jsx";

const DISCIPLINES = ["Management & Business", "Economics & Finance", "Computer Science & AI", "Engineering", "Medicine & Public Health",
  "Psychology", "Education", "Sociology", "Environmental Science", "Biology & Life Sciences", "Law & Policy", "Humanities & History"];
const TYPES = ["Empirical research article", "Systematic literature review", "Conceptual / theoretical paper", "Case study", "Mixed-methods study"];

export default function Setup({ project, navigate, setProject }) {
  const toast = useToast();
  const [form, setForm] = useState(() => ({
    title: project?.title || "",
    topic: project?.topic || "",
    discipline: project?.discipline || "",
    article_type: project?.article_type || TYPES[0],
    citation_style: project?.citation_style || "APA",
    target_words: project?.target_words || 6000,
    authors: (project?.authors || []).join(", "),
    affiliation: project?.affiliation || "",
  }));
  const [saving, setSaving] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e?.target ? e.target.value : e }));

  const submit = async (e) => {
    e.preventDefault();
    setSaving(true);
    const payload = { ...form, target_words: Number(form.target_words), authors: form.authors.split(",").map((a) => a.trim()).filter(Boolean) };
    try {
      if (project) {
        const p = await api.update(project.id, payload);
        setProject(p);
        navigate(p.id, "references");
      } else {
        const p = await api.create(payload);
        navigate(p.id, "references");
      }
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form className="page" onSubmit={submit}>
      <div className="eyebrow rise">Step 01 — Topic & title</div>
      <h1 className="display rise" style={{ "--i": 1, fontSize: "clamp(34px,4.4vw,56px)" }}>What is the <em>article</em> about?</h1>
      <p className="lede rise" style={{ "--i": 2 }}>A precise working title and a short description of the angle help RAF plan research queries and structure every segment.</p>

      <div className="stack" style={{ marginTop: 34 }}>
        <div className="field rise" style={{ "--i": 3 }}>
          <label htmlFor="title">Working title</label>
          <input id="title" className="input title-input" required minLength={5} value={form.title} onChange={set("title")}
            placeholder="e.g. Digital Transformation and SME Productivity in Emerging Economies" autoFocus />
        </div>
        <div className="field rise" style={{ "--i": 4 }}>
          <label htmlFor="topic">Topic, angle & research focus <span className="opt">recommended</span></label>
          <textarea id="topic" className="textarea" value={form.topic} onChange={set("topic")} rows={4}
            placeholder="Describe the problem, context, population, variables or debates you want the article to address." />
        </div>

        <div className="grid-2 rise" style={{ "--i": 5 }}>
          <div className="field">
            <label htmlFor="discipline">Discipline</label>
            <input id="discipline" className="input" list="disciplines" value={form.discipline} onChange={set("discipline")} placeholder="Choose or type a field" />
            <datalist id="disciplines">{DISCIPLINES.map((d) => <option key={d} value={d} />)}</datalist>
          </div>
          <div className="field">
            <label htmlFor="type">Article type</label>
            <select id="type" className="select" value={form.article_type} onChange={set("article_type")}>
              {TYPES.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
        </div>

        <div className="grid-2 rise" style={{ "--i": 6 }}>
          <div className="field">
            <label>Citation style</label>
            <Segmented value={form.citation_style} onChange={set("citation_style")}
              options={["APA", "Harvard", "Chicago", "IEEE"].map((v) => ({ value: v, label: v }))} />
          </div>
          <div className="field">
            <label htmlFor="words">Target length <span className="mono">{Number(form.target_words).toLocaleString()} words</span></label>
            <input id="words" type="range" className="range" min={2500} max={12000} step={500} value={form.target_words} onChange={set("target_words")} />
          </div>
        </div>

        <div className="grid-2 rise" style={{ "--i": 7 }}>
          <div className="field">
            <label htmlFor="authors">Author(s) <span className="opt">comma separated</span></label>
            <input id="authors" className="input" value={form.authors} onChange={set("authors")} placeholder="Jane Doe, John Smith" />
          </div>
          <div className="field">
            <label htmlFor="aff">Affiliation <span className="opt">optional</span></label>
            <input id="aff" className="input" value={form.affiliation} onChange={set("affiliation")} placeholder="Department, University" />
          </div>
        </div>
      </div>

      <div className="actions-bar">
        <span className="muted">You can change these details later.</span>
        <Button variant="primary" iconRight="arrow" disabled={saving || form.title.trim().length < 5}>
          {project ? "Save & continue" : "Create project"}
        </Button>
      </div>
    </form>
  );
}
