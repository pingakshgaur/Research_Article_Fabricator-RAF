"""1.9 — the text-tool engine (textops.py): Expand, Condense, Formalize, Simplify, Add citations, Polish, Humanize, Strengthen.

The model is replaced by small stand-ins that answer one paragraph at a time, so the layers around it can be checked:
rules, repair, the gate, selection, retries, and long text.
"""
import re

import pytest

from app import llm, store, textops
from conftest import make_project, wait

MACHINE = ("Moreover, digital tools play a crucial role in the modern landscape of small firms [R1]. It is important to note that adoption "
           "rates rose from 12% to 31% between 2015 and 2021, underscoring the pivotal nature of this shift [R2]. Furthermore, managers "
           "who were trained saw larger gains than managers who were not trained in the same period of time [R1]. Overall, this highlights "
           "the multifaceted and nuanced relationship between technology and productivity in emerging economies.")
HUMAN = ("Digital tools now sit at the centre of how small firms work [R1]. Adoption rose from 12% to 31% between 2015 and 2021 [R2]. "
         "The gains were uneven. Managers who had been trained drew more from the same tools than those who had not, over the same period [R1]. "
         "Technology and productivity are linked in emerging economies, then, but the link runs through the people who use the tools.")


@pytest.fixture
def model(monkeypatch):
    """`answers` is a function prompt -> text (or a list consumed in order). Every call is recorded."""
    box = {"answers": lambda prompt: "", "calls": []}

    def generate(system, prompt, **kw):
        box["calls"].append(prompt)
        a = box["answers"]
        out = a.pop(0) if isinstance(a, list) else a(prompt)
        if isinstance(out, Exception):
            raise out
        return out
    monkeypatch.setattr(llm, "generate", generate)
    monkeypatch.setattr(llm, "generate_json", lambda system, prompt, default, **kw: box.setdefault("checks", []).append(prompt) or box.get("verdict", {"errors": []}))
    monkeypatch.setattr(llm, "embed", lambda texts: None)
    monkeypatch.setattr(llm, "runtime", llm._Runtime())
    return box


def paragraph_of(prompt: str) -> str:
    return prompt.split("PARAGRAPH:\n", 1)[1].split("\n\nReturn only", 1)[0]


# ------------------------------------------------------------------ the layers on their own
def test_the_rule_layer_removes_padding_without_touching_content():
    out = textops.rules("humanize", MACHINE)
    assert out.startswith("Digital tools play") and "Adoption rates rose from 12% to 31%" in out and "Managers who were trained" in out
    assert "Moreover" not in out and "It is important to note" not in out and "Furthermore" not in out
    assert textops._labels(out) == textops._labels(MACHINE) and textops._numbers(out) == textops._numbers(MACHINE)
    assert textops.rules("formalize", "We don't know why it's rising, and they can't say! In order to check, e.g. the 2019 data were used.") == \
        "We do not know why it is rising, and they cannot say. To check, e.g. the 2019 data were used."
    twice = "Adoption rose quickly in the cities [R1]. Rural firms lagged behind [R2]. In the cities, adoption rose quickly [R1]. Costs fell."
    assert textops.rules("condense", twice) == "Adoption rose quickly in the cities [R1]. Rural firms lagged behind [R2]. Costs fell."
    assert textops.rules("polish", "The the results of of the survey are are clear , and that that is known.") == "The results of the survey are clear, and that that is known."
    assert textops.tidy('Here is the revised paragraph:\n\n**Adoption** rose sharply. [R1][R2] It then slowed [R3] .\n\nNote: I shortened it.') == \
        "Adoption rose sharply [R1, R2]. It then slowed [R3]."


def test_dropped_citations_are_put_back_and_invented_ones_removed():
    original = "Adoption rose from 12% to 31% [R2]. Trained managers gained the most [R1, R4]. Costs fell."
    rewrite = "Between the surveys adoption rose from 12% to 31%. The largest gains went to managers with training [R9]. Costs fell [R1]."
    fixed = textops.repair_citations(original, rewrite, allowed={"R1", "R2", "R4"})
    assert fixed == "Between the surveys adoption rose from 12% to 31% [R2]. The largest gains went to managers with training [R4]. Costs fell [R1]."
    assert textops.repair_citations(original, "Something entirely different is said here.", {"R1", "R2", "R4"}) == "Something entirely different is said here."


def test_the_diagnosis_finds_what_to_change():
    found = textops.tells(MACHINE)
    assert {"crucial", "landscape", "pivotal", "multifaceted", "nuanced"} <= set(found["stock vocabulary"])
    assert "trailing -ing clause" in found and "'this highlights/underscores'" in found and "summing-up sentence" in found
    assert textops.naturalness(HUMAN) > textops.naturalness(MACHINE) + 15
    uniform = " ".join(f"The firms in group {n} adopted the tools at a steady pace during that year." for n in "ABCDE")
    plan = textops.rhythm_plan(uniform, {}, 2)
    assert any("Join the sentences" in p for p in plan) and any("short sentence of under ten words" in p for p in plan) and any("open with “The”" in p for p in plan)
    assert textops.uncited("This article reviews the evidence. Adoption rose sharply in the cities over the decade. Rural firms lagged far behind them [R2]. Why did this happen at all in rural firms?") \
        == ["Adoption rose sharply in the cities over the decade."]
    assert textops.informality("We don't really get why lots of firms did it, but it's a big deal!") >= 6 and textops.informality(HUMAN) == 0


@pytest.mark.parametrize("tool, candidate, problem", [
    ("humanize", HUMAN.replace(" [R2]", ""), "citations dropped: R2"),
    ("humanize", HUMAN.replace("31%", "38%"), "numbers dropped: 31%"),
    ("humanize", HUMAN + " A 2023 survey of 4,000 firms confirms it.", "numbers that are not in the original"),
    ("humanize", HUMAN.replace("[R2]", "[R2, R7]"), "citations not supported by the evidence: R7"),
    ("humanize", "Here is the revised paragraph: " + HUMAN, "remark about the rewrite"),
    ("humanize", HUMAN.replace("The gains were uneven.", "The gains reveal a nuanced tapestry."), "new stock wording was introduced: tapestry"),
    ("humanize", MACHINE, None),                                                  # passes the hard checks, but changes nothing: goal not met
    ("condense", MACHINE, "length is 100% of the original"),
    ("condense", "Digital tools matter [R1, R2].", "numbers dropped"),
    ("expand", HUMAN, "length is"),
    ("polish", HUMAN, "too much of the content is gone"),
    ("simplify", "Tools. [R1] [R2]", "too much of the content is gone"),
])
def test_the_gate_rejects_what_breaks_the_text(tool, candidate, problem, model):
    problems, gain, met = textops.gate(tool, 2, MACHINE, candidate, allowed=set(), evidence="", profile={})
    if problem is None:
        assert problems == [] and met is False
    else:
        assert any(problem in p for p in problems), problems


def test_a_good_rewrite_passes_and_reaches_the_goal(model):
    assert textops.gate("humanize", 2, MACHINE, HUMAN, allowed=set(), evidence="", profile={})[0::2] == ([], True)
    short = ("Digital tools sit at the centre of small firms [R1]. Adoption rates rose from 12% to 31% between 2015 and 2021 [R2]. Trained managers saw larger gains than "
             "untrained ones in the same period [R1]. Technology and productivity are thus related in emerging economies.")
    assert textops.gate("condense", 2, MACHINE, short, allowed=set(), evidence="", profile={})[0::2] == ([], True)
    cited = MACHINE.replace("emerging economies.", "emerging economies [R5].")
    assert textops.gate("add_citations", 2, MACHINE, cited, allowed={"R5"}, evidence="[R5] …", profile={})[0::2] == ([], True)
    assert textops.gate("add_citations", 2, MACHINE, cited, allowed=set(), evidence="", profile={})[0] == ["citations not supported by the evidence: R5"]


# ------------------------------------------------------------------ one paragraph through all layers
def test_a_rejected_answer_is_retried_with_the_reason(model):
    model["answers"] = [HUMAN.replace("31%", "about a third"), HUMAN]
    new, rep = textops.rewrite_block("humanize", MACHINE, strength=2, context={"title": "T", "section": "Introduction"})
    assert new == HUMAN and rep["status"] == "rewritten" and rep["met"] is True and rep["attempts"] == 2
    first, second = model["calls"]
    assert "Numbers to keep exactly: 12%, 2015, 2021, 31%" in first and "Citation markers to keep" in first and "stock vocabulary" in first
    assert "YOUR PREVIOUS ANSWER WAS NOT ACCEPTED: numbers dropped: 31%" in second


def test_a_rewrite_that_reverses_the_meaning_is_caught_by_the_fidelity_check(model, monkeypatch):
    wrong = HUMAN.replace("The gains were uneven.", "The gains were the same for every firm.")
    model["answers"] = [wrong, HUMAN]
    verdicts = [{"errors": [{"type": "contradiction", "edited": "The gains were the same for every firm.", "why": "original says trained managers gained more"},
                            {"type": "invention", "edited": "words that are nowhere in the rewrite at all", "why": "made up by the checker"}]}, {"errors": []}]
    monkeypatch.setattr(llm, "generate_json", lambda system, prompt, default, **kw: (model.setdefault("checks", []).append(prompt), verdicts.pop(0))[1])
    new, rep = textops.rewrite_block("humanize", MACHINE, strength=2, context={})
    assert new == HUMAN and rep["attempts"] == 2 and len(model["checks"]) == 2 and "ORIGINAL:" in model["checks"][0] and "EDITED:" in model["checks"][0]
    assert "contradiction — “The gains were the same for every firm.”" in model["calls"][1] and "nowhere in the rewrite" not in model["calls"][1]
    assert textops.unfaithful("polish", MACHINE, wrong) == []                      # a polish stays close to the original by construction: no extra call
    plain = "Organisers don't really get how fast things go wrong when a queue stops moving, and lots of them say so [R4]."
    heavy = "Organisers do not comprehend how expeditiously circumstances deteriorate when a queue discontinues moving, and numerous organisers acknowledge this [R4]."
    assert textops.gate("formalize", 2, plain, heavy, allowed=set(), evidence="", profile={})[0]                       # thesaurus prose is not accepted as formal
    assert textops.gate("formalize", 2, plain, "Organisers often fail to grasp how fast matters go wrong when a queue stops moving, and many of them say so [R4].", allowed=set(), evidence="", profile={})[0::2] == ([], True)


def test_content_of_a_neighbouring_paragraph_is_not_pulled_in(model):
    after = "It is clear that organisers do not see how fast things go wrong when a queue stops moving [R4]."
    leak = MACHINE.replace("in emerging economies.", "in emerging economies, as seen when a queue stops moving at an entrance.")
    model["answers"] = [leak, leak]
    new, rep = textops.rewrite_block("polish", MACHINE, strength=2, context={}, after=after)
    assert rep["status"] == "rules" and "when a queue stops moving" not in new and rep["problems"]
    assert textops._borrowed(leak, MACHINE, "", after) == "when a queue stops moving" and textops._borrowed(HUMAN, MACHINE, "", after) == ""
    model["answers"] = [leak, HUMAN]
    new, rep = textops.rewrite_block("humanize", MACHINE, strength=2, context={}, after=after)
    assert new == HUMAN and "“when a queue stops moving” was taken from the neighbouring text" in model["calls"][-1]
    assert "do not use its content" in model["calls"][0]
    added = MACHINE + " Cloud accounting, mobile payments and online marketplaces spread fastest among retailers, wholesalers and transport operators."
    assert textops.gate("polish", 3, MACHINE, added, allowed=set(), evidence="", profile={})[0]                    # a polish that adds a sentence is not a polish


def test_a_model_that_drops_markers_is_repaired_not_rejected(model):
    model["answers"] = [re.sub(r" \[R\d\]", "", HUMAN)]
    new, rep = textops.rewrite_block("humanize", MACHINE, strength=2, context={})
    assert rep["status"] == "rewritten" and rep["attempts"] == 1 and sorted(set(textops._labels(new))) == ["R1", "R2"]


def test_when_the_model_fails_the_rules_still_improve_the_text(model):
    model["answers"] = lambda prompt: "I cannot help with that."
    new, rep = textops.rewrite_block("humanize", MACHINE, strength=2, context={})
    assert rep["status"] == "rules" and new == textops.rules("humanize", MACHINE) and "citations dropped: R1, R2" in rep["problems"]
    model["answers"] = lambda prompt: llm.LLMError("offline")
    new, rep = textops.rewrite_block("expand", MACHINE, strength=2, context={})
    assert new == MACHINE and rep["status"] == "unchanged" and "model error: offline" in rep["problems"][0]


def test_the_best_passing_answer_is_kept_even_when_the_goal_is_only_partly_reached(model):
    sents = textops._sentences(MACHINE)
    model["answers"] = [" ".join(sents[:3]) + " Technology and productivity are related in emerging economies.", MACHINE, MACHINE]     # ~85%, then nothing cut at all
    new, rep = textops.rewrite_block("condense", MACHINE, strength=3, context={})
    assert rep["status"] == "rewritten" and rep["met"] is False and new.startswith("Digital tools play") and "still" in model["calls"][1]


def test_add_citations_cites_only_what_the_evidence_offers(model):
    text = "Adoption rose sharply in the cities over the decade. Rural firms lagged far behind them [R2]. Managers with training gained the most from the tools."
    seen = []

    def evidence_for(passage):
        seen.append(passage)
        return "[R3] (Lee, 2020): Urban adoption of digital tools tripled between 2010 and 2020.", {"R3"}
    model["answers"] = [text.replace("over the decade.", "over the decade [R3].").replace("from the tools.", "from the tools [R8].")]
    new, rep = textops.rewrite_block("add_citations", text, strength=2, context={}, evidence_for=evidence_for)
    assert new == text.replace("over the decade.", "over the decade [R3].") and rep["status"] == "rewritten"            # R8 was not on offer: removed
    assert "Rural firms" not in seen[0] and "Statements without support" in model["calls"][0] and "[R3] (Lee, 2020)" in model["calls"][0]
    model["answers"] = [text]                                                                       # the model finds nothing it can honestly cite
    new, rep = textops.rewrite_block("add_citations", text, strength=3, context={}, evidence_for=evidence_for)
    assert new == text and rep["attempts"] == 1 and rep["problems"] == ["the sources found do not support the statements that lack a citation"]   # … and is not pushed
    model["calls"].clear()
    model["answers"] = []
    done, rep = textops.rewrite_block("add_citations", "Adoption rose sharply in the cities [R1]. Rural firms lagged far behind them [R2].", strength=2, context={}, evidence_for=evidence_for)
    assert rep == {"status": "unchanged", "met": True, "problems": ["every statement already carries a citation"], "evidence": "", "attempts": 0} and len(model["calls"]) == 0


# ------------------------------------------------------------------ long text
def long_text(paragraphs: int = 24) -> str:
    out = ["2. Background"]
    for n in range(1, paragraphs + 1):
        out.append(f"Moreover, the firms of region {n} adopted digital tools at very different speeds during the period under study [R{n}]. "
                   f"It is important to note that the adoption rate in region {n} reached {40 + n}% by the end of the period, which is a wide range of outcomes [R{n}]. "
                   f"Furthermore, managers in region {n} who had been trained reported larger gains than managers who had not been trained at all [R{n + 30}]. "
                   f"Overall, this pattern in region {n} suggests that training matters at least as much as the tools themselves do.")
        if n == 5:
            out.append("[[TABLE 1]]")
    return "\n\n".join(out)


def test_a_long_section_is_worked_through_paragraph_by_paragraph(model):
    text = long_text()

    def condense(prompt):       # an editor that keeps the two sentences that carry the finding
        s = textops._sentences(paragraph_of(prompt))
        return f"{s[0]} {s[1]} Trained managers gained more {textops.MARKER.findall(s[2])[0]}."
    model["answers"] = condense
    notes = []
    out, rep = textops.run("condense", text, strength=2, title="T", section="Background", progress=notes.append)
    assert len(text.split()) > 1900 and rep["paragraphs"] == 25 and rep["attempted"] == 24 and rep["rewritten"] == 24 and rep["kept"] == []
    assert len(model["calls"]) == 24 and max(len(c.split()) for c in model["calls"]) < 420              # never the whole section in one request
    assert 0.4 < rep["words_after"] / rep["words_before"] < 0.75 and rep["citations_preserved"] == "48/48" and rep["numbers_preserved"] == "48/48"
    blocks = out.split("\n\n")
    assert blocks[0] == "2. Background" and blocks[6] == "[[TABLE 1]]" and len(blocks) == 26             # heading and table untouched, order kept
    assert "Moreover" not in out and all(f"region {n} reached {40 + n}%" in out for n in range(1, 25))
    assert "TEXT BEFORE (for flow only;" in model["calls"][3] and notes[0] == "Condense: working on 24 paragraph(s), each checked against the original"
    assert textops.summary(rep).startswith("24 of 24 paragraph(s) changed · ") and "citations kept 48/48" in textops.summary(rep)

    model["calls"].clear()
    model["answers"] = lambda prompt: "Sorry."                                                            # a model that produces nothing usable
    out, rep = textops.run("humanize", text, strength=2)
    assert rep["rewritten"] == 0 and rep["rules_only"] == 24 and rep["changed"] and "Moreover" not in out and rep["citations_preserved"] == "48/48"
    assert rep["naturalness_after"] >= rep["naturalness_before"]


def test_a_very_long_paragraph_is_split_into_windows(model):
    one = " ".join(p for p in long_text(8).split("\n\n")[1:] if not p.startswith("[["))
    model["answers"] = lambda prompt: textops.rules("humanize", paragraph_of(prompt)).replace("adopted digital tools at very different speeds", "took up digital tools at very different speeds") \
        .replace("reported larger gains than managers who had not been trained at all", "gained more than their untrained peers")
    new, rep = textops.rewrite_block("humanize", one, strength=1, context={})
    assert len(one.split()) > 500 and len(model["calls"]) >= 3 and max(len(paragraph_of(c).split()) for c in model["calls"]) < 260
    assert rep["status"] == "rewritten" and "\n" not in new and sorted(set(textops._labels(new))) == sorted(set(textops._labels(one)))


# ------------------------------------------------------------------ in the Studio
def test_a_tool_in_the_studio_saves_a_version_and_reports_what_it_did(client, model, monkeypatch):
    p = make_project()
    seg = p.segments["introduction"]
    p.segments["introduction"].content = MACHINE + "\n\n" + seg.content.split("\n\n")[1]
    store.save(p)
    model["answers"] = lambda prompt: HUMAN if "crucial role" in paragraph_of(prompt) else paragraph_of(prompt)
    r = client.post(f"/api/projects/{p.id}/segments/introduction/tool", json={"tool": "humanize", "strength": 3})
    assert r.status_code == 200
    wait(p.id)
    seg = store.load(p.id).segments["introduction"]
    assert seg.content.startswith(HUMAN) and seg.status == "draft" and seg.versions[-1].reason == "humanize: 1/2 paragraphs" and len(seg.versions) == 2
    t = seg.quality.tool
    assert t["tool"] == "humanize" and t["strength"] == 3 and t["rewritten"] == 1 and t["kept"][0]["paragraph"] == 2 and t["citations_preserved"] == "2/2"
    assert seg.quality.humanize == t and seg.quality.citations == 4 and t["naturalness_after"] > t["naturalness_before"]

    model["answers"] = lambda prompt: paragraph_of(prompt)                                                 # a model that changes nothing
    client.post(f"/api/projects/{p.id}/segments/introduction/tool", json={"tool": "polish"})
    wait(p.id)
    seg = store.load(p.id).segments["introduction"]
    assert len(seg.versions) == 2 and seg.quality.tool["tool"] == "polish" and seg.quality.tool["changed"] is False and seg.status == "draft"

    part = seg.content.split("\n\n")[1]
    model["answers"] = lambda prompt: " ".join(textops._sentences(paragraph_of(prompt))[:1])               # the selected passage only
    client.post(f"/api/projects/{p.id}/segments/introduction/tool", json={"tool": "condense", "selection": part, "strength": 3})
    wait(p.id)
    seg = store.load(p.id).segments["introduction"]
    assert seg.content.startswith(HUMAN + "\n\n") and len(seg.content.split("\n\n")[1].split()) < len(part.split()) and seg.versions[-1].reason == "tool: condense"

    assert client.post(f"/api/projects/{p.id}/segments/title/tool", json={"tool": "polish"}).status_code == 422
    assert client.post(f"/api/projects/{p.id}/segments/introduction/tool", json={"tool": "polish", "strength": 7}).status_code == 422
