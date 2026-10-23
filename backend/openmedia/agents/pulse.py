"""Le pouls : les jours sans passage, un relevé gratuit (aucune IA) des titres de GDELT sur le
sujet. Il dit si un sujet espacé s'emballe, et avance alors son passage : espacer un
sujet calme ne fait pas rater une nouvelle importante.

Seuls les titres, médias et dates sont lus, en une requête par langue. Les comptes du jour
nourrissent aussi le rythme conseillé."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlmodel import select

from .. import events
from ..collect import gdelt
from ..collect.dedupe import same_title
from ..collect.rss import fold
from ..db import session
from ..models import Article, Topic, TopicArticle
from .rhythm import LOG_SIZE, _aware, state

MIN_TITLES = 3
MIN_MEDIA = 4
SURGE = 2.5  # fois la médiane des derniers jours
BASELINE_DAYS = 14
KEEP_DAYS = 30
KNOWN_DAYS = 30
PAUSE = 1.0  # secondes entre deux sujets : on reste discret avec Google


def _queries(topic: Topic) -> dict[str, list[str]]:
    spec = topic.spec or {}
    out = {}
    if "fr" in topic.languages and spec.get("queries_fr"):
        out["fr"] = spec["queries_fr"][:2]
    if "en" in topic.languages and spec.get("queries_en"):
        out["en"] = spec["queries_en"][:2]
    return out


def _keywords(topic: Topic) -> list[str]:
    words = [fold(k) for k in (topic.spec or {}).get("keywords", []) if len(k) >= 3]
    return words or [w for w in fold(topic.name).split() if len(w) >= 5]


def fresh_headlines(topic: Topic, cands, since: datetime, known: list[str]) -> list:
    """Les titres parus depuis `since`, qui touchent au sujet et qu'on n'a pas déjà retenus."""
    keys = _keywords(topic)
    out = []
    for c in sorted((c for c in cands if c.published_at and c.title), key=lambda c: c.published_at, reverse=True):
        if _aware(c.published_at) < since:
            continue
        title = fold(c.title)
        if keys and not any(k in title for k in keys):
            continue
        if any(same_title(c.title, k) for k in known) or any(same_title(c.title, o.title) for o in out):
            continue
        out.append(c)
    return out


def _known_titles(topic_id: int) -> list[str]:
    start = datetime.now(timezone.utc) - timedelta(days=KNOWN_DAYS)
    with session() as s:
        rows = s.exec(select(Article.title, Article.published_at).join(TopicArticle, TopicArticle.article_id == Article.id).where(TopicArticle.topic_id == topic_id)).all()
    return [t for t, p in rows if p is None or _aware(p) >= start]


def surging(titles: int, media: int, counts: dict, today: str) -> bool:
    past = [v.get("media", 0) for d, v in sorted(counts.items()) if d < today][-BASELINE_DAYS:]
    base = median(past) if past else 0
    return titles >= MIN_TITLES and media >= max(MIN_MEDIA, SURGE * base)


async def check(topic: Topic, at: datetime) -> dict | None:
    """Le relevé du jour pour un sujet (une fois par jour) ; rend {titles, media, hot, sample}."""
    st = state(topic)
    pulse = dict(st["pulse"] or {})
    today = at.date().isoformat()
    if pulse.get("day") == today:
        return None
    queries = _queries(topic)
    found = []
    if queries:
        try:
            found = await gdelt.search(queries, 1, per_lang=1)
        except Exception:  # noqa: BLE001 — hors ligne, ou GDELT limite : on réessaiera demain
            found = []
    since = _aware(topic.last_run_at) or (at - timedelta(days=1))
    fresh = fresh_headlines(topic, found, since, _known_titles(topic.id))
    media = len({c.source_name for c in fresh if c.source_name})
    counts = dict(pulse.get("counts") or {})
    hot = surging(len(fresh), media, counts, today)
    counts[today] = {"titles": len(fresh), "media": media}
    keep = (at.date() - timedelta(days=KEEP_DAYS)).isoformat()
    pulse.update(day=today, counts={d: v for d, v in counts.items() if d >= keep})
    if hot:
        pulse["advanced"] = [d for d in pulse.get("advanced", []) if d >= keep] + [today]
    with session() as s:
        t = s.get(Topic, topic.id)
        st = {**state(t), "pulse": pulse}
        if hot:
            note = {"at": datetime.now(timezone.utc).isoformat(), "from": None, "to": None, "by": "pulse", "reason": f"Passage avancé : le sujet s'emballe ({media} médias, {len(fresh)} titres nouveaux)."}
            st["log"] = [*st["log"], note][-LOG_SIZE:]
        t.rhythm = st
        s.add(t)
        s.commit()
    return {"titles": len(fresh), "media": media, "hot": hot, "sample": [c.title for c in fresh[:5]]}


def candidates(topics: list[Topic], settings, at: datetime, due: set[int]) -> list[Topic]:
    """Les sujets à relever : actifs ou en veille, déjà passés une fois, qui ne passent pas
    aujourd'hui, une fois la première heure de passage du jour arrivée."""
    from .. import scheduler

    first = min(scheduler.general(settings).hours)
    if f"{at:%H:%M}" < first:
        return []
    out = []
    for t in topics:
        if t.id in due or t.status == "archived" or t.kind == "recherche" or not t.last_run_at:
            continue
        if (state(t)["pulse"] or {}).get("day") == at.date().isoformat():
            continue
        if t.status == "active" and scheduler.cadence(t, settings).runs_on(at.date()):
            continue
        out.append(t)
    return out


async def sweep(topics: list[Topic], settings, at: datetime, due: set[int]) -> list[int]:
    """Relève le pouls des sujets qui ne passent pas aujourd'hui ; rend ceux qui s'emballent,
    dont le passage est avancé."""
    hot = []
    for n, t in enumerate(candidates(topics, settings, at, due)):
        if n:
            await asyncio.sleep(PAUSE)
        result = await check(t, at)
        if result and result["hot"]:
            hot.append(t.id)
            events.publish("rhythm", topic_id=t.id, by="pulse", message=f"« {t.name} » s'emballe ({result['media']} médias, {result['titles']} titres nouveaux) : passage avancé.")
    return hot
