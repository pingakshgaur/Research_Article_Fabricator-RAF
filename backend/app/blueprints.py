"""Segment blueprints: the rules, rhetorical moves and quality checks RAF follows for each part of an article.

Each blueprint encodes established academic-writing models:
  * Introduction — Swales' CARS model (establish territory → niche → occupy niche)
  * Literature review — thematic synthesis (not source-by-source summary) ending in a gap statement
  * Methodology — replicability checklist (design, data, procedure, analysis, validity, ethics)
  * Results — report-then-interpret-nothing: numbers, tests, effect sizes, tables/figures referenced in text
  * Discussion — Hopkins & Dudley-Evans moves (restate → compare with literature → explain → implications)
  * Abstract — IMRaD micro-structure (context, aim, method, key result, conclusion) in one paragraph
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Move:
    name: str
    instruction: str
    queries: tuple[str, ...] = ()      # retrieval query templates; {title} and {topic} are substituted
    share: float = 0.25                # share of the segment's word budget


@dataclass(frozen=True)
class Blueprint:
    key: str
    title: str
    description: str
    order: int                         # generation order (dependencies first)
    display_order: int                 # position in the published article
    word_share: float                  # share of the article's target length
    moves: tuple[Move, ...] = ()
    rules: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()       # yes/no questions the critic answers
    depends_on: tuple[str, ...] = ()
    needs_evidence: bool = True
    citations: bool = True
    special: str = ""                  # handled by a dedicated builder instead of the move pipeline
    extra: dict = field(default_factory=dict)


COMMON_RULES = (
    "Write original prose in your own words. Never copy phrases of more than six consecutive words from the evidence.",
    "Synthesize: connect ideas across several sources in the same paragraph instead of summarising one source at a time.",
    "Every factual claim drawn from the evidence carries an inline citation marker such as [R3] or [W7], exactly as labelled in the evidence.",
    "Never invent statistics, sample sizes, dates, names or findings. Use only numbers that appear in the evidence or the analysis findings.",
    "Use a confident, measured scholarly voice: precise verbs, hedging where the evidence is uncertain (suggests, indicates, appears).",
    "Vary sentence length and structure naturally; mix short declarative sentences with longer analytical ones.",
    "Avoid clichés and filler such as 'delve', 'in today's fast-paced world', 'it is important to note', 'a testament to', 'plays a crucial role', 'in conclusion'.",
    "Do not use bullet points unless the blueprint asks for them. Write connected paragraphs with clear topic sentences and transitions.",
    "Do not write the section heading; RAF adds headings when it assembles the article.",
)

BLUEPRINTS: dict[str, Blueprint] = {
    "title": Blueprint(
        key="title", title="Title", order=90, display_order=0, word_share=0.0, needs_evidence=False, citations=False,
        special="title", depends_on=("introduction", "results"),
        description="Refines the working title into a precise, searchable scholarly title with optional subtitle.",
        rules=("10–20 words", "Name the core variables/phenomenon, population or context, and design where relevant",
               "No abbreviations, no question marks unless the article is genuinely exploratory", "No hype words (revolutionary, novel, groundbreaking)"),
    ),
    "abstract": Blueprint(
        key="abstract", title="Abstract", order=80, display_order=1, word_share=0.04, citations=False, special="abstract",
        depends_on=("introduction", "methodology", "results", "discussion", "conclusion"),
        description="A single structured paragraph (150–250 words): purpose, design, key findings, conclusions, value.",
        rules=("One paragraph of 180–250 words with no citations, no abbreviations left undefined",
               "Sequence: context (1 sentence) → aim → design/method → principal quantitative or thematic findings → conclusion → originality/value",
               "Report the headline numbers exactly as they appear in the Results section"),
        checks=("Does it state the purpose?", "Does it describe the method?", "Does it report concrete findings?", "Does it state implications?"),
    ),
    "keywords": Blueprint(
        key="keywords", title="Keywords", order=85, display_order=2, word_share=0.0, needs_evidence=False, citations=False,
        special="keywords", depends_on=("abstract",),
        description="5–7 indexing keywords chosen from statistically salient terms in the article and reference corpus.",
    ),
    "introduction": Blueprint(
        key="introduction", title="Introduction", order=10, display_order=3, word_share=0.13,
        description="Swales' CARS model: establish the territory, reveal the gap, state aims, questions and contribution.",
        moves=(
            Move("Establishing the territory", "Open with the real-world and scholarly significance of the topic. Show why it matters now, citing broad evidence of scale or impact.",
                 ("importance and significance of {topic}", "{title} background context", "recent developments trends {topic}"), 0.3),
            Move("Reviewing core previous work", "Briefly characterise what is already known, grouping sources that agree and noting where they diverge.",
                 ("previous studies findings {title}", "theoretical perspectives {topic}"), 0.25),
            Move("Establishing the niche", "Identify the specific gap, contradiction or unresolved problem in the literature, explaining why it is consequential.",
                 ("limitations of existing research {topic}", "gap unresolved questions {title}", "inconsistent findings {topic}"), 0.2),
            Move("Occupying the niche", "State the aim of this article, two to four research questions or objectives, the approach taken, and the contribution. Close with a one-sentence roadmap of the article structure.",
                 ("research objectives {title}",), 0.25),
        ),
        rules=("Funnel from broad to specific", "Research questions must be answerable by the methods actually used"),
        checks=("Does it establish why the topic matters with citations?", "Is a specific research gap stated?", "Are the aim and research questions explicit?", "Is the contribution stated?"),
    ),
    "literature_review": Blueprint(
        key="literature_review", title="Review of Literature", order=20, display_order=4, word_share=0.2, special="literature_review",
        description="Thematic synthesis of the reference corpus: concepts, theories, empirical streams, debates and the resulting gap.",
        moves=(
            Move("Conceptual foundations", "Define the key constructs precisely and show how different authors conceptualise them.", ("definition concept of {topic}", "theoretical framework {title}"), 0.2),
        ),
        rules=("Organise by themes, not by author", "Each theme compares, contrasts and evaluates sources", "End with a synthesis of the gap that motivates the study",
               "Where justified, derive testable propositions or hypotheses (H1, H2 …) from the reviewed evidence"),
        checks=("Is the review organised thematically?", "Does it compare and contrast sources?", "Does it critically evaluate evidence?", "Does it end with a clear gap?"),
    ),
    "methodology": Blueprint(
        key="methodology", title="Methodology", order=30, display_order=5, word_share=0.12, special="methodology", depends_on=("introduction", "literature_review"),
        description="Research design, data sources, sampling, variables, analytical procedures, validity and ethics — grounded in what RAF actually executed.",
        moves=(
            Move("Research design and philosophy", "Justify the overall design (e.g. quantitative secondary-data design, systematic literature synthesis, mixed methods) with reference to methodological literature.",
                 ("research design methodology {topic}", "methods used in studies of {title}"), 0.25),
            Move("Data sources and sample", "Describe exactly which data sources were used, coverage, units of analysis and inclusion criteria. Use only the facts provided in the ANALYSIS PROTOCOL.", (), 0.25),
            Move("Variables and measurement", "Define each variable and how it was operationalised, referencing the protocol.", ("measurement of variables {topic}",), 0.2),
            Move("Analytical procedures", "Describe each statistical or analytical procedure in the order performed and why it was chosen, including assumption checks and corrections.", (), 0.2),
            Move("Validity, reliability and ethics", "Address validity, reliability, limitations of secondary data, and ethical handling of data.", ("validity reliability secondary data research",), 0.1),
        ),
        rules=("Describe only procedures listed in the ANALYSIS PROTOCOL; never claim surveys, interviews, or experiments that did not happen",
               "Past tense, passive or first-person plural consistently", "Enough detail for replication"),
        checks=("Is the research design justified?", "Are data sources and sample described?", "Are analysis procedures described?", "Are validity or ethics addressed?"),
    ),
    "results": Blueprint(
        key="results", title="Results / Analysis", order=40, display_order=6, word_share=0.15, special="results", depends_on=("methodology",),
        description="Objective reporting of the statistical findings with integrated tables and figures; interpretation is left for the Discussion.",
        rules=("Report findings in the order of the research questions", "Every statistic comes verbatim from the ANALYSIS FINDINGS",
               "Report test statistic, p-value and effect size together", "Refer to each table and figure in the text (e.g. 'Table 1 shows…') before it appears",
               "Do not interpret causes or compare with literature here"),
        checks=("Are statistics reported with tests and p-values?", "Are tables/figures referenced in the text?", "Is interpretation avoided?"),
    ),
    "discussion": Blueprint(
        key="discussion", title="Discussion", order=50, display_order=7, word_share=0.15, depends_on=("introduction", "results"),
        description="Interprets results against the research questions and prior literature, explaining agreements, contradictions and mechanisms.",
        moves=(
            Move("Restating the principal findings", "Open by answering each research question in plain language using the key results (no new numbers).", (), 0.2),
            Move("Comparison with prior literature", "Compare each principal finding with earlier studies, stating clearly where results confirm, extend or contradict them.",
                 ("findings consistent with {topic}", "contradictory evidence {title}", "empirical results {topic}"), 0.35),
            Move("Explaining the findings", "Offer theoretically grounded explanations for the patterns, including plausible mechanisms and alternative explanations.",
                 ("theory explains mechanism {topic}", "factors influencing {title}"), 0.25),
            Move("Theoretical contribution", "State what the findings add to theory and to the scholarly conversation.", ("theoretical implications {topic}",), 0.2),
        ),
        rules=("Link every interpretive claim to either a result or a citation", "Avoid overclaiming causality from correlational evidence"),
        checks=("Are findings compared with literature?", "Are explanations offered?", "Is causality handled carefully?"),
    ),
    "conclusion": Blueprint(
        key="conclusion", title="Conclusion & Implications", order=60, display_order=8, word_share=0.07, depends_on=("introduction", "results", "discussion"),
        description="Synthesises the answer to the research problem and derives practical, policy and theoretical implications.",
        moves=(
            Move("Synthesis", "Summarise how the article addressed its aim and what it found, without repeating the abstract word for word.", (), 0.4),
            Move("Practical and policy implications", "Derive concrete, actionable implications for practitioners, managers or policymakers, each grounded in a finding.",
                 ("practical implications {topic}", "policy recommendations {title}"), 0.4),
            Move("Closing statement", "End with a forward-looking sentence on the significance of the work.", (), 0.2),
        ),
        rules=("No new data", "Implications must follow from the findings"),
        checks=("Does it answer the research aim?", "Are practical implications concrete?"),
    ),
    "limitations": Blueprint(
        key="limitations", title="Limitations & Scope for Future Research", order=70, display_order=9, word_share=0.05, depends_on=("methodology", "results"),
        description="Honest appraisal of design, data and generalisability constraints, each paired with a specific future research direction.",
        moves=(
            Move("Limitations", "Discuss the most important limitations of the design, data, measurement and generalisability, and how each might affect the conclusions.",
                 ("limitations of {topic} research",), 0.5),
            Move("Future research", "Propose specific future studies that address each limitation (designs, populations, variables, methods).",
                 ("future research directions {topic}",), 0.5),
        ),
        checks=("Is each limitation explained?", "Are future directions specific?"),
    ),
    "references": Blueprint(
        key="references", title="References", order=95, display_order=10, word_share=0.0, needs_evidence=False, citations=False, special="references",
        description="Bibliography of every uploaded reference and online source actually cited, formatted in the chosen style.",
    ),
    "appendices": Blueprint(
        key="appendices", title="Appendices", order=97, display_order=11, word_share=0.0, needs_evidence=False, citations=False, special="appendices",
        description="Supplementary material: data provenance, variable dictionary, full analysis log and the source corpus.",
    ),
}

ALL_KEYS = [b.key for b in sorted(BLUEPRINTS.values(), key=lambda b: b.display_order)]


def generation_order(keys: list[str]) -> list[str]:
    return sorted(keys, key=lambda k: BLUEPRINTS[k].order)


def catalogue() -> list[dict]:
    return [
        {"key": b.key, "title": b.title, "description": b.description, "order": b.display_order, "depends_on": list(b.depends_on)}
        for b in sorted(BLUEPRINTS.values(), key=lambda b: b.display_order)
    ]
