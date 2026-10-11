"""Article structure (1.6): rename, custom segments, order, leaving segments out, and the reference list that follows."""
import re

from app import history, llm, publisher, revisions, store, structure
from app.blueprints import BLUEPRINTS
from app.models import WebSource
from conftest import DATA, make_project, wait


def headings(client, pid):
    md = client.get(f"/api/projects/{pid}/export/md?draft=true").text
    return [h for h in re.findall(r"^## (.+)$", md, re.M) if h not in ("Abstract", "Contents", "Evidence from Emerging Economies")]   # last: the subtitle


def approve_all(client, pid):
    for key in store.load(pid).segments:
        client.post(f"/api/projects/{pid}/segments/{key}/approve")


def test_a_new_project_has_the_twelve_segments_in_the_usual_order(client, project):
    rows = client.get(f"/api/projects/{project.id}").json()["structure"]
    assert [r["key"] for r in rows] == sorted(BLUEPRINTS, key=lambda k: BLUEPRINTS[k].display_order)
    intro = next(r for r in rows if r["key"] == "introduction")
    assert intro == {**intro, "title": "Introduction", "kind": "builtin", "custom": False, "included": True, "numbered": True, "written": True, "lengthable": True, "cites": True}
    assert [r["key"] for r in rows if r["front"]] == ["title", "abstract", "keywords"] and not next(r for r in rows if r["key"] == "references")["numbered"]
    assert headings(client, project.id) == ["1. Introduction", "2. Discussion", "References"]


def test_rename_reaches_the_studio_the_export_and_the_importer(client, project):
    pid = project.id
    out = client.put(f"/api/projects/{pid}/structure/titles/discussion", json={"title": "  Interpretation of   the Evidence "}).json()
    assert out["segments"]["discussion"]["title"] == "Interpretation of the Evidence" and out["titles"] == {"discussion": "Interpretation of the Evidence"}
    assert headings(client, pid) == ["1. Introduction", "2. Interpretation of the Evidence", "References"]
    p = store.load(pid)
    (DATA / "renamed.md").write_text(publisher.to_markdown(publisher.assemble(p)), encoding="utf8")
    assert "complement managerial skill" in publisher.import_document(p, DATA / "renamed.md")["discussion"]          # found under its new heading
    (DATA / "usual.md").write_text("# T\n\n## Discussion\n\nA body written elsewhere under the usual heading.\n", encoding="utf8")
    assert publisher.import_document(p, DATA / "usual.md")["discussion"].startswith("A body written elsewhere")       # and under the usual one
    assert "Segment renamed — “Discussion” is now “Interpretation of the Evidence”" in [e["summary"] for e in history.read(pid)]
    back = client.put(f"/api/projects/{pid}/structure/titles/discussion", json={"title": ""}).json()                    # empty = the usual name again
    assert back["segments"]["discussion"]["title"] == "Discussion" and back["titles"] == {}
    assert client.put(f"/api/projects/{pid}/structure/titles/nope", json={"title": "x"}).status_code == 404


def test_segments_written_by_the_author(client, project):
    pid = project.id
    made = client.post(f"/api/projects/{pid}/structure/segments", json={"gallery": "funding"}).json()
    key, p = made["key"], made["project"]
    assert p["segments"][key]["content"].startswith("This research received no specific grant") and p["segments"][key]["status"] == "draft"
    row = next(r for r in p["structure"] if r["key"] == key)
    assert row["kind"] == "manual" and row["custom"] and not row["numbered"] and not row["lengthable"] and not row["cites"]
    assert headings(client, pid) == ["1. Introduction", "2. Discussion", "Funding", "References"]                      # before the references, unnumbered
    assert client.post(f"/api/projects/{pid}/segments/{key}/regenerate").status_code == 422                            # RAF does not write it
    assert client.post(f"/api/projects/{pid}/segments/{key}/write").status_code == 422
    client.put(f"/api/projects/{pid}/segments/{key}", json={"content": "Funded by the Example Foundation, grant 42."})
    assert store.load(pid).segments[key].content.endswith("grant 42.")

    blank = client.post(f"/api/projects/{pid}/structure/segments", json={"title": "Acknowledgements", "kind": "manual"}).json()
    approve_all(client, pid)
    client.post(f"/api/projects/{pid}/segments/{blank['key']}/approve?approved=false")
    assert client.get(f"/api/projects/{pid}/export/md").status_code == 200                                             # an empty hand-written segment does not block
    ai = client.post(f"/api/projects/{pid}/structure/segments", json={"gallery": "ai_use"}).json()
    assert "During the preparation of this work" in ai["project"]["segments"][ai["key"]]["content"]                      # filled from the History


def test_segment_written_by_raf(client, project, stub_llm):
    pid = project.id
    body = {"title": "Theoretical Framework", "purpose": "Set out the theory the study rests on and define its constructs.", "after": "introduction", "words": 300, "cites": False}
    key = client.post(f"/api/projects/{pid}/structure/segments", json=body).json()["key"]
    p = store.load(pid)
    assert structure.order(p)[3:6] == ["introduction", key, "literature_review"] and key not in p.segments              # defined, not written yet
    bp = structure.blueprint_for(p, key)
    assert [m.name for m in bp.moves] == ["Purpose and context", "Core content", "Link to the article"] and bp.depends_on == ("introduction",)
    assert structure.generation_order(p, ["discussion", key, "introduction", "abstract"]) == ["introduction", key, "discussion", "abstract"]
    assert structure.deps(p, key, ["introduction", key]) == ["introduction"] and structure.segment_words(p, key) == 300

    assert client.post(f"/api/projects/{pid}/segments/{key}/write").status_code == 200
    wait(pid)
    p = store.load(pid)
    assert p.segments[key].status == "draft" and "research gap explicitly" in p.segments[key].content and p.segments[key].title == "Theoretical Framework"
    assert key in p.selected and p.segments[key].quality.target_words == 300
    assert headings(client, pid) == ["1. Introduction", "2. Theoretical Framework", "3. Discussion", "References"]      # numbered, in its place
    drafts = [c for c in stub_llm if "RHETORICAL MOVE" in c["prompt"]]
    assert len(drafts) == 3 and "This section's purpose: Set out the theory" in drafts[0]["prompt"] and "ARTICLE CONTEXT" in drafts[0]["prompt"]

    edited = client.patch(f"/api/projects/{pid}/structure/segments/{key}", json={"words": 99999, "numbered": False, "moves": [
        {"name": "Core {constructs}", "instruction": "Define each construct.", "queries": ["construct definition {x}"], "share": 5}, {"name": "", "instruction": "dropped"}]}).json()
    row = next(r for r in edited["structure"] if r["key"] == key)
    assert row["words"] == 6000 and not row["numbered"] and row["moves"] == [
        {"name": "Core constructs", "instruction": "Define each construct.", "queries": ["construct definition x"], "share": 1.0}]
    citing = client.post(f"/api/projects/{pid}/structure/segments", json={**body, "title": "Policy Context", "cites": True}).json()["key"]
    assert client.post(f"/api/projects/{pid}/segments/{citing}/write").status_code == 422                               # needs the references to have been read
    assert client.patch(f"/api/projects/{pid}/structure/segments/discussion", json={"words": 500}).status_code == 404   # built-in segments are not edited here


def test_rules_for_adding_segments(client, project, monkeypatch):
    pid = project.id
    add = lambda **b: client.post(f"/api/projects/{pid}/structure/segments", json=b)
    assert add(title="", kind="manual").status_code == 422
    assert add(title="Hypotheses", purpose="too short").status_code == 422                                              # RAF needs to know what to write
    assert add(title="discussion", kind="manual").json()["detail"] == "This article already has a segment called “discussion”."
    assert add(gallery="nope").status_code == 422 and add(title="X", kind="weird").status_code == 422
    for i in range(structure.MAX_CUSTOM):
        assert add(title=f"Note {i}", kind="manual").status_code == 200
    assert "at most" in add(title="One too many", kind="manual").json()["detail"]
    monkeypatch.setattr(llm, "health", lambda: {"ollama": False, "model": "stub", "model_available": False})
    out = client.post(f"/api/projects/{pid}/structure/propose", json={"title": "Case Description", "purpose": "Describe the case that was studied and why."}).json()
    assert out["by"] == "default" and len(out["moves"]) == 3 and out["moves"][0]["queries"][0] == "Case Description digital tools and productivity"
    assert client.post(f"/api/projects/{pid}/generate", json={"segments": ["introduction", "c_unknown"]}).status_code == 422


def test_order_and_leaving_segments_out(client, project):
    pid = project.id
    key = client.post(f"/api/projects/{pid}/structure/segments", json={"gallery": "conflict"}).json()["key"]
    out = client.put(f"/api/projects/{pid}/structure/order", json={"order": ["abstract", "references", "discussion", key, "introduction", "nonsense"]}).json()
    seq = [r["key"] for r in out["structure"]]
    assert seq[:3] == ["title", "abstract", "keywords"]                                                                # front matter stays first
    assert [k for k in seq if k in ("references", "discussion", key, "introduction")] == ["references", "discussion", key, "introduction"]
    assert headings(client, pid) == ["References", "1. Discussion", "Conflict of Interest", "2. Introduction"]          # numbers follow the new order
    assert "structure.reordered" in [e["kind"] for e in history.read(pid)]

    approve_all(client, pid)
    client.post(f"/api/projects/{pid}/segments/discussion/approve?approved=false")
    assert client.get(f"/api/projects/{pid}/export/md").status_code == 422                                             # an unapproved segment blocks …
    left_out = client.put(f"/api/projects/{pid}/structure/included/discussion?included=false").json()
    assert left_out["excluded"] == ["discussion"] and "discussion" in left_out["segments"]                              # … unless it is left out; its text is kept
    md = client.get(f"/api/projects/{pid}/export/md")
    assert md.status_code == 200 and "complement managerial skill" not in md.text and "## 1. Introduction" in md.text
    client.put(f"/api/projects/{pid}/structure/included/discussion?included=true")
    assert "## 1. Discussion" in client.get(f"/api/projects/{pid}/export/md?draft=true").text
    assert client.put(f"/api/projects/{pid}/structure/included/nope?included=false").status_code == 404


def test_the_reference_list_follows_the_citations(client):
    p = make_project()
    p.web_sources = [WebSource(source="openalex", title="Broadband and firm growth", authors=["Okafor, C."], year="2020", venue="World Development", abstract="x" * 200)]
    store.save(p)
    pid, disc = p.id, p.segments["discussion"].content
    refs = lambda: store.load(pid).segments["references"].content
    assert "Okafor" not in refs()                                                                                       # an online source is listed only when cited
    client.put(f"/api/projects/{pid}/segments/discussion", json={"content": disc + " Connectivity matters as well [W1]."})
    assert "Okafor, C. (2020). Broadband and firm growth." in refs() and store.load(pid).segments["references"].versions[-1].reason == "rebuilt from the citations"
    client.put(f"/api/projects/{pid}/structure/included/discussion?included=false")
    assert "Okafor" not in refs()                                                                                       # left-out text cites nothing
    client.put(f"/api/projects/{pid}/structure/included/discussion?included=true")
    assert "Okafor" in refs() and "segment.rebuilt" in [e["kind"] for e in history.read(pid)]

    mine = refs() + "\nAn entry I added by hand. (2024)."
    client.put(f"/api/projects/{pid}/segments/references", json={"content": mine})
    client.put(f"/api/projects/{pid}/segments/discussion", json={"content": disc})                                      # the citation is gone again …
    assert refs() == mine                                                                                               # … but a hand-edited list is left alone


def test_deleting_a_custom_segment_and_getting_it_back_from_a_revision(client, project):
    pid = project.id
    key = client.post(f"/api/projects/{pid}/structure/segments", json={"gallery": "data_availability"}).json()["key"]
    client.put(f"/api/projects/{pid}/structure/titles/introduction", json={"title": "Background"})
    client.post(f"/api/projects/{pid}/revisions", json={"name": "With data statement"})
    assert client.delete(f"/api/projects/{pid}/structure/segments/introduction").status_code == 404                     # built-ins cannot be deleted
    gone = client.delete(f"/api/projects/{pid}/structure/segments/{key}").json()
    assert key not in gone["segments"] and key not in gone["custom_segments"] and key not in [r["key"] for r in gone["structure"]]
    client.put(f"/api/projects/{pid}/structure/titles/introduction", json={"title": ""})

    back = client.post(f"/api/projects/{pid}/revisions/1/restore?key={key}").json()                                     # one segment: its definition returns with it
    assert back["segments"][key]["content"].startswith("The data that support") and back["custom_segments"][key]["title"] == "Data Availability"
    assert back["titles"] == {}                                                                                         # the rest of the structure is untouched
    client.delete(f"/api/projects/{pid}/structure/segments/{key}")
    whole = client.post(f"/api/projects/{pid}/revisions/1/restore").json()                                              # whole article: the structure returns too
    assert whole["titles"] == {"introduction": "Background"} and key in whole["custom_segments"] and whole["segments"]["introduction"]["title"] == "Background"
    assert [r["title"] for r in whole["structure"] if r["written"] and not r["front"]] == ["Background", "Discussion", "Data Availability", "References"]
    assert revisions.get(pid, 1)["structure"]["custom_segments"][key]["kind"] == "manual"
