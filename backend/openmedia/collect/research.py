"""Veille de recherche : les derniers articles scientifiques, jugés sur leur titre et leur
résumé (les papiers complets sont trop longs). Sources ouvertes, sans clé :

- arXiv (prépublications : informatique, IA, physique, maths, biologie quantitative, économie)
- OpenAlex (index mondial des publications, revues comprises)
- PubMed (biologie, médecine)
- bioRxiv / medRxiv (prépublications en biologie et en médecine)
- HAL (archive ouverte de la recherche française)
"""

from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import feedparser

from .base import Candidate, client, parse_date
from .rss import matches

# Domaines proposés au lecteur, et les sources ou catégories qui les couvrent.
FIELDS = {
    "ia": {"label": "Intelligence artificielle", "arxiv": ["cs.AI", "cs.LG", "cs.CL", "cs.CV", "stat.ML"], "pubmed": False},
    "informatique": {"label": "Informatique", "arxiv": ["cs.*"], "pubmed": False},
    "biologie": {"label": "Biologie", "arxiv": ["q-bio.*"], "pubmed": True, "biorxiv": "biorxiv"},
    "medecine": {"label": "Médecine et santé", "arxiv": [], "pubmed": True, "biorxiv": "medrxiv"},
    "physique": {"label": "Physique", "arxiv": ["physics.*", "cond-mat.*", "quant-ph", "astro-ph.*"], "pubmed": False},
    "maths": {"label": "Mathématiques", "arxiv": ["math.*"], "pubmed": False},
    "climat": {"label": "Climat et environnement", "arxiv": ["physics.ao-ph", "physics.geo-ph"], "pubmed": False},
    "economie": {"label": "Économie", "arxiv": ["econ.*", "q-fin.*"], "pubmed": False},
    "sciences_sociales": {"label": "Sciences sociales", "arxiv": ["cs.CY", "physics.soc-ph"], "pubmed": False},
}

RESEARCH_DOMAINS = {"arxiv.org", "openalex.org", "doi.org", "ncbi.nlm.nih.gov", "biorxiv.org", "medrxiv.org", "archives-ouvertes.fr", "hal.science"}
_SPACES = re.compile(r"\s+")


def _clean(text: str | None) -> str:
    return _SPACES.sub(" ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def _paper(url: str, title: str, abstract: str, published, venue: str, origin: str, authors: list[str], preprint: bool, doi: str = "") -> Candidate:
    return Candidate(
        url=url,
        title=_clean(title),
        origin=origin,
        source_name=venue,
        published_at=parse_date(published),
        snippet=_clean(abstract)[:4000],
        extra={"authors": authors[:8], "venue": venue, "preprint": preprint, "doi": doi, "research": True},
    )


# ── arXiv ────────────────────────────────────────────────────────────────────


def arxiv_url(query: str, categories: list[str], max_results: int = 40) -> str:
    q = f'all:"{query}"' if " " in query else f"all:{query}"
    if categories:
        q = f"({q}) AND ({' OR '.join(f'cat:{c}' for c in categories)})"
    return "http://export.arxiv.org/api/query?" + urlencode({"search_query": q, "sortBy": "submittedDate", "sortOrder": "descending", "max_results": max_results})


def parse_arxiv(xml: str) -> list[Candidate]:
    out = []
    for e in feedparser.parse(xml).entries:
        cat = getattr(e, "arxiv_primary_category", {}).get("term", "") if hasattr(e, "arxiv_primary_category") else ""
        out.append(_paper(e.get("id", "").replace("http://", "https://"), e.get("title", ""), e.get("summary", ""), e.get("published"), f"arXiv {cat}".strip(), "arxiv", [a.get("name", "") for a in e.get("authors", [])], True, e.get("arxiv_doi", "")))
    return [c for c in out if c.url and c.title]


# ── OpenAlex ─────────────────────────────────────────────────────────────────


def _abstract(inverted: dict | None) -> str:
    if not inverted:
        return ""
    words = sorted((pos, w) for w, positions in inverted.items() for pos in positions)
    return " ".join(w for _, w in words)


def openalex_url(query: str, since: datetime, per_page: int = 40) -> str:
    return "https://api.openalex.org/works?" + urlencode({"search": query, "filter": f"from_publication_date:{since:%Y-%m-%d},has_abstract:true", "sort": "publication_date:desc", "per-page": per_page})


def parse_openalex(payload: dict) -> list[Candidate]:
    out = []
    for w in payload.get("results", []):
        loc = w.get("primary_location") or {}
        venue = ((loc.get("source") or {}).get("display_name")) or "OpenAlex"
        url = loc.get("landing_page_url") or w.get("doi") or w.get("id", "")
        preprint = (loc.get("version") == "submittedVersion") or (w.get("type") == "preprint")
        authors = [(a.get("author") or {}).get("display_name", "") for a in w.get("authorships", [])]
        out.append(_paper(url, w.get("title") or "", _abstract(w.get("abstract_inverted_index")), w.get("publication_date"), venue, "openalex", authors, preprint, w.get("doi") or ""))
    return [c for c in out if c.url and c.title]


# ── PubMed ───────────────────────────────────────────────────────────────────

_PM_ARTICLE = re.compile(r"<PubmedArticle>.*?</PubmedArticle>", re.S)


def _tag(xml: str, name: str) -> str:
    m = re.search(rf"<{name}[^>]*>(.*?)</{name}>", xml, re.S)
    return m.group(1) if m else ""


def parse_pubmed(xml: str) -> list[Candidate]:
    out = []
    for block in _PM_ARTICLE.findall(xml):
        pmid = _tag(block, "PMID")
        abstract = " ".join(re.findall(r"<AbstractText[^>]*>(.*?)</AbstractText>", block, re.S))
        date = _tag(block, "PubDate")
        year, month, day = _tag(date, "Year") or "1900", _tag(date, "Month") or "01", _tag(date, "Day") or "01"
        try:
            month = month if month.isdigit() else str(datetime.strptime(month[:3], "%b").month)
            published = f"{year}-{int(month):02d}-{int(day):02d}"
        except ValueError:
            published = f"{year}-01-01"
        authors = [f"{_tag(a, 'ForeName')} {_tag(a, 'LastName')}".strip() for a in re.findall(r"<Author[ >].*?</Author>", block, re.S)]
        out.append(_paper(f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", _tag(block, "ArticleTitle"), abstract, published, _clean(_tag(block, "Title")) or "PubMed", "pubmed", authors, False))
    return [c for c in out if c.title and c.snippet]


# ── bioRxiv / medRxiv ────────────────────────────────────────────────────────


def parse_biorxiv(payload: dict, server: str, keywords: list[str]) -> list[Candidate]:
    out = []
    for p in payload.get("collection", []):
        text = f"{p.get('title', '')} {p.get('abstract', '')}"
        if not matches(text, keywords):
            continue
        out.append(_paper(f"https://www.{server}.org/content/{p.get('doi')}", p.get("title", ""), p.get("abstract", ""), p.get("date"), server, server, (p.get("authors") or "").split("; "), True, p.get("doi", "")))
    return out


# ── HAL ──────────────────────────────────────────────────────────────────────


def hal_url(query: str, days: int) -> str:
    return "https://api.archives-ouvertes.fr/search/?" + urlencode({"q": query, "fq": f"producedDate_tdate:[NOW-{days}DAYS TO NOW]", "fl": "title_s,abstract_s,uri_s,producedDate_tdate,journalTitle_s,authFullName_s,docType_s", "rows": 30, "sort": "producedDate_tdate desc", "wt": "json"})


def parse_hal(payload: dict) -> list[Candidate]:
    out = []
    for d in (payload.get("response") or {}).get("docs", []):
        title = (d.get("title_s") or [""])[0]
        abstract = (d.get("abstract_s") or [""])[0]
        if not abstract:
            continue
        out.append(_paper(d.get("uri_s", ""), title, abstract, d.get("producedDate_tdate"), d.get("journalTitle_s") or "HAL", "hal", d.get("authFullName_s") or [], d.get("docType_s") in ("UNDEFINED", "PREPRINT")))
    return [c for c in out if c.url]


# ── Collecte ─────────────────────────────────────────────────────────────────


async def collect(fields: list[str], queries: list[str], keywords: list[str], since: datetime) -> list[Candidate]:
    days = max(1, (datetime.now(timezone.utc) - since).days + 1)
    cats = sorted({c for f in fields for c in FIELDS.get(f, {}).get("arxiv", [])})
    pubmed = any(FIELDS.get(f, {}).get("pubmed") for f in fields)
    biorxiv = sorted({FIELDS[f]["biorxiv"] for f in fields if FIELDS.get(f, {}).get("biorxiv")})
    out: list[Candidate] = []
    async with client(timeout=30) as http:

        async def get(url: str, kind: str):
            try:
                r = await http.get(url)
                if r.status_code != 200:
                    return []
                if kind == "arxiv":
                    return parse_arxiv(r.text)
                if kind == "openalex":
                    return parse_openalex(r.json())
                if kind == "hal":
                    return parse_hal(r.json())
            except Exception:
                return []
            return []

        jobs = []
        for q in queries[:3]:
            if cats or not fields:
                jobs.append(get(arxiv_url(q, cats), "arxiv"))
            jobs.append(get(openalex_url(q, since), "openalex"))
            jobs.append(get(hal_url(q, days), "hal"))
        for chunk in await asyncio.gather(*jobs):
            out += chunk

        if pubmed:
            for q in queries[:2]:
                try:
                    r = await http.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?" + urlencode({"db": "pubmed", "term": q, "reldate": days, "datetype": "pdat", "retmode": "json", "retmax": 30}))
                    ids = r.json().get("esearchresult", {}).get("idlist", [])
                    if ids:
                        r = await http.get("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?" + urlencode({"db": "pubmed", "id": ",".join(ids), "retmode": "xml"}))
                        out += parse_pubmed(r.text)
                except Exception:
                    pass
                await asyncio.sleep(0.4)  # NCBI : trois requêtes par seconde au plus sans clé

        for server in biorxiv:
            start = (datetime.now(timezone.utc) - timedelta(days=min(days, 14))).strftime("%Y-%m-%d")
            end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            for cursor in (0, 100, 200):
                try:
                    r = await http.get(f"https://api.biorxiv.org/details/{server}/{start}/{end}/{cursor}")
                    out += parse_biorxiv(r.json(), server, keywords or queries)
                except Exception:
                    break
    horizon = datetime.now(timezone.utc) + timedelta(days=2)  # certaines revues annoncent des dates futures
    return [c for c in out if not c.published_at or (since - timedelta(days=1) <= c.published_at <= horizon)]


def field_options() -> list[dict]:
    return [{"id": k, "label": v["label"]} for k, v in FIELDS.items()]

