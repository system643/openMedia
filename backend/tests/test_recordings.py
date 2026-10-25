"""Les enregistrements : repérer un article ouvert, le mettre de côté, rassembler des sources."""

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from openmedia.agents import recordings
from openmedia.agents.schemas import Dossier, DossierPoint, FactcheckQueries, TriageItem, TriageResult
from openmedia.db import session
from openmedia.models import Article, DroppedLink, Recording, Topic
from openmedia.server import app
from openmedia.sources import registry

ARTICLE = "https://www.lemonde.fr/politique/article/2026/10/19/le-budget-est-adopte-par-l-assemblee_6123456_823448.html"
TITLE = "Le budget est adopté par l'Assemblée nationale"


@pytest.fixture(autouse=True)
def no_fetch(monkeypatch):
    async def keep(article):
        return article

    monkeypatch.setattr(recordings, "ensure_text", keep)


def test_check_page_recognises_articles_only():
    assert recordings.check_page(ARTICLE, TITLE)["is_article"]
    assert not recordings.check_page("https://www.lemonde.fr/", "Le Monde.fr - Actualités et infos en France et dans le monde")["is_article"]
    assert not recordings.check_page("https://www.youtube.com/watch?v=abc", "Une vidéo quelconque sur YouTube, assez longue")["is_article"]


def test_save_is_idempotent_and_listed():
    with TestClient(app) as c:
        first = c.post("/recordings", json={"url": ARTICLE + "?utm_source=twitter", "title": TITLE}).json()
        again = c.post("/recordings", json={"url": ARTICLE, "title": TITLE}).json()
        assert first["id"] == again["id"] and first["status"] == "enregistre"
        assert [r["id"] for r in c.get("/recordings").json()].count(first["id"]) == 1
        assert c.post("/page/check", json={"url": ARTICLE, "title": TITLE}).json()["recording_id"] == first["id"]
        assert c.post("/recordings", json={"url": "file:///C:/x.html"}).status_code == 400
        assert c.delete(f"/recordings/{first['id']}").json()["ok"]
        assert c.post("/page/check", json={"url": ARTICLE, "title": TITLE}).json()["recording_id"] is None


def test_assign_then_topic_deletion_releases_the_recording():
    rec = recordings.save(ARTICLE.replace("6123456", "6123457"), TITLE)
    with session() as s:
        t = Topic(name="Budget", prompt="Suis le budget")
        s.add(t)
        s.commit()
        s.refresh(t)
    with TestClient(app) as c:
        out = c.post(f"/recordings/{rec.id}/assign", json={"topic_id": t.id}).json()
        assert out["status"] == "suivi" and out["topic_id"] == t.id
        with session() as s:
            assert s.exec(select(DroppedLink).where(DroppedLink.topic_id == t.id)).first()
        c.delete(f"/topics/{t.id}")
        assert recordings.get(rec.id)["status"] == "enregistre"


async def test_gather_keeps_only_sourced_points(monkeypatch):
    rec = recordings.save(ARTICLE.replace("6123456", "6123458"), TITLE)
    with session() as s:
        a = s.get(Article, s.get(Recording, rec.id).article_id)
        a.text = "Le budget a été adopté par 300 voix."
        s.add(a)
        other = Article(url="https://www.reuters.com/budget-adopted-987650", title="Budget adopted", domain="reuters.com", text="The budget was adopted by 300 votes.")
        s.add(other)
        s.commit()
        s.refresh(a)
        s.refresh(other)
    pairs = [(a, registry.lookup(a.domain)), (other, registry.lookup("reuters.com"))]

    async def check(article_id, llm, meter, coverage_anyway=False):
        assert coverage_anyway
        return {"status": "rien", "claims": [], "sources": [], "others": 1}, pairs

    class FakeLLM:
        async def parse(self, meter, *, model, task, content, schema, **_):
            assert task == "dossier" and schema is Dossier and f'ref="S{other.id}"' in content
            return Dossier(
                summary="Le budget est adopté [S1].",
                points=[
                    DossierPoint(text=f"Le texte est adopté par 300 voix [S{a.id}].", refs=[f"S{a.id}", f"S{other.id}"]),
                    DossierPoint(text="Il crée 12 500 postes.", refs=[f"S{a.id}"]),
                    DossierPoint(text="Un point inventé.", refs=["S999999"]),
                ],
                context=[],
                open_questions=["Le Sénat suivra-t-il ?"],
                next_steps="",
            )

    monkeypatch.setattr(recordings, "check_article", check)
    assert recordings.mark_gathering(rec.id)
    assert not recordings.mark_gathering(rec.id)  # déjà en cours
    dossier = await recordings.gather(rec.id, llm=FakeLLM())
    assert dossier["status"] == "ok"
    points = dossier["synthesis"]["points"]
    assert len(points) == 2 and points[0]["text"] == "Le texte est adopté par 300 voix." and "check" not in points[0]
    assert points[1]["check"] == "chiffre_non_retrouve"
    assert dossier["synthesis"]["summary"] == "Le budget est adopté."
    assert recordings.get(rec.id)["dossier"]["status"] == "ok"


async def test_gather_reports_errors(monkeypatch):
    rec = recordings.save(ARTICLE.replace("6123456", "6123459"), TITLE)

    async def broken(*a, **k):
        raise RuntimeError("Aucun moteur IA")

    monkeypatch.setattr(recordings, "check_article", broken)
    dossier = await recordings.gather(rec.id, llm=object())
    assert dossier == {**dossier, "status": "erreur", "message": "Aucun moteur IA"}


async def test_coverage_without_claims(monkeypatch):
    """Un article sans affirmation vérifiable : on cherche quand même qui en parle."""
    from openmedia.agents import factcheck

    with session() as s:
        a = Article(url="https://www.liberation.fr/idees/tribune-budget-2026-10-19-abcdef", title="Tribune sur le budget", domain="liberation.fr", text="Une opinion sur le budget.")
        b = Article(url="https://www.ouest-france.fr/budget-vote-2026-10-19-123456", title="Le budget voté", domain="ouest-france.fr", text="Le budget a été voté.")
        c = Article(url="https://www.lequipe.fr/football-2026-10-19-654321", title="Un match", domain="lequipe.fr", text="Un match de football.")
        for x in (a, b, c):
            s.add(x)
        s.commit()
        for x in (a, b, c):
            s.refresh(x)

    class FakeLLM:
        async def parse(self, meter, *, model, task, content, schema, **_):
            if schema is FactcheckQueries:
                return FactcheckQueries(queries_fr=["budget"], queries_en=["budget"])
            refs = [x.split('"')[0] for x in content.split('ref="')[1:]]
            return TriageResult(items=[TriageItem(ref=r, relevance=0.9 if r != f"S{c.id}" else 0.1, nature="opinion" if r == f"S{a.id}" else "fait", sensationalism=0.0, injection=False, keep=r != f"S{c.id}", reason="", claims=[]) for r in refs])

        async def search(self, *a, **k):
            return []

    async def gather_articles(topic, spec, since, at, extra=None):
        return [(b, registry.lookup(b.domain), "gdelt"), (c, registry.lookup(c.domain), "gdelt")]

    async def no_search(*a, **k):
        return []

    monkeypatch.setattr("openmedia.agents.topic_agent.gather_articles", gather_articles)
    monkeypatch.setattr(factcheck.news_search, "search", no_search)
    from openmedia.agents.llm import RunMeter

    result, pairs = await factcheck.check_article(a.id, FakeLLM(), RunMeter(), coverage_anyway=True)
    assert result["status"] == "rien" and result["others"] == 1
    assert [x.id for x, _ in pairs] == [a.id, b.id]
