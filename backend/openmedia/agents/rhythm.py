"""Rythme conseillé : un sujet qui bouge peu n'a pas besoin d'un passage chaque jour. Sans IA,
d'après ce que chaque passage a réellement apporté (`Fiche.novelty`).

- Le conseil : espacer (1 jour sur 2, 3, 4, 7), resserrer, ou passer à un contrôle par
  semaine. Le retard qu'aurait coûté un rythme plus lent est simulé sur l'historique réel,
  et l'économie chiffrée comme dans « Consommation ».
- Le pilote automatique (`rhythm.auto`) applique le conseil lui-même, entre deux bornes, et
  revient au rythme le plus serré dès que le sujet repart. Chaque changement est consigné et
  annoncé au lecteur, qui peut l'annuler.
- Les jours d'échéance gardent leur passage, et le pouls (`pulse.py`) avance le passage d'un
  sujet espacé qui s'emballe : espacer ne fait rien rater."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from statistics import mean

from sqlmodel import select

from .. import events
from ..config import Settings, load_settings
from ..db import session
from ..models import Fiche, Run, Topic, now

MIN_RUNS = 6  # passages au rythme actuel avant de conseiller quoi que ce soit
LOOK = 14  # passages examinés au plus
CHOICES = (2, 3, 4, 7)
MAX_DELAY = 1.5  # jours de retard moyen acceptés pour une nouvelle
IMPORTANCE_CAP = {5: 2, 4: 3}  # un sujet important n'est jamais trop espacé
QUIET_FOR_WEEKLY = 8  # passages sans nouveauté avant de conseiller un contrôle par semaine
RICH = 2  # nouveautés d'un passage « riche »
DISMISS_DAYS = 14
LOG_SIZE = 30
DEFAULTS = {"auto": False, "min_every": 1, "max_every": 4, "dismissed": None, "changed_at": None, "log": [], "pulse": {}}


def state(topic: Topic) -> dict:
    return {**DEFAULTS, **(topic.rhythm or {})}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse(value: str | None) -> datetime | None:
    try:
        return _aware(datetime.fromisoformat(value)) if value else None
    except ValueError:
        return None


# ── La mesure ────────────────────────────────────────────────────────────────


def history(topic_id: int, days: int = 30) -> list[dict]:
    """Chaque passage des `days` derniers jours, du plus ancien au plus récent : ce qu'il a
    apporté et ce qu'il a coûté."""
    start = now() - timedelta(days=days)
    with session() as s:
        fiches = s.exec(select(Fiche).where(Fiche.topic_id == topic_id, Fiche.created_at >= start).order_by(Fiche.version)).all()
        runs = {r.id: r for r in s.exec(select(Run).where(Run.id.in_([f.run_id for f in fiches if f.run_id]))).all()} if fiches else {}
    out = []
    for f in fiches:
        n = f.novelty or {}
        run = runs.get(f.run_id)
        at = _aware(f.created_at)
        out.append({
            "at": at,
            "day": at.astimezone().date().isoformat(),
            "new": n.get("new", 0 if f.nothing_new else len(f.content.get("whats_new", []))),
            "confirmations": n.get("confirmations", 0),
            "rectifications": n.get("rectifications", len(f.content.get("corrections", []))),
            "reprises": n.get("reprises", 0),
            "importance": f.content.get("importance") or 0,
            "skipped": bool(n.get("synth_skipped")),
            "tokens": (run.input_tokens + run.output_tokens) if run else 0,
            "cost": (run.cost_usd or 0.0) if run else 0.0,
        })
    return out


def _delays(days: list[date], start: date, k: int) -> list[int]:
    """Le retard de chaque jour porteur si le sujet n'était passé qu'un jour sur `k` depuis `start`."""
    return [(-(d - start).days) % k for d in days]


def _current(c) -> int:
    """L'intervalle actuel, en jours (une semaine de cinq jours compte pour un jour sur un)."""
    return c.every if not c.weekdays else max(1, round(7 / len(c.weekdays)))


# ── Le conseil ───────────────────────────────────────────────────────────────


def advise(topic: Topic, settings: Settings | None = None, at: datetime | None = None, hist: list[dict] | None = None, *, honor_dismissal: bool = True) -> dict:
    from .. import scheduler

    settings = settings or load_settings()
    at = at or datetime.now().astimezone()
    st = state(topic)
    c = scheduler.cadence(topic, settings)
    current = _current(c)
    hist = history(topic.id) if hist is None else hist
    changed = _parse(st["changed_at"])
    runs = [h for h in hist if changed is None or h["at"] >= changed][-LOOK:]
    out = {"current": current, "observed": len(runs), "needed": MIN_RUNS, "direction": None, "every": None, "reason": "", "simulation": None, "confidence": None, "dismissed": False}
    if topic.status == "archived" or topic.kind == "recherche":
        return out
    if len(runs) < MIN_RUNS:
        out["reason"] = f"On observe encore ce sujet : {len(runs)} passage{'s' if len(runs) > 1 else ''} sur {MIN_RUNS} au rythme actuel."
        return out
    news = [h for h in runs if h["new"] > 0]
    share = len(news) / len(runs)
    pulse = st["pulse"] or {}
    advanced = [d for d in pulse.get("advanced", []) if d >= (at.date() - timedelta(days=14)).isoformat()]
    direction, every, reason = None, None, ""
    last3 = runs[-3:]
    if current >= 2 and (all(h["new"] >= RICH for h in last3) or len(advanced) >= 2):
        direction, every = "resserrer", max(1, current // 2)
        reason = f"Le pouls a avancé {len(advanced)} passages en deux semaines." if len(advanced) >= 2 else f"Les {len(last3)} derniers passages ont chacun apporté au moins {RICH} nouveautés."
    elif not news and len(runs) >= QUIET_FOR_WEEKLY and current < 7:
        direction, every = "veille", 7
        reason = f"Aucune nouveauté sur les {len(runs)} derniers passages."
    elif share < 1:
        cap = IMPORTANCE_CAP.get(topic.importance, 7)
        ideal = 7 if not news else round(1 / share)
        start = date.fromisoformat(runs[0]["day"])
        news_days = sorted({date.fromisoformat(h["day"]) for h in news})
        for k in sorted((k for k in CHOICES if current < k <= min(ideal, cap)), reverse=True):
            delays = _delays(news_days, start, k)
            if not delays or mean(delays) <= MAX_DELAY:
                direction, every = "espacer", k
                break
        plural = "s" if len(runs) > 1 else ""
        reason = f"{len(news)} passage{'s' if len(news) > 1 else ''} sur les {len(runs)} dernier{plural} {'ont' if len(news) > 1 else 'a'} apporté du neuf." if news else f"Aucune nouveauté sur les {len(runs)} derniers passages."
    if direction is None:
        return out
    dismissed = st["dismissed"] or {}
    if honor_dismissal and dismissed.get("every") == every and (_parse(dismissed.get("until")) or at) > at:
        return {**out, "dismissed": True}

    # Ce que change le nouveau rythme : passages par mois (échéances comprises), tokens et retard.
    proposed = replace(c, every=every, weekdays=(), anchor=at.date())
    saved = scheduler.runs_per_month(c, at) - scheduler.runs_per_month(proposed, at)
    quiet = [h for h in runs if h["new"] == 0 and h["tokens"]] or [h for h in runs if h["tokens"]]
    per_run_tokens = mean(h["tokens"] for h in quiet) if quiet else 0
    per_run_cost = mean(h["cost"] for h in quiet) if quiet else 0.0
    news_days = sorted({date.fromisoformat(h["day"]) for h in news})
    delays = _delays(news_days, date.fromisoformat(runs[0]["day"]), every) if direction != "resserrer" else []
    out.update(
        direction=direction,
        every=every,
        reason=reason,
        confidence="elevee" if len(runs) >= LOOK else "moyenne" if len(runs) >= 10 else "faible",
        simulation={
            "runs_saved": round(saved, 1),
            "tokens_saved": round(saved * per_run_tokens),
            "cost_saved": round(saved * per_run_cost, 4),
            "mean_delay": round(mean(delays), 1) if delays else 0.0,
            "max_delay": max(delays) if delays else 0,
            "news_runs": len(news),
            "runs": len(runs),
        },
    )
    return out


# ── Les actions ──────────────────────────────────────────────────────────────


def _label(every: int) -> str:
    return "chaque jour" if every == 1 else "une fois par semaine" if every == 7 else f"1 jour sur {every}"


def apply(topic_id: int, every: int, *, by: str = "user", reason: str = "") -> Topic:
    """Passe le sujet à un passage tous les `every` jours, à partir d'aujourd'hui (ses heures et
    ses jours d'échéance ne changent pas). Consigné et annoncé."""
    from .. import scheduler

    with session() as s:
        t = s.get(Topic, topic_id)
        settings = load_settings()
        before = _current(scheduler.cadence(t, settings))
        st = state(t)
        t.run_every_days, t.run_weekdays = every, []
        t.run_anchor = datetime.now().astimezone().date().isoformat()
        st["changed_at"] = now().isoformat()
        st["dismissed"] = None
        st["log"] = [*st["log"], {"at": now().isoformat(), "from": before, "to": every, "reason": reason, "by": by}][-LOG_SIZE:]
        t.rhythm = st
        if t.status == "sleeping" and by != "auto":
            t.status, t.quiet_runs = "active", 0
        s.add(t)
        s.commit()
        s.refresh(t)
    if before != every:
        who = "Rythme adaptatif" if by == "auto" else "Pouls" if by == "pulse" else "Rythme"
        events.publish("rhythm", topic_id=topic_id, every=every, previous=before, by=by, message=f"{who} : « {t.name} » passe à {_label(every)}{f'. {reason}' if reason else ''}")
    return t


def dismiss(topic_id: int, every: int) -> Topic:
    with session() as s:
        t = s.get(Topic, topic_id)
        st = state(t)
        st["dismissed"] = {"every": every, "until": (now() + timedelta(days=DISMISS_DAYS)).isoformat()}
        t.rhythm = st
        s.add(t)
        s.commit()
        s.refresh(t)
    return t


def configure(topic_id: int, *, auto: bool | None = None, min_every: int | None = None, max_every: int | None = None) -> Topic:
    with session() as s:
        t = s.get(Topic, topic_id)
        st = state(t)
        if auto is not None:
            st["auto"] = auto
        if min_every is not None:
            st["min_every"] = max(1, min(min_every, 30))
        if max_every is not None:
            st["max_every"] = max(1, min(max_every, 30))
        st["max_every"] = max(st["max_every"], st["min_every"])
        t.rhythm = st
        s.add(t)
        s.commit()
        s.refresh(t)
    if auto:
        after_run(topic_id)  # le pilote prend la main tout de suite s'il a de quoi décider
        with session() as s:
            t = s.get(Topic, topic_id)
    return t


def holds_sleep(topic: Topic) -> bool:
    """Avec le rythme adaptatif, un sujet calme s'espace d'abord ; il ne se met en veille
    qu'une fois au rythme le plus lent permis."""
    st = state(topic)
    return bool(st["auto"]) and (topic.run_every_days or 1) < st["max_every"]


def after_run(topic_id: int) -> dict | None:
    """Après chaque passage : le pilote automatique applique le conseil, dans ses bornes. Un
    passage riche ramène tout de suite au rythme le plus serré."""
    from .. import scheduler

    with session() as s:
        topic = s.get(Topic, topic_id)
    if not topic or not state(topic)["auto"] or topic.status == "archived":
        return None
    st, settings = state(topic), load_settings()
    current = _current(scheduler.cadence(topic, settings))
    hist = history(topic_id)
    last = hist[-1] if hist else None
    if last and last["new"] >= RICH and last["importance"] >= 3 and current > st["min_every"]:
        apply(topic_id, st["min_every"], by="auto", reason=f"Le sujet repart : {last['new']} nouveautés au dernier passage.")
        return {"every": st["min_every"]}
    adv = advise(topic, settings, hist=hist, honor_dismissal=False)
    if not adv["direction"]:
        return None
    target = max(st["min_every"], min(adv["every"], st["max_every"]))
    if (target < current) if adv["direction"] == "resserrer" else (target > current):
        apply(topic_id, target, by="auto", reason=adv["reason"])
        return {"every": target}
    return None


def strip(topic: Topic, days: int = 30, hist: list[dict] | None = None) -> list[dict]:
    """La bande d'activité : pour chaque jour, les passages (et ce qu'ils ont apporté) et le pouls."""
    hist = history(topic.id, days) if hist is None else hist
    pulse = (state(topic)["pulse"] or {}).get("counts", {})
    advanced = set((state(topic)["pulse"] or {}).get("advanced", []))
    today = datetime.now().astimezone().date()
    out = []
    for back in range(days - 1, -1, -1):
        d = (today - timedelta(days=back)).isoformat()
        runs = [{k: h[k] for k in ("new", "confirmations", "rectifications", "reprises", "skipped")} for h in hist if h["day"] == d]
        p = pulse.get(d) or {}
        out.append({"day": d, "runs": runs, "pulse": p.get("titles"), "pulse_media": p.get("media"), "advanced": d in advanced})
    return out


def overview(topic: Topic, settings: Settings | None = None) -> dict:
    hist = history(topic.id)
    st = state(topic)
    return {
        "advice": advise(topic, settings, hist=hist),
        "strip": strip(topic, hist=hist),
        "auto": st["auto"],
        "min_every": st["min_every"],
        "max_every": st["max_every"],
        "log": list(reversed(st["log"]))[:10],
    }
