"""1.8 — articles without reference files (source modes, reading list, open-access full text) and the Window (live writing)."""
import json

import httpx
import pytest

from app import estimate, history, ingest, jobs, live, llm, research, store, writer
from app.models import Project, WebSource
from conftest import DATA, wait


def source(n: int, **kw) -> WebSource:
    return WebSource(**{"source": "openalex", "title": f"Digital tools and small firm productivity, study {n}", "authors": [f"Author{n}, A."], "year": str(2015 + n),
                        "venue": "Journal of Small Business", "doi": f"10.1000/s{n}", "oa_url": f"https://example.org/{n}.pdf",
                        "abstract": ("Digital adoption raises productivity in small firms when managers are trained. " * 6).strip(), **kw})


@pytest.fixture
def events(monkeypatch):
    """Everything sent to the browser while the test runs."""
    seen = []
    real = jobs.emit
    monkeypatch.setattr(jobs, "emit", lambda pid, kind, message="", **data: (seen.append({"kind": kind, "message": message, **data}), real(pid, kind, message, **data))[1])
    return seen


# ------------------------------------------------------------------ the Window
def test_model_output_streams_and_a_retry_starts_the_passage_over(monkeypatch):
    replies = [["Hel", httpx.ReadError("connection dropped")], ["Hello", " world", "."]]

    class Stream:
        status_code = 200

        def __init__(self, pieces):
            self.pieces = pieces

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_lines(self):
            for piece in self.pieces:
                if isinstance(piece, Exception):
                    raise piece
                yield json.dumps({"message": {"content": piece}, "done": False})
            yield json.dumps({"message": {"content": ""}, "done": True})

    class Client:
        def __init__(self, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, json):
            assert json["stream"] is True
            return Stream(replies.pop(0))

        def post(self, url, json):
            return type("R", (), {"status_code": 200, "text": "", "json": lambda self: {"message": {"content": "{\"ok\": true}"}}})()

    monkeypatch.setattr(llm.httpx, "Client", Client)
    monkeypatch.setattr(llm, "wait_for_ollama", lambda seconds: True)
    got = []
    with llm.streaming(got.append):
        assert llm.generate("system", "prompt") == "Hello world."
        assert llm.generate_json("system", "prompt", default={}) == {"ok": True}          # JSON calls are never streamed
    assert got == [None, "Hel", None, "Hello", " world", "."]                                # None = "start over"
    assert llm.generate_json("system", "prompt", default={}) == {"ok": True} and len(got) == 6   # and nothing streams outside the block


def test_sheets_gather_pieces_and_remember_the_state_for_late_joiners(events, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(live.time, "monotonic", lambda: clock[0])
    pid = "livetest0001"
    live.begin(pid, "introduction", "First paragraph.\n\n")
    for piece in ("Small ", "firms ", "account "):          # arrive within one flush interval: sent together
        live.feed(pid, "introduction", piece)
    assert [e for e in events if e["kind"] == "delta"] == [{"kind": "delta", "message": "", "key": "introduction", "text": "Small "}]
    clock[0] += 1
    live.feed(pid, "introduction", "for most.")
    assert [e["text"] for e in events if e["kind"] == "delta"] == ["Small ", "firms account for most."]
    assert live.snapshot(pid)["introduction"] == {"text": "First paragraph.\n\n", "live": "Small firms account for most.", "edits": []}
    live.feed(pid, "introduction", None)                    # the model call is retried
    assert live.snapshot(pid)["introduction"]["live"] == "" and events[-1] == {"kind": "sheet", "message": "", "key": "introduction", "text": "First paragraph.\n\n", "live": ""}
    live.commit(pid, "introduction", "First paragraph.\n\nSecond paragraph.")
    live.edit(pid, "introduction", "removed", "An unsupported sentence.")
    snap = live.snapshot(pid)["introduction"]
    assert snap["text"].endswith("Second paragraph.") and snap["edits"][0]["change"] == "removed" and events[-1]["before"] == "An unsupported sentence."
    live.close(pid, "introduction")
    assert live.snapshot(pid) == {} and events[-1]["closed"] is True
    assert all(e["kind"] not in {"delta", "sheet", "edit"} for e in (store.load(pid).log if store.load(pid) else []))


# ------------------------------------------------------------------ source modes
def test_source_mode_decides_how_many_files_are_needed(client, stub_llm):
    pid = client.post("/api/projects", json={"title": "Digital adoption in small firms"}).json()["id"]
    run = lambda **body: client.post(f"/api/projects/{pid}/generate", json={"segments": ["introduction"], **body})
    assert "at least 10" in run().json()["detail"]                                             # My references
    assert client.put(f"/api/projects/{pid}/source-mode?mode=mixed").json()["source_mode"] == "mixed"
    assert "at least 1 reference article (" in run().json()["detail"]
    assert client.put(f"/api/projects/{pid}/source-mode?mode=nonsense").status_code == 422
    client.put(f"/api/projects/{pid}/source-mode?mode=research")
    assert "Online research switched on" in run(web_research=False).json()["detail"]           # research alone needs research
    assert history.read(pid)[0]["summary"] == "Sources: Research only"


def test_open_access_papers_are_read_in_full(monkeypatch):
    directory = DATA / "fulltext"
    directory.mkdir(exist_ok=True)
    sources = [source(n) for n in range(1, 8)]
    sources[2].oa_url, sources[2].doi = "", ""                                                  # nothing to download
    sources[3].oa_url = ""                                                                      # only a DOI: Unpaywall is asked
    asked = []
    monkeypatch.setattr(research, "unpaywall", lambda doi: asked.append(doi) or "https://example.org/found.pdf")
    monkeypatch.setattr(research, "download_pdf", lambda url, dest: "5.pdf" not in url and (dest.write_bytes(b"%PDF-1.4"), True)[1])
    monkeypatch.setattr(ingest, "read_pdf", lambda path: ingest.ParsedDoc(text="A full paper. " * (10 if "s2" in path.name or sources[1].id in path.name else 400)))
    notes = []
    assert research.fetch_fulltext(sources, directory, limit=3, progress=notes.append) == 3
    assert [s.fulltext for s in sources] == [True, False, False, True, False, True, False]      # too short · no address · download failed · limit reached
    assert asked == ["10.1000/s4"] and sources[0].chars > 3000 and len(notes) == 3
    assert (directory / f"web_{sources[0].id}.txt").exists() and not list(directory.glob("*.pdf"))   # the PDFs themselves are not kept
    again = [s.model_copy(update={"fulltext": False}) for s in sources]
    assert research.fetch_fulltext(again, directory, limit=3) == 3 and [s.fulltext for s in again] == [s.fulltext for s in sources]   # kept from the first time


def test_research_only_article_pauses_for_the_reading_list_then_writes(client, stub_llm, events, monkeypatch):
    found = [source(n) for n in range(1, 6)] + [WebSource(source="wikipedia", title="Productivity", abstract="Encyclopaedia text about productivity. " * 8),
                                                WebSource(source="web", title="A blog on small firms and digital tools", abstract="Blog text on digital productivity. " * 8)]
    rounds = []
    monkeypatch.setattr(research, "research", lambda queries, discipline, progress=None: rounds.append(list(queries)) or (found if len(rounds) == 1 else [source(9)]))
    monkeypatch.setattr(writer, "followup_queries", lambda p, web, asked: ["managerial skill digital adoption"])

    def fulltext(sources, directory, limit=12, progress=None):
        (directory / f"web_{sources[0].id}.txt").write_text("Digital adoption raises productivity in small firms when managers are trained. " * 60, encoding="utf-8")
        sources[0].fulltext, sources[0].chars = True, 4700
        return 1
    monkeypatch.setattr(research, "fetch_fulltext", fulltext)
    monkeypatch.setattr(estimate, "probe_speed", lambda deadline=14: {"tok_s": 5.0, "seconds": 0.0, "model": "stub"})
    stub = llm.chat      # the stand-in model cites [R1] and [R2]; here the sources are online ones, W1 and W2
    monkeypatch.setattr(llm, "chat", lambda messages, **kw: stub(messages, **kw).replace("[R1, R2]", "[W1, W2]").replace("[R1]", "[W1]").replace("[R2]", "[W2]"))

    pid = client.post("/api/projects", json={"title": "Digital adoption and productivity in small firms", "topic": "digital tools and productivity"}).json()["id"]
    client.put(f"/api/projects/{pid}/source-mode?mode=research")
    body = {"segments": ["introduction"], "depth": "quick", "web_research": True}
    assert client.post(f"/api/projects/{pid}/generate", json=body).status_code == 200            # no reference file at all
    wait(pid)
    p = store.load(pid)
    assert p.run.status == "review" and not any(s.content for s in p.segments.values())          # paused before a word is written
    assert len(rounds) == 2 and rounds[1] == ["managerial skill digital adoption"]               # the search ran in two rounds
    assert len(p.web_sources) == 6 and {w.source for w in p.web_sources} == {"openalex"}         # no Wikipedia, no blogs as evidence
    assert sum(w.fulltext for w in p.web_sources) == 1 and p.options["search"] == {"queries": 4, "rounds": 1} or p.options["search"]["rounds"] == 2
    view = client.get(f"/api/projects/{pid}").json()
    assert view["evidence"] == {"references": 0, "online": 6, "online_full": 1, "online_abstract": 5}
    assert history.read(pid)[0]["kind"] == "run.paused"

    drop, keep = p.web_sources[-1].id, p.web_sources[1].id
    assert client.delete(f"/api/projects/{pid}/sources/{drop}").json()["evidence"]["online"] == 5
    assert client.put(f"/api/projects/{pid}/sources/{keep}/pin").status_code == 200 and client.delete(f"/api/projects/{pid}/sources/nope").status_code == 404
    assert client.post(f"/api/projects/{pid}/generate", json={**body, "resume": True}).status_code == 200
    wait(pid)
    assert store.load(pid).run.status == "review"                                               # resuming without approval pauses again
    assert len(rounds) == 2                                                                      # … without searching again

    events.clear()
    assert client.post(f"/api/projects/{pid}/generate", json={**body, "resume": True, "sources_confirmed": True}).status_code == 200
    wait(pid, 60)
    p = store.load(pid)
    assert p.run.status == "completed" and len(p.web_sources) == 5 and p.segments["introduction"].content and p.segments["references"].content
    assert "[W1]" in p.segments["introduction"].content and "Author1, A. (2016)." in p.segments["references"].content   # online sources are cited and listed
    protocol = writer.analysis_protocol(p)
    assert "Literature base: a structured search of openalex" in protocol and "5 sources retained" in protocol
    assert "1 of them were read in full text" in protocol and "remaining 4 were assessed from title and abstract only" in protocol
    assert "reference documents supplied" not in protocol                                        # nothing is claimed that did not happen
    chunks = writer.Workspace(pid).index.chunks
    assert sum(c.label == "W1" for c in chunks) >= 3 and sum(c.label == "W2" for c in chunks) == 1  # the full paper is indexed like a reference, the others by abstract
    pinned = [c for c in writer.retrieve(writer.Workspace(pid), ["something entirely unrelated to the corpus"], k_each=1, cap=1) if c.source_id == keep]
    assert len(pinned) == 1                                                                      # a pinned source always reaches the writer

    sheets = [e for e in events if e["kind"] == "sheet" and e.get("key") == "introduction"]
    assert sheets[0]["text"] == "" and sheets[-1].get("closed") is True                          # the Window: opened empty, closed when done
    texts = [e["text"] for e in sheets if "text" in e]
    assert any(t.count("\n\n") >= 1 for t in texts) and texts[-1] == p.segments["introduction"].content   # grew part by part into the final text
    assert not any(e["kind"] in {"sheet", "delta", "edit"} for e in p.log)                       # none of it is stored
