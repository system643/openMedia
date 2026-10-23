"""Recherche dans le journal : sujets, faits des dernières fiches (avec leur statut), articles.
Partagée par la palette de l'interface (Ctrl+K) et le serveur MCP."""

from __future__ import annotations

from sqlmodel import select

from ..collect.rss import fold
from ..db import session
from ..models import Article, Fiche, Topic


def _words(query: str) -> list[str]:
    return [w for w in fold(query).split() if len(w) > 1]


def search(query: str, limit: int = 20) -> dict:
    words = _words(query)
    if not words:
        return {"topics": [], "facts": [], "articles": []}
    match = lambda text: all(w in fold(text or "") for w in words)  # noqa: E731

    with session() as s:
        topics = s.exec(select(Topic).where(Topic.status != "archived")).all()
        latest = {}
        for t in topics:
            f = s.exec(select(Fiche).where(Fiche.topic_id == t.id).order_by(Fiche.version.desc())).first()
            if f:
                latest[t.id] = f
        articles = s.exec(select(Article).order_by(Article.published_at.desc()).limit(3000)).all()

    found_topics = [{"id": t.id, "name": t.name, "status": t.status} for t in topics if match(f"{t.name} {t.prompt} {(t.spec or {}).get('summary', '')}")]
    facts = []
    for t in topics:
        f = latest.get(t.id)
        if not f:
            continue
        sources = {x["ref"]: x for x in f.sources}
        for key in ("whats_new", "key_facts", "timeline"):
            for item in f.content.get(key, []):
                text = item.get("text") or item.get("event", "")
                if match(text):
                    facts.append({"topic_id": t.id, "topic": t.name, "text": text, "status": item.get("status", "confirme" if key == "timeline" else ""), "refs": item.get("refs", []), "sources": [sources[r]["name"] for r in item.get("refs", []) if r in sources]})
    found_articles = [{"id": a.id, "title": a.title, "url": a.url, "domain": a.domain, "published_at": a.published_at} for a in articles if match(a.title)][:limit]
    return {"topics": found_topics[:limit], "facts": facts[:limit], "articles": found_articles}
