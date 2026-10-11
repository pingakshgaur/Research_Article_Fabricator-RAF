import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api.js";
import { Button, Icon, Select, Spinner, Toggle, timeAgo, useToast } from "../ui.jsx";
import { STAGE_LABEL } from "./Home.jsx";
import { fmtDuration } from "./Processing.jsx";

const SORTS = [
  { value: "updated", label: "Last activity" },
  { value: "created", label: "Date created" },
  { value: "title", label: "Title (A–Z)" },
  { value: "progress", label: "Progress" },
  { value: "words", label: "Length" },
];
const progress = (p) => (p.segments ? p.approved / p.segments : 0);

export default function Library({ navigate }) {
  const toast = useToast();
  const [projects, setProjects] = useState(null);
  const [q, setQ] = useState("");
  const [stage, setStage] = useState("all");
  const [sort, setSort] = useState("updated");
  const [showArchived, setShowArchived] = useState(false);
  const [renaming, setRenaming] = useState(null);   // { id, title }
  const [working, setWorking] = useState("");       // id of the project an action is running on
  const restoreRef = useRef(null);

  const load = () => api.projects().then(setProjects).catch(() => setProjects([]));
  useEffect(() => { load(); }, []);

  const archivedCount = projects?.filter((p) => p.archived).length || 0;
  const shown = useMemo(() => {
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const list = (projects || []).filter((p) =>
      (showArchived || !p.archived) && (stage === "all" || p.stage === stage) &&
      words.every((w) => `${p.title} ${p.discipline} ${p.article_type}`.toLowerCase().includes(w)));
    const by = {
      updated: (a, b) => b.updated - a.updated, created: (a, b) => b.created - a.created, title: (a, b) => a.title.localeCompare(b.title),
      progress: (a, b) => progress(b) - progress(a) || b.updated - a.updated, words: (a, b) => b.words - a.words,
    };
    return list.sort(by[sort]);
  }, [projects, q, stage, sort, showArchived]);

  const act = async (id, fn, message) => {
    setWorking(id);
    try {
      await fn();
      if (message) toast(message);
      await load();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setWorking("");
    }
  };

  const saveName = (p) => {
    const title = renaming.title.trim();
    setRenaming(null);
    if (title && title !== p.title) act(p.id, () => api.rename(p.id, title), "Renamed");
  };

  const restore = (file) => file && act("restore", async () => {
    const p = await api.restoreBackup(file);
    toast(`Restored “${p.title}”`);
  });

  return (
    <div className="page">
      <div className="eyebrow rise">Library</div>
      <h1 className="display rise" style={{ "--i": 1, fontSize: "clamp(34px,4.4vw,56px)" }}>Every <em>article</em> you have started.</h1>

      <div className="lib-toolbar rise" style={{ "--i": 2 }}>
        <input className="input" type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by title, discipline or article type" aria-label="Search projects" />
        <Select value={stage} onChange={setStage} aria-label="Filter by stage"
          options={[{ value: "all", label: "All stages" }, ...Object.entries(STAGE_LABEL).map(([value, label]) => ({ value, label }))]} />
        <Select value={sort} onChange={setSort} aria-label="Sort by" options={SORTS} />
      </div>
      <div className="row between wrap rise" style={{ "--i": 3, margin: "14px 0 10px" }}>
        <div className="row wrap">
          <span className="mono muted" style={{ fontSize: 12 }}>
            {projects ? `${shown.length} of ${projects.length - (showArchived ? 0 : archivedCount)} project${projects.length === 1 ? "" : "s"}` : ""}
          </span>
          {archivedCount > 0 && <Toggle checked={showArchived} onChange={setShowArchived} label={`Show archived (${archivedCount})`} />}
        </div>
        <div className="row">
          <Button size="sm" icon="upload" disabled={working === "restore"} onClick={() => restoreRef.current.click()}>
            {working === "restore" ? "Restoring…" : "Restore a backup"}
          </Button>
          <input ref={restoreRef} type="file" hidden accept=".zip" onChange={(e) => { restore(e.target.files[0]); e.target.value = ""; }} />
          <Button size="sm" variant="primary" icon="plus" onClick={() => navigate(null, "new")}>New article</Button>
        </div>
      </div>

      {!projects && <div className="empty"><Spinner /> Loading…</div>}
      {projects && projects.length === 0 && <div className="empty card">No articles yet. Your first one is a title away.</div>}
      {projects && projects.length > 0 && shown.length === 0 && <div className="empty card">No project matches these filters.</div>}

      <div className="project-list">
        {shown.map((p) => (
          <div key={p.id} className={`lib-row ${p.archived ? "archived" : ""}`}>
            <div className="lib-main" onClick={() => !renaming && navigate(p.id)}>
              {renaming?.id === p.id ? (
                <input className="input" autoFocus value={renaming.title} onClick={(e) => e.stopPropagation()}
                  onChange={(e) => setRenaming({ id: p.id, title: e.target.value })} onBlur={() => saveName(p)}
                  onKeyDown={(e) => { if (e.key === "Enter") saveName(p); if (e.key === "Escape") setRenaming(null); }} aria-label="Project title" />
              ) : <div className="p-title">{p.title}</div>}
              <div className="muted lib-meta">
                <span>{p.article_type}</span>
                <span>{p.references} references</span>
                <span>{p.segments ? `${p.approved}/${p.segments} segments approved` : "nothing written yet"}</span>
                {p.words > 0 && <span>{p.words.toLocaleString()} words</span>}
                {p.seconds > 0 && <span>{fmtDuration(p.seconds, true)} of fabrication</span>}
              </div>
              {p.segments > 0 && <div className="meter lib-meter"><i style={{ width: `${progress(p) * 100}%` }} /></div>}
            </div>
            <div className="lib-side">
              <span className={`badge ${p.archived ? "" : p.stage === "published" ? "ok" : "accent"}`}>{p.archived ? "Archived" : STAGE_LABEL[p.stage]}</span>
              <span className="muted" style={{ fontSize: 12.5 }} title={`Created ${new Date(p.created * 1000).toLocaleDateString()}`}>{timeAgo(p.updated)}</span>
            </div>
            <div className="lib-actions">
              {working === p.id ? <Spinner /> : (
                <>
                  <button className="btn ghost icon sm" title="Rename" aria-label={`Rename ${p.title}`} onClick={() => setRenaming({ id: p.id, title: p.title })}><Icon name="edit" /></button>
                  <button className="btn ghost icon sm" title="Duplicate" aria-label={`Duplicate ${p.title}`}
                    onClick={() => act(p.id, () => api.duplicate(p.id), "Copy created")}><Icon name="copy" /></button>
                  <button className="btn ghost icon sm" title="Download a backup (.zip)" aria-label={`Back up ${p.title}`}
                    onClick={() => act(p.id, () => api.backup(p.id), "Backup downloaded")}><Icon name="download" /></button>
                  <button className="btn ghost icon sm" title={p.archived ? "Take out of the archive" : "Archive"} aria-label={`${p.archived ? "Unarchive" : "Archive"} ${p.title}`}
                    onClick={() => act(p.id, () => api.archive(p.id, !p.archived), p.archived ? "Back in the Library" : "Archived")}><Icon name="archive" /></button>
                  <button className="btn ghost icon sm danger" title="Delete" aria-label={`Delete ${p.title}`}
                    onClick={() => confirm(`Delete “${p.title}” and all of its files? This cannot be undone. Download a backup first if you may want it again.`) &&
                      act(p.id, () => api.remove(p.id), "Project deleted")}><Icon name="trash" /></button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
