"""Test setup. Tests never touch real projects and never need Ollama: the data folder is a throw-away one under
.scratch/ and the language model is replaced by `stub_llm`.

Run from the project root:   .venv\\Scripts\\python -m pytest backend/tests
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / ".scratch" / "pytest-data"
shutil.rmtree(DATA, ignore_errors=True)
DATA.mkdir(parents=True)
os.environ["RAF_DATA_DIR"] = str(DATA)          # must be set before the app is imported
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app import jobs, llm, store  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Project, QualityReport, Reference, Segment, Version  # noqa: E402

TEXT = {
    "title": "Digital Adoption and Productivity in Small Firms: Evidence from Emerging Economies",
    "abstract": "Small firms adopt digital tools unevenly. This article reviews the evidence on how adoption relates to productivity and finds "
                "a consistent positive association that depends on managerial skill. Implications for policy are discussed.",
    "keywords": "digital adoption; small firms; productivity; emerging economies; managerial skill",
    "introduction": "Small firms account for most employment in emerging economies, yet their productivity lags behind larger competitors [R1]. "
                    "Digital tools are widely promoted as a remedy for this gap [R2].\n\n"
                    "The evidence on whether adoption raises productivity remains divided, because studies measure adoption in incompatible ways [R1, R2]. "
                    "This article asks under which conditions digital adoption is associated with higher productivity in small firms.",
    "discussion": "The reviewed studies agree that adoption alone explains little of the variation in productivity [R1]. "
                  "Firms with trained managers benefit far more than firms without them [R2].\n\n"
                  "This pattern suggests that digital tools complement managerial skill instead of replacing it.",
    "references": "Smith, J. (2021). Digital adoption in small firms. Journal of Small Business.\nGarcia, M. (2019). Managers and technology. Research Policy.",
}


def make_project(title: str = "Digital adoption and productivity in small firms", approved: bool = False, keys=tuple(TEXT)) -> Project:
    """A project with written segments, saved straight to disk (no model involved)."""
    refs = [Reference(filename="smith.pdf", kind="pdf", title="Digital adoption in small firms", authors=["Smith, J."], year="2021", venue="Journal of Small Business", status="parsed"),
            Reference(filename="garcia.pdf", kind="pdf", title="Managers and technology", authors=["Garcia, M."], year="2019", venue="Research Policy", status="parsed")]
    segs = {}
    for k in keys:
        t = TEXT[k]
        segs[k] = Segment(key=k, title={"title": "Title", "abstract": "Abstract", "keywords": "Keywords", "introduction": "Introduction",
                                        "discussion": "Discussion", "references": "References"}[k],
                          status="approved" if approved else "draft", content=t, versions=[Version(content=t, reason="initial draft", created=time.time() - 3600)],
                          quality=QualityReport(words=len(t.split()), citations=t.count("[R")))
    p = Project(title=title, topic="digital tools and productivity", references=refs, segments=segs, selected=list(keys), stage="studio")
    p.created = time.time() - 7200
    if "references" in segs:    # the list exactly as RAF builds it, so it only changes when the citations do
        from app import citations
        built = "\n".join(citations.reference_list(p, [s.content for k, s in segs.items() if k != "references"])[0])
        segs["references"].content, segs["references"].versions[0].content = built, built
    return store.save(p)


def wait(pid: str, seconds: float = 30) -> None:
    """Block until every background job of the project has finished."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not jobs.any_running(pid):
            return
        time.sleep(0.05)
    raise AssertionError(f"job still running: {jobs.any_running(pid)}")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project():
    return make_project()


@pytest.fixture
def stub_llm(monkeypatch):
    """Replace the model. Prose calls return a fixed revised paragraph; JSON calls answer by what the prompt asks for."""
    calls = []

    def chat(messages, *, json_mode=False, **kw):
        system, prompt = messages[0]["content"], messages[-1]["content"]
        calls.append({"system": system, "prompt": prompt, "json": json_mode})
        if not json_mode:
            return ("Small firms account for most employment in emerging economies, yet their productivity lags behind larger competitors [R1]. "
                    "Following the reviewer's advice, the section now states the research gap explicitly and defines digital adoption as the routine "
                    "use of connected software in daily operations [R2]. Earlier studies measured adoption in incompatible ways, which explains the divided evidence [R1, R2].")
        if "plan a revision" in system:
            return json.dumps({"points": [
                {"comment": "The research gap is not stated clearly in the introduction.", "segment": "introduction", "instruction": "State the research gap explicitly."},
                {"comment": "Define what digital adoption means.", "segment": "introduction", "instruction": "Add a definition of digital adoption."},
                {"comment": "The discussion overstates causality.", "segment": "discussion", "instruction": "Soften causal claims."},
                {"comment": "Section nobody has.", "segment": "nonexistent", "instruction": "Improve the methods description."}]})
        if "response-to-reviewers" in system:
            import re
            return json.dumps({"responses": [{"point": int(n), "response": f"We have revised the section to answer point {n}."} for n in re.findall(r"POINT (\d+)", prompt)]})
        return "{}"

    monkeypatch.setattr(llm, "chat", chat)
    monkeypatch.setattr(llm, "embed", lambda texts: None)
    monkeypatch.setattr(llm, "health", lambda: {"ollama": True, "model": "stub", "model_available": True, "embed_model_available": False, "models": ["stub"]})
    return calls
