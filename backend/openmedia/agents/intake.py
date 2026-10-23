"""Un lien glissé dans la bulle : extraire l'article et proposer où le ranger."""

from __future__ import annotations

from sqlmodel import select

from ..collect.base import Candidate
from ..collect.dedupe import canonical_url, detect_wire, simhash
from ..collect.extract import fetch_many
from ..config import load_settings
from ..db import session
from ..models import Article, DroppedLink, Topic
from ..sources import registry
from .llm import LLM, RunMeter, get_llm
from .material import article_block, as_json
from .schemas import IntakeSuggestion


async def intake(url: str, llm: LLM | None = None) -> DroppedLink:
    settings = load_settings()
    [(cand, ex)] = await fetch_many([Candidate(url=url, title=url, origin="drop")])
    final = canonical_url(ex.url if ex else cand.url)
    with session() as s:
        article = s.exec(select(Article).where(Article.url == final)).first()
        if not article:
            text = ex.text if ex else ""
            article = Article(url=final, title=(ex.title if ex and ex.title else url)[:500], domain=registry.registered_domain(final), published_at=ex.published_at if ex else None, lang=ex.lang if ex else "", text=text, simhash=simhash(text) if text else "", wire=detect_wire(text))
            s.add(article)
            s.commit()
            s.refresh(article)
        topics = s.exec(select(Topic).where(Topic.status != "archived")).all()
    source = registry.ensure(article.domain)
    listing = [{"id": t.id, "nom": t.name, "resume": t.spec.get("summary", t.prompt[:200])} for t in topics]
    meter = RunMeter()
    try:
        llm = llm or get_llm()
        suggestion = await llm.parse(meter, model=settings.models.triage, task="intake", content=f"<sujets>\n{as_json(listing)}\n</sujets>\n\n{article_block(article, source, 2500)}", schema=IntakeSuggestion, effort="low", max_tokens=2000)
        data = suggestion.model_dump()
    except Exception as e:  # sans clé API, on propose quand même de créer un sujet
        data = {"action": "new_topic", "topic_id": None, "topic_name": article.title[:60], "prompt_draft": f"Suis l'actualité liée à : {article.title}", "reason": str(e)}
    from .topic_agent import log_run

    log_run("intake", meter)
    with session() as s:
        drop = DroppedLink(url=final, title=article.title, domain=source.name, article_id=article.id, suggestion=data)
        s.add(drop)
        s.commit()
        s.refresh(drop)
    return drop
