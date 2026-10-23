"""Mes lectures : historique des navigateurs (lu localement), filtre « actualité », médias lus
souvent, sources prioritaires et vérification d'un article."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from openmedia.agents import readings
from openmedia.agents.topic_agent import select_candidates
from openmedia.collect import history
from openmedia.collect.base import Candidate
from openmedia.db import session
from openmedia.models import Reading, Source
from openmedia.sources import registry

NOW = datetime.now(timezone.utc)


def chrome_time(dt: datetime) -> int:
    return int((dt - history.CHROME_EPOCH).total_seconds() * 1_000_000)


def make_chromium(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT, visit_count INTEGER)")
    con.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)")
    for i, (url, title, when) in enumerate(rows, 1):
        con.execute("INSERT INTO urls VALUES (?, ?, ?, 1)", (i, url, title))
        con.execute("INSERT INTO visits (url, visit_time) VALUES (?, ?)", (i, chrome_time(when)))
    con.commit()
    con.close()


def make_firefox(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE moz_places (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
    con.execute("CREATE TABLE moz_historyvisits (id INTEGER PRIMARY KEY, place_id INTEGER, visit_date INTEGER)")
    for i, (url, title, when) in enumerate(rows, 1):
        con.execute("INSERT INTO moz_places VALUES (?, ?, ?)", (i, url, title))
        con.execute("INSERT INTO moz_historyvisits (place_id, visit_date) VALUES (?, ?)", (i, int(when.timestamp() * 1_000_000)))
    con.commit()
    con.close()


ROWS = [
    ("https://www.lemonde.fr/politique/article/2026/10/18/budget-2027-les-deputes-rejettent-la-taxe_123456_823448.html", "Budget 2027 : les députés rejettent la taxe sur les holdings", NOW - timedelta(days=1)),
    ("https://www.lemonde.fr/politique/", "Politique - Le Monde", NOW - timedelta(days=1)),
    ("https://www.google.com/search?q=budget+2027", "budget 2027 - Recherche Google", NOW - timedelta(days=1)),
    ("https://mail.google.com/mail/u/0/#inbox", "Boîte de réception", NOW - timedelta(days=1)),
    ("https://www.youtube.com/watch?v=abc", "Vidéo", NOW - timedelta(days=1)),
    ("https://petit-journal-local.fr/actualite/la-mairie-annonce-la-renovation-complete-de-la-piscine", "La mairie annonce la rénovation complète de la piscine municipale", NOW - timedelta(days=2)),
    ("https://www.reuters.com/world/europe/france-lawmakers-reject-holding-tax-2026-10-17/", "France lawmakers reject holding tax", NOW - timedelta(days=200)),
    ("http://localhost:1427/", "openMedia", NOW - timedelta(days=1)),
]


@pytest.fixture
def browsers(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    make_chromium(tmp_path / "local/Google/Chrome/User Data/Default/History", ROWS)
    (tmp_path / "local/Google/Chrome/User Data/Local State").write_text('{"profile": {"info_cache": {"Default": {"name": "Perso"}}}}', encoding="utf-8")
    make_chromium(tmp_path / "local/BraveSoftware/Brave-Browser/User Data/Profile 1/History", ROWS[:1])
    make_firefox(tmp_path / "roaming/Mozilla/Firefox/Profiles/abc.default-release/places.sqlite", [ROWS[0], ROWS[5]])
    return tmp_path


def test_detects_browsers_and_profiles(browsers):
    found = {(p.browser, p.profile, p.label) for p in history.detect()}
    assert ("chrome", "Default", "Perso") in found
    assert ("brave", "Profile 1", "Profile 1") in found
    assert any(b == "firefox" for b, _, _ in found)


def test_reads_dates_for_chromium_and_firefox(browsers):
    chrome = next(p for p in history.detect() if p.browser == "chrome")
    visits = history.read_visits(chrome, NOW - timedelta(days=30))
    assert len(visits) == 7  # la visite de plus de 200 jours est hors période
    assert abs((visits[0].last_visit - ROWS[0][2]).total_seconds()) < 1
    ff = next(p for p in history.detect() if p.browser == "firefox")
    assert {v.url for v in history.read_visits(ff, NOW - timedelta(days=30))} == {ROWS[0][0], ROWS[5][0]}


def test_news_filter():
    known = {"lemonde.fr": "national", "reddit.com": "reseau_social"}
    keep = lambda url, title="Un titre d'article suffisamment long pour être crédible": history.is_news(url, title, known)  # noqa: E731
    assert keep(ROWS[0][0])
    assert not keep("https://www.lemonde.fr/politique/")  # rubrique
    assert not keep(ROWS[2][0]) and not keep(ROWS[3][0]) and not keep(ROWS[4][0]) and not keep(ROWS[7][0])
    assert keep(ROWS[5][0], ROWS[5][1])  # média inconnu, mais vraie page d'article
    assert not keep("https://www.reddit.com/r/france/comments/abc/un_long_titre_de_discussion_ici/")
    assert not keep("https://monsite-perso.fr/a-propos")


def test_import_keeps_only_news_and_merges_browsers(browsers):
    report = readings.import_history([{"browser": "chrome", "profile": "Default"}, {"browser": "brave", "profile": "Profile 1"}, {"browser": "firefox", "profile": "abc.default-release"}], 90)
    assert report["articles_kept"] == 2  # Le Monde (vu dans 3 navigateurs) + le journal local
    with session() as s:
        rows = s.exec(select(Reading)).all()
    assert len(rows) == 2


def test_diet_suggests_priority_sources():
    with session() as s:
        for r in s.exec(select(Reading)).all():
            s.delete(r)
        s.commit()
    from openmedia.models import Article

    with session() as s:
        for i in range(6):
            a = Article(url=f"https://www.lefigaro.fr/x/{i}-un-article", title="t", domain="lefigaro.fr")
            s.add(a)
            s.commit()
            s.refresh(a)
            s.add(Reading(article_id=a.id, visits=1))
        s.commit()
    d = readings.diet()
    assert d["media"][0]["domain"] == "lefigaro.fr" and d["media"][0]["reads"] == 6
    assert any(m["domain"] == "lefigaro.fr" for m in d["suggestions"])
    readings.set_priority("lefigaro.fr", True)
    assert not any(m["domain"] == "lefigaro.fr" for m in readings.diet()["suggestions"])


def test_priority_sources_come_first():
    readings.set_priority("liberation.fr", True)
    at = NOW
    cands = [
        Candidate(url="https://www.lemonde.fr/a", title="Le Monde parle du budget", origin="rss", published_at=at),
        Candidate(url="https://www.liberation.fr/b", title="Libération analyse les votes", origin="rss", published_at=at),
    ]
    out = select_candidates(cands, at - timedelta(days=1))
    assert out[0].url.startswith("https://www.liberation.fr")
    readings.set_priority("liberation.fr", False)
    registry.invalidate()


def test_locked_history_is_read_without_copy(browsers, monkeypatch):
    chrome = next(p for p in history.detect() if p.browser == "chrome")

    def locked(*a, **k):
        raise PermissionError("verrouillé par le navigateur")

    monkeypatch.setattr(history.shutil, "copy2", locked)
    assert len(history.read_visits(chrome, NOW - timedelta(days=30))) == 7


async def test_factcheck_marks_article_claims(monkeypatch):
    from openmedia.agents import factcheck
    from openmedia.agents.schemas import ExtractedClaim, Fact, FactcheckQueries, TriageItem, TriageResult, VerifyResult
    from openmedia.models import Article

    with session() as s:
        a = Article(url="https://www.lefigaro.fr/eco/budget-vote-123456", title="Le budget est voté", domain="lefigaro.fr", text="Le budget a été adopté par 300 voix selon l'Assemblée.")
        s.add(a)
        s.commit()
        s.refresh(a)
        other = Article(url="https://www.reuters.com/x-budget-vote-987654", title="Budget adopted", domain="reuters.com", text="The budget was adopted by 300 votes.")
        s.add(other)
        s.commit()
        s.refresh(other)
        r = Reading(article_id=a.id)
        s.add(r)
        s.commit()
        s.refresh(r)

    class FakeLLM:
        async def parse(self, meter, *, model, task, content, schema, **_):
            if schema is FactcheckQueries:
                return FactcheckQueries(queries_fr=["budget voté"], queries_en=["budget adopted"])
            if schema is TriageResult:
                refs = [x.split('"')[0] for x in content.split('ref="')[1:]]
                return TriageResult(items=[TriageItem(ref=x, relevance=0.9, nature="fait", sensationalism=0.0, injection=False, keep=True, reason="ok", claims=[ExtractedClaim(text="Le budget est adopté par 300 voix", kind="chiffre", due=None)]) for x in refs])
            if schema is VerifyResult:
                return VerifyResult(facts=[Fact(text="Le budget est adopté par 300 voix", refs=[f"S{a.id}", f"S{other.id}"], contradicted_by=[], status="confirme", due=None)])
            raise AssertionError(schema)

        async def search(self, *a, **k):
            return []

    async def gather(topic, spec, since, at, extra=None):
        return [(other, registry.lookup("reuters.com"), "gdelt")]

    async def no_search(*a, **k):
        return []

    monkeypatch.setattr("openmedia.agents.topic_agent.gather_articles", gather)
    monkeypatch.setattr(factcheck.gdelt, "search", no_search)
    result = await factcheck.factcheck_reading(r.id, llm=FakeLLM())
    assert result["status"] == "ok"
    [claim] = result["claims"]
    assert claim["status"] == "confirme" and claim["independent"] == 2
    with session() as s:
        assert s.get(Reading, r.id).factcheck["claims"][0]["status"] == "confirme"


def test_more_browsers_scan_and_manual_file(browsers, tmp_path):
    # Navigateurs supplémentaires connus : Comet (Chromium) et LibreWolf (Gecko)
    make_chromium(browsers / "local/Perplexity/Comet/User Data/Default/History", ROWS[:1])
    make_firefox(browsers / "roaming/librewolf/Profiles/x.default/places.sqlite", ROWS[:1])
    # Ni exploration du disque (un navigateur inconnu, une application Electron), ni client de
    # messagerie : seulement les navigateurs de la liste.
    unknown = browsers / "local/NouveauNavigateur/User Data/Default"
    make_chromium(unknown / "History", ROWS[:1])
    (unknown / "Bookmarks").write_text("{}", encoding="utf-8")
    (unknown / "Extensions").mkdir()
    make_firefox(browsers / "roaming/Thunderbird/Profiles/m.default/places.sqlite", ROWS[:1])
    found = {p.browser_name for p in history.detect()}
    assert {"Comet (Perplexity)", "LibreWolf"} <= found
    assert not found & {"NouveauNavigateur", "Thunderbird"}
    # Fichier indiqué à la main
    other = tmp_path / "copie/History"
    make_chromium(other, ROWS[:1])
    report = readings.import_history([{"path": str(other)}, {"path": str(tmp_path / "absent/History")}], 30)
    assert report["profiles"] == 1 and len(report["errors"]) == 1


def test_phone_visits_synced_into_chrome_are_labelled(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    db = tmp_path / "local/Google/Chrome/User Data/Default/History"
    make_chromium(db, [ROWS[0], ROWS[5]])
    con = sqlite3.connect(db)
    con.execute("ALTER TABLE visits ADD COLUMN originator_cache_guid TEXT DEFAULT ''")
    con.execute("UPDATE visits SET originator_cache_guid = 'telephone-pixel' WHERE url = 2")
    con.commit()
    con.close()
    chrome = next(p for p in history.detect() if p.browser == "chrome")
    by_url = {v.url: v for v in history.read_visits(chrome, NOW - timedelta(days=30))}
    assert by_url[ROWS[5][0]].synced == 1 and by_url[ROWS[0][0]].synced == 0
    assert readings._device(by_url[ROWS[5][0]]) == "telephone" and readings._device(by_url[ROWS[0][0]]) == "ordinateur"


def test_takeout_zip_with_chrome_and_my_activity(tmp_path):
    import json
    import zipfile

    from openmedia.collect import takeout

    z = tmp_path / "takeout-20261019.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("Takeout/Chrome/History.json", json.dumps({"Browser History": [{"url": ROWS[0][0], "title": ROWS[0][1], "time_usec": int(NOW.timestamp() * 1e6), "client_id": "x"}]}))
        f.writestr("Takeout/Mon activité/Google Actualités/MonActivité.json", json.dumps([
            {"header": "Google Actualités", "title": "A consulté La mairie annonce la rénovation complète de la piscine municipale", "titleUrl": "https://www.google.com/url?q=" + ROWS[5][0] + "&usg=x", "time": NOW.isoformat()},
            {"header": "Google Actualités", "title": "A recherché budget", "time": NOW.isoformat()},
        ]))
    visits = {v.url: v for v in takeout.read(str(z))}
    assert ROWS[0][0] in visits and ROWS[5][0] in visits
    assert visits[ROWS[5][0]].title.startswith("La mairie annonce")
    report = readings.import_takeout(str(z))
    assert report["articles_kept"] >= 1


def test_hidden_media_disappear_and_are_skipped(browsers):
    readings.import_history([{"browser": "chrome", "profile": "Default"}], 30)
    readings.set_hidden("petit-journal-local.fr", True, delete=True)
    with session() as s:
        from openmedia.models import Article

        rows = s.exec(select(Reading, Article).join(Article, Article.id == Reading.article_id)).all()
    assert all(a.domain != "petit-journal-local.fr" for _, a in rows)
    readings.import_history([{"browser": "chrome", "profile": "Default"}], 30)  # réimport : toujours écarté
    with session() as s:
        from openmedia.models import Article

        rows = s.exec(select(Reading, Article).join(Article, Article.id == Reading.article_id)).all()
    assert all(a.domain != "petit-journal-local.fr" for _, a in rows)
    assert "petit-journal-local.fr" in readings.diet()["hidden"]


def test_prune_drops_pages_the_filter_now_rejects():
    from openmedia.models import Article

    with session() as s:
        a = Article(url="https://www.crunchyroll.com/fr/watch/G0XHWM1JP/saison-un-episode-tres-long", title="Saison 1 un épisode - Regardez sur Crunchyroll", domain="crunchyroll.com")
        s.add(a)
        s.commit()
        s.refresh(a)
        s.add(Reading(article_id=a.id, browser="Chrome", profile="Default", visits=1))
        s.commit()
    registry.ensure("crunchyroll.com")  # inscrit « unknown » : ne doit pas passer pour un média connu
    assert readings.prune() >= 1
    with session() as s:
        assert not s.exec(select(Reading).where(Reading.article_id == a.id)).first()


def test_auto_sync_follows_the_last_import(browsers):
    """« Mes lectures » se met à jour seule : mêmes navigateurs qu'au dernier import, seulement
    les historiques modifiés, pas deux fois de suite, et jamais quand c'est désactivé."""
    from openmedia.config import update_settings

    with session() as s:
        for r in s.exec(select(Reading)).all():
            s.delete(r)
        s.commit()
    update_settings({"history_auto": True})
    before = readings.import_history([{"browser": "firefox", "profile": "abc.default-release"}], 90)["readings_total"]
    assert readings.sync_history(max_age_minutes=5) is None  # l'import vient d'avoir lieu
    # Une nouvelle lecture dans Firefox (choisi) et une dans Chrome (non choisi).
    fresh = ("https://www.lefigaro.fr/politique/le-senat-adopte-le-budget-2027-apres-une-nuit-de-debats-20261021", "Le Sénat adopte le budget 2027 après une nuit de débats", NOW)
    places = browsers / "roaming/Mozilla/Firefox/Profiles/abc.default-release/places.sqlite"
    places.unlink()
    make_firefox(places, [ROWS[0], ROWS[5], fresh])
    update_settings({"history_synced_at": (NOW - timedelta(hours=1)).isoformat()})
    report = readings.sync_history(max_age_minutes=5)
    assert report["profiles"] == 1 and report["articles_kept"] == 1
    with session() as s:
        assert len(s.exec(select(Reading)).all()) == before + 1
    update_settings({"history_auto": False, "history_synced_at": None})
    assert readings.sync_history() is None
    update_settings({"history_auto": True, "history_sources": []})
