"""Rythme conseillé : espacer un sujet qui bouge peu, le resserrer quand il repart, sans IA ;
et le pouls, qui avance le passage d'un sujet espacé qui s'emballe."""

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from openmedia import scheduler
from openmedia.agents import pulse, rhythm
from openmedia.collect.base import Candidate
from openmedia.config import Settings
from openmedia.db import session
from openmedia.models import Fiche, Topic, now
from openmedia.server import app

TZ = timezone(timedelta(hours=2))
AT = datetime(2026, 10, 22, 9, 0, tzinfo=TZ)


def _hist(news: dict[int, int], days: int = 8, tokens: int = 50_000) -> list[dict]:
    """Un passage par jour pendant `days` jours, finissant la veille de AT ; `news` : {jour: nouveautés}."""
    out = []
    for d in range(days):
        at = AT - timedelta(days=days - d)
        out.append({"at": at, "day": at.date().isoformat(), "new": news.get(d, 0), "confirmations": 0, "rectifications": 0, "reprises": 0, "importance": 3 if news.get(d) else 0, "skipped": not news.get(d), "tokens": tokens, "cost": 0.5})
    return out


def _topic(**kw):
    return Topic(name="Sujet", prompt="x", follow_deadlines=False, **kw)


def test_quiet_daily_topic_is_spaced_with_a_simulated_delay():
    adv = rhythm.advise(_topic(), Settings(), AT, _hist({1: 2, 5: 1}))
    # 2 passages sur 8 : idéalement 1 sur 4, mais une nouvelle aurait attendu 3 jours ; 1 sur 3 : 1,5 jour.
    assert adv["direction"] == "espacer" and adv["every"] == 3
    sim = adv["simulation"]
    assert sim["mean_delay"] == 1.5 and sim["max_delay"] == 2
    assert sim["runs_saved"] == 20.0 and sim["tokens_saved"] == 1_000_000 and sim["cost_saved"] == 10.0
    assert adv["reason"] == "2 passages sur les 8 derniers ont apporté du neuf." and adv["confidence"] == "faible"


def test_an_important_topic_is_never_spaced_much():
    assert rhythm.advise(_topic(importance=5), Settings(), AT, _hist({1: 2, 5: 1}))["every"] == 2


def test_a_dead_topic_goes_weekly_and_a_new_one_is_observed():
    assert rhythm.advise(_topic(), Settings(), AT, _hist({}))["direction"] == "veille"
    young = rhythm.advise(_topic(), Settings(), AT, _hist({}, days=4))
    assert young["direction"] is None and young["reason"].startswith("On observe encore ce sujet : 4 passages sur 6")


def test_a_spaced_topic_that_heats_up_is_tightened():
    adv = rhythm.advise(_topic(run_every_days=4), Settings(), AT, _hist({5: 3, 6: 2, 7: 4}))
    assert adv["direction"] == "resserrer" and adv["every"] == 2
    pulsed = _topic(run_every_days=4, rhythm={"pulse": {"advanced": [(AT.date() - timedelta(days=d)).isoformat() for d in (2, 9)]}})
    assert rhythm.advise(pulsed, Settings(), AT, _hist({}))["direction"] == "resserrer"


def test_a_dismissed_advice_waits_two_weeks():
    t = _topic(rhythm={"dismissed": {"every": 3, "until": (now() + timedelta(days=3)).isoformat()}})
    adv = rhythm.advise(t, Settings(), AT, _hist({1: 2, 5: 1}))
    assert adv["direction"] is None and adv["dismissed"]
    assert rhythm.advise(t, Settings(), AT, _hist({1: 2, 5: 1}), honor_dismissal=False)["every"] == 3


def test_own_interval_starts_the_day_it_is_chosen():
    t = _topic(run_every_days=3, run_anchor="2026-10-22")
    c = scheduler.cadence(t, Settings())
    assert [c.runs_on(date(2026, 10, d)) for d in (22, 23, 24, 25)] == [True, False, False, True]


def _db_topic(**kw) -> Topic:
    with session() as s:
        t = Topic(name="Pilote", prompt="x", follow_deadlines=False, **kw)
        s.add(t)
        s.commit()
        s.refresh(t)
    return t


def _fiche(topic_id: int, version: int, days_ago: float, new: int, importance: int = 3):
    with session() as s:
        s.add(Fiche(topic_id=topic_id, version=version, content={"importance": importance if new else 0, "whats_new": [{}] * new}, nothing_new=not new, novelty={"new": new}, created_at=now() - timedelta(days=days_ago)))
        s.commit()


def test_autopilot_spaces_then_comes_back(monkeypatch):
    published = []
    monkeypatch.setattr(rhythm.events, "publish", lambda kind, **data: published.append((kind, data)))
    t = _db_topic(rhythm={"auto": True, "min_every": 1, "max_every": 4})
    for v in range(8):
        _fiche(t.id, v + 1, 8 - v, 2 if v in (1, 5) else 0)
    assert rhythm.after_run(t.id) == {"every": 3}
    with session() as s:
        t = s.get(Topic, t.id)
    assert t.run_every_days == 3 and t.run_anchor == datetime.now().astimezone().date().isoformat()
    entry = t.rhythm["log"][-1]
    assert entry["by"] == "auto" and entry["from"] == 1 and entry["to"] == 3
    assert published[-1][0] == "rhythm" and "passe à 1 jour sur 3" in published[-1][1]["message"]
    assert rhythm.holds_sleep(t)  # au rythme intermédiaire, la veille automatique attend

    # Une nouvelle fiche riche : retour immédiat au rythme le plus serré.
    _fiche(t.id, 9, 0, 3)
    assert rhythm.after_run(t.id) == {"every": 1}
    with session() as s:
        assert s.get(Topic, t.id).run_every_days == 1


def test_autopilot_stays_within_its_bounds():
    t = _db_topic(rhythm={"auto": True, "min_every": 1, "max_every": 2})
    for v in range(8):
        _fiche(t.id, v + 1, 8 - v, 0)
    rhythm.after_run(t.id)
    with session() as s:
        assert s.get(Topic, t.id).run_every_days == 2  # « une fois par semaine » plafonné à 2


def test_without_autopilot_nothing_changes():
    t = _db_topic()
    for v in range(8):
        _fiche(t.id, v + 1, 8 - v, 0)
    assert rhythm.after_run(t.id) is None


def test_rhythm_api(monkeypatch):
    monkeypatch.setattr(rhythm.events, "publish", lambda kind, **data: None)
    t = _db_topic()
    for v in range(8):
        _fiche(t.id, v + 1, 8 - v, 2 if v in (1, 5) else 0)
    with TestClient(app) as c:
        r = c.get(f"/topics/{t.id}/rhythm").json()
        assert r["advice"]["direction"] == "espacer" and len(r["strip"]) == 30 and r["auto"] is False
        assert sum(len(d["runs"]) for d in r["strip"]) == 8
        assert c.post(f"/topics/{t.id}/rhythm/dismiss", json={"every": r["advice"]["every"]}).status_code == 200
        assert c.get(f"/topics/{t.id}/rhythm").json()["advice"]["dismissed"]
        topic = c.post(f"/topics/{t.id}/rhythm/apply", json={"every": 3}).json()
        assert topic["run_every_days"] == 3 and topic["schedule"]["own"]
        r = c.get(f"/topics/{t.id}/rhythm").json()
        assert r["log"][0]["by"] == "user" and r["advice"]["direction"] is None  # le compteur repart
        r = c.patch(f"/topics/{t.id}/rhythm", json={"auto": True, "max_every": 7}).json()
        assert r["auto"] and r["max_every"] == 7
        assert any(row["topic_id"] == t.id for row in c.get("/rhythm").json())


# ── Le pouls ─────────────────────────────────────────────────────────────────


def _cand(title, source, hours=2):
    return Candidate(url=f"https://exemple.fr/{abs(hash(title))}", title=title, origin="gdelt", source_name=source, published_at=datetime.now(timezone.utc) - timedelta(hours=hours))


def test_pulse_thresholds():
    assert pulse.surging(5, 6, {}, "2026-10-22")
    assert not pulse.surging(2, 6, {}, "2026-10-22")  # trop peu de titres
    busy = {f"2026-10-{d:02d}": {"titles": 4, "media": 4} for d in range(8, 22)}
    assert not pulse.surging(5, 6, busy, "2026-10-22")  # un sujet toujours bavard ne s'emballe pas à 6 médias
    assert pulse.surging(12, 10, busy, "2026-10-22")


async def test_pulse_counts_only_new_headlines_once_a_day(monkeypatch):
    calls = []
    t = _db_topic(spec={"queries_fr": ["budget écoles"], "keywords": ["écoles"]}, languages=["fr"], last_run_at=now() - timedelta(days=1))

    async def search(queries, days, per_lang=3):
        calls.append((queries, days))
        return [
            _cand("Écoles : le plan voté à l'Assemblée", "Le Monde"),
            _cand("Écoles : le plan voté à l'Assemblée nationale", "Le Figaro"),  # même titre
            _cand("Le Sénat amende le plan pour les écoles", "Libération"),
            _cand("Écoles : les maires inquiets", "Ouest-France"),
            _cand("Écoles rurales : la carte change", "La Croix"),
            _cand("Match de football ce soir", "L'Équipe"),  # hors sujet
            _cand("Écoles : une annonce d'avant-hier", "BFM", hours=60),  # avant le dernier passage
        ]

    monkeypatch.setattr(pulse.gdelt, "search", search)
    at = datetime.now().astimezone()
    result = await pulse.check(t, at)
    assert calls == [({"fr": ["budget écoles"]}, 1)]
    assert result["titles"] == 4 and result["media"] == 4 and result["hot"]
    with session() as s:
        t = s.get(Topic, t.id)
    assert t.rhythm["pulse"]["counts"][at.date().isoformat()] == {"titles": 4, "media": 4}
    assert t.rhythm["pulse"]["advanced"] == [at.date().isoformat()] and t.rhythm["log"][-1]["by"] == "pulse"
    assert await pulse.check(t, at) is None and len(calls) == 1  # une fois par jour


def test_pulse_skips_topics_that_run_today():
    today = datetime(2026, 10, 22, 9, 0, tzinfo=TZ)
    runs_today = _topic(run_every_days=3, run_anchor="2026-10-22", last_run_at=now())
    off_day = _topic(run_every_days=3, run_anchor="2026-10-21", last_run_at=now())
    never = _topic(run_every_days=3, run_anchor="2026-10-21")
    runs_today.id, off_day.id, never.id = 101, 102, 103
    picked = pulse.candidates([runs_today, off_day, never], Settings(run_hours=["06:30"]), today, set())
    assert [t.id for t in picked] == [102]
    assert pulse.candidates([off_day], Settings(run_hours=["10:00"]), today, set()) == []  # avant la première heure
