"""Vérifier un article, affirmation par affirmation : on extrait ce qu'il affirme, on cherche
d'autres médias sur les mêmes faits, puis la règle d'indépendance tranche. L'article lui-même
ne compte que pour une source."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from ..collect import news_search
from ..collect.dedupe import detect_wire, simhash
from ..collect.extract import fetch_many
from ..collect.base import Candidate
from ..config import load_settings
from ..db import session
from ..models import Article, Reading, Source, Topic, now
from ..sources import registry
from .llm import LLM, RunMeter, get_llm
from .material import ref
from .proof import build_proof
from .qualify import qualify_sources
from ..security import clean
from .schemas import FactcheckQueries
from .triage import triage
from .verify import verify

MAX_CLAIMS = 5
UNREADABLE = "Le texte de l'article n'a pas pu être lu (paywall ou page protégée)."
NOTHING = "Aucune affirmation factuelle vérifiable dans cet article (opinion, analyse ou texte trop court)."


async def ensure_text(article: Article) -> Article:
    """Télécharge le texte d'un article qui n'en a pas encore (titre et date au passage)."""
    if article.text:
        return article
    [(_, ex)] = await fetch_many([Candidate(url=article.url, title=article.title, origin="lecture")])
    if ex:
        with session() as s:
            a = s.get(Article, article.id)
            a.text, a.title = ex.text, ex.title or a.title
            a.published_at = a.published_at or ex.published_at
            a.simhash, a.wire = simhash(ex.text), detect_wire(ex.text)
            s.add(a)
            s.commit()
            s.refresh(a)
            return a
    return article


async def factcheck_reading(reading_id: int, llm: LLM | None = None) -> dict:
    with session() as s:
        reading = s.get(Reading, reading_id)
    meter = RunMeter()
    result, _ = await check_article(reading.article_id, llm or get_llm(), meter)
    _save(reading_id, result, meter)
    return result


async def check_article(article_id: int, llm: LLM, meter: RunMeter, *, coverage_anyway: bool = False) -> tuple[dict, list[tuple[Article, Source]]]:
    """Rend le résultat de la vérification et les articles lus, l'article vérifié en tête.
    `coverage_anyway` : chercher d'autres médias même quand l'article est illisible ou
    n'affirme rien de vérifiable (le dossier d'un enregistrement en a besoin)."""
    settings = load_settings()
    with session() as s:
        article = s.get(Article, article_id)
    article = await ensure_text(article)
    source = registry.lookup(article.domain)
    if not article.text and not coverage_anyway:
        return {"status": "illisible", "message": UNREADABLE, "claims": [], "checked_at": now().isoformat()}, []
    spec = {"summary": article.title, "angle": "Vérifier les affirmations factuelles de cet article", "keywords": [], "keep_opinions": False}

    # 1. Ce que l'article affirme
    own = await triage(llm, meter, settings.models.triage, spec, [(article, source)]) if article.text else {}
    claims = (own.get(article.id).claims if article.id in own else [])[:MAX_CLAIMS]
    if not claims and not coverage_anyway:
        return {"status": "rien", "message": NOTHING, "claims": [], "checked_at": now().isoformat()}, [(article, source)]

    # 2. D'autres médias sur les mêmes faits
    listing = clean("\n".join(f"- {c.text}" for c in claims)) or "(aucune affirmation relevée : chercher le même sujet)"
    queries = await llm.parse(meter, model=settings.models.triage, task="factcheck_queries", content=f"Titre : {clean(article.title)}\n\nAffirmations :\n{listing}", schema=FactcheckQueries, effort="low", max_tokens=2000)
    days = 45
    since = (article.published_at or now()) - timedelta(days=days)
    web = f"Trouve des articles de presse sur : {clean(article.title)}. Faits à recouper :\n{listing}" if settings.claude_search_fallback else None
    others = await find_corroboration(llm, meter, settings.models.topic, {"fr": queries.queries_fr, "en": queries.queries_en}, since, days=days, exclude={article.id}, web_prompt=web)
    await qualify_sources(llm, meter, settings.models.topic, [(article, source), *others])

    # 3. Recoupement : l'article et les autres médias, avec la règle d'indépendance
    verdicts = await triage(llm, meter, settings.models.triage, {**spec, "summary": f"{article.title}. Affirmations à recouper : {listing}"}, others[:20]) if others else {}
    kept = {i: v for i, v in verdicts.items() if v.keep and v.relevance >= 0.4}
    meta = {article.id: (article, source), **{a.id: (a, s) for a, s in others}}
    checked = []
    if claims:
        kept[article.id] = own[article.id]
        facts = await verify(llm, meter, settings.models.topic, kept, {i: meta[i] for i in kept})
        mine = ref(article.id)
        for f in facts:
            if mine not in f.refs and mine not in f.contradicted_by:
                continue  # un fait qui ne concerne pas l'article vérifié
            proof = build_proof(0, f.refs, f.contradicted_by, f.status)
            checked.append({"text": f.text, "status": f.status, "refs": f.refs, "contradicted_by": f.contradicted_by, "explanation": proof["explanation"], "independent": proof["independent"]})
    # Sans affirmation à recouper, on garde les articles que le tri juge sur le même sujet.
    related = others if claims or not verdicts else [(a, s) for a, s in others if a.id in kept]
    meta = {article.id: (article, source), **{a.id: (a, s) for a, s in related}}
    sources = [{"ref": ref(a.id), "id": a.id, "title": a.title, "url": a.url, "domain": a.domain, "name": s.name, "published_at": a.published_at.isoformat() if a.published_at else None, "country": s.country, "kind": s.kind, "owner_type": s.owner_type or "inconnu"} for a, s in meta.values()]
    status = "ok" if claims else ("illisible" if not article.text else "rien")
    result = {"status": status, "message": {"ok": None, "illisible": UNREADABLE, "rien": NOTHING}[status], "claims": checked, "sources": sources, "others": len(related), "cost_usd": round(meter.cost_usd, 4), "checked_at": now().isoformat()}
    return result, list(meta.values())


async def find_corroboration(llm: LLM, meter: RunMeter, model: str, queries: dict[str, list[str]], since: datetime, *, days: int | None = None, exclude: set[int] | None = None, web_prompt: str | None = None, limit: int = 24) -> list[tuple[Article, Source]]:
    """D'autres médias sur les mêmes faits : GDELT et Bing Actualités, puis la recherche web du
    modèle (`web_prompt`) si moins de deux groupes de presse répondent. Les articles déjà en
    base sont repris sans être retéléchargés."""
    from .topic_agent import gather_articles, select_candidates  # import local : évite un cycle

    exclude = exclude or set()
    days = days or max(1, math.ceil((now() - since).total_seconds() / 86400))
    cands = await news_search.search({lang: qs for lang, qs in queries.items() if qs}, days, per_lang=2, tries=1)
    pseudo = Topic(id=0, name="recoupement", prompt="", languages=list(queries))
    found = await gather_articles(pseudo, {}, since, now(), extra=select_candidates(cands, since, limit=limit))
    others = [(a, s) for a, s, _ in found if a.id not in exclude]
    if web_prompt and len({registry.owner_key(s) for _, s in others}) < 2:
        extra = await llm.search(meter, model=model, prompt=web_prompt)
        more = await gather_articles(pseudo, {}, since, now(), extra=[Candidate(url=r["url"], title=r.get("title") or r["url"], origin="claude_search") for r in extra])
        others += [(a, s) for a, s, _ in more if a.id not in exclude and all(a.id != o.id for o, _ in others)]
    return others


def _save(reading_id: int, result: dict, meter: RunMeter) -> None:
    from .topic_agent import log_run

    log_run("factcheck", meter)
    with session() as s:
        r = s.get(Reading, reading_id)
        r.factcheck = result
        s.add(r)
        s.commit()

