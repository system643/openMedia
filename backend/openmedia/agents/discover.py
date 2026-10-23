"""« Découvrir » : les histoires à la une des médias (`collect/fronts`), regroupées et proposées au suivi."""

from __future__ import annotations

import time

from sqlmodel import select

from ..collect import fronts
from ..config import load_settings
from ..db import session
from ..models import Topic
from .llm import LLM, RunMeter, get_llm
from .material import as_json
from .schemas import DiscoverResult

_cache: dict = {"at": 0.0, "data": None}
TTL = 3600


async def discover(llm: LLM | None = None, force: bool = False) -> dict:
    settings = load_settings()
    # Une option : les titres à la une et les noms des sujets suivis partent à l'IA.
    if not settings.discover_enabled:
        return {"stories": [], "generated_at": None, "disabled": "option"}
    if not force and _cache["data"] and time.time() - _cache["at"] < TTL:
        return _cache["data"]
    from ..config import require_consent

    require_consent()  # les unes sont lues sur Internet : pas avant l'accord
    heads = await fronts.headlines(settings.languages)
    seen, unique = set(), []
    for h in heads:
        if h.title.lower() not in seen:
            seen.add(h.title.lower())
            unique.append(h)
    unique = unique[:220]
    with session() as s:
        topics = [{"id": t.id, "nom": t.name} for t in s.exec(select(Topic).where(Topic.status != "archived")).all()]
    lines = [{"i": i, "media": h.source_name, "titre": h.title} for i, h in enumerate(unique)]
    llm = llm or get_llm()
    meter = RunMeter()
    try:
        result = await llm.parse(meter, model=settings.models.triage, task="discover", content=f"<sujets_suivis>\n{as_json(topics)}\n</sujets_suivis>\n\n<titres>\n{as_json(lines)}\n</titres>", schema=DiscoverResult, effort="low", max_tokens=8000)
    finally:
        from .topic_agent import log_run

        log_run("discover", meter)
    stories = []
    for story in result.stories:
        items = [unique[i] for i in story.refs if 0 <= i < len(unique)]
        media = sorted({h.source_name for h in items if h.source_name})
        stories.append({**story.model_dump(), "size": len(media), "sources": media[:8]})
    data = {"stories": stories, "generated_at": time.time()}
    _cache.update(at=time.time(), data=data)
    return data
