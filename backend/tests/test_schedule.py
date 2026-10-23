"""Rythme des passages (tous les N jours, certains jours de la semaine, plusieurs heures, jours
d'échéance), plafond de tokens, rapport de consommation et calendrier."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from openmedia import scheduler
from openmedia.config import Settings, update_settings
from openmedia.db import session
from openmedia.models import Announcement, Brief, Fiche, Run, Topic
from openmedia.scheduler import Cadence, cadence, due_today, last_slot, next_run, next_slot, slots_between

TZ = timezone(timedelta(hours=2))
MONDAY = date(2026, 10, 19)


def at(day: int, hour: int = 8, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


def every(days: int, start: date = MONDAY, hours: tuple[str, ...] = ("06:30",)) -> Cadence:
    return Cadence(every=days, hours=hours, anchor=start)


def test_slots_follow_the_calendar():
    # Chaque jour : le créneau d'aujourd'hui une fois l'heure passée, sinon celui d'hier.
    assert last_slot(at(21, 8), every(1)) == at(21, 6, 30)
    assert last_slot(at(21, 6), every(1)) == at(20, 6, 30)
    # Un jour sur deux à partir du lundi 19 : lundi, mercredi, vendredi…
    assert last_slot(at(20, 8), every(2)) == at(19, 6, 30)
    assert last_slot(at(21, 8), every(2)) == at(21, 6, 30)
    assert next_slot(at(21, 8), every(2)) == at(23, 6, 30)
    assert next_slot(at(21, 6), every(2)) == at(21, 6, 30)
    # Un jour sur trois, chaque semaine, et n'importe quel intervalle.
    assert last_slot(at(24, 8), every(3)) == at(22, 6, 30)
    assert next_slot(at(22, 8), every(3)) == at(25, 6, 30)
    assert next_slot(at(20, 8), every(7)) == at(26, 6, 30)
    assert next_slot(at(20, 8), every(5)) == at(24, 6, 30)
    # Une ancre future marche aussi (jours de passage avant elle).
    assert last_slot(at(20, 8), every(2, date(2026, 10, 30))) == at(20, 6, 30)


def test_several_hours_and_weekdays():
    twice = every(1, hours=("06:30", "18:00"))
    assert last_slot(at(21, 12), twice) == at(21, 6, 30)
    assert next_slot(at(21, 12), twice) == at(21, 18)
    assert next_slot(at(21, 19), twice) == at(22, 6, 30)
    assert len(slots_between(at(19, 0), at(26, 0), twice)) == 14
    # Lundi, mercredi, vendredi : le 19 est un lundi.
    mwf = Cadence(weekdays=(0, 2, 4), hours=("07:00",))
    assert last_slot(at(20, 8), mwf) == at(19, 7)
    assert next_slot(at(21, 8), mwf) == at(23, 7)
    assert next_slot(at(23, 8), mwf) == at(26, 7)
    # Un jour d'échéance s'ajoute au rythme.
    with_deadline = Cadence(weekdays=(0, 2, 4), hours=("07:00",), extra=frozenset({date(2026, 10, 22)}))
    assert next_slot(at(21, 8), with_deadline) == at(22, 7)
    assert not with_deadline.regular(date(2026, 10, 22))


def test_due_today_with_frequency_catch_up_and_override():
    settings = Settings(run_hours=["06:30"], run_every_days=2, schedule_anchor="2026-10-19")
    ran_monday = datetime(2026, 10, 19, 5, 0, tzinfo=timezone.utc)  # 07:00 à Paris
    topic = Topic(name="t", prompt="p", last_run_at=ran_monday)
    assert not due_today(topic, settings, at(20, 9))  # mardi : jour « off »
    assert due_today(topic, settings, at(21, 9))  # mercredi : jour de passage
    assert not due_today(topic, settings, at(21, 6))  # pas avant l'heure
    assert due_today(topic, settings, at(22, 9))  # PC éteint mercredi : rattrapé jeudi
    topic.run_every_days = 1  # ce sujet-là reste quotidien
    assert due_today(topic, settings, at(20, 9))
    topic.run_every_days = 7
    assert not due_today(topic, settings, at(25, 9)) and due_today(topic, settings, at(26, 9))
    # Ses propres jours (le mardi) et ses propres heures (20:00).
    topic.run_every_days, topic.run_weekdays, topic.run_hours = None, [1], ["20:00"]
    assert not due_today(topic, settings, at(20, 19)) and due_today(topic, settings, at(20, 21))
    # L'ancienne heure unique d'un sujet reste comprise, avec les jours des réglages.
    topic.run_weekdays, topic.run_hours, topic.run_hour = [], [], "08:00"
    assert cadence(topic, settings).hours == ("08:00",) and cadence(topic, settings).every == 2


def test_old_settings_keep_their_hour():
    assert Settings.model_validate({"run_hour": "07:15"}).run_hours == ["07:15"]
    assert Settings.model_validate({"run_hour": "07:15", "run_hours": ["05:00", "19:00"]}).run_hours == ["05:00", "19:00"]


@pytest.fixture
def clean_db():
    # Les sujets des autres tests sont archivés (leurs fiches les retiennent), passages et briefs effacés.
    with session() as s:
        for model in (Run, Brief):
            for row in s.exec(select(model)).all():
                s.delete(row)
        for t in s.exec(select(Topic)).all():
            t.status = "archived"
            s.add(t)
        s.commit()
    yield
    update_settings({"run_every_days": 1, "run_weekdays": [], "schedule_anchor": "", "monthly_token_cap": 0, "run_hours": ["06:30"]})


@pytest.fixture
def fake_tick(monkeypatch):
    calls = {"ran": [], "brief": 0}

    async def run_many(ids, settings, llm=None):
        calls["ran"].append(list(ids))
        return len(ids)

    async def brief_now(llm=None):
        calls["brief"] += 1

    async def check_due(*_):
        pass

    monkeypatch.setattr(scheduler, "any_engine", lambda _: True)
    monkeypatch.setattr(scheduler, "engine_status", lambda: {})
    monkeypatch.setattr(scheduler, "month_cost", lambda: 0.0)
    monkeypatch.setattr(scheduler, "run_many", run_many)
    monkeypatch.setattr(scheduler, "brief_now", brief_now)
    monkeypatch.setattr(scheduler, "check_due", check_due)
    monkeypatch.setattr(scheduler, "get_llm", lambda: None)
    return calls


async def test_no_brief_on_off_days(clean_db, fake_tick):
    now = datetime.now().astimezone()
    # Hier était le jour de passage ; aujourd'hui est « off » ; le sujet et le brief ont tourné hier.
    update_settings({"run_every_days": 2, "schedule_anchor": f"{now - timedelta(days=1):%Y-%m-%d}", "run_hours": ["00:00"]})
    yesterday = (now - timedelta(days=1)).replace(hour=0, minute=30).astimezone(timezone.utc)
    with session() as s:
        s.add(Topic(name="t", prompt="p", last_run_at=yesterday))
        s.add(Brief(day=f"{yesterday:%Y-%m-%d}", created_at=yesterday))
        s.commit()
    await scheduler.tick()
    assert fake_tick["ran"] == [] and fake_tick["brief"] == 0
    update_settings({"run_every_days": 1})  # chaque jour : aujourd'hui redevient un jour de passage
    await scheduler.tick()
    assert len(fake_tick["ran"]) == 1 and fake_tick["brief"] == 1


async def test_token_cap_suspends_scheduled_runs_only(clean_db, fake_tick):
    update_settings({"monthly_token_cap": 1000})
    with session() as s:
        s.add(Topic(name="t", prompt="p"))
        s.add(Run(kind="topic", status="done", input_tokens=900, output_tokens=200))
        s.commit()
    await scheduler.tick()
    assert fake_tick["ran"] == []
    await scheduler.tick(force_all=True)  # « Tout mettre à jour » reste possible
    assert len(fake_tick["ran"]) == 1


def test_costs_report_tokens_and_estimates(clean_db):
    from openmedia.server import app

    with session() as s:
        daily, weekly = Topic(name="Quotidien", prompt="p"), Topic(name="Hebdo", prompt="p", run_every_days=7)
        s.add_all([daily, weekly])
        s.commit()
        for _ in range(2):
            s.add(Run(topic_id=daily.id, kind="topic", status="done", input_tokens=80_000, cache_read_tokens=30_000, output_tokens=20_000, cost_usd=0.1))
        s.add(Run(kind="director", status="done", input_tokens=9_000, output_tokens=1_000))
        s.commit()
    with TestClient(app) as c:
        assert c.patch(f"/topics/{weekly.id}", json={"run_every_days": 31}).status_code == 400
        assert c.patch(f"/topics/{weekly.id}", json={"run_hours": ["25:00"]}).status_code == 400
        assert c.patch(f"/topics/{weekly.id}", json={"run_weekdays": [7]}).status_code == 400
        assert c.patch("/settings", json={"run_every_days": 0}).status_code == 400
        assert c.patch("/settings", json={"run_hours": []}).status_code == 400
        report = c.get("/costs").json()
        # Un sujet 1 jour sur 2, l'autre 1 sur 3, général 1 sur 3 : le brief tourne 2 jours sur 3.
        c.patch(f"/topics/{daily.id}", json={"run_every_days": 2})
        c.patch(f"/topics/{weekly.id}", json={"run_every_days": None})
        assert c.patch("/settings", json={"run_every_days": 3}).json()["schedule_anchor"] == f"{datetime.now().astimezone():%Y-%m-%d}"
        assert c.get("/costs").json()["brief"]["per_month"] == 20
    assert len(report["days"]) == 30 and report["days"][-1]["topics"] == 200_000 and report["days"][-1]["brief"] == 10_000
    assert report["month"]["tokens"] == {"in": 169_000, "cached": 60_000, "out": 41_000, "total": 210_000}
    assert report["today"]["tokens"] == 210_000
    rows = {r["name"]: r for r in report["topics"]}
    assert rows["Quotidien"]["avg_tokens"] == 100_000 and rows["Quotidien"]["monthly_tokens"] == 3_000_000
    # Sans historique : la moyenne des autres sujets, signalée comme estimation.
    assert rows["Hebdo"]["estimated"] and rows["Hebdo"]["runs_per_month"] == 4.3 and rows["Hebdo"]["monthly_tokens"] == round(100_000 * 30 / 7)
    assert report["brief"]["per_month"] == 30 and report["brief"]["avg_tokens"] == 10_000 and report["projection"]["tokens"] == 3_000_000 + round(100_000 * 30 / 7) + 300_000
    assert report["next_run"]


def test_rhythm_patch_counts_hours_and_weekdays(clean_db):
    from openmedia.server import app

    with session() as s:
        t = Topic(name="Rythmé", prompt="p")
        s.add(t)
        s.commit()
    with TestClient(app) as c:
        # Matin et soir, du lundi au vendredi : 10 passages par semaine.
        out = c.patch(f"/topics/{t.id}", json={"run_weekdays": [4, 0, 1, 2, 3, 3], "run_hours": ["18:00", "06:30"], "run_every_days": None}).json()
        assert out["run_weekdays"] == [0, 1, 2, 3, 4] and out["run_hours"] == ["06:30", "18:00"] and out["schedule"]["own"]
        row = next(r for r in c.get("/costs").json()["topics"] if r["topic_id"] == t.id)
        assert row["runs_per_month"] == round(10 * 30 / 7, 1) and row["own_schedule"]
        # Revenir au rythme général.
        out = c.patch(f"/topics/{t.id}", json={"run_weekdays": [], "run_hours": [], "run_every_days": None}).json()
        assert not out["schedule"]["own"] and out["schedule"]["hours"] == ["06:30"]
        # Réglages : deux heures, certains jours ; l'ancre suit le changement de jours.
        st = c.patch("/settings", json={"run_hours": ["19:30", "07:00"], "run_weekdays": [6, 5]}).json()
        assert st["run_hours"] == ["07:00", "19:30"] and st["run_weekdays"] == [5, 6]
        assert st["schedule_anchor"] == f"{datetime.now().astimezone():%Y-%m-%d}"


def test_deadlines_add_runs_and_fill_the_calendar(clean_db):
    from openmedia.server import app

    today = datetime.now().astimezone().date()
    soon = today + timedelta(days=3)
    with session() as s:
        t = Topic(name="Échéancier", prompt="p", run_every_days=30)
        s.add(t)
        s.commit()
        s.add(Announcement(topic_id=t.id, text="Vote du texte", due=f"{soon:%Y-%m-%d}"))
        s.add(Announcement(topic_id=t.id, text="Décret d'application", due=f"{soon:%Y-%m}"))
        s.add(Announcement(topic_id=t.id, text="Sommet annulé", due=f"{today + timedelta(days=5):%Y-%m-%d}", status="abandonne"))
        s.add(Fiche(topic_id=t.id, version=1, content={"timeline": [{"date": f"{today:%Y-%m-%d}", "event": "Dépôt du texte", "refs": ["S1"]}], "whats_new": [{"text": "x"}]}, sources=[{"ref": "S1", "id": 1, "title": "Article", "domain": "exemple.fr", "url": "https://exemple.fr/a"}]))
        s.commit()
    settings = Settings(run_hours=["06:30"], schedule_anchor=f"{today:%Y-%m-%d}")
    # Le jour du vote et le lendemain ; rien pour l'échéance abandonnée ni pour celle datée au mois.
    assert cadence(t, settings).extra == frozenset({soon, soon + timedelta(days=1)})
    after_today = datetime.combine(today + timedelta(days=1), datetime.min.time()).astimezone()
    ran_tonight = (after_today - timedelta(minutes=1)).astimezone(timezone.utc)
    assert next_run(Topic(**{**t.model_dump(), "last_run_at": ran_tonight}), settings, after_today).date() == soon
    t.follow_deadlines = False
    assert cadence(t, settings).extra == frozenset()

    with TestClient(app) as client:
        first = today.replace(day=1)
        last = first + timedelta(days=62)
        cal = client.get(f"/calendar?start={first}&end={last}&topic_id={t.id}").json()
        assert {d["text"] for d in cal["deadlines"]} == {"Vote du texte", "Sommet annulé"}
        assert [u["text"] for u in cal["undated"]] == ["Décret d'application"]
        assert cal["events"][0]["text"] == "Dépôt du texte" and cal["events"][0]["sources"][0]["domain"] == "exemple.fr"
        assert len(cal["runs"]) == 1 and cal["runs"][0]["news"] == 1
        assert any(p["deadline"] and p["date"] == f"{soon:%Y-%m-%d}" for p in cal["planned"])
        # Tous les sujets : échéances et événements, sans les passages.
        everything = client.get(f"/calendar?start={first}&end={last}").json()
        assert everything["runs"] == [] and everything["planned"] == [] and everything["deadlines"]
        assert client.get(f"/calendar?start={first}&end={first + timedelta(days=200)}").status_code == 400
