"""Un passage complet hors ligne : collecteurs simulés et faux modèle, vraie base et vraie logique."""

import re
from datetime import timedelta

import pytest

from openmedia.agents import director, topic_agent
from openmedia.agents.schemas import (
    Announcement,
    BriefContent,
    CorrectionOut,
    BriefPoint,
    Fact,
    FicheContent,
    Item,
    NeutralityIssue,
    NeutralityReport,
    RevisePatch,
    RevisePatches,
    TimelineEvent,
    TopicSpec,
    TriageItem,
    TriageResult,
    ExtractedClaim,
    VerifyResult,
)
from openmedia.collect.base import Candidate
from openmedia.collect.extract import Extracted
from openmedia.config import Settings
from openmedia.db import session
from openmedia.models import Fiche, Run, Topic, now

REFS = re.compile(r'ref="(S\d+)"')
PLAN = "Un plan de 2,5 milliards d'euros est présenté."
REVISED = "Le plan est revu à 1,8 milliard d'euros, selon Reuters."


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.corrections = lambda refs: []

    async def parse(self, meter, *, model, task, content, schema, **_):
        self.calls.append(task)
        refs = REFS.findall(content) or re.findall(r'"(S\d+)"', content)
        if task == "spec":
            return TopicSpec(name="Plan écoles", summary="Le plan de rénovation des écoles", angle="factuel", queries_fr=["plan écoles"], queries_en=["schools plan"], keywords=["écoles"], exclusions=[], sections=[], keep_opinions=False, start_date=None)
        claim = REVISED if "1,8 milliard" in content else PLAN
        if task == "triage":
            return TriageResult(items=[TriageItem(ref=r, relevance=0.9, nature="opinion" if i == 2 else "fait", sensationalism=0.1, injection=False, keep=i != 2, reason="ok", claims=[ExtractedClaim(text=claim, kind="chiffre", due=None)]) for i, r in enumerate(refs)])
        if task == "verify":
            return VerifyResult(facts=[Fact(text=claim, refs=sorted(set(refs)), contradicted_by=[], status="confirme", due=None)])
        if task == "revise":
            return RevisePatches(patches=[RevisePatch(excerpt="présente un plan", replacement="expose un plan"), RevisePatch(excerpt="introuvable", replacement="x")])
        if task == "synth":
            cited = sorted(set(refs))[:2] + ["S9999"]
            corrections = [CorrectionOut(**c) for c in self.corrections(refs)] if "<fiche_precedente>\nAucune" not in content else []
            announce = [Announcement(text="Le gouvernement promet le vote du budget des écoles", due="2026-12", refs=cited[:1], status="a_venir")]
            return FicheContent(title="Plan écoles", lede="Le gouvernement présente un plan [S1].", state="en_cours", nothing_new=False, whats_new=[Item(text="Un plan de 2,5 milliards d'euros est présenté.", refs=cited, status="confirme", contradicted_by=[])], changes=[], key_facts=[], timeline=[TimelineEvent(date="2026-10-15", event="Présentation", refs=cited)], perspectives=[], uncertainties=[], watch=[], announcements=announce, custom_sections=[], corrections=corrections, importance=4, confidence="moyenne")
        if task == "neutrality":
            return NeutralityReport(issues=[NeutralityIssue(excerpt="présente", problem="autre", suggestion="expose")] if "revise" not in self.calls else [])
        if task == "director":
            return BriefContent(headline="Un plan pour les écoles", points=[BriefPoint(topic_id=1, topic_name="Plan écoles", text="Un plan est présenté.", why="Il engage le budget.")], cross_links=[], quiet_topics=[], audio_script="Bonjour.")
        raise AssertionError(task)

    async def raw(self, *a, **kw):
        raise AssertionError("pas de recherche Claude attendue")


TEXT = "Le gouvernement a présenté mercredi un plan de 2,5 milliards d'euros pour la rénovation des écoles, selon le ministère. {extra}"


@pytest.fixture
def offline(monkeypatch):
    at = now()
    cands = [
        Candidate(url="https://www.lemonde.fr/a", title="Écoles : un plan de rénovation", origin="une", source_name="Le Monde", published_at=at - timedelta(hours=3)),
        Candidate(url="https://www.bbc.com/b", title="France unveils school renovation plan", origin="gdelt", published_at=at - timedelta(hours=5)),
        Candidate(url="https://www.lefigaro.fr/c", title="Tribune : ce plan ne suffira pas", origin="une", published_at=at - timedelta(hours=2)),
    ]

    async def fronts_collect(keywords, since, langs):
        return [c for c in cands if c.origin == "une"]

    async def gdelt_search(queries, days, per_lang=3):
        return [c for c in cands if c.origin == "gdelt"]

    async def no_rss(*a):
        return []

    async def fetch_many(cs, concurrency=8):
        return [(c, Extracted(url=c.url, title=c.title, text=TEXT.format(extra=c.title * 20), published_at=c.published_at, author="", sitename="", lang="fr")) for c in cs]

    monkeypatch.setattr(topic_agent.fronts, "collect", fronts_collect)
    monkeypatch.setattr(topic_agent.gdelt, "search", gdelt_search)
    monkeypatch.setattr(topic_agent.rss, "collect", no_rss)
    monkeypatch.setattr(topic_agent, "fetch_many", fetch_many)
    monkeypatch.setattr(topic_agent, "load_settings", lambda: Settings(claude_search_fallback=False))


async def test_full_run_then_nothing_new_then_director(offline):
    with session() as s:
        t = Topic(name="Plan écoles", prompt="Suis le plan de rénovation des écoles")
        s.add(t)
        s.commit()
        s.refresh(t)
    llm = FakeLLM()

    first = await topic_agent.run_topic(t.id, llm=llm)
    assert first["version"] == 1 and not first["nothing_new"]
    assert llm.calls.count("revise") == 1  # la relecture a relevé un problème, corrigé une fois
    with session() as s:
        fiche = s.get(Fiche, first["fiche_id"])
        topic = s.get(Topic, t.id)
        run = s.exec(__import__("sqlmodel").select(Run).where(Run.topic_id == t.id)).first()
    assert fiche.content["lede"].startswith("Le gouvernement expose un plan")  # correctif appliqué, le reste intact
    assert any("écartés" in line and "introuvable" in line for line in run.log)
    refs = fiche.content["whats_new"][0]["refs"]
    assert "S9999" not in refs and len(refs) == 2  # la référence inventée a été retirée
    assert {s["ref"] for s in fiche.sources} == set(refs)
    assert fiche.coverage["articles"] == 2
    assert topic.spec["name"] == "Plan écoles" and topic.last_run_at is not None
    assert run.status == "done"

    second = await topic_agent.run_topic(t.id, llm=llm)  # mêmes articles : déjà connus
    assert second["version"] == 2 and second["nothing_new"]
    with session() as s:
        v2 = s.get(Fiche, second["fiche_id"])
    assert v2.content["whats_new"] == [] and v2.content["title"] == "Plan écoles"

    brief = await director.run_director(llm=llm)
    assert brief.content["headline"] == "Un plan pour les écoles"


async def test_corrections_and_announcements_follow_the_reader(offline, monkeypatch):
    from openmedia import events as ev
    from openmedia.models import Announcement as AnnouncementRow, Correction

    published = []
    monkeypatch.setattr(ev, "publish", lambda kind, **data: published.append((kind, data)))
    monkeypatch.setattr("openmedia.agents.corrections.events.publish", lambda kind, **data: published.append((kind, data)))
    with session() as s:
        t = Topic(name="Plan écoles bis", prompt="Suis le plan")
        s.add(t)
        s.commit()
        s.refresh(t)
    llm = FakeLLM()
    first = await topic_agent.run_topic(t.id, llm=llm)
    with session() as s:
        fiche1 = s.get(Fiche, first["fiche_id"])
        topic = s.get(Topic, t.id)
        topic.last_seen_at = now()  # le lecteur a ouvert la fiche
        topic.last_run_at = None  # pour que le second passage reprenne la même fenêtre
        s.add(topic)
        s.commit()
    assert "[S1]" not in fiche1.content["lede"]

    # second passage : de nouveaux articles démentent le fait publié (et une correction inventée)
    new_url = "https://www.reuters.com/z"
    async def search(keywords, since, langs):
        return [Candidate(url=new_url, title="Le plan écoles revu à 1,8 milliard", origin="une", source_name="Reuters", published_at=now())]
    monkeypatch.setattr(topic_agent.fronts, "collect", search)
    llm.corrections = lambda refs: [
        {"previous_text": "Un plan de 2,5 milliards est présenté", "previous_status": "confirme", "new_status": "corrige", "explanation": "Le montant est revu à 1,8 milliard selon Reuters.", "refs": refs[-1:]},
        {"previous_text": "Le président démissionne", "previous_status": "confirme", "new_status": "dementi", "explanation": "inventé", "refs": refs[-1:]},
    ]
    await topic_agent.run_topic(t.id, llm=llm)
    with session() as s:
        rows = s.exec(__import__("sqlmodel").select(Correction).where(Correction.topic_id == t.id)).all()
        anns = s.exec(__import__("sqlmodel").select(AnnouncementRow).where(AnnouncementRow.topic_id == t.id)).all()
    assert len(rows) == 1 and rows[0].new_status == "corrige" and rows[0].read_by_user
    assert rows[0].previous_text == "Un plan de 2,5 milliards d'euros est présenté."
    assert any(kind == "correction" for kind, _ in published)
    assert len(anns) == 1 and anns[0].due == "2026-12"  # même annonce sur deux passages : une seule ligne


async def test_a_broken_engine_is_an_error_not_a_quiet_run(offline):
    """L'IA tombe pendant le tri : le passage est en erreur, aucune fiche « rien de neuf », et le
    compteur de passages calmes (qui mène à la mise en veille) ne bouge pas."""
    from openmedia.agents.llm import LLMError

    class Broken(FakeLLM):
        async def parse(self, meter, *, model, task, content, schema, **kw):
            if task == "triage":
                raise LLMError("Mistral (403) : accès refusé")
            return await super().parse(meter, model=model, task=task, content=content, schema=schema, **kw)

    with session() as s:
        t = Topic(name="Plan écoles panne", prompt="Suis le plan")
        s.add(t)
        s.commit()
        s.refresh(t)
    with pytest.raises(LLMError):
        await topic_agent.run_topic(t.id, llm=Broken())
    from sqlmodel import select

    with session() as s:
        run = s.exec(select(Run).where(Run.topic_id == t.id)).first()
        assert run.status == "error" and "tri des articles" in run.error
        assert not s.exec(select(Fiche).where(Fiche.topic_id == t.id)).all()
        assert s.get(Topic, t.id).quiet_runs == 0


def test_prefilter_drops_pages_without_any_topic_word():
    from openmedia.models import Article, Source

    spec = {"keywords": ["écoles"], "queries_fr": ["plan rénovation écoles"], "queries_en": ["schools renovation"]}
    src = Source(domain="x.fr", name="x", owner="x")
    found = [
        (Article(id=1, url="https://x.fr/1", title="Le plan pour les écoles", domain="x.fr", text="Les écoles seront rénovées."), src, "gdelt"),
        (Article(id=2, url="https://x.fr/2", title="Résultats du match", domain="x.fr", text="Le club a gagné."), src, "gdelt"),
        (Article(id=3, url="https://x.fr/3", title="Écoles", domain="x.fr", text="Please verify you are human to continue."), src, "gdelt"),
        (Article(id=4, url="https://x.fr/4", title="Sans rapport", domain="x.fr", text="Rien."), src, "drop"),  # lien glissé : gardé
    ]
    kept, dropped = topic_agent.prefilter(found, spec)
    assert [a.id for a, _, _ in kept] == [1, 4] and dropped == 2


async def test_quiet_day_brief_costs_nothing(offline):
    """Aucune fiche n'a de neuf : le Brief est écrit par le programme, sans appel au modèle."""
    from openmedia.agents import director as director_mod

    class NoCall(FakeLLM):
        async def parse(self, *a, **k):
            raise AssertionError("aucun appel attendu")

    pairs_before = director_mod.latest_fiches
    with session() as s:
        t = Topic(name="Calme plat", prompt="p")
        s.add(t)
        s.commit()
        s.refresh(t)
        f = Fiche(topic_id=t.id, version=1, content={"whats_new": []}, nothing_new=True)
        s.add(f)
        s.commit()
        s.refresh(f)
    director_mod.latest_fiches = lambda since: [(t, f)]
    try:
        brief = await director.run_director(llm=NoCall())
    finally:
        director_mod.latest_fiches = pairs_before
    assert brief.content["points"] == [] and brief.content["quiet_topics"] == ["Calme plat"]


async def test_bing_alone_feeds_a_run_when_gdelt_and_fronts_are_empty(offline, monkeypatch):
    """Un moteur sans recherche web, GDELT saturé, rien dans les unes : Bing Actualités suffit."""
    at = now()

    async def nothing(*a, **k):
        return []

    async def bing(queries, since, per_lang=3):
        return [
            Candidate(url="https://www.ouest-france.fr/x", title="Écoles : le plan de rénovation présenté", origin="bing", source_name="Ouest-France", published_at=at - timedelta(hours=4)),
            Candidate(url="https://www.reuters.com/y", title="France school renovation plan unveiled", origin="bing", source_name="Reuters", published_at=at - timedelta(hours=6)),
        ]

    monkeypatch.setattr(topic_agent.fronts, "collect", nothing)
    monkeypatch.setattr(topic_agent.gdelt, "search", nothing)
    monkeypatch.setattr("openmedia.collect.bing_news.search", bing)
    with session() as s:
        t = Topic(name="Écoles Bing", prompt="Suis le plan de rénovation des écoles")
        s.add(t)
        s.commit()
        s.refresh(t)
    result = await topic_agent.run_topic(t.id, llm=FakeLLM())
    assert not result["nothing_new"]
    with session() as s:
        run = s.exec(__import__("sqlmodel").select(Run).where(Run.topic_id == t.id)).first()
    assert any(line.startswith("Collecte : ") and "Bing Actualités 2" in line for line in run.log), run.log
