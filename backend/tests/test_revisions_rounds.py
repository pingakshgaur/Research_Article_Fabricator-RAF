"""Article Revisions (save, compare, restore, changes export) and revision rounds."""
from app import history, llm, revisions, rounds, store
from conftest import wait


def edit(client, pid, key, text):
    assert client.put(f"/api/projects/{pid}/segments/{key}", json={"content": text}).status_code == 200


def test_save_compare_and_restore(client, project):
    pid, intro = project.id, project.segments["introduction"].content
    first = client.post(f"/api/projects/{pid}/revisions", json={"name": "First draft"}).json()
    assert first["n"] == 1 and first["name"] == "First draft" and first["stats"]["segments"] == 6 and "segments" not in first

    edit(client, pid, "introduction", intro.replace("remains divided", "remains sharply divided") + "\n\nA new closing paragraph was added here.")
    cmp = client.get(f"/api/projects/{pid}/compare?a=1&b=current").json()
    by = {s["key"]: s for s in cmp["segments"]}
    assert by["introduction"]["status"] == "changed" and by["discussion"]["status"] == "same"
    assert by["introduction"]["added"] == 8 and by["introduction"]["removed"] == 0 and cmp["totals"]["changed_segments"] == 1
    assert ["+", "sharply"] in by["introduction"]["diff"]
    assert "".join(t for op, t in by["discussion"]["diff"]) == project.segments["discussion"].content   # text survives the diff unchanged

    # restoring one segment keeps the rest, and saves the state that is being replaced
    out = client.post(f"/api/projects/{pid}/revisions/1/restore?key=introduction").json()
    assert out["segments"]["introduction"]["content"] == intro
    assert out["segments"]["introduction"]["versions"][-1]["reason"].startswith("restored from revision")
    revs = client.get(f"/api/projects/{pid}/revisions").json()
    assert [r["name"] for r in revs] == ["Before restoring “First draft”", "First draft"] and revs[0]["auto"] is True
    assert revisions.get(pid, 2)["segments"]["introduction"]["content"].endswith("added here.")


def test_whole_restore_makes_the_article_equal_the_revision(client, project):
    pid = project.id
    client.post(f"/api/projects/{pid}/segments/abstract/approve")
    client.post(f"/api/projects/{pid}/revisions", json={"name": "Submitted"})
    edit(client, pid, "abstract", "A different abstract.")
    store.mutate(pid, lambda p: p.segments.pop("discussion"))
    out = client.post(f"/api/projects/{pid}/revisions/1/restore").json()
    assert set(out["segments"]) == set(project.segments) and out["segments"]["discussion"]["content"] == project.segments["discussion"].content
    assert out["segments"]["abstract"]["status"] == "approved" and out["segments"]["introduction"]["status"] == "draft"
    assert history.read(pid)[0]["summary"] == "Whole article restored from revision “Submitted”"


def test_automatic_revisions_are_not_saved_twice(client, project):
    pid = project.id
    a = revisions.snapshot(pid, "Before import", auto=True, trigger="import")
    b = revisions.snapshot(pid, "Before fabrication run", auto=True, trigger="run")
    assert a["n"] == b["n"] == 1 and len(revisions.list_(pid)) == 1
    assert client.post(f"/api/projects/{pid}/revisions", json={"name": ""}).json()["name"] == "Revision 2"      # a manual save always saves
    assert client.patch(f"/api/projects/{pid}/revisions/1", json={"name": "Kept"}).json()["auto"] is False
    assert client.delete(f"/api/projects/{pid}/revisions/2").json() == {"ok": True}
    assert client.get(f"/api/projects/{pid}/compare?a=9").status_code == 404 and client.get(f"/api/projects/{pid}/compare?a=x").status_code == 422


def test_publishing_saves_a_revision(client):
    from conftest import make_project
    pid = make_project(approved=True).id
    assert client.get(f"/api/projects/{pid}/export/md?draft=true").status_code == 200
    assert revisions.list_(pid) == []                                   # a draft export is not a milestone
    md = client.get(f"/api/projects/{pid}/export/md")
    assert md.status_code == 200 and "## Contents" in md.text and "(Smith, 2021)" in md.text
    assert [r["name"] for r in revisions.list_(pid)] == ["Published · Markdown"]
    assert [e["kind"] for e in history.read(pid)[:3]] == ["article.published", "revision.saved", "article.draft_exported"]
    assert store.load(pid).stage == "published"


def test_changes_export(client, project):
    pid = project.id
    client.post(f"/api/projects/{pid}/revisions", json={"name": "v1"})
    edit(client, pid, "discussion", project.segments["discussion"].content.replace("far more", "considerably more"))
    docx_file = client.get(f"/api/projects/{pid}/compare/export/docx?a=1")
    assert docx_file.status_code == 200 and docx_file.content[:2] == b"PK"
    import docx
    import io
    runs = [r for p in docx.Document(io.BytesIO(docx_file.content)).paragraphs for r in p.runs]
    assert any(r.font.strike and r.text.strip() == "far" for r in runs) and any(r.font.underline and r.text.strip() == "considerably" for r in runs)
    assert any("(Garcia, 2019)" in r.text for r in runs)                # citations appear as published, not as [R2]
    pdf = client.get(f"/api/projects/{pid}/compare/export/pdf?a=1&b=current")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"


def test_revision_round_end_to_end(client, project, stub_llm):
    pid = project.id
    rnd = client.post(f"/api/projects/{pid}/rounds", json={"comments": "1. The research gap is unclear. 2. Define adoption. 3. Causality is overstated."}).json()
    assert rnd["status"] == "analysing" and rnd["name"] == "Round 1"
    wait(pid)
    rnd = client.get(f"/api/projects/{pid}/rounds/{rnd['id']}").json()
    assert rnd["status"] == "ready" and rnd["analysed_by"] == "model" and len(rnd["points"]) == 4
    assert rnd["points"][3]["segment"] == "methodology" or rnd["points"][3]["segment"] in project.segments      # an unknown section is re-assigned

    points = rnd["points"][:3]
    points[2]["decision"] = "skip"
    points[0]["instruction"] = "State the research gap in one explicit sentence."
    rnd = client.put(f"/api/projects/{pid}/rounds/{rnd['id']}", json={"points": points}).json()
    assert [p["decision"] for p in rnd["points"]] == ["accept", "accept", "skip"]

    assert client.post(f"/api/projects/{pid}/rounds/{rnd['id']}/apply").status_code == 200
    assert client.post(f"/api/projects/{pid}/revisions", json={"name": "x"}).status_code == 409            # the project is busy meanwhile
    wait(pid)
    rnd = client.get(f"/api/projects/{pid}/rounds/{rnd['id']}").json()
    assert rnd["status"] == "done" and [p["state"] for p in rnd["points"]] == ["applied", "applied", "skipped"]
    p = store.load(pid)
    assert "states the research gap explicitly" in p.segments["introduction"].content and p.segments["introduction"].status == "draft"
    assert p.segments["discussion"].content == project.segments["discussion"].content                         # the skipped point changed nothing
    assert p.segments["introduction"].versions[-1].reason == "revision round: Round 1"

    # both points on the Introduction went to the model in ONE revision request
    revise_calls = [c for c in stub_llm if "AUTHOR'S REVISION REQUEST" in c["prompt"]]
    assert len(revise_calls) == 1 and "1. State the research gap in one explicit sentence." in revise_calls[0]["prompt"] and "2. Add a definition" in revise_calls[0]["prompt"]

    names = {r["n"]: r["name"] for r in revisions.list_(pid)}
    assert names[rnd["before"]] == "Round 1 — before" and names[rnd["after"]] == "Round 1 — revised"
    assert "## Comment 1" in rnd["letter"] and "We have revised the section to answer point 1." in rnd["letter"]
    assert "[No change was made for this comment" in rnd["letter"] and "**Change made** (Introduction)" in rnd["letter"]
    assert "research gap" in rnd["points"][0]["change"] and "[R" not in rnd["points"][0]["change"]            # the relevant sentence, as published
    assert client.put(f"/api/projects/{pid}/rounds/{rnd['id']}", json={"points": []}).status_code == 409       # finished rounds are fixed
    edited = client.put(f"/api/projects/{pid}/rounds/{rnd['id']}", json={"letter": rnd["letter"] + "\n\nKind regards."}).json()
    assert edited["letter"].endswith("Kind regards.")
    assert client.get(f"/api/projects/{pid}/rounds/{rnd['id']}/letter.docx").content[:2] == b"PK"
    events = history.read(pid)
    assert {"round.started", "round.analysed", "round.completed", "segment.revised"} <= {e["kind"] for e in events}
    assert all(e["actor"] == "RAF" for e in events if e["kind"] == "revision.saved") and rnd["finished"] >= rnd["created"]


def test_revising_the_abstract_never_adds_citations(client, project, stub_llm):
    from app import writer
    writer.revise_segment(project.id, "abstract", "State the main limitation.")
    text = store.load(project.id).segments["abstract"].content
    assert "research gap explicitly" in text and "[R" not in text and " ." not in text


def test_round_works_without_the_model(client, project, monkeypatch):
    monkeypatch.setattr(llm, "health", lambda: {"ollama": False, "model": "stub", "model_available": False})
    pid = project.id
    text = ("Reviewer 1\n\n1. The introduction does not motivate the research question well enough.\n"
            "2. Table 2 and the regression results need effect sizes.\n\n- The abstract is too vague about the findings.\n\nThanks.")
    rnd = client.post(f"/api/projects/{pid}/rounds", json={"comments": text, "name": "Supervisor"}).json()
    wait(pid)
    rnd = client.get(f"/api/projects/{pid}/rounds/{rnd['id']}").json()
    assert rnd["analysed_by"] == "plain" and [p["segment"] for p in rnd["points"]] == ["introduction", "discussion", "abstract"]
    assert rnd["points"][1]["comment"].startswith("Table 2")                                                  # numbering stripped
    assert client.post(f"/api/projects/{pid}/rounds/{rnd['id']}/apply").status_code == 503                    # applying needs the model
    assert rounds.get(pid, rnd["id"])["status"] == "ready"
    assert client.post(f"/api/projects/{pid}/rounds", json={"comments": "too short"}).status_code == 422
