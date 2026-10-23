"""Annoncé et réalisé : chaque annonce datée relevée dans une fiche est suivie, puis revérifiée
automatiquement à son échéance (recherche ciblée, extraction, verdict sourcé)."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone

from rapidfuzz import fuzz
from sqlmodel import select

from .. import events
from ..collect import claude_search
from ..collect.rss import fold
from ..db import session
from ..models import Announcement, Run, Topic, TopicArticle, now
from .llm import LLM, RunMeter
from .material import article_block, ref
from .schemas import AnnouncementCheck

MATCH = 85
OPEN = ("a_venir", "en_retard")
RESOLVED = ("realise", "reporte", "abandonne")
GRACE_DAYS = 60  # au-delà, on cesse de revérifier
RECHECK_DAYS = 3


def due_date(value: str | None) -> date | None:
    """« 2026-12 » → 31/12/2026 ; « 2026-12-05 » → 05/12/2026 ; « 2027 » → 31/12/2027."""
    if not value:
        return None
    parts = value.strip()[:10].split("-")
    try:
        year = int(parts[0])
        month = int(parts[1]) if len(parts) > 1 else 12
        day = int(parts[2]) if len(parts) > 2 else calendar.monthrange(year, month)[1]
        return date(year, month, day)
    except (ValueError, IndexError):
        return None


def sync_from_fiche(topic_id: int, content: dict) -> list[Announcement]:
    """Ajoute les annonces nouvelles et met à jour celles déjà suivies (rapprochées par le texte)."""
    incoming = [a for a in content.get("announcements", []) if a.get("text")]
    if not incoming:
        return []
    changed = []
    with session() as s:
        existing = s.exec(select(Announcement).where(Announcement.topic_id == topic_id)).all()
        for a in incoming:
            match = max(existing, key=lambda e: fuzz.token_set_ratio(fold(e.text), fold(a["text"])), default=None)
            if match is not None and fuzz.token_set_ratio(fold(match.text), fold(a["text"])) >= MATCH:
                row = match
                row.refs = sorted(set(row.refs or []) | set(a.get("refs", [])))
                if a.get("due") and a["due"] != row.due and a.get("status") == "reporte":
                    row.due = a["due"]
                if a.get("status") in RESOLVED and row.status != a["status"]:
                    row.status, row.resolved_at = a["status"], now()
                    changed.append(row)
            else:
                row = Announcement(topic_id=topic_id, text=a["text"], due=a.get("due", ""), status=a.get("status") if a.get("status") in (*OPEN, *RESOLVED) else "a_venir", refs=a.get("refs", []))
                existing.append(row)
            s.add(row)
        s.commit()
        for r in changed:
            s.refresh(r)
    return changed


def due_for_check(today: date, limit: int) -> list[Announcement]:
    with session() as s:
        rows = s.exec(select(Announcement).where(Announcement.status.in_(OPEN))).all()
    out = []
    for a in rows:
        d = due_date(a.due)
        if d is None or d > today or (today - d).days > GRACE_DAYS:
            continue
        last = a.last_checked_at
        if last and datetime.now(timezone.utc) - last < timedelta(days=RECHECK_DAYS):
            continue
        out.append(a)
    return sorted(out, key=lambda a: due_date(a.due))[:limit]


async def check_one(llm: LLM, meter: RunMeter, model: str, announcement_id: int) -> Announcement:
    from .topic_agent import gather_articles  # import local : topic_agent importe ce module

    with session() as s:
        a = s.get(Announcement, announcement_id)
        topic = s.get(Topic, a.topic_id)
    at = now()
    since = at - timedelta(days=90)
    question = f"« {a.text} » (annonce liée au sujet « {topic.name} », prévue pour {a.due}). Cela a-t-il eu lieu, a-t-il été reporté ou abandonné ?"
    candidates = await claude_search.search(llm, meter, model, question, [a.text], since)
    found = await gather_articles(topic, topic.spec or {}, since, at, extra=candidates)
    with session() as s:
        for article, _, _ in found:
            s.merge(TopicArticle(topic_id=topic.id, article_id=article.id, origin="verification", relevance=1.0, nature="fait", kept=True, reason=f"Vérification de l'annonce : {a.text[:120]}"))
        s.commit()

    status, explanation, refs = "inconnu", "Aucun article exploitable n'a été trouvé.", []
    if found:
        material = "\n\n".join(article_block(art, src, 2000) for art, src, _ in found[:12])
        content = f"Date du jour : {at:%Y-%m-%d}\n\n<annonce echeance=\"{a.due}\">\n{a.text}\n</annonce>\n\n<articles>\n{material}\n</articles>"
        verdict = await llm.parse(meter, model=model, task="announcement_check", content=content, schema=AnnouncementCheck, effort="low", max_tokens=3000)
        valid = {ref(art.id) for art, _, _ in found}
        refs = [r for r in verdict.refs if r in valid]
        status, explanation = verdict.status, verdict.explanation
        if status in RESOLVED and not refs:  # un verdict sans source ne compte pas
            status, explanation = "inconnu", "Verdict écarté : aucune source citée."
    return apply_verdict(announcement_id, status, explanation, refs)


def apply_verdict(announcement_id: int, status: str, explanation: str, refs: list[str]) -> Announcement:
    with session() as s:
        a = s.get(Announcement, announcement_id)
        before = a.status
        a.last_checked_at = now()
        if status in RESOLVED:
            a.status, a.resolution, a.resolution_refs, a.resolved_at = status, explanation, refs, now()
        else:
            d = due_date(a.due)
            if d and d < date.today():
                a.status = "en_retard"
            a.resolution = explanation
        s.add(a)
        s.commit()
        s.refresh(a)
        topic = s.get(Topic, a.topic_id)
    if a.status != before:
        label = {"realise": "réalisée", "reporte": "reportée", "abandonne": "abandonnée", "en_retard": "en retard"}.get(a.status, a.status)
        events.publish("announcement", topic_id=a.topic_id, announcement_id=a.id, title=f"{topic.name} : annonce {label}", body=a.text)
    return a


async def check_due(llm: LLM, model: str, limit: int = 5) -> int:
    from .topic_agent import _finish

    todo = due_for_check(date.today(), limit)
    if not todo:
        return 0
    meter = RunMeter()
    with session() as s:
        run = Run(kind="announcement")
        s.add(run)
        s.commit()
        s.refresh(run)
    done = 0
    for a in todo:
        try:
            await check_one(llm, meter, model, a.id)
            done += 1
        except Exception as e:  # une vérification ratée sera retentée au prochain tic
            events.publish("warning", message=f"Vérification d'annonce impossible : {e}")
    _finish(run.id, meter, "done")
    return done

