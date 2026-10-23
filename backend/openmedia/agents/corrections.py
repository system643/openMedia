"""Journal des corrections : quand un fait déjà publié dans une fiche est démenti, contesté
ou corrigé par de nouvelles sources, le lecteur qui l'avait lu en est averti.

Le modèle propose les corrections ; ce module n'en garde que celles qui portent vraiment sur
un fait de la fiche précédente et qui citent une source nouvelle valide.
"""

from __future__ import annotations

from rapidfuzz import fuzz
from sqlmodel import select

from .. import events
from ..collect.rss import fold
from ..db import session
from ..models import Correction, Fiche, Topic, now
from .material import ref_id

MATCH = 70  # similarité minimale avec un fait de la fiche précédente


def previous_facts(previous: dict | None) -> list[dict]:
    if not previous:
        return []
    facts = [*previous.get("whats_new", []), *previous.get("key_facts", [])]
    facts += [{"text": e.get("event", ""), "status": "confirme", "refs": e.get("refs", [])} for e in previous.get("timeline", [])]
    return [f for f in facts if f.get("text")]


def _best_match(text: str, facts: list[dict]) -> tuple[dict | None, float]:
    best, score = None, 0.0
    for f in facts:
        s = fuzz.token_set_ratio(fold(text), fold(f["text"]))
        if s > score:
            best, score = f, s
    return best, score


def validate_corrections(corrections: list[dict], previous: dict | None, texts: dict[int, str]) -> list[dict]:
    """Retire les corrections sans source valide ou sans fait correspondant dans la fiche
    précédente ; reprend le texte exact du fait corrigé et son statut d'origine."""
    facts = previous_facts(previous)
    out = []
    for c in corrections:
        refs = [r for r in c.get("refs", []) if ref_id(r) in texts]
        match, score = _best_match(c.get("previous_text", ""), facts)
        if not refs or match is None or score < MATCH:
            continue
        out.append({**c, "refs": refs, "previous_text": match["text"], "previous_status": match.get("status") or c.get("previous_status", "")})
    return out


def save_corrections(topic_id: int, fiche: Fiche, previous: Fiche | None, corrections: list[dict]) -> list[Correction]:
    """Enregistre les corrections ; celles qui touchent un fait que le lecteur avait sous les
    yeux (version affichée avant sa dernière visite du sujet) donnent lieu à une notification."""
    if not corrections or previous is None:
        return []
    with session() as s:
        topic = s.get(Topic, topic_id)
        seen = topic.last_seen_at
        read = bool(seen and previous.created_at and previous.created_at <= seen)
        rows = []
        for c in corrections:
            row = Correction(
                topic_id=topic_id,
                fiche_id=fiche.id,
                version=fiche.version,
                previous_text=c["previous_text"],
                previous_status=c.get("previous_status", ""),
                new_status=c["new_status"],
                explanation=c.get("explanation", ""),
                refs=c["refs"],
                read_by_user=read,
            )
            s.add(row)
            rows.append(row)
        s.commit()
        for r in rows:
            s.refresh(r)
        name = topic.name
    for r in rows:
        if r.read_by_user:
            label = {"dementi": "démenti", "conteste": "contesté", "corrige": "corrigé"}[r.new_status]
            events.publish("correction", topic_id=topic_id, correction_id=r.id, title=f"{name} : un fait que tu as lu est {label}", body=r.previous_text)
    return rows


def unseen_count() -> int:
    with session() as s:
        return len(s.exec(select(Correction.id).where(Correction.seen_at == None)).all())  # noqa: E711


def mark_seen(ids: list[int] | None = None) -> None:
    with session() as s:
        q = select(Correction).where(Correction.seen_at == None)  # noqa: E711
        if ids:
            q = q.where(Correction.id.in_(ids))
        for c in s.exec(q).all():
            c.seen_at = now()
            s.add(c)
        s.commit()
