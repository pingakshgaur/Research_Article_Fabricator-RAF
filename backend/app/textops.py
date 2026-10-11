"""The engine behind the Studio's text tools: Expand, Condense, Formalize, Simplify, Add citations, Polish, Humanize
and Strengthen.

A tool never hands a whole section to the model in one request (which is what made the old tools fail on long text: the
answer was cut off at the output limit, or the model summarised). Every tool runs the same layers, paragraph by
paragraph, with several paragraphs in work at once:

1. Split      the text into paragraphs; tables, figures and headings are set aside; a very long paragraph is worked on
              in windows of a few sentences.
2. Diagnose   measure the paragraph (rhythm, formulaic wording, register, readability, uncited claims …) and decide
              what exactly has to change. No model involved.
3. Rules      deterministic edits that are always safe (filler phrases, stock connectors, contractions, duplicate
              sentences, spacing). They guarantee a result even when the model produces nothing usable.
4. Rewrite    the model rewrites the paragraph with a measured brief: targets in words, the sentences to split or
              merge, the phrases to replace, the evidence it may cite. Its neighbours are shown for flow.
5. Repair     citation markers the model dropped are put back on the sentence they belonged to; invented ones go.
6. Gate       hard checks every candidate must pass (citations, numbers, names, content, length window), then a
              tool-specific measure of how far the goal was reached. A candidate that passes is read once more by the
              model as a checker: does it contradict the original anywhere, or state something the original does not?
7. Select     of the candidates that pass, the one that reaches the goal best is kept. If none passes, the rules-only
              version is used; if that changed nothing, the paragraph stays as it was, with the reason reported.

`strength` (1 light · 2 balanced · 3 strong) scales the targets of every tool.

This engine improves writing. It does not promise anything about AI-text detectors, which are unreliable.
"""
from __future__ import annotations

import difflib
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from rapidfuzz import fuzz, utils

from . import llm, style
from .ingest import split_sentences

MARKER, PLACEHOLDER, NUMBER, WORD, STOP = style.MARKER, style.PLACEHOLDER, style.NUMBER, style.WORD, style.STOP
LABEL = re.compile(r"[RW]\d+")
SYSTEM = ("You are a senior academic editor. You change how a passage is written exactly as the brief says and never what it claims. "
          "You return the passage only.")

# what each tool is, per strength: the length it aims for (× the original) and the window a result must fall in
TOOLS: dict[str, dict] = {
    "expand": {"label": "Expand", "adds": True, "target": {1: 1.2, 2: 1.4, 3: 1.7}, "window": lambda t: (1.08, t + 0.45), "recall": 0.62, "min_words": 15},
    "condense": {"label": "Condense", "adds": False, "target": {1: 0.82, 2: 0.66, 3: 0.5}, "window": lambda t: (max(0.25, t - 0.26), 0.95), "recall": {1: 0.55, 2: 0.45, 3: 0.35}, "min_words": 30},
    "formalize": {"label": "Formalize", "adds": False, "target": {1: 1.0, 2: 1.0, 3: 1.05}, "window": lambda t: (0.8, 1.3), "recall": 0.52, "min_words": 12},
    "simplify": {"label": "Simplify", "adds": False, "target": {1: 1.0, 2: 0.95, 3: 0.9}, "window": lambda t: (0.72, 1.25), "recall": 0.5, "min_words": 15},
    "add_citations": {"label": "Add citations", "adds": True, "target": {1: 1.0, 2: 1.05, 3: 1.12}, "window": lambda t: (0.95, t + 0.3), "recall": 0.8, "min_words": 12},
    "polish": {"label": "Polish", "adds": False, "target": {1: 1.0, 2: 1.0, 3: 1.0}, "window": lambda t: (0.88, 1.14), "recall": 0.75, "min_words": 10},
    "humanize": {"label": "Humanize", "adds": False, "target": {1: 1.0, 2: 1.0, 3: 1.0}, "window": lambda t: (0.78, 1.28), "recall": {1: 0.58, 2: 0.48, 3: 0.4}, "min_words": 20},
    "strengthen_argument": {"label": "Strengthen", "adds": True, "target": {1: 1.05, 2: 1.15, 3: 1.3}, "window": lambda t: (0.88, t + 0.35), "recall": 0.58, "min_words": 20},
}
ATTEMPTS = {1: 2, 2: 2, 3: 3}
TEMPERATURES = (0.7, 0.5, 0.85)
LONG_PARAGRAPH, WINDOW_WORDS = 260, 150

# ---- wording that marks machine-drafted or padded prose (beyond style.GENERIC_PHRASES)
AI_ISMS = ("delve", "tapestry", "testament", "intricate", "intricacies", "pivotal", "underscore", "showcase", "foster", "landscape", "realm", "nuanced",
           "multifaceted", "comprehensive", "robust", "crucial", "leverage", "navigate", "navigating", "embark", "holistic", "seamless", "paramount",
           "noteworthy", "commendable", "meticulous", "ever-evolving", "groundbreaking", "transformative", "invaluable", "vibrant", "myriad", "plethora",
           "garner", "bolster", "elucidate", "shed light", "sheds light", "pave the way", "paves the way", "in the realm of", "it is important to note",
           "it is worth noting", "plays a crucial role", "plays a pivotal role", "plays a vital role", "plays a key role", "a wide range of", "valuable insights")
TELLS = {
    "trailing -ing clause": re.compile(r",\s(?:thereby\s|thus\s)?(?:highlighting|underscoring|emphasi[sz]ing|showcasing|reflecting|demonstrating|illustrating|"
                                       r"suggesting|indicating|underlining|reinforcing|ensuring|enabling|fostering|paving)\b", re.I),
    "'not only … but also'": re.compile(r"\bnot only\b.{3,90}?\bbut(?: also)?\b", re.I | re.S),
    "summing-up sentence": re.compile(r"(?:^|(?<=[.!?]\s))(?:overall|in essence|in summary|ultimately|taken together|in sum|all in all),?\s", re.I),
    "'this highlights/underscores'": re.compile(r"\b(?:this|these|such)(?:\s\w+){0,3}\s(?:highlights?|underscores?|underlines?|demonstrates?|illustrates?|exemplif(?:y|ies))\s(?:the|how|that)\b", re.I),
    "stacked hedges": re.compile(r"\b(?:may|might|could|can)\s(?:potentially|possibly|perhaps|arguably)\b|\b(?:potentially|possibly)\s(?:may|might|could)\b", re.I),
    "'serves as / stands as'": re.compile(r"\b(?:serves?|stands?|acts?)\sas\s(?:a|an|the)\b", re.I),
    "'it is … that' framing": re.compile(r"\bit is (?:\w+ ){0,2}(?:clear|evident|important|essential|crucial|worth \w+|interesting|notable) (?:that|to)\b", re.I),
    "'from … to …' sweep": re.compile(r"\bfrom\s(?:\w+\s){1,4}to\s(?:\w+\s){1,4}(?:and|,)", re.I),
}
STOCK_START = re.compile(r"(^|(?<=[.!?]\s))(?:Moreover|Furthermore|Additionally|In addition|Notably|Importantly|Indeed|Interestingly|Crucially|Significantly|"
                         r"It is clear that|It is evident that|It should be noted that|It is important to note that|It is worth noting that|"
                         r"It is worth mentioning that|It is noteworthy that|Needless to say),?\s+(\w)")
FILLERS = [  # (pattern, replacement) — each replacement keeps the sentence grammatical
    (re.compile(r"\bit (?:is|should be) (?:important|worth|interesting|crucial|essential|noteworthy) (?:to )?(?:not(?:e|ing)|mention(?:ing)?|emphasi[sz](?:e|ing)|highlight(?:ing)?|recogni[sz](?:e|ing)) that\s+", re.I), ""),
    (re.compile(r"\bit should be noted that\s+", re.I), ""),
    (re.compile(r"\bit(?: is|'s) (?:pretty |quite |very |fairly |abundantly )?(?:clear|obvious|evident|apparent) that\s+", re.I), ""),
    (re.compile(r"\bin order to\b", re.I), "to"),
    (re.compile(r"\bdue to the fact that\b", re.I), "because"),
    (re.compile(r"\bin spite of the fact that\b", re.I), "although"),
    (re.compile(r"\bat this point in time\b", re.I), "now"),
    (re.compile(r"\ba (?:wide|broad|diverse|vast) (?:range|variety|array|spectrum) of\b", re.I), "many"),
    (re.compile(r"\ba (?:myriad|plethora|multitude) of\b", re.I), "many"),
    (re.compile(r"\bin today's (?:rapidly evolving|fast-paced|ever-changing|ever-evolving|modern|digital)?\s?(?:world|landscape|environment|era|age|society),?\s+", re.I), ""),
    (re.compile(r"\bfor the purpose of\b", re.I), "for"),
    (re.compile(r"\bhas the (?:ability|capacity) to\b", re.I), "can"),
    (re.compile(r"\bhave the (?:ability|capacity) to\b", re.I), "can"),
    (re.compile(r"\butili[sz]es\b", re.I), "uses"), (re.compile(r"\butili[sz]ed\b", re.I), "used"),
    (re.compile(r"\butili[sz]ing\b", re.I), "using"), (re.compile(r"\butili[sz]e\b", re.I), "use"),
]
CONTRACTIONS = {"don't": "do not", "doesn't": "does not", "didn't": "did not", "can't": "cannot", "couldn't": "could not", "won't": "will not",
                "wouldn't": "would not", "shouldn't": "should not", "isn't": "is not", "aren't": "are not", "wasn't": "was not", "weren't": "were not",
                "hasn't": "has not", "haven't": "have not", "hadn't": "had not", "it's": "it is", "that's": "that is", "there's": "there is",
                "what's": "what is", "let's": "let us", "they're": "they are", "we're": "we are", "you're": "you are", "i'm": "I am",
                "they've": "they have", "we've": "we have", "i've": "I have", "they'll": "they will", "we'll": "we will", "it'll": "it will"}
INFORMAL = re.compile(r"\b(?:a lot of|lots of|kind of|sort of|pretty much|really|very|totally|basically|actually|stuff|things?|huge|big deal|"
                      r"get|gets|got|gotten|find out|look into|come up with|go up|go down|a bit|a couple of|plenty of|nowadays|anyway|ok|okay|"
                      r"kids?|guys?|bad|good|show up|deal with|make sure|figure out|point out|bring up|carry out|you|your)\b", re.I)
VAGUE = re.compile(r"\b(?:some|many|several|various|numerous|a number of|certain|somewhat|rather|fairly|quite|relatively|to some extent|in some ways|"
                   r"it (?:seems|appears) that|may or may not|more or less|tends? to|arguably)\b", re.I)
PADDING = style.FORMULAIC_WORDS | {w for phrase in AI_ISMS for w in phrase.split()} | {"role", "plays", "play", "nature", "relationship", "aspect", "aspects", "context", "terms"}
LINKS = re.compile(r"\b(?:because|therefore|thus|hence|consequently|as a result|it follows that|this implies|which means|for this reason|"
                   r"however|although|whereas|nevertheless|by contrast|conversely|yet)\b", re.I)
NOT_A_CLAIM = re.compile(r"^(?:this (?:article|paper|study|section|review|chapter)|the (?:present|current) (?:study|article|paper|section)|we |our |in this (?:section|article|paper)|"
                         r"the (?:following|next|remainder)|table \d|figure \d|first,|second,|third,|finally,|section \d|"
                         r"(?:overall|in sum|in summary|taken together|in short|in conclusion|thus|therefore|hence),?\s|"
                         r"(?:this|these|such)(?:\s\w+){0,3}\s(?:highlights?|suggests?|shows?|implies|impl(?:y|ies)|means?|indicates?|demonstrates?|points? to)\b)", re.I)


# ============================================================================================ small helpers
def _words(text: str) -> int:
    return len(MARKER.sub("", text).split())


def _labels(text: str) -> list[str]:
    return [l for m in MARKER.findall(text) for l in LABEL.findall(m)]


def _numbers(text: str) -> set[str]:
    return set(NUMBER.findall(MARKER.sub(" ", text)))


def _stems(text: str) -> set[str]:
    """The content words of a text, by stem. Formulaic words do not count: removing them is the point of several tools."""
    return {w.lower()[:6] for w in WORD.findall(MARKER.sub(" ", text)) if len(w) >= 4 and w.lower() not in STOP and w.lower() not in PADDING}


def _alike(a: str, b: str) -> float:
    """0–100: how much two sentences say the same thing, whatever the word order."""
    return fuzz.token_set_ratio(a, b, processor=utils.default_process)


def _recall(original: str, rewrite: str) -> float:
    """Share of the original's content words that are still there (by stem)."""
    a = _stems(original)
    return len(a & _stems(rewrite)) / max(1, len(a))


def _novel(original: str, candidate: str) -> float:
    """Share of the candidate's content words that the original does not have."""
    c = _stems(candidate)
    return len(c - _stems(original)) / max(1, len(c))


def _borrowed(candidate: str, block: str, *around: str) -> str:
    """Five words in a row that the candidate shares with a neighbouring paragraph but not with its own original."""
    tokens = lambda text: re.findall(r"[\w'%-]+", MARKER.sub("", text).lower())
    own, cand = " " + " ".join(tokens(block)) + " ", " " + " ".join(tokens(candidate)) + " "
    for text in around:
        w = tokens(text)
        for i in range(len(w) - 4):
            run = " " + " ".join(w[i:i + 5]) + " "
            if run in cand and run not in own:
                return run.strip()
    return ""


def _closeness(a: str, b: str) -> float:
    """1.0 = the same words in the same order."""
    return difflib.SequenceMatcher(None, a.lower().split(), b.lower().split(), autojunk=False).ratio()


def _cosine(a: str, b: str) -> float | None:
    """Meaning similarity from the embedding model, when one is installed."""
    vectors = llm.embed([MARKER.sub("", a), MARKER.sub("", b)])
    if not vectors or len(vectors) != 2:
        return None
    x, y = vectors
    norm = (sum(v * v for v in x) ** 0.5) * (sum(v * v for v in y) ** 0.5)
    return sum(p * q for p, q in zip(x, y)) / norm if norm else None


def _sentences(text: str) -> list[str]:
    return [s for s in split_sentences(text) if s.strip()]


def _word_length(text: str) -> float:
    words = WORD.findall(MARKER.sub(" ", text))
    return sum(map(len, words)) / max(1, len(words))


def _first_up(text: str) -> str:
    return re.sub(r"^(\W*)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text, count=1)


def _reading_ease(text: str) -> float:
    try:
        import textstat
        return float(textstat.flesch_reading_ease(MARKER.sub("", text)))
    except Exception:  # noqa: BLE001 - textstat is optional
        sents = _sentences(text) or [text]
        return 120 - 1.4 * len(text.split()) / len(sents)


# ============================================================================================ layer 2 · diagnosis
def tells(text: str) -> dict[str, list[str]]:
    """Formulaic patterns found in the text: name -> the places where they occur."""
    plain = MARKER.sub("", text)
    low = plain.lower()
    found: dict[str, list[str]] = {}
    words = sorted({w for w in AI_ISMS if re.search(r"\b" + re.escape(w), low)})
    if words:
        found["stock vocabulary"] = words
    for name, pattern in TELLS.items():
        hits = [m.group(0).strip(" ,") for m in pattern.finditer(plain)]
        if hits:
            found[name] = hits[:4]
    if plain.count("—") + plain.count(" – ") > 1:
        found["dashes used as a habit"] = ["—"]
    return found


def naturalness(text: str, profile: dict | None = None) -> float:
    """0–100. The style score (rhythm, openers, connectors, diversity) with the formulaic patterns taken off."""
    m = style.metrics(text)
    base = style.score(m, profile) if m.get("score") is not None else 92.0
    per_100 = 100 / max(40, len(text.split()))
    return max(0.0, base - sum(len(v) for v in tells(text).values()) * 5 * per_100)


def informality(text: str) -> int:
    plain = MARKER.sub("", text)
    return (len(re.findall(r"\b\w+'(?:t|s|re|ve|ll|m|d)\b", plain)) + len(INFORMAL.findall(plain)) + plain.count("!")
            + len(re.findall(r"(?:^|(?<=[.!?]\s))(?:And|But|So|Plus|Also)\b", plain)))


def uncited(text: str) -> list[str]:
    """Sentences that state something and carry no citation."""
    return [s for s in _sentences(text) if not MARKER.search(s) and len(s.split()) >= 9 and not s.rstrip().endswith("?") and not NOT_A_CLAIM.match(s.strip())]


def rhythm_plan(text: str, profile: dict | None, strength: int) -> list[str]:
    """Concrete sentence-level instructions that make the rhythm less uniform. Derived from the sentence lengths only."""
    sents = _sentences(MARKER.sub("", text))
    if len(sents) < 3:
        return []
    lengths = [len(s.split()) for s in sents]
    quote = lambda i: "“" + " ".join(sents[i].split()[:6]) + " …”"
    plan = []
    cv = statistics.pstdev(lengths) / statistics.mean(lengths)
    if cv < (profile or {}).get("sentence_length_variation", 0.5) or strength == 3:
        longest = max(range(len(sents)), key=lengths.__getitem__)
        if lengths[longest] >= 30:
            plan.append(f"Split the sentence that begins {quote(longest)} ({lengths[longest]} words) into two.")
        pair = next((i for i in range(len(sents) - 1) if lengths[i] <= 15 and lengths[i + 1] <= 15), None)
        if pair is not None and min(lengths) > 9:
            plan.append(f"Join the sentences that begin {quote(pair)} and {quote(pair + 1)} into one.")
        if min(lengths) > 11:
            mid = min(range(len(sents)), key=lambda i: abs(lengths[i] - statistics.median(lengths)))
            plan.append(f"State one point in a short sentence of under ten words, for example the point made in {quote(mid)}.")
    openers = [re.sub(r"[^a-z]", "", s.split()[0].lower()) for s in sents]
    for word in {o for o in openers if o and openers.count(o) >= max(2, len(sents) // 3)}:
        which = [i for i, o in enumerate(openers) if o == word]
        plan.append(f"{len(which)} sentences open with “{word.capitalize()}”: begin the one starting {quote(which[-1])} differently.")
    if strength == 3:
        plan.append("Change which idea leads in at least two sentences (move a condition, a result or a source to the front or to the end).")
    return plan[:5]


# ============================================================================================ layer 3 · rules
def tidy(text: str) -> str:
    """Clean what a model returns: no preamble, no Markdown, markers and punctuation in place."""
    text = text.strip().strip("`").strip()
    text = re.sub(r"^(?:here(?: is|'s)|sure|certainly|of course|okay|revised|rewritten|polished|condensed|expanded)[^\n:]{0,80}:\s*", "", text, flags=re.I)
    text = re.sub(r"^(?:\*\*|#+\s*)?(?:revised|rewritten|final|output|paragraph|passage)[^\n]{0,30}:?\**\s*\n", "", text, flags=re.I)
    text = re.sub(r"\n+(?:note|explanation|changes made|what (?:i|was) changed)\b.*\Z", "", text, flags=re.I | re.S)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), text)
    text = text.strip().strip('"“”').strip()
    text = re.sub(r"\]\s*\[(?=[RW]\d)", ", ", text)                    # [R1][R2] -> [R1, R2]
    text = re.sub(r"([.,;:])\s*(\[(?:[RW]\d+[,;\s]*)+\])", r" \2\1", text)  # "claim. [R1]" -> "claim [R1]."
    text = re.sub(r"[ \t]+([.,;:])(?!\d)", r"\1", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def rules(tool: str, text: str) -> str:
    """The deterministic layer of a tool: edits that cannot change what the text says."""
    out = text
    if tool in {"humanize", "condense", "polish", "formalize"}:
        for pattern, repl in FILLERS:
            out = pattern.sub(lambda m, repl=repl: _keep_case(m.group(0), repl) if repl else "\x00", out)
        out = re.sub(r"(^|(?<=[.!?]\s))\x00(\w)", lambda m: m.group(1) + m.group(2).upper(), out).replace("\x00", "")   # a sentence that lost its opening keeps its capital
    if tool in {"humanize", "condense"}:
        out = STOCK_START.sub(lambda m: m.group(1) + m.group(2).upper(), out)
    if tool == "formalize":
        out = re.sub(r"\b[\w]+'(?:t|s|re|ve|ll|m)\b", lambda m: _keep_case(m.group(0), CONTRACTIONS.get(m.group(0).lower(), m.group(0))), out)
        out = out.replace("!", ".")
    if tool == "condense":
        kept: list[str] = []
        for s in _sentences(out):       # a sentence that repeats an earlier one adds nothing
            bare = MARKER.sub("", s)
            if not any(_alike(bare, MARKER.sub("", k)) >= 92 and not set(_labels(s)) - set(_labels(k)) for k in kept):
                kept.append(s)
        out = " ".join(kept) if kept else out
    if tool in {"polish", "humanize", "condense", "formalize", "simplify"}:
        out = re.sub(r"\b(the|a|an|of|in|to|and|is|are|for|on|with|by)\s+\1\b", r"\1", out, flags=re.I)   # "the the"
    return tidy(out)


def _keep_case(original: str, new: str) -> str:
    return new[0].upper() + new[1:] if original[0].isupper() else new


# ============================================================================================ layer 5 · repair
def repair_citations(original: str, rewrite: str, allowed: set[str]) -> str:
    """Put back citation markers the model dropped, on the sentence that says what the cited sentence said, and remove
    markers for sources it was not allowed to cite."""
    def clean(m):
        keep = [l for l in LABEL.findall(m.group(0)) if l in allowed]
        return "[" + ", ".join(keep) + "]" if keep else ""
    rewrite = re.sub(r"\s+([.,;:])(?!\d)", r"\1", MARKER.sub(clean, rewrite))
    have = set(_labels(rewrite))
    targets = _sentences(rewrite)
    for source in _sentences(original):
        missing = [l for l in dict.fromkeys(_labels(source)) if l not in have]
        if not missing or not targets:
            continue
        bare = MARKER.sub("", source)
        best = max(range(len(targets)), key=lambda i: _alike(bare, MARKER.sub("", targets[i])))
        if _alike(bare, MARKER.sub("", targets[best])) < 50:
            continue
        t = targets[best]
        existing = MARKER.search(t)
        if existing and existing.end() >= len(t.rstrip()) - 1:      # the sentence already ends in a marker: extend it
            new = t[:existing.end() - 1] + ", " + ", ".join(missing) + t[existing.end() - 1:]
        else:
            m = re.search(r"[.!?]\s*$", t)
            new = (t[:m.start()] + f" [{', '.join(missing)}]" + t[m.start():]) if m else t + f" [{', '.join(missing)}]"
        rewrite = rewrite.replace(t, new, 1)
        targets[best] = new
        have.update(missing)
    return rewrite


# ============================================================================================ layer 6 · gate
def gate(tool: str, strength: int, original: str, candidate: str, *, allowed: set[str], evidence: str, profile: dict | None) -> tuple[list[str], float, bool]:
    """Returns (hard problems, how far the goal was reached, goal met). A candidate with problems is not used."""
    spec = TOOLS[tool]
    problems: list[str] = []
    old, new = set(_labels(original)), set(_labels(candidate))
    if old - new:
        problems.append("citations dropped: " + ", ".join(sorted(old - new)))
    if new - old - (allowed if spec["adds"] else set()):
        problems.append("citations not supported by the evidence: " + ", ".join(sorted(new - old - allowed)))
    nums_old, nums_new = _numbers(original), _numbers(candidate)
    need = {1: 1.0, 2: 0.9, 3: 0.75}[strength] if tool == "condense" else 1.0
    kept = sum(n in candidate for n in nums_old) / len(nums_old) if nums_old else 1.0
    if kept < need:
        problems.append("numbers dropped: " + ", ".join(sorted(n for n in nums_old if n not in candidate)[:6]))
    fresh = [n for n in nums_new - nums_old if n not in original and not re.fullmatch(r"\d", n) and not (spec["adds"] and n in evidence)]
    if fresh:
        problems.append("numbers that are not in the original" + (" or the evidence" if spec["adds"] else "") + ": " + ", ".join(sorted(fresh)[:6]))
    names = style.inventory(original)["names"]
    lost = [n for n in names if n.lower() not in candidate.lower()]
    if len(lost) > max(1, len(names) // (2 if tool == "condense" and strength == 3 else 4)):
        problems.append("names dropped: " + ", ".join(lost[:5]))
    recall = _recall(original, candidate)
    floor = spec["recall"][strength] if isinstance(spec["recall"], dict) else spec["recall"]
    if recall < floor:
        problems.append(f"too much of the content is gone ({recall:.0%} of the key words kept, {floor:.0%} needed)")
    ratio = _words(candidate) / max(1, _words(original))
    lo, hi = spec["window"](spec["target"][strength])
    if not lo <= ratio <= hi:
        problems.append(f"length is {ratio:.0%} of the original; it must be between {lo:.0%} and {hi:.0%}")
    if re.match(r"(?:here is|here's|sure|certainly|i have|i've|this revised|the revised|revised (?:paragraph|passage|text))\b", candidate.strip(), re.I):
        problems.append("contains a remark about the rewrite")
    if not problems and tool != "expand":
        cos = _cosine(original, candidate)
        if cos is not None and cos < (0.62 if tool == "condense" else 0.74):
            problems.append(f"the meaning moved too far from the original (similarity {cos:.2f})")
    if problems:
        return problems, 0.0, False

    close = _closeness(original, candidate)
    changed = MARKER.sub("", candidate).split() != MARKER.sub("", original).split()
    if tool in {"humanize", "formalize", "polish"}:
        stock = sorted(set(tells(candidate).get("stock vocabulary", [])) - set(tells(original).get("stock vocabulary", [])))
        if stock:
            return ["new stock wording was introduced: " + ", ".join(stock) + "; use the plain word"], 0.0, False
    if tool == "humanize":
        gain = naturalness(candidate, profile) - naturalness(original, profile)
        if gain < -1:
            return [f"reads less natural than before (score {gain:+.0f})"], gain, False
        most_alike = {1: 0.95, 2: 0.86, 3: 0.74}[strength]      # a Humanize that changes nothing is not one
        met = changed and close <= most_alike and (gain >= {1: 1, 2: 2, 3: 3}[strength] or naturalness(candidate, profile) >= 90)
        return [], gain + (1 - close) * {1: 4, 2: 12, 3: 22}[strength], met
    if tool == "condense":
        if _novel(original, candidate) > 0.3:
            return ["new content was added while cutting"], 0.0, False
        return [], 1 - ratio, ratio <= spec["target"][strength] + 0.1
    if tool == "expand":
        return [], ratio + 0.15 * len(new - old), ratio >= spec["target"][strength] - 0.12
    if tool == "simplify":
        ease = _reading_ease(candidate) - _reading_ease(original)
        mean = lambda t: statistics.mean(len(s.split()) for s in _sentences(MARKER.sub("", t)) or [t])
        shorter = 1 - mean(candidate) / max(1.0, mean(original))
        if ease < -2 and shorter <= 0:
            return [f"not easier to read than before (reading ease {ease:+.0f})"], ease, False
        return [], ease + shorter * 40, ease >= {1: 2, 2: 5, 3: 9}[strength] or shorter >= {1: 0.08, 2: 0.15, 3: 0.25}[strength]
    if tool == "formalize":
        drop = informality(original) - informality(candidate)
        if drop < 0:
            return ["more informal wording than before"], float(drop), False
        heavier = _word_length(candidate) - _word_length(original)
        if heavier > 0.45:      # "fast" became "velocity": formal is not the same as heavy
            return [f"plain, correct words were replaced by heavier ones (average word length +{heavier:.1f} letters); change only what is informal"], 0.0, False
        return [], drop + (1 - close) * 3, changed and (drop > 0 or informality(candidate) == 0)
    if tool == "polish":
        if close < {1: 0.78, 2: 0.62, 3: 0.5}[strength]:
            return [f"rewritten too heavily for a polish ({close:.0%} of the wording kept)"], 0.0, False
        if _novel(original, candidate) > {1: 0.1, 2: 0.16, 3: 0.22}[strength]:
            return ["content was added that the paragraph did not have; a polish only corrects"], 0.0, False
        return [], 1 - close, changed
    if tool == "add_citations":
        if close < 0.5:
            return ["rewritten too heavily: only citations and short supporting detail may be added"], 0.0, False
        return [], float(len(new - old)) + (len(uncited(original)) - len(uncited(candidate))) * 0.5, bool(new - old)
    # strengthen_argument
    plain_old, plain_new = MARKER.sub("", original), MARKER.sub("", candidate)
    sharper = (len(VAGUE.findall(plain_old)) + sum(len(v) for k, v in tells(original).items() if k == "stacked hedges")
               - len(VAGUE.findall(plain_new)) - sum(len(v) for k, v in tells(candidate).items() if k == "stacked hedges"))
    linked = len(LINKS.findall(plain_new)) - len(LINKS.findall(plain_old))
    return [], sharper + linked + 0.5 * len(new - old), changed and (sharper > 0 or linked > 0 or len(new - old) > 0)


def unfaithful(tool: str, original: str, candidate: str, evidence: str = "") -> list[str]:
    """The fidelity check: the model reads original and rewrite side by side and names contradictions and inventions.
    Only findings that quote words really present in the rewrite count, so a careless checker cannot block a good rewrite."""
    if tool == "polish":
        return []
    allowed = "the ORIGINAL or the EVIDENCE" if evidence and TOOLS[tool]["adds"] else "the ORIGINAL"
    data = llm.generate_json(
        "You compare an edited paragraph of a journal article with its original. Reply with JSON only.",
        f"ORIGINAL:\n{original}\n\n" + (f"EVIDENCE:\n{evidence}\n\n" if evidence and TOOLS[tool]["adds"] else "") + f"EDITED:\n{candidate}\n\n"
        "Look for two kinds of error only:\n"
        "1. contradiction — on some point the EDITED text says the opposite of the ORIGINAL, or reverses a negation, a cause or a comparison.\n"
        f"2. invention — a fact, cause, name or number in the EDITED text that {allowed} does not contain.\n"
        "Different wording, word order or sentence boundaries are not errors. Left-out padding"
        + (" and left-out minor detail are" if tool == "condense" else " is") + " not an error."
        + (" Explanation of reasoning that is already in the ORIGINAL is not an invention." if TOOLS[tool]["adds"] else "") + "\n\n"
        'JSON: {"errors": [{"type": "contradiction or invention", "edited": "the exact words from the EDITED text", "why": "at most 12 words"}]}  — an empty list when there is none.',
        default={}, max_tokens=400,
    )
    low = re.sub(r"\s+", " ", candidate.lower())
    out = []
    for e in (data.get("errors") or [])[:4] if isinstance(data, dict) else []:
        quoted = re.sub(r"\s+", " ", str(e.get("edited", "")).lower()).strip(" .\"“”")
        if isinstance(e, dict) and len(quoted) >= 12 and quoted[:60] in low and str(e.get("type", "")).lower().startswith(("contra", "invent")):
            out.append(f"{str(e['type']).lower()} — “{str(e['edited']).strip()[:120]}”: {str(e.get('why', ''))[:90]}")
    return out


# ============================================================================================ layer 4 · the brief
def brief(tool: str, strength: int, block: str, *, profile: dict | None, evidence: str, counterpoint: bool = False) -> list[str]:
    """What the model is asked to do to this paragraph, in measured terms."""
    words = _words(block)
    target = round(words * TOOLS[tool]["target"][strength] / 5) * 5
    how_much = {1: "lightly", 2: "clearly", 3: "thoroughly"}[strength]
    if tool == "humanize":
        found = tells(block)
        m = style.metrics(block)
        out = [f"Rewrite the paragraph {how_much} so that it reads as written by a careful specialist, not drafted by a machine: "
               "concrete subjects, precise verbs, links that follow from the logic."]
        out += rhythm_plan(block, profile, strength)
        out += [f"Replace or remove — {name}: {', '.join(dict.fromkeys(hits))}." for name, hits in found.items()]
        out += [f for f in (style.issues(m, profile) if m.get("score") is not None else []) if "Sentence lengths" not in f and "open the same way" not in f][:3]
        out.append("Do not swap words for fancier synonyms and do not add emphasis words; plain, exact wording is the goal.")
        return out
    if tool == "condense":
        return [f"Cut the paragraph from {words} words to about {target} words.",
                "Remove repetition, throat-clearing, restatement and anything a reader of this field already knows.",
                "Merge sentences that make the same point; keep the reasoning chain and every finding.",
                "Citations of merged sentences are grouped, e.g. [R1, R4]; none may disappear."]
    if tool == "expand":
        out = [f"Develop the paragraph from {words} words to about {target} words.",
               "Keep everything it says, then deepen it: explain the mechanism behind a claim, spell out a consequence, or set two sources against each other."]
        out.append("New factual statements must come from the EVIDENCE below and carry its marker, e.g. [R3]. Do not use a source that is not listed."
                   if evidence else "Add no new facts, names or numbers: develop the reasoning that is already there.")
        return out
    if tool == "simplify":
        long_ones = [s for s in _sentences(MARKER.sub("", block)) if len(s.split()) >= 28]
        return ([f"Make the paragraph {how_much} easier to read for a scholar from another field. Same meaning, same citations."]
                + [f"Split the sentence that begins “{' '.join(s.split()[:6])} …” ({len(s.split())} words)." for s in long_ones[:4]]
                + ["Prefer the plain word (use, show, help, about) to the heavy one (utilise, demonstrate, facilitate, approximately).",
                   "Turn noun chains into verbs (“the implementation of X” → “implementing X”) and passives into actives where the actor is known.",
                   "Keep technical terms of the field; explain one in a few words only where the paragraph depends on it."])
    if tool == "formalize":
        found = sorted({m.group(0).lower() for m in INFORMAL.finditer(MARKER.sub("", block))})
        return ([f"Raise the paragraph {how_much} to the register of a journal article."]
                + ([f"Replace the informal wording: {', '.join(found[:12])}."] if found else [])
                + ["No contractions, no direct address of the reader, no rhetorical questions or exclamations.",
                   "Use the exact term of the field where a loose word stands; hedge only where the evidence is uncertain, and only once per claim.",
                   "Keep every word that is already plain and correct (fast, use, show, many, die): formal does not mean longer, heavier or more abstract.",
                   "Remove framing such as “it is clear that” and doubled hedges such as “may potentially”."])
    if tool == "polish":
        return [f"Correct grammar, spelling, punctuation and agreement; {'smooth' if strength > 1 else 'only repair'} the transitions between sentences.",
                "Keep the author's wording wherever it is already correct. Do not rephrase for its own sake and do not change the order of ideas.",
                "The first sentence should connect to the text before it, the last should hand over to the text after it."]
    if tool == "add_citations":
        need = uncited(block)
        return (["Add citation markers to the statements that lack one, using only the EVIDENCE below.",
                 "Statements without support:\n" + "\n".join(f"  • {s}" for s in need[:6]),
                 "Attach a marker such as [R3] only where that source really says it. A statement no source supports stays as it is, unmarked.",
                 "Leave the wording alone otherwise; you may add one short clause of supporting detail from the cited source."
                 + (" Add at most one clause per statement." if strength < 3 else "")])
    out = [f"Make the argument of the paragraph {how_much} stronger without claiming more than the evidence allows.",
           "Replace vague quantities and soft verbs with the specific claim (who, what, how much, under which condition).",
           "Make the chain of reasoning explicit: say why one statement follows from another (because, therefore, which means)."]
    hedges = sorted({m.group(0).lower() for m in VAGUE.finditer(MARKER.sub("", block))})
    if hedges:
        out.append(f"Vague wording to make specific or remove: {', '.join(hedges[:10])}.")
    if counterpoint:
        out.append("Name the most obvious objection in one sentence and answer it" + (" with the EVIDENCE below." if evidence else " from what the paragraph already establishes."))
    if evidence:
        out.append("Support added from the EVIDENCE carries its marker, e.g. [R3]. Do not use a source that is not listed.")
    return out


def _prompt(tool: str, block: str, tasks: list[str], *, context: dict, before: str, after: str, evidence: str, one_paragraph: bool) -> str:
    inv = style.inventory(block)
    keep = ["Keep every claim, qualification and step of reasoning" + (" that the cut leaves room for; drop the least important first." if tool == "condense" else "."),
            f"Citation markers to keep, each on the statement it supports: {', '.join(inv['markers']) or 'none'}.",
            f"Numbers to keep exactly: {', '.join(inv['numbers']) or 'none'}.",
            f"Names and terms to keep: {', '.join(inv['names'] + inv['terms'][:8]) or 'none'}."]
    if not TOOLS[tool]["adds"] or not evidence:
        keep.append("Add no facts, names, numbers or citations.")
    keep.append("One paragraph, plain text." if one_paragraph else "Plain text; a new paragraph only where a new point begins.")
    return (f"ARTICLE: {context.get('title', '')}\nSECTION: {context.get('section', '')}"
            + (f"\nSECTION PURPOSE: {context['purpose']}" if context.get("purpose") else "")
            + (f"\n{context['tone_rule']}" if context.get("tone_rule") else "")
            + (f"\n{style.profile_rule(context['profile'])}" if context.get("profile") else "")
            + "\n\nTASK:\n" + "\n".join(f"- {t}" for t in tasks)
            + "\n\nWHAT MUST NOT CHANGE:\n" + "\n".join(f"- {k}" for k in keep)
            + (f"\n\nEVIDENCE (the only sources you may add):\n{evidence}" if evidence and TOOLS[tool]["adds"] else "")
            + (f"\n\nTEXT BEFORE (for flow only; do not rewrite it and do not use its content): … {before}" if before else "")
            + (f"\nTEXT AFTER (for flow only; do not rewrite it and do not use its content): {after} …" if after else "")
            + f"\n\nPARAGRAPH:\n{block}\n\nReturn only the new paragraph.")


# ============================================================================================ layers 4–7 for one paragraph
def rewrite_block(tool: str, block: str, *, strength: int, context: dict, before: str = "", after: str = "", evidence_for: Callable | None = None,
                  counterpoint: bool = False) -> tuple[str, dict]:
    """One paragraph through the rewrite, repair, gate and selection layers."""
    if _words(block) > LONG_PARAGRAPH:      # too long for one careful rewrite: work through it a few sentences at a time
        pieces, current = [], []
        for s in _sentences(block):
            current.append(s)
            if sum(len(x.split()) for x in current) >= WINDOW_WORDS:
                pieces.append(" ".join(current))
                current = []
        if current and (not pieces or sum(len(x.split()) for x in current) >= 40):
            pieces.append(" ".join(current))
        elif current:                       # a short tail goes with the window before it
            pieces[-1] += " " + " ".join(current)
        done, reports = [], []
        for i, piece in enumerate(pieces):
            new, rep = rewrite_block(tool, piece, strength=strength, context=context, before=(done[-1] if done else before)[-300:],
                                     after=pieces[i + 1][:200] if i + 1 < len(pieces) else after, evidence_for=evidence_for, counterpoint=counterpoint and i == 0)
            done.append(new)
            reports.append(rep)
        status = "rewritten" if any(r["status"] == "rewritten" for r in reports) else "rules" if any(r["status"] == "rules" for r in reports) else "unchanged"
        return " ".join(done), {"status": status, "met": all(r["met"] for r in reports), "problems": [p for r in reports for p in r["problems"]][:3],
                                "evidence": "\n".join(r["evidence"] for r in reports if r["evidence"]), "attempts": sum(r["attempts"] for r in reports)}

    spec, profile = TOOLS[tool], context.get("profile") or {}
    evidence, allowed = "", set()
    if spec["adds"] and evidence_for:
        evidence, allowed = evidence_for(block if tool != "add_citations" else " ".join(uncited(block)) or block)
    if tool == "add_citations" and (not uncited(block) or not evidence):
        return block, {"status": "unchanged", "met": True, "problems": ["every statement already carries a citation" if not uncited(block) else "no evidence found for it"],
                       "evidence": "", "attempts": 0}
    tasks = brief(tool, strength, block, profile=profile, evidence=evidence, counterpoint=counterpoint)
    one_paragraph = not (tool == "expand" and _words(block) * spec["target"][strength] > 230)
    base = _prompt(tool, block, tasks, context=context, before=before, after=after, evidence=evidence, one_paragraph=one_paragraph)
    lo, hi = spec["window"](spec["target"][strength])
    best: tuple[float, str] | None = None
    problems: list[str] = []
    prompt = base
    attempts = 0
    for attempt in range(ATTEMPTS[strength]):
        attempts += 1
        try:
            raw = llm.generate(SYSTEM, prompt, temperature=TEMPERATURES[attempt] + (0.1 if tool == "humanize" and strength == 3 else 0),
                               max_tokens=int(_words(block) * hi * 1.9) + 260)
        except llm.LLMError as exc:
            problems = [f"model error: {exc}"]
            break
        candidate = tidy(raw)
        if one_paragraph:
            candidate = re.sub(r"\s*\n\s*", " ", candidate)
        candidate = repair_citations(block, candidate if spec["adds"] else rules(tool, candidate), allowed | set(_labels(block)))
        found, gain, met = gate(tool, strength, block, candidate, allowed=allowed, evidence=evidence, profile=profile)
        same = candidate.split() == block.split()
        took = "" if found else _borrowed(candidate, block, before, after)
        if took:
            found = [f"“{took}” was taken from the neighbouring text, which is shown for flow only; work with this paragraph's own content"]
        if tool == "add_citations" and not found and not (set(_labels(candidate)) - set(_labels(block))):
            # nothing cited: the evidence does not support these statements, and asking again would only push the model to force a citation
            return block, {"status": "unchanged", "met": True, "problems": ["the sources found do not support the statements that lack a citation"], "evidence": "", "attempts": attempts}
        if not found and not same:
            found = unfaithful(tool, block, candidate, evidence)
            met = met and not found
        if not found and not same and (best is None or gain > best[0]):
            best = (gain, candidate)
        if not found and met:
            return candidate, {"status": "rewritten", "met": True, "problems": [], "evidence": evidence, "attempts": attempts}
        problems = found or [_miss(tool, strength, block, candidate)]
        prompt = base + "\n\nYOUR PREVIOUS ANSWER WAS NOT ACCEPTED: " + "; ".join(problems) + ". Write it again and correct this."
    if best is not None:            # passed every hard check, reached the goal only in part: still an improvement
        return best[1], {"status": "rewritten", "met": False, "problems": problems[:2], "evidence": evidence, "attempts": attempts}
    fallback = rules("humanize" if tool == "formalize" else tool, rules(tool, block)) if not spec["adds"] else block
    if fallback != block and not gate(tool, strength, block, fallback, allowed=allowed, evidence=evidence, profile=profile)[0]:
        return fallback, {"status": "rules", "met": False, "problems": problems[:3], "evidence": "", "attempts": attempts}
    return block, {"status": "unchanged", "met": False, "problems": problems[:3], "evidence": "", "attempts": attempts}


def _miss(tool: str, strength: int, original: str, candidate: str) -> str:
    """Why a candidate that broke nothing still did not reach the goal — said in a way the model can act on."""
    ratio = _words(candidate) / max(1, _words(original))
    target = TOOLS[tool]["target"][strength]
    return {"condense": f"still {ratio:.0%} of the original length; about {target:.0%} is wanted, so cut further",
            "expand": f"only {ratio:.0%} of the original length; about {target:.0%} is wanted, so develop it further",
            "humanize": "too close to the original wording and rhythm; restructure the sentences as the task lists",
            "simplify": "not noticeably easier to read; shorten the long sentences and use plainer words",
            "formalize": "informal wording remains; replace it",
            "polish": "nothing was corrected",
            "add_citations": "no citation was added; attach the markers of the evidence that supports the listed statements",
            "strengthen_argument": "the claims are no more specific and the reasoning no more explicit than before"}[tool]


# ============================================================================================ the whole text
def _workable(tool: str, block: str) -> bool:
    b = block.strip()
    if not b or PLACEHOLDER.match(b) or re.match(r"^Appendix [A-Z]\.", b) or re.fullmatch(r"(?:\[\[(?:TABLE|FIGURE) \d+\]\]\s*)+", b):
        return False
    if len(b.split()) < 14 and not re.search(r"[.!?][\"”’)\]]*$", b):      # a heading or a label
        return False
    return _words(b) >= TOOLS[tool]["min_words"]


def run(tool: str, text: str, *, strength: int = 2, title: str = "", section: str = "", purpose: str = "", tone_rule: str = "", profile: dict | None = None,
        evidence_for: Callable | None = None, only_below: int | None = None, progress: Callable | None = None, on_edit: Callable | None = None) -> tuple[str, dict]:
    """Apply a tool to a text of any length. Returns the new text and a report of what happened to each paragraph."""
    spec, strength = TOOLS[tool], max(1, min(3, int(strength)))
    context = {"title": title, "section": section, "purpose": purpose, "tone_rule": tone_rule, "profile": profile or {}}
    blocks = re.split(r"(\n\s*\n)", text)
    targets = []
    for i, b in enumerate(blocks):
        if not _workable(tool, b):
            continue
        if only_below is not None:
            m = style.metrics(b.strip())
            if m.get("score") is None or m["score"] >= only_below:
                continue
        targets.append(i)
    body = [i for i, b in enumerate(blocks) if b.strip() and not PLACEHOLDER.match(b.strip())]
    report = {"tool": tool, "label": spec["label"], "strength": strength, "paragraphs": len(body), "attempted": len(targets), "rewritten": 0, "rules_only": 0,
              "kept": [], "partial": 0, "words_before": _words(text), "score_before": style.metrics(text).get("score"), "evidence": ""}
    if progress and targets:
        progress(f"{spec['label']}: working on {len(targets)} paragraph(s), each checked against the original")
    longest = max(targets, key=lambda i: _words(blocks[i])) if targets else None      # Strengthen answers one objection, in the weightiest paragraph

    source = list(blocks)      # neighbours are read from the text as it was, whatever order the paragraphs finish in

    def neighbour(i: int, step: int) -> str:
        j = i + step
        while 0 <= j < len(source) and (not source[j].strip() or PLACEHOLDER.match(source[j].strip())):
            j += step
        if not 0 <= j < len(source):
            return ""
        sents = _sentences(source[j].strip())
        return (sents[-1] if step < 0 else sents[0])[:300] if sents else ""

    def work(i: int):
        return i, rewrite_block(tool, blocks[i].strip(), strength=strength, context=context, before=neighbour(i, -1), after=neighbour(i, 1),
                                evidence_for=evidence_for, counterpoint=i == longest)

    done = 0
    evidence_seen: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, llm.runtime.capacity)) as pool:
        for i, (new, rep) in pool.map(work, targets):
            done += 1
            number = body.index(i) + 1
            if rep["status"] in {"rewritten", "rules"}:
                if on_edit:
                    on_edit(blocks[i].strip(), new)
                lead = re.match(r"\s*", blocks[i]).group(0)
                blocks[i] = lead + new
                report["rewritten" if rep["status"] == "rewritten" else "rules_only"] += 1
                report["partial"] += rep["status"] == "rewritten" and not rep["met"]
                if rep["evidence"]:
                    evidence_seen.append(rep["evidence"])
            else:
                report["kept"].append({"paragraph": number, "reasons": rep["problems"][:3]})
            if progress and len(targets) > 3 and done % max(1, len(targets) // 4) == 0 and done < len(targets):
                progress(f"{spec['label']}: {done} of {len(targets)} paragraphs done")
    out = "".join(blocks)
    old_labels, new_labels = set(_labels(text)), set(_labels(out))
    old_numbers = _numbers(text)
    report.update(
        words_after=_words(out), score_after=style.metrics(out).get("score"), evidence="\n\n".join(dict.fromkeys(evidence_seen)),
        naturalness_before=round(naturalness(text, profile)), naturalness_after=round(naturalness(out, profile)),
        reading_ease_before=round(_reading_ease(text)), reading_ease_after=round(_reading_ease(out)),
        citations_preserved=f"{len(old_labels & new_labels)}/{len(old_labels)}", citations_added=len(new_labels - old_labels),
        citation_marks_before=len(MARKER.findall(text)), citation_marks_after=len(MARKER.findall(out)),
        numbers_preserved=f"{sum(n in out for n in old_numbers)}/{len(old_numbers)}",
        uncited_before=len(uncited(text)), uncited_after=len(uncited(out)), changed=out != text,
    )
    return out, report


def summary(report: dict) -> str:
    """One line for the log and the History."""
    tool, did = report["tool"], f"{report['rewritten'] + report['rules_only']} of {report['attempted']} paragraph(s) changed"
    extra = {"condense": f"{report['words_before']} → {report['words_after']} words", "expand": f"{report['words_before']} → {report['words_after']} words",
             "humanize": f"naturalness {report['naturalness_before']} → {report['naturalness_after']}",
             "simplify": f"reading ease {report['reading_ease_before']} → {report['reading_ease_after']}",
             "add_citations": f"{report['citations_added']} source(s) newly cited · statements without a citation {report['uncited_before']} → {report['uncited_after']}",
             "strengthen_argument": f"{report['words_before']} → {report['words_after']} words"}.get(tool, "")
    return (f"{did}" + (f" · {extra}" if extra else "") + f" · citations kept {report['citations_preserved']} · numbers kept {report['numbers_preserved']}"
            + (f" · {len(report['kept'])} left as they were" if report["kept"] else ""))
