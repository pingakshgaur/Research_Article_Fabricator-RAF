"""Storage, the Library actions and the History log."""
import io
import json
import zipfile

from app import history, store
from conftest import DATA, make_project


def kinds(pid):
    return [e["kind"] for e in history.read(pid)]


def test_old_project_files_are_upgraded_on_load(project):
    path = DATA / "projects" / project.id / "project.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["schema_version"], data["archived"]          # a file written by RAF 1.4
    path.write_text(json.dumps(data), encoding="utf-8")
    p = store.load(project.id)
    assert p.schema_version == store.SCHEMA_VERSION and p.archived is False


def test_summaries_follow_changes(client, project):
    row = next(s for s in client.get("/api/projects").json() if s["id"] == project.id)
    assert row["segments"] == 6 and row["approved"] == 0 and row["words"] > 50
    client.post(f"/api/projects/{project.id}/segments/abstract/approve")
    row = next(s for s in client.get("/api/projects").json() if s["id"] == project.id)
    assert row["approved"] == 1


def test_create_rename_archive_are_recorded(client):
    pid = client.post("/api/projects", json={"title": "A study of something specific"}).json()["id"]
    assert client.post(f"/api/projects/{pid}/rename", json={"title": "abc"}).status_code == 422
    assert client.post(f"/api/projects/{pid}/rename", json={"title": "A sharper title for the study"}).json()["title"] == "A sharper title for the study"
    assert client.post(f"/api/projects/{pid}/archive").json()["archived"] is True
    assert client.post(f"/api/projects/{pid}/archive?archived=false").json()["archived"] is False
    assert kinds(pid) == ["project.unarchived", "project.archived", "project.updated", "project.created"]


def test_duplicate_is_an_independent_copy(client, project):
    copy = client.post(f"/api/projects/{project.id}/duplicate").json()
    assert copy["id"] != project.id and copy["title"].endswith("(copy)")
    assert copy["segments"]["introduction"]["content"] == project.segments["introduction"].content
    client.put(f"/api/projects/{copy['id']}/segments/abstract", json={"content": "Changed only in the copy."})
    assert store.load(project.id).segments["abstract"].content != "Changed only in the copy."
    # the copy inherits the article's past, then starts its own record
    assert kinds(copy["id"])[:2] == ["segment.edited", "project.created"] and "segment.drafted" in kinds(copy["id"])
    assert "project.duplicated" in kinds(project.id) and "segment.edited" not in kinds(project.id)


def test_backup_and_restore(client, project):
    blob = client.get(f"/api/projects/{project.id}/backup").content
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    assert "project.json" in names and "history.jsonl" in names
    # the project still exists -> the restore gets a new id and says so in the title
    again = client.post("/api/projects/restore", files={"file": ("backup.raf.zip", blob, "application/zip")}).json()
    assert again["id"] != project.id and again["title"].endswith("(restored)")
    # after the original is deleted, the same backup comes back under its own id
    client.delete(f"/api/projects/{project.id}")
    back = client.post("/api/projects/restore", files={"file": ("backup.raf.zip", blob, "application/zip")}).json()
    assert back["id"] == project.id and back["title"] == project.title
    assert back["segments"]["discussion"]["content"] == project.segments["discussion"].content


def test_restore_refuses_bad_archives(client):
    def zipped(files):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, text in files.items():
                z.writestr(name, text)
        return buf.getvalue()

    good = make_project().model_dump_json()
    for files in ({"notes.txt": "hello"}, {"project.json": good, "../outside.txt": "x"}, {"project.json": "{\"not\": \"a project\"}"}):
        r = client.post("/api/projects/restore", files={"file": ("b.zip", zipped(files), "application/zip")})
        assert r.status_code == 422, files.keys()
    assert not (DATA / "outside.txt").exists() and not (DATA / "projects" / "outside.txt").exists()
    assert client.post("/api/projects/restore", files={"file": ("b.txt", b"x", "text/plain")}).status_code == 422


def test_studio_actions_are_recorded(client, project):
    pid = project.id
    client.put(f"/api/projects/{pid}/segments/abstract", json={"content": project.segments["abstract"].content + " One more sentence here."})
    client.post(f"/api/projects/{pid}/segments/abstract/approve")
    client.post(f"/api/projects/{pid}/segments/abstract/approve")                      # approving twice is one event
    client.post(f"/api/projects/{pid}/segments/abstract/approve?approved=false")
    client.post(f"/api/projects/{pid}/segments/abstract/restore/0")
    events = history.read(pid)
    assert [e["kind"] for e in events[:4]] == ["segment.restored", "segment.unapproved", "segment.approved", "segment.edited"]
    assert "(+4 words)" in events[3]["summary"] and events[3]["actor"] == "you" and events[3]["segment"] == "abstract"
    assert events[0]["summary"] == "Abstract restored to version 1 (-4 words)"


def test_history_is_rebuilt_for_projects_made_before_1_5(project):
    events = history.read(project.id)      # no history file existed: it is rebuilt from the project file
    assert events[-1]["kind"] == "project.created" and events[-1]["meta"]["reconstructed"]
    drafted = [e for e in events if e["kind"] == "segment.drafted"]
    assert len(drafted) == 6 and all(e["actor"] == "RAF" for e in drafted)


def test_ai_use_statement_states_only_recorded_facts(client, project):
    pid = project.id
    assert client.put(f"/api/projects/{pid}/segments/keywords", json={"content": "one; two; three; four; five"}).status_code == 200
    out = client.get(f"/api/projects/{pid}/ai-statement").json()
    f = out["facts"]
    assert f["drafted_by_raf"] == ["Title", "Abstract", "Keywords", "Introduction", "Discussion"] and f["manual_edits"] == 1
    assert f["uploaded_references"] == 2 and f["statistics_computed"] is False and f["share_changed_by_hand"] > 0
    assert "Introduction and Discussion" in out["statement"] and "statistics engine" not in out["statement"]
    assert "full responsibility" in out["statement"]
    empty = client.post("/api/projects", json={"title": "Nothing written yet here"}).json()["id"]
    assert client.get(f"/api/projects/{empty}/ai-statement").json()["statement"] == ""
