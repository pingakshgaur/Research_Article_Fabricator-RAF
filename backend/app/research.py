"""Online research across disciplines. Every source tries its dedicated Python library first and falls
back to the public REST endpoint via httpx, so a missing or broken package never stops the pipeline.

Sources (all key-free):
  OpenAlex (all fields) · Crossref (all fields) · Semantic Scholar (all fields) · arXiv (STEM, econ)
  PubMed/NCBI (health, life sciences) · Europe PMC (biomedical) · DOAJ (open-access, humanities & social)
  Wikipedia (background) · DuckDuckGo web search + trafilatura/BeautifulSoup page extraction
"""
from __future__ import annotations

import html
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import httpx

from .config import settings
from .models import WebSource

log = logging.getLogger("raf.research")
UA = {"User-Agent": f"RAF-Research-Article-Fabricator/1.0 (mailto:{settings.contact_email})"}
N = settings.research_results_per_source


def _client() -> httpx.Client:
    return httpx.Client(timeout=settings.http_timeout, headers=UA, follow_redirects=True)


def _strip_tags(text: str | None) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).strip()


def _abstract_from_inverted(inv: dict | None) -> str:
    if not inv:
        return ""
    positions = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in positions)


# ------------------------------------------------------------------ scholarly sources
def openalex(query: str) -> list[WebSource]:
    try:
        import pyalex

        pyalex.config.email = settings.contact_email
        works = pyalex.Works().search(query).filter(has_abstract=True).get(per_page=N)
    except Exception:  # noqa: BLE001 - library missing or failed: use REST
        with _client() as c:
            r = c.get("https://api.openalex.org/works", params={"search": query, "per-page": N, "filter": "has_abstract:true", "mailto": settings.contact_email})
            r.raise_for_status()
            works = r.json().get("results", [])
    out = []
    for w in works:
        out.append(
            WebSource(
                source="openalex",
                title=w.get("title") or w.get("display_name") or "",
                url=(w.get("primary_location") or {}).get("landing_page_url") or w.get("id", ""),
                authors=[a["author"]["display_name"] for a in (w.get("authorships") or [])[:8] if a.get("author")],
                year=str(w.get("publication_year") or ""),
                venue=(((w.get("primary_location") or {}).get("source") or {}) or {}).get("display_name") or "",
                doi=(w.get("doi") or "").replace("https://doi.org/", ""),
                abstract=_abstract_from_inverted(w.get("abstract_inverted_index")),
            )
        )
    return out


def crossref(query: str) -> list[WebSource]:
    try:
        from habanero import Crossref

        items = Crossref(mailto=settings.contact_email).works(query=query, limit=N, filter={"has-abstract": True})["message"]["items"]
    except Exception:  # noqa: BLE001
        with _client() as c:
            r = c.get("https://api.crossref.org/works", params={"query": query, "rows": N, "filter": "has-abstract:true", "mailto": settings.contact_email})
            r.raise_for_status()
            items = r.json()["message"]["items"]
    out = []
    for it in items:
        year = ""
        for key in ("published-print", "published-online", "issued"):
            parts = (it.get(key) or {}).get("date-parts") or [[None]]
            if parts[0] and parts[0][0]:
                year = str(parts[0][0])
                break
        out.append(
            WebSource(
                source="crossref",
                title=" ".join(it.get("title") or [""]),
                url=it.get("URL", ""),
                authors=[f"{a.get('family', '')}, {a.get('given', '')}".strip(", ") for a in (it.get("author") or [])[:8]],
                year=year,
                venue=" ".join(it.get("container-title") or []),
                doi=it.get("DOI", ""),
                abstract=_strip_tags(it.get("abstract")),
            )
        )
    return out


def semantic_scholar(query: str) -> list[WebSource]:
    fields = "title,abstract,year,venue,authors,externalIds,url"
    # REST first with a single short retry: the client library retries 429s for minutes, which stalled whole runs.
    with _client() as c:
        r = c.get("https://api.semanticscholar.org/graph/v1/paper/search", params={"query": query, "limit": N, "fields": fields})
        if r.status_code == 429:
            time.sleep(3)
            r = c.get("https://api.semanticscholar.org/graph/v1/paper/search", params={"query": query, "limit": N, "fields": fields})
    if r.status_code == 429:
        r.raise_for_status()  # lets the circuit breaker in research() skip this source for the rest of the run
    if r.status_code == 200:
        papers = r.json().get("data", [])
    else:
        from semanticscholar import SemanticScholar

        results = SemanticScholar(timeout=settings.http_timeout, retry=False).search_paper(query, limit=N, fields=fields.split(","))
        papers = [p.raw_data for p in list(results)[:N]]
    return [
        WebSource(
            source="semanticscholar",
            title=p.get("title") or "",
            url=p.get("url") or "",
            authors=[a.get("name", "") for a in (p.get("authors") or [])[:8]],
            year=str(p.get("year") or ""),
            venue=p.get("venue") or "",
            doi=(p.get("externalIds") or {}).get("DOI", "") or "",
            abstract=p.get("abstract") or "",
        )
        for p in papers
        if p.get("abstract")
    ]


def arxiv_search(query: str) -> list[WebSource]:
    # arXiv needs explicit boolean syntax; a bare phrase matches almost nothing.
    terms = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{2,}", query) if w.lower() not in {"the", "and", "for", "with", "from", "into", "among"}][:5]
    search = " AND ".join(f"all:{t}" for t in terms) or f"all:{query}"
    try:
        import feedparser

        with httpx.Client(timeout=settings.http_timeout, headers=UA, follow_redirects=True) as c:
            r = c.get("https://export.arxiv.org/api/query", params={"search_query": search, "max_results": N, "sortBy": "relevance"})
            r.raise_for_status()
        feed = feedparser.parse(r.text)
        return [
            WebSource(source="arxiv", title=" ".join(e.title.split()), url=e.link, authors=[a.name for a in e.get("authors", [])[:8]],
                      year=e.get("published", "")[:4], venue="arXiv", doi=e.get("arxiv_doi", ""), abstract=" ".join(e.get("summary", "").split()))
            for e in feed.entries
        ]
    except Exception:  # noqa: BLE001 - fall back to the arxiv client library
        import arxiv

        results = list(arxiv.Client(num_retries=1, delay_seconds=1).results(arxiv.Search(query=search, max_results=N)))
        return [
            WebSource(source="arxiv", title=r.title, url=r.entry_id, authors=[a.name for a in r.authors[:8]],
                      year=str(r.published.year), venue="arXiv", doi=r.doi or "", abstract=r.summary.replace("\n", " "))
            for r in results
        ]


def pubmed(query: str) -> list[WebSource]:
    try:
        from Bio import Entrez, Medline

        Entrez.email = settings.contact_email
        ids = Entrez.read(Entrez.esearch(db="pubmed", term=query, retmax=N))["IdList"]
        if not ids:
            return []
        records = list(Medline.parse(Entrez.efetch(db="pubmed", id=",".join(ids), rettype="medline", retmode="text")))
        return [
            WebSource(source="pubmed", title=rec.get("TI", ""), url=f"https://pubmed.ncbi.nlm.nih.gov/{rec.get('PMID', '')}/",
                      authors=rec.get("AU", [])[:8], year=rec.get("DP", "")[:4], venue=rec.get("JT", ""),
                      doi=next((x.split(" ")[0] for x in rec.get("AID", []) if "[doi]" in x), ""), abstract=rec.get("AB", ""))
            for rec in records
            if rec.get("AB")
        ]
    except Exception:  # noqa: BLE001
        return europe_pmc(query)


def europe_pmc(query: str) -> list[WebSource]:
    with _client() as c:
        r = c.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                  params={"query": query, "format": "json", "pageSize": N, "resultType": "core"})
        r.raise_for_status()
        items = r.json().get("resultList", {}).get("result", [])
    return [
        WebSource(source="europepmc", title=i.get("title", ""), url=f"https://europepmc.org/article/{i.get('source')}/{i.get('id')}",
                  authors=[a.strip() for a in (i.get("authorString") or "").split(",")[:8]], year=str(i.get("pubYear", "")),
                  venue=(i.get("journalInfo") or {}).get("journal", {}).get("title", ""), doi=i.get("doi", ""),
                  abstract=_strip_tags(i.get("abstractText")))
        for i in items
        if i.get("abstractText")
    ]


def doaj(query: str) -> list[WebSource]:
    with _client() as c:
        r = c.get(f"https://doaj.org/api/search/articles/{httpx.QueryParams({'q': query})['q']}", params={"pageSize": N})
        r.raise_for_status()
        items = r.json().get("results", [])
    out = []
    for it in items:
        b = it.get("bibjson", {})
        out.append(
            WebSource(source="doaj", title=b.get("title", ""), url=next((l.get("url") for l in b.get("link", [])), ""),
                      authors=[a.get("name", "") for a in b.get("author", [])[:8]], year=str(b.get("year", "")),
                      venue=(b.get("journal") or {}).get("title", ""),
                      doi=next((i.get("id") for i in b.get("identifier", []) if i.get("type") == "doi"), ""),
                      abstract=_strip_tags(b.get("abstract")))
        )
    return [o for o in out if o.abstract]


# ------------------------------------------------------------------ general knowledge & web
def wikipedia(query: str) -> list[WebSource]:
    with _client() as c:
        r = c.get("https://en.wikipedia.org/w/api.php", params={"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 2})
        titles = [s["title"] for s in r.json().get("query", {}).get("search", [])]
    out = []
    for title in titles:
        text = ""
        try:
            import wikipediaapi

            page = wikipediaapi.Wikipedia(user_agent=UA["User-Agent"], language="en").page(title)
            text = page.summary if page.exists() else ""
        except Exception:  # noqa: BLE001
            with _client() as c:
                r = c.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}")
                text = r.json().get("extract", "") if r.status_code == 200 else ""
        if text:
            out.append(WebSource(source="wikipedia", title=title, url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                                 venue="Wikipedia", abstract=text[:4000]))
    return out


def web_search(query: str) -> list[WebSource]:
    hits: list[dict] = []
    try:
        from ddgs import DDGS

        hits = list(DDGS().text(query, max_results=N))
    except Exception:  # noqa: BLE001
        try:
            from bs4 import BeautifulSoup

            with _client() as c:
                r = c.post("https://html.duckduckgo.com/html/", data={"q": query})
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.select("a.result__a")[:N]:
                hits.append({"title": a.get_text(" ", strip=True), "href": a.get("href", ""), "body": ""})
        except Exception as exc:  # noqa: BLE001
            log.info("web search unavailable: %s", exc)
    hits = [h for h in hits if (h.get("href") or h.get("url")) and not any(
        bad in (h.get("href") or h.get("url")) for bad in ("youtube.com", "facebook.com", "instagram.com", "tiktok.com", "pinterest."))]
    out = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        bodies = list(pool.map(lambda h: fetch_page_text(h.get("href") or h.get("url")), hits))
    for h, body in zip(hits, bodies):
        url = h.get("href") or h.get("url")
        body = body or h.get("body", "")
        if len(body) > 300:
            out.append(WebSource(source="web", title=h.get("title", url), url=url, abstract=body[:6000]))
    return out


def fetch_page_text(url: str) -> str:
    """Download once with a strict timeout, then extract with trafilatura (BeautifulSoup as fallback)."""
    try:
        with httpx.Client(timeout=12, headers={**UA, "Accept": "text/html"}, follow_redirects=True) as c:
            r = c.get(url)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return ""
        html_text = r.text
    except Exception:  # noqa: BLE001
        return ""
    try:
        import trafilatura

        text = trafilatura.extract(html_text, include_comments=False, include_tables=False)
        if text:
            return text
    except Exception:  # noqa: BLE001
        pass
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()
        paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        return "\n\n".join(p for p in paras if len(p) > 60)
    except Exception:  # noqa: BLE001
        return ""


SOURCES: dict[str, Callable[[str], list[WebSource]]] = {
    "openalex": openalex,
    "crossref": crossref,
    "semanticscholar": semantic_scholar,
    "arxiv": arxiv_search,
    "pubmed": pubmed,
    "doaj": doaj,
    "wikipedia": wikipedia,
    "web": web_search,
}

# Which sources matter for which broad discipline. Unknown disciplines use all of them.
DISCIPLINE_ROUTING = {
    "health": ["openalex", "pubmed", "crossref", "semanticscholar", "wikipedia", "web"],
    "life": ["openalex", "pubmed", "crossref", "semanticscholar", "arxiv", "wikipedia"],
    "stem": ["openalex", "arxiv", "semanticscholar", "crossref", "wikipedia", "web"],
    "social": ["openalex", "crossref", "doaj", "semanticscholar", "wikipedia", "web"],
    "business": ["openalex", "crossref", "doaj", "semanticscholar", "web", "wikipedia"],
    "humanities": ["openalex", "doaj", "crossref", "wikipedia", "web"],
}


def route(discipline: str) -> list[str]:
    d = discipline.lower()
    table = {
        "health": ("medic", "health", "nurs", "clinic", "pharma", "public health", "epidem", "psychiat"),
        "life": ("bio", "ecolog", "genet", "agri", "environment", "zoolog", "botan"),
        "stem": ("comput", "engineer", "physic", "math", "statist", "chem", "data", "ai", "machine"),
        "social": ("sociol", "psycholog", "educat", "politic", "law", "anthrop", "geograph", "social"),
        "business": ("business", "manage", "market", "financ", "econom", "account", "commerce", "hrm", "tourism"),
        "humanities": ("history", "philosoph", "literat", "linguist", "art", "music", "religio", "cultur"),
    }
    for group, stems in table.items():
        if any(s in d for s in stems):
            return DISCIPLINE_ROUTING[group]
    return list(SOURCES)


# Polite per-source spacing (seconds between requests). arXiv asks for 3 s; Semantic Scholar's shared pool is tight.
THROTTLE = {"arxiv": 3.2, "semanticscholar": 1.5, "pubmed": 0.4, "wikipedia": 0.2, "web": 1.0}
_throttle_state: dict[str, tuple[threading.Lock, list[float]]] = {s: (threading.Lock(), [0.0]) for s in THROTTLE}


RATE_LIMIT_COOLDOWN = 600  # seconds a source is skipped after it answers "429 Too Many Requests"
_blocked_until: dict[str, float] = {}


class SourceSkipped(RuntimeError):
    pass


def _throttled(source: str, query: str) -> list[WebSource]:
    if time.monotonic() < _blocked_until.get(source, 0):
        raise SourceSkipped("rate-limited earlier in this run")
    if source in _throttle_state:
        lock, last = _throttle_state[source]
        with lock:
            wait = THROTTLE[source] - (time.monotonic() - last[0])
            if wait > 0:
                time.sleep(wait)
            last[0] = time.monotonic()
    try:
        return SOURCES[source](query)
    except Exception as exc:
        if "429" in str(exc) or getattr(getattr(exc, "response", None), "status_code", None) == 429:
            _blocked_until[source] = time.monotonic() + RATE_LIMIT_COOLDOWN
            raise SourceSkipped("rate limit reached (HTTP 429); skipping this source for 10 minutes") from exc
        raise


def research(queries: list[str], discipline: str, progress: Callable[[str], None] | None = None) -> list[WebSource]:
    """Run every query against every routed source in parallel; de-duplicate by DOI/title."""
    sources = route(discipline)
    jobs = [(q, s) for q in queries for s in sources]
    found: list[WebSource] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_throttled, s, q): (q, s) for q, s in jobs}
        for fut in as_completed(futures):
            q, s = futures[fut]
            try:
                res = fut.result()
                found.extend(res)
                if progress:
                    progress(f"{s}: {len(res)} result(s) for “{q[:60]}”")
            except Exception as exc:  # noqa: BLE001
                log.info("source %s failed for %r: %s", s, q, exc)
                if progress and not (isinstance(exc, SourceSkipped) and str(exc).startswith("rate-limited earlier")):
                    reason = str(exc) if isinstance(exc, SourceSkipped) else type(exc).__name__
                    progress(f"{s}: unavailable ({reason}), continuing with other sources")
    seen, unique = set(), []
    for w in found:
        key = (w.doi or re.sub(r"\W+", "", w.title.lower()))[:120]
        if not key or key in seen or len(w.abstract) < 150:
            continue
        seen.add(key)
        unique.append(w)
    return unique
