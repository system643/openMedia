"""Les passages : un « tic » toutes les 10 minutes lance les sujets dont le dernier créneau est
passé sans qu'ils aient tourné. Un créneau, c'est l'une des heures du passage un jour de
passage : tous les N jours (alignés sur le calendrier pour que les sujets d'un même rythme
tournent ensemble) ou certains jours de la semaine, plus, si le sujet suit ses échéances, le
jour de chacune et le lendemain. Le même mécanisme rattrape un passage manqué (PC éteint) dès
le lancement de l'application. Le Directeur suit les agents."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import func
from sqlmodel import select

from . import events
from .agents.director import run_director
from .agents.llm import NoApiKey
from .agents.topic_agent import run_topic
from .audio.tts import brief_audio
from .agents import pulse
from .agents.announcements import check_due
from .agents.batching import BatchingLLM
from .agents.llm import LLM, any_engine, engine_status, get_llm
from .config import ConsentRequired, Settings, consented, load_settings
from .db import session
from .models import Brief, Run, Topic

_running: set[int] = set()
_cap_warned = ""  # jour du dernier avertissement de plafond, pour ne pas le répéter à chaque tic
_lock = asyncio.Lock()
scheduler = AsyncIOScheduler()


def month_costs() -> dict:
    """Le mois en cours : ce qui est facturé (clés API) et l'équivalent couvert par
    l'abonnement Claude Code."""
    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with session() as s:
        total, sub = s.exec(select(func.coalesce(func.sum(Run.cost_usd), 0.0), func.coalesce(func.sum(Run.subscription_usd), 0.0)).where(Run.started_at >= start)).one()
    return {"real": float(total) - float(sub), "subscription": float(sub)}


def month_cost() -> float:
    """Ce qui est réellement facturé ce mois-ci : c'est ce que le budget borne."""
    return month_costs()["real"]


def month_tokens() -> dict:
    """Tokens du mois : lus (`in`, cache compris, dont `cached`), écrits (`out`) et leur somme
    (`total`), que le plafond borne."""
    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    zero = lambda col: func.coalesce(func.sum(col), 0)  # noqa: E731
    with session() as s:
        read, cached, out = s.exec(select(zero(Run.input_tokens), zero(Run.cache_read_tokens), zero(Run.output_tokens)).where(Run.started_at >= start)).one()
    return {"in": int(read), "cached": int(cached), "out": int(out), "total": int(read) + int(out)}


def _local(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone()


def anchor(settings: Settings) -> date:
    try:
        return date.fromisoformat(settings.schedule_anchor)
    except ValueError:
        return date(2026, 1, 5)  # un lundi : la fréquence hebdomadaire tombe alors le lundi


@dataclass(frozen=True)
class Cadence:
    """Le rythme d'un sujet ou du journal : tous les `every` jours depuis `anchor`, ou certains
    jours de la semaine (`weekdays`, lundi = 0), à une ou plusieurs heures. `extra` : des jours
    de passage en plus, ceux des échéances datées."""

    every: int = 1
    weekdays: tuple[int, ...] = ()
    hours: tuple[str, ...] = ("06:30",)
    anchor: date = date(2026, 1, 5)
    extra: frozenset[date] = field(default_factory=frozenset)

    def regular(self, day: date) -> bool:
        if self.weekdays:
            return day.weekday() in self.weekdays
        return (day - self.anchor).days % self.every == 0

    def runs_on(self, day: date) -> bool:
        return day in self.extra or self.regular(day)

    def slots_on(self, at: datetime, day: date) -> list[datetime]:
        return [_at_day(at, day, h) for h in self.hours] if self.runs_on(day) else []


HORIZON = 400  # jours explorés pour trouver un créneau ; le rythme le plus lent en compte 30


def general(settings: Settings) -> Cadence:
    """Le rythme des réglages, que suivent les sujets sans rythme propre, et le brief."""
    return Cadence(every=max(1, settings.run_every_days or 1), weekdays=tuple(sorted(set(settings.run_weekdays))), hours=tuple(sorted(set(settings.run_hours))) or ("06:30",), anchor=anchor(settings))


def deadline_days(topic_id: int) -> frozenset[date]:
    """Le jour de chaque échéance datée au jour près, et le lendemain pour en lire l'issue."""
    from .agents.announcements import due_date
    from .models import Announcement

    with session() as s:
        rows = s.exec(select(Announcement.due).where(Announcement.topic_id == topic_id, Announcement.status != "abandonne")).all()
    days = set()
    for due in rows:
        d = due_date(due) if due and len(due.strip()) >= 10 else None
        if d:
            days |= {d, d + timedelta(days=1)}
    return frozenset(days)


def cadence(topic: Topic | None, settings: Settings) -> Cadence:
    base = general(settings)
    if topic is None:
        return base
    every, weekdays, start = base.every, base.weekdays, base.anchor
    if topic.run_weekdays:
        every, weekdays = 1, tuple(sorted(set(topic.run_weekdays)))
    elif topic.run_every_days:
        every, weekdays = max(1, topic.run_every_days), ()
        # Un intervalle propre part du jour où il a été choisi : passer à « 1 jour sur 3 » un
        # lundi fait tourner le sujet jeudi, quelle que soit l'ancre des réglages.
        try:
            start = date.fromisoformat(topic.run_anchor) if topic.run_anchor else start
        except ValueError:
            pass
    hours = tuple(sorted(set(topic.run_hours or ([topic.run_hour] if topic.run_hour else [])))) or base.hours
    extra = deadline_days(topic.id) if topic.follow_deadlines and topic.id else frozenset()
    return Cadence(every=every, weekdays=weekdays, hours=hours, anchor=start, extra=extra)


PROJECTION_DAYS = 84  # douze semaines : un multiple de 7, de 2, de 3, de 4 et de 6


def runs_per_month(c: Cadence, at: datetime) -> float:
    """Les passages d'un rythme sur un mois, comptés sur les douze semaines à venir."""
    start = at.replace(hour=0, minute=0, second=0, microsecond=0)
    return len(slots_between(start, start + timedelta(days=PROJECTION_DAYS), c)) * 30 / PROJECTION_DAYS


def _at_day(at: datetime, day: date, hour_text: str) -> datetime:
    hour, minute = map(int, hour_text.split(":"))
    return at.replace(year=day.year, month=day.month, day=day.day, hour=hour, minute=minute, second=0, microsecond=0)


def last_slot(at: datetime, c: Cadence) -> datetime | None:
    """Le dernier créneau déjà passé."""
    for back in range(HORIZON):
        past = [s for s in c.slots_on(at, at.date() - timedelta(days=back)) if s <= at]
        if past:
            return past[-1]
    return None


def next_slot(at: datetime, c: Cadence) -> datetime | None:
    """Le prochain créneau à venir."""
    for ahead in range(HORIZON):
        future = [s for s in c.slots_on(at, at.date() + timedelta(days=ahead)) if s > at]
        if future:
            return future[0]
    return None


def slots_between(start: datetime, end: datetime, c: Cadence) -> list[datetime]:
    """Les créneaux de `start` (compris) à `end` (exclu)."""
    out, day = [], start.date()
    while day <= end.date():
        out += [s for s in c.slots_on(start, day) if start <= s < end]
        day += timedelta(days=1)
    return out


def due_today(topic: Topic, settings: Settings, at: datetime) -> bool:
    if topic.status == "archived":
        return False
    last = _local(topic.last_run_at)
    if topic.status == "sleeping":  # contrôle hebdomadaire d'un sujet en veille
        return last is None or at - last >= timedelta(days=7)
    slot = last_slot(at, cadence(topic, settings))
    return last is None or (slot is not None and last < slot)


def next_run(topic: Topic, settings: Settings, at: datetime) -> datetime | None:
    """Quand le sujet tournera : maintenant s'il est en attente, sinon son prochain créneau."""
    if topic.status == "archived":
        return None
    if due_today(topic, settings, at):
        return at
    if topic.status == "sleeping":
        return _local(topic.last_run_at) + timedelta(days=7)
    return next_slot(at, cadence(topic, settings))


def is_running(topic_id: int) -> bool:
    return topic_id in _running


async def run_one(topic_id: int, llm: LLM | None = None) -> dict | None:
    if topic_id in _running:
        return None
    _running.add(topic_id)
    try:
        return await run_topic(topic_id, llm=llm)
    finally:
        _running.discard(topic_id)


async def run_many(topic_ids: list[int], settings: Settings, llm: LLM | None = None) -> int:
    sem = asyncio.Semaphore(settings.max_parallel_topics)

    async def guarded(tid):
        async with sem:
            try:
                return await run_one(tid, llm)
            except (NoApiKey, ConsentRequired):
                raise
            except Exception:  # l'erreur est déjà consignée dans Run et publiée
                return None

    results = await asyncio.gather(*[guarded(t) for t in topic_ids])
    return sum(1 for r in results if r)


async def brief_now(llm: LLM | None = None) -> Brief | None:
    brief = await run_director(llm)
    # La voix est celle de Microsoft (en ligne) : seulement si le lecteur l'a demandé.
    if brief and load_settings().brief_audio_auto:
        try:
            await brief_audio(brief.id)
        except Exception as e:  # l'audio est un bonus : son échec ne bloque pas le brief
            events.publish("warning", message=f"Audio du brief indisponible : {e}")
    return brief


async def tick(force_all: bool = False) -> None:
    global _cap_warned
    if _lock.locked():
        return
    # Rien avant l'accord sur les conditions de fonctionnement : ni passage, ni pouls.
    if not consented() or not any_engine(engine_status()):
        return
    async with _lock:
        settings = load_settings()
        # Le budget borne ce qui est facturé (clés API) ; Claude Code relève de l'abonnement.
        if month_cost() >= settings.monthly_budget_usd:
            events.publish("warning", message=f"Budget mensuel atteint ({settings.monthly_budget_usd:.2f} $) : passages suspendus.")
            return
        at = datetime.now().astimezone()
        with session() as s:
            topics = s.exec(select(Topic).where(Topic.status != "archived")).all()
        due = [t.id for t in topics if force_all and t.status == "active" or due_today(t, settings, at)]
        # Le plafond de tokens suspend les passages planifiés, pas ceux qu'on lance soi-même.
        if not force_all and settings.monthly_token_cap and settings.engine != "local" and month_tokens()["total"] >= settings.monthly_token_cap:
            if due and _cap_warned != f"{at:%Y-%m-%d}":
                _cap_warned = f"{at:%Y-%m-%d}"
                events.publish("warning", message=f"Plafond mensuel de tokens atteint : {len(due)} passage(s) planifié(s) suspendu(s). « Tout mettre à jour » reste possible.")
            return
        # Le pouls (aucune IA) avance le passage d'un sujet espacé qui s'emballe.
        if not force_all:
            try:
                due += [i for i in await pulse.sweep(topics, settings, at, set(due)) if i not in due]
            except Exception as e:  # le pouls est un filet : son échec ne bloque aucun passage
                events.publish("warning", message=f"Pouls des sujets indisponible : {e}")
        # Mode Économie : seul le passage planifié passe par les lots, jamais une action manuelle.
        llm = BatchingLLM(get_llm()) if settings.economy_batch and due and not force_all else None
        if llm:
            events.publish("run", stage="economy", message="Passage en mode Économie : les lots peuvent prendre de quelques minutes à quelques heures")
        try:
            ran = await run_many(due, settings, llm) if due else 0
        except (NoApiKey, ConsentRequired) as e:
            events.publish("warning", message=f"Passages suspendus : {e}")
            return
        try:
            await check_due(llm or get_llm(), settings.models.topic)
        except Exception as e:
            events.publish("warning", message=f"Vérification des annonces impossible : {e}")
        # Sans sujet mis à jour, le brief n'est rédigé qu'un jour de passage : rien les jours « off ».
        slot = last_slot(at, general(settings))
        with session() as s:
            latest = s.exec(select(Brief).order_by(Brief.id.desc())).first()
        if ran or latest is None or (slot is not None and _local(latest.created_at) < slot):
            try:
                await brief_now(llm)
            except Exception as e:
                events.publish("warning", message=f"Le Directeur n'a pas pu rédiger le brief : {e}")


async def sync_readings() -> None:
    """« Mes lectures » à jour sans import : les nouvelles visites, toutes les 15 minutes.
    Aucune IA : seulement la lecture locale de l'historique des navigateurs."""
    from .agents.readings import sync_history

    try:
        result = await asyncio.to_thread(sync_history, 10)
    except Exception as e:  # historique verrouillé, profil disparu… : on réessaie au prochain tour
        events.publish("warning", message=f"Mise à jour de « Mes lectures » impossible : {e}")
        return
    from .agents import recurring

    if result and result["articles_kept"]:
        events.publish("readings", added=result["articles_kept"])
    # De nouvelles lectures, ou aucun calcul encore : les sujets récurrents sont refaits
    # (gratuit) ; Haiku ne nomme que les sujets qu'il n'a jamais vus.
    if (result and result["articles_kept"]) or recurring.load().get("result") is None:
        try:
            await recurring.refresh()
        except Exception as e:
            events.publish("warning", message=f"Sujets de tes lectures : calcul impossible ({e})")


def start() -> None:
    scheduler.add_job(tick, "interval", minutes=10, id="tick", next_run_time=datetime.now() + timedelta(seconds=20), max_instances=1, coalesce=True, misfire_grace_time=None)
    scheduler.add_job(sync_readings, "interval", minutes=15, id="readings", next_run_time=datetime.now() + timedelta(seconds=40), max_instances=1, coalesce=True, misfire_grace_time=None)
    scheduler.start()
