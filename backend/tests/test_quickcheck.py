"""La vérification rapide : Haiku seul, deux appels au plus, un résultat gardé, et un statut
qui vient de la règle d'indépendance plutôt que du modèle."""

import pytest
from fastapi.testclient import TestClient

from openmedia.agents import quickcheck
from openmedia.agents.schemas import QuickClaims, QuickVerdict, QuickVerdicts
from openmedia.db import session
from openmedia.models import Article, Source
from openmedia.server import app
from openmedia.sources import registry

TEXT = "L'Assemblée nationale a adopté le budget 2027 par 312 voix contre 250, mardi soir. Le texte part au Sénat."


def _article(url: str, domain: str, text: str, title: str = "Le budget 2027 adopté") -> Article:
    with session() as s:
        a = Article(url=url, title=title, domain=domain, text=text)
        s.add(a)
        s.commit()
        s.refresh(a)
    return a


def _owner(domain: str, owner: str) -> None:
    registry.ensure(domain)
    with session() as s:
        row = s.get(Source, domain)
        row.owner, row.quality, row.quality_origin = owner, 0.9, "lin2023"  # une note établie hors IA
        s.add(row)
        s.commit()
    registry._known.cache_clear()


class FakeLLM:
    def __init__(self, verdicts):
        self.verdicts, self.calls = verdicts, []

    async def parse(self, meter, *, model, task, content, schema, **_):
        self.calls.append((model, task, content))
        meter.record(task=task, model=model, fresh=1000, output=100)
        if schema is QuickClaims:
            return QuickClaims(claims=["Le budget 2027 est adopté par 312 voix"], queries_fr=["budget 2027 adopté"], queries_en=["France budget 2027"])
        if schema is QuickVerdicts:
            return QuickVerdicts(verdicts=self.verdicts)
        raise AssertionError(schema)


@pytest.fixture
def others(monkeypatch):
    """Trois autres médias : deux du même groupe, un d'un groupe différent."""
    tag = str(id(monkeypatch))
    main = _article(f"https://journal-a.fr/budget-{tag}", "journal-a.fr", TEXT)
    _owner("journal-a.fr", "Groupe A")
    a = _article(f"https://journal-b.fr/budget-{tag}", "journal-b.fr", "Les députés ont voté le budget 2027 par 312 voix. La droite a voté contre.")
    b = _article(f"https://journal-c.fr/budget-{tag}", "journal-c.fr", "Le budget 2027 a été voté par 312 voix à l'Assemblée.")
    c = _article(f"https://journal-d.fr/budget-{tag}", "journal-d.fr", "Le budget 2027 a été adopté par 290 voix seulement.")
    _owner("journal-b.fr", "Groupe B")
    _owner("journal-c.fr", "Groupe B")
    _owner("journal-d.fr", "Groupe D")

    async def search(queries, days, per_lang=3, tries=1):
        return []

    async def gather(topic, spec, since, at, extra=None):
        return [(x, registry.lookup(x.domain), "gdelt") for x in (a, b, c)]

    monkeypatch.setattr(quickcheck.news_search, "search", search)
    monkeypatch.setattr("openmedia.agents.topic_agent.gather_articles", gather)
    return main, a, b, c


async def test_haiku_only_two_calls_then_cached(others):
    main, a, b, c = others
    llm = FakeLLM([QuickVerdict(claim=1, supports=[f"S{a.id}", "S999999"], contradicts=[], note="")])
    result = await quickcheck.quick_check(main.id, llm=llm)
    assert {m for m, _, _ in llm.calls} == {"claude-haiku-5-5"} and len(llm.calls) == 2
    [claim] = result["claims"]
    assert claim["status"] == "confirme" and claim["independent"] == 2
    assert "S999999" not in claim["refs"]  # une référence inventée est écartée
    # Un seul article par groupe : journal-c (même groupe que journal-b) n'est pas envoyé.
    assert f'ref="S{b.id}"' not in llm.calls[1][2]
    assert result["model"] == "claude-haiku-5-5" and result["cost_usd"] > 0
    again = await quickcheck.quick_check(main.id, llm=llm)
    assert len(llm.calls) == 2 and again["checked_at"] == result["checked_at"]


async def test_contradiction_and_missing_number(others):
    main, a, b, c = others
    llm = FakeLLM([QuickVerdict(claim=1, supports=[], contradicts=[f"S{c.id}"], note="290 voix selon Libération")])
    result = await quickcheck.quick_check(main.id, llm=llm, force=True)
    assert result["claims"][0]["status"] == "conteste"
    # Confirmé par un extrait qui ne contient pas le chiffre : reste à confirmer.
    a.text = "Les députés ont voté le budget 2027. La droite a voté contre."
    llm = FakeLLM([QuickVerdict(claim=1, supports=[f"S{a.id}"], contradicts=[], note="")])
    result = await quickcheck.quick_check(main.id, llm=llm, force=True)
    assert result["claims"][0]["status"] == "non_confirme" and result["claims"][0]["check"] == "chiffre_non_retrouve"


async def test_unreadable_page_without_usable_title_costs_nothing(monkeypatch):
    a = _article("https://www.lemonde.fr/illisible-1", "lemonde.fr", "", title="Vidéo")

    async def keep(article):
        return article

    async def no_teaser(url):
        return "", ""

    monkeypatch.setattr(quickcheck, "ensure_text", keep)
    monkeypatch.setattr(quickcheck, "fetch_teaser", no_teaser)
    llm = FakeLLM([])
    result = await quickcheck.quick_check(a.id, llm=llm)
    assert result["status"] == "illisible" and not llm.calls


async def test_paywalled_article_checked_from_title_and_teaser(others, monkeypatch):
    """Réservé aux abonnés : titre et chapô suffisent, et les autres médias lisibles sont
    proposés en accès libre."""
    _, a, b, c = others
    main = _article("https://journal-a.fr/abonnes-budget", "journal-a.fr", "", title="Budget 2027 : l'Assemblée adopte le texte par 312 voix")

    async def teaser(url):
        return "", "Les députés ont adopté mardi le budget 2027, par 312 voix contre 250."

    async def keep(article):
        return article

    monkeypatch.setattr(quickcheck, "ensure_text", keep)
    monkeypatch.setattr(quickcheck, "fetch_teaser", teaser)
    llm = FakeLLM([QuickVerdict(claim=1, supports=[f"S{a.id}"], contradicts=[], note="")])
    result = await quickcheck.quick_check(main.id, llm=llm)
    assert "<chapo>" in llm.calls[0][2] and "312 voix contre 250" in llm.calls[0][2]
    assert result["status"] == "ok" and result["paywalled"] and result["message"].startswith("Article réservé aux abonnés")
    assert result["claims"][0]["status"] == "confirme"
    assert {r["url"] for r in result["reads"] if r["open"]} == {a.url, c.url}


def test_route_creates_the_article(monkeypatch):
    seen = []

    async def fake(article_id, llm=None, *, force=False):
        seen.append(article_id)
        return {"status": "ok", "claims": []}

    monkeypatch.setattr(quickcheck, "quick_check", fake)
    with TestClient(app) as client:
        out = client.post("/page/quickcheck", json={"url": "https://www.lemonde.fr/politique/article/2026/10/21/nouvel-article_1.html", "title": "Un nouvel article"})
        assert out.status_code == 200 and seen
        assert client.post("/page/quickcheck", json={"url": "chrome://settings"}).status_code == 400


async def test_headlines_when_links_cannot_be_decoded(monkeypatch):
    """Les pages trouvées sont illisibles (paywall, blocage) : les titres et leur éditeur servent."""
    main = _article("https://journal-a.fr/budget-titres", "journal-a.fr", TEXT)
    _owner("journal-e.fr", "Groupe E")
    from openmedia.collect.base import Candidate

    async def search(queries, days, per_lang=3, tries=1):
        return [Candidate(url="https://journal-e.fr/budget-titres", title="Budget 2027 : adopté par 312 voix à l'Assemblée", origin="gdelt", source_name="journal-e.fr")]

    async def nothing(*a, **k):
        return []

    monkeypatch.setattr(quickcheck.news_search, "search", search)
    monkeypatch.setattr("openmedia.agents.topic_agent.gather_articles", nothing)
    llm = FakeLLM(None)

    async def parse(meter, *, model, task, content, schema, **_):
        if schema is QuickVerdicts:
            [ref] = [x.split('"')[0] for x in content.split('ref="')[1:]]
            assert "titre seul" in content
            return QuickVerdicts(verdicts=[QuickVerdict(claim=1, supports=[ref], contradicts=[], note="")])
        return await FakeLLM.parse(llm, meter, model=model, task=task, content=content, schema=schema)

    llm.parse = parse
    result = await quickcheck.quick_check(main.id, llm=llm)
    [claim] = result["claims"]
    # Un autre média connu par son seul titre ne confirme rien : on ne sait pas ce qu'il dit.
    assert claim["status"] == "non_confirme" and claim["independent"] == 2
    assert any(s["domain"] == "journal-e.fr" for s in result["sources"])
