import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Button, Icon, timeAgo, useToast } from "../ui.jsx";

const PIPELINE = [
  ["01", "Read", "PDF, DOCX & Markdown references parsed, cleaned and chunked."],
  ["02", "Research", "OpenAlex, Crossref, Semantic Scholar, arXiv, PubMed, DOAJ, Wikipedia & the open web."],
  ["03", "Analyse", "Assumption-checked statistics, curated tables and figures."],
  ["04", "Write", "Blueprint-driven moves, peer-review passes, originality guard."],
  ["05", "Publish", "Enterprise-grade DOCX, PDF and Markdown."],
];

const STAGE_LABEL = { setup: "Setup", references: "References", segments: "Segments", processing: "Fabricating", studio: "In studio", published: "Published" };

export default function Home({ navigate, health }) {
  const [projects, setProjects] = useState(null);
  const toast = useToast();

  useEffect(() => {
    api.projects().then(setProjects).catch(() => setProjects([]));
  }, []);

  const remove = async (e, id) => {
    e.stopPropagation();
    if (!confirm("Delete this project and all of its files?")) return;
    try {
      await api.remove(id);
      setProjects((list) => list.filter((p) => p.id !== id));
    } catch (err) {
      toast(err.message, "error");
    }
  };

  return (
    <div className="page">
      <section className="hero">
        <div className="hero-orb" />
        <div className="eyebrow rise">Local · private · evidence-grounded</div>
        <h1 className="display rise" style={{ "--i": 1 }}>
          From a title and a stack of papers<br />to a <em>publishable</em> article.
        </h1>
        <p className="lede rise" style={{ "--i": 2 }}>
          RAF reads your references, researches the topic across scholarly databases, runs the statistics, and writes each
          segment with its own rhetorical blueprint — then hands you the pen to revise, approve and publish.
        </p>
        <div className="row rise" style={{ "--i": 3, marginTop: 28 }}>
          <Button variant="primary" size="lg" iconRight="arrow" onClick={() => navigate(null, "new")}>Begin a new article</Button>
          {health && !health.ollama && <span className="badge bad">Start Ollama to fabricate</span>}
          {health?.ollama && !health.model_available && <span className="badge warn">Run: ollama pull {health.model}</span>}
        </div>
      </section>

      <div className="pipeline-strip rise" style={{ "--i": 4 }}>
        {PIPELINE.map(([n, t, d]) => (
          <div key={n}>
            <span className="mono">{n}</span>
            <b>{t}</b>
            <p>{d}</p>
          </div>
        ))}
      </div>

      <div className="row between rise" style={{ "--i": 5, marginBottom: 10 }}>
        <h2 className="h2">Your articles</h2>
        <span className="muted mono" style={{ fontSize: 12 }}>{projects ? `${projects.length} project${projects.length === 1 ? "" : "s"}` : ""}</span>
      </div>
      {projects && projects.length === 0 && <div className="empty card">No articles yet. Your first one is a title away.</div>}
      <div className="project-list">
        {projects?.map((p, i) => (
          <div key={p.id} className="project-row rise" style={{ "--i": 6 + i }} onClick={() => navigate(p.id)}>
            <div>
              <div className="p-title">{p.title}</div>
              <div className="muted" style={{ fontSize: 12.5 }}>{p.references} references · {p.approved}/{p.segments} segments approved</div>
            </div>
            <span className={`badge ${p.stage === "published" ? "ok" : "accent"}`}>{STAGE_LABEL[p.stage]}</span>
            <span className="muted" style={{ fontSize: 12.5 }}>{timeAgo(p.updated)}</span>
            <button className="btn ghost icon sm danger" aria-label="Delete project" onClick={(e) => remove(e, p.id)}><Icon name="trash" /></button>
          </div>
        ))}
      </div>
    </div>
  );
}
