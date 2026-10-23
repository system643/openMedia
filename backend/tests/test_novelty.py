"""Que du neuf : un article en retard qui redit un fait connu n'en refait pas une nouveauté.
Il est compté (reprise), il appuie ou confirme le fait, ou il le rectifie ; sans rien de
nouveau, la fiche est reconduite sans appel au modèle de synthèse."""

from datetime import datetime, timedelta, timezone

from sqlmodel import select

from openmedia.agents import novelty, topic_agent
from openmedia.agents.schemas import Fact
from openmedia.collect.base import Candidate
from openmedia.db import session
from openmedia.models import Article, Claim, Fiche, Source, Topic, TopicArticle, now

from test_pipeline import PLAN, FakeLLM, offline  # noqa: F401 — `offline` est une fixture


def _art(i, domain, wire=""):
    return Article(id=i, url=f"https://{domain}/{i}", title=f"t{i}", domain=domain, text="texte", wire=wire)


def _src(domain, owner):
    return Source(domain=domain, name=domain.split(".")[0].capitalize(), owner=owner, country="FR", kind="national", quality=0.8)


META = {i: (_art(i, d), _src(d, o)) for i, (d, o) in enumerate([("lemonde.fr", "Le Monde"), ("lefigaro.fr", "Dassault"), ("liberation.fr", "Libé"), ("bfmtv.com", "Altice"), ("leparisien.fr", "LVMH")], start=1)}


def _fact(text="Le projet est écrit en Rust.", refs=("S1",), status="non_confirme", **kw):
    return Fact(text=text, refs=list(refs), contradicted_by=[], status=status, due=None, **kw)


def _claim(cid, status, ids, text="Le projet est écrit en Rust."):
    return Claim(id=cid, topic_id=1, text=text, status=status, article_ids=list(ids))


def test_each_fact_gets_its_kind():
    known = [_claim(1, "confirme", [1, 2]), _claim(2, "non_confirme", [1]), _claim(3, "confirme", [1, 2, 3]), _claim(4, "confirme", [1, 2]), _claim(5, "non_confirme", [1])]
    facts = [
        _fact("Un fait inconnu", refs=["S4"]),
        _fact("Un fait ancien", refs=["S4"], first_reported="2026-09-01"),
        _fact(refs=["S4", "S1", "S2"], status="confirme", claim_id=1, known_status="confirme"),  # 2 médias : la source s'ajoute
        _fact(refs=["S4", "S1"], status="confirme", claim_id=2, known_status="non_confirme"),  # enfin confirmé
        _fact(refs=["S4", "S1", "S2", "S3"], status="confirme", claim_id=3, known_status="confirme"),  # déjà 3 médias
        _fact(refs=["S4", "S1", "S2"], status="conteste", claim_id=4, known_status="confirme"),  # contredit
        _fact(refs=["S1"], status="non_confirme", claim_id=5, known_status="non_confirme"),  # rien de plus
    ]
    summary = novelty.classify(facts, META, known)
    assert [f.novelty for f in facts] == ["nouveau", "deja_paru", "appui", "confirmation", "reprise", "rectification", "reprise"]
    assert facts[2].new_refs == ["S4"] and facts[2].new_media == ["Bfmtv"]
    assert facts[4].new_refs == ["S4"]  # une reprise garde ses articles du jour, pour les compter
    assert summary == {"new": 1, "late": 1, "rectifications": 1, "confirmations": 2, "reprises": 2}
    assert novelty.has_news(facts) and not novelty.has_news(facts[1:5])


def test_same_wire_adds_no_independent_source():
    meta = {**META, 6: (_art(6, "ouest-france.fr", wire="AFP"), _src("ouest-france.fr", "Sipa")), 7: (_art(7, "sudouest.fr", wire="AFP"), _src("sudouest.fr", "Sud Ouest"))}
    known = [_claim(1, "non_confirme", [6])]
    [f] = [_fact(refs=["S7", "S6"], claim_id=1, known_status="non_confirme")]
    novelty.classify([f], meta, known)
    assert f.novelty == "reprise"  # la même dépêche AFP n'apprend rien


def test_near_identical_fact_is_attached_without_the_model():
    known = [_claim(9, "confirme", [1, 2], text="Les applications Pinceau sont écrites en Rust.")]
    facts = [_fact("Les applications Pinceau sont écrites en Rust", refs=["S4"]), _fact("Bobine sort en version 1.0", refs=["S4"])]
    novelty.attach(facts, known)
    assert facts[0].claim_id == 9 and facts[1].claim_id is None


def test_known_claims_brings_back_settled_facts_close_to_today():
    with session() as s:
        t = Topic(name="connus", prompt="x")
        s.add(t)
        s.commit()
        s.refresh(t)
        s.add(Claim(topic_id=t.id, text="Les applications Pinceau sont écrites en Rust.", status="confirme", article_ids=[]))
        s.add(Claim(topic_id=t.id, text="Le budget 2027 prévoit 12 milliards d'économies.", status="confirme", article_ids=[]))
        s.add(Claim(topic_id=t.id, text="Selon un message viral, REA dépasse 100 000 étoiles.", status="non_confirme", article_ids=[]))
        s.add(Claim(topic_id=t.id, text="Fait confirmé il y a deux mois sur Pinceau en Rust.", status="confirme", article_ids=[], last_seen=now() - timedelta(days=60)))
        s.commit()
    claims, _ = novelty.known_claims(t.id, now(), ["Selon le Snap Store, les applications Pinceau sont écrites en Rust."])
    texts = [c.text for c in claims]
    assert texts[0].startswith("Selon un message viral")  # les faits ouverts d'abord, toujours
    assert "Les applications Pinceau sont écrites en Rust." in texts
    assert not any("budget" in x or "deux mois" in x for x in texts)


def test_confirmed_fact_never_drops_back_when_matched_by_text():
    with session() as s:
        t = Topic(name="statut", prompt="x")
        s.add(t)
        s.commit()
        s.refresh(t)
        s.add(Claim(topic_id=t.id, text="Le plan est voté.", status="confirme", article_ids=[1, 2]))
        s.commit()
    topic_agent._save_claims(t.id, [_fact("Le plan est voté.", refs=["S3"], status="non_confirme")])
    with session() as s:
        [c] = s.exec(select(Claim).where(Claim.topic_id == t.id)).all()
    assert c.status == "confirme" and c.article_ids == [1, 2, 3]


def test_carry_forward_updates_statuses_and_sources():
    previous = {"title": "x", "importance": 4, "whats_new": [{"text": "vieux", "refs": ["S1"], "status": "confirme"}], "corrections": [{"previous_text": "a"}], "key_facts": [{"text": "Selon Le Monde, le projet est écrit en Rust.", "refs": ["S1"], "status": "non_confirme", "contradicted_by": []}]}
    f = _fact(refs=["S4", "S1"], status="confirme", claim_id=2, known_status="non_confirme", known_text="Le projet est écrit en Rust.")
    f.novelty, f.new_refs = "confirmation", ["S4"]
    content = novelty.carry_forward(previous, [f])
    assert content["whats_new"] == [] and content["corrections"] == [] and content["importance"] == 0 and content["nothing_new"]
    assert content["key_facts"][0]["status"] == "confirme" and content["key_facts"][0]["refs"] == ["S1", "S4"]
    assert previous["key_facts"][0]["status"] == "non_confirme"  # la version précédente n'est pas touchée


def test_window_follows_a_spaced_rhythm():
    at = datetime(2026, 10, 22, 8, tzinfo=timezone.utc)
    t = Topic(name="x", prompt="x", last_run_at=at - timedelta(days=9))
    assert topic_agent.window(t, at) == at - timedelta(days=7)
    assert topic_agent.window(t, at, every=10) == at - timedelta(days=9, hours=6)


# ── Un passage complet ───────────────────────────────────────────────────────


async def test_late_article_on_a_known_fact_is_not_news(offline, monkeypatch):
    with session() as s:
        t = Topic(name="Plan écoles retard", prompt="Suis le plan")
        s.add(t)
        s.commit()
        s.refresh(t)
    llm = FakeLLM()
    first = await topic_agent.run_topic(t.id, llm=llm)
    assert not first["nothing_new"]

    async def late(url, title, source):
        async def search(keywords, since, langs):
            return [Candidate(url=url, title=title, origin="une", source_name=source, published_at=now())]

        monkeypatch.setattr(topic_agent.fronts, "collect", search)
        with session() as s:
            topic = s.get(Topic, t.id)
            topic.last_run_at = None
            s.add(topic)
            s.commit()
        llm.calls.clear()
        return await topic_agent.run_topic(t.id, llm=llm)

    # Un troisième média redit le fait déjà confirmé par deux : appui, sans rédaction.
    second = await late("https://www.reuters.com/plan", "School plan: 2.5 billion euros", "Reuters")
    assert second["nothing_new"]
    assert "synth" not in llm.calls and "neutrality" not in llm.calls and "revise" not in llm.calls
    with session() as s:
        v2 = s.get(Fiche, second["fiche_id"])
    assert v2.content["whats_new"] == [] and v2.content["importance"] == 0
    [conf] = v2.content["updates"]["confirmations"]
    assert conf["kind"] == "appui" and conf["text"] == PLAN and len(conf["refs_new"]) == 1
    assert v2.novelty["synth_skipped"] and v2.novelty["new"] == 0 and v2.novelty["confirmations"] == 1

    # Un quatrième : le fait a déjà trois médias, c'est une simple reprise, comptée.
    third = await late("https://www.francetvinfo.fr/plan", "Plan pour les écoles : 2,5 milliards", "franceinfo")
    with session() as s:
        v3 = s.get(Fiche, third["fiche_id"])
    assert third["nothing_new"] and v3.content["updates"]["confirmations"] == []
    assert v3.content["updates"]["reprises"]["articles"] == 1 and v3.novelty["reprises"] == 1

    # Le même titre repris ailleurs : écarté avant même le tri.
    fourth = await late("https://www.msn.com/fr-fr/ecoles", "Écoles : un plan de rénovation", "MSN")
    assert "triage" not in llm.calls and fourth["nothing_new"]
    with session() as s:
        link = s.exec(select(TopicArticle).join(Article, Article.id == TopicArticle.article_id).where(TopicArticle.topic_id == t.id, Article.url == "https://msn.com/fr-fr/ecoles")).first()
        v4 = s.get(Fiche, fourth["fiche_id"])
    assert link and not link.kept and link.reason.startswith("Reprise de « Écoles : un plan de rénovation »")
    assert v4.content["updates"]["reprises"]["articles"] == 1
