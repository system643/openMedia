"""Le Directeur de rédaction : relit les fiches du jour et rédige Le Brief."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import select

from .. import events
from ..config import load_settings
from ..db import session
from ..models import Brief, Fiche, Run, Topic, now
from .llm import LLM, RunMeter, get_llm
from .material import as_json
from .schemas import BriefContent
from .topic_agent import _finish


def latest_fiches(since: datetime) -> list[tuple[Topic, Fiche]]:
    with session() as s:
        topics = s.exec(select(Topic).where(Topic.status != "archived")).all()
        out = []
        for t in topics:
            f = s.exec(select(Fiche).where(Fiche.topic_id == t.id).order_by(Fiche.version.desc())).first()
            if f and f.created_at.replace(tzinfo=since.tzinfo) >= since:
                out.append((t, f))
    return out


async def run_director(llm: LLM | None = None, day: str | None = None) -> Brief | None:
    settings = load_settings()
    llm = llm or get_llm()
    meter = RunMeter()
    at = now()
    day = day or f"{datetime.now():%Y-%m-%d}"
    pairs = latest_fiches(at - timedelta(hours=26))
    if not pairs:
        return None
    with session() as s:
        run = Run(kind="director")
        s.add(run)
        s.commit()
        s.refresh(run)
    if all(f.nothing_new and not f.content.get("whats_new") for _, f in pairs):
        # Rien de neuf nulle part : rien à hiérarchiser, donc pas d'appel au modèle.
        names = [t.name for t, _ in pairs]
        quiet = BriefContent(headline="Rien de neuf aujourd'hui sur tes sujets", points=[], cross_links=[], quiet_topics=names, audio_script=f"Bonjour. Aucune nouveauté aujourd'hui sur tes sujets : {', '.join(names)}. À demain.")
        with session() as s:
            row = Brief(day=day, content=quiet.model_dump(), run_id=run.id)
            s.add(row)
            s.commit()
            s.refresh(row)
        meter.note("rien de neuf : Brief écrit par le programme, sans appel au modèle")
        _finish(run.id, meter, "done")
        events.publish("brief", brief_id=row.id, day=day, headline=quiet.headline)
        return row
    events.publish("run", run_id=run.id, stage="director", message=f"Le Directeur relit {len(pairs)} fiche(s)")
    material = [
        {
            "topic_id": t.id,
            "sujet": t.name,
            "importance_pour_le_lecteur": t.importance,
            "etat": f.content.get("state"),
            "rien_de_neuf": f.nothing_new,
            "chapeau": f.content.get("lede"),
            "nouveautes": [{"fait": i["text"], "statut": i["status"]} for i in f.content.get("whats_new", [])],
            "importance_des_nouveautes": f.content.get("importance"),
            "a_surveiller": f.content.get("watch", [])[:3],
        }
        for t, f in pairs
    ]
    try:
        brief = await llm.parse(meter, model=settings.models.director, task="director", content=f"Date : {day}\n\n<fiches>\n{as_json(material)}\n</fiches>", schema=BriefContent, effort="high", max_tokens=12000)
    except Exception as e:
        _finish(run.id, meter, "error", str(e))
        raise
    with session() as s:
        row = Brief(day=day, content=brief.model_dump(), run_id=run.id)
        s.add(row)
        s.commit()
        s.refresh(row)
    _finish(run.id, meter, "done")
    events.publish("brief", brief_id=row.id, day=day, headline=brief.headline)
    return row
