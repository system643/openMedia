"""Suivi quotidien plus fiable : notation des médias, recoupement d'un passage à l'autre,
recherche active pour les faits à source unique, et nouvelles anciennes repérées."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlmodel import select

from openmedia.agents import freshness, qualify, topic_agent
from openmedia.agents.schemas import Fact, FreshnessResult, FreshnessVerdict, QualifyResult, SourceQualification
from openmedia.agents.synth import validate
from openmedia.agents.verify import _merge_tracked, enforce_independence
from openmedia.collect.base import Candidate
from openmedia.collect.dedupe import detect_wire
from openmedia.db import session
from openmedia.models import Article, Claim, Source, Topic
from openmedia.server import app
from openmedia.sources import quality, registry


def _art(i, domain):
    return Article(id=i, url=f"https://{domain}/{i}", title=f"t{i}", domain=domain, text="texte", wire="")


def _src(domain, owner, q=None):
    return Source(domain=domain, name=domain, owner=owner, country="US", kind="specialise", quality=q)


def _fact(text="x", refs=("S1",), status="non_confirme", **kw):
    return Fact(text=text, refs=list(refs), contradicted_by=[], status=status, due=None, **kw)


class Recorder:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    async def parse(self, meter, *, model, task, content, schema, **_):
        self.calls.append((task, content))
        return self.answers[task](content)


# ── Notation des médias ──────────────────────────────────────────────────────


def test_open_dataset_rates_known_domains_but_not_open_platforms():
    assert 0.6 < quality.rated("lemonde.fr") < 0.7
    assert quality.rated("www.techcrunch.com") == quality.rated("techcrunch.com") > 0.8
    assert quality.rated("someone.medium.com") is None  # sur une plateforme, la note ne dit rien de l'auteur
    assert quality.rated("site-inconnu-openmedia.io") is None
    assert quality.is_low(quality.rated("infowars.com"))


def test_registry_carries_the_rating():
    assert registry.lookup("https://www.lemonde.fr/x").quality_origin == "lin2023"
    fresh = registry.lookup("https://techcrunch.com/2026/10/20/x")
    assert fresh.quality and fresh.quality > 0.8


def test_low_quality_source_never_confirms():
    meta = {1: (_art(1, "techcrunch.com"), _src("techcrunch.com", "Yahoo", 0.88)), 2: (_art(2, "ferme.io"), _src("ferme.io", "ferme.io", 0.15))}
    [f] = enforce_independence([_fact(refs=["S1", "S2"], status="confirme")], meta)
    assert f.status == "non_confirme"


async def test_qualify_scores_unknown_domains_once(monkeypatch):
    with session() as s:
        s.add(Source(domain="seo-farm-test.io", name="seo-farm-test.io", owner="seo-farm-test.io"))
        s.add(Source(domain="reader-pick-test.io", name="reader-pick-test.io", owner="x", quality=0.9, quality_origin="lecteur"))
        s.commit()
    registry.invalidate()
    farm, pick = registry.lookup("seo-farm-test.io"), registry.lookup("reader-pick-test.io")
    llm = Recorder({"qualify": lambda c: QualifyResult(sources=[SourceQualification(domain="seo-farm-test.io", category="ferme_contenu", reliability="faible", name="SEO Farm", reason="Titres à mots-clés, aucun auteur.")])})
    pairs = [(_art(1, "seo-farm-test.io"), farm), (_art(2, "reader-pick-test.io"), pick)]
    assert await qualify.qualify_sources(llm, topic_agent.RunMeter(), "m", pairs) == 1
    assert "reader-pick-test.io" not in llm.calls[0][1]  # une note du lecteur n'est jamais requalifiée
    assert farm.quality == 0.1 and farm.kind == "blog" and farm.name == "SEO Farm"  # le passage en cours la voit
    stored = registry.lookup("seo-farm-test.io")
    assert stored.quality_origin == "ia" and stored.quality_note.startswith("ferme de contenu")
    assert await qualify.qualify_sources(llm, topic_agent.RunMeter(), "m", [(_art(1, "seo-farm-test.io"), stored)]) == 0
    assert len(llm.calls) == 1


def test_reader_can_override_then_reset_a_rating():
    with TestClient(app) as c:
        r = c.patch("/sources/lemonde.fr", json={"quality": 0.2}).json()
        assert r["quality"] == 0.2 and r["quality_origin"] == "lecteur"
        r = c.patch("/sources/lemonde.fr", json={"quality": None}).json()
        assert r["quality_origin"] == "lin2023" and r["quality"] == quality.rated("lemonde.fr")


def test_wire_credit_is_not_a_mere_mention():
    assert detect_wire("Le ministre, interrogé par l'AFP, a démenti. Selon l'Agence France-Presse, rien n'est décidé.") == ""
    assert detect_wire("PARIS (AFP) - Le gouvernement a présenté un plan.") == "AFP"
    assert detect_wire("The minister told the Associated Press on Monday.") == ""


# ── Recoupement d'un passage à l'autre ───────────────────────────────────────


def test_tracked_fact_is_confirmed_by_a_new_independent_source():
    yesterday = Claim(id=7, topic_id=1, text="Haiku 5.5 est annoncé", status="non_confirme", article_ids=[1])
    meta = {1: (_art(1, "programmez.com"), _src("programmez.com", "Programmez", 0.6)), 2: (_art(2, "techcrunch.com"), _src("techcrunch.com", "Yahoo", 0.88))}
    facts = [_fact(refs=["S2"], claim_id=7), _fact(text="autre", refs=["S2"], claim_id=99)]
    _merge_tracked(facts, [yesterday])
    out = enforce_independence(facts, meta)
    assert out[0].refs == ["S2", "S1"] and out[0].status == "confirme"
    assert out[1].claim_id is None and out[1].status == "non_confirme"  # identifiant inconnu : ignoré


def test_save_claims_merges_by_claim_id():
    with session() as s:
        t = Topic(name="claims", prompt="x")
        s.add(t)
        s.commit()
        s.refresh(t)
        c = Claim(topic_id=t.id, text="Texte d'hier", article_ids=[1])
        s.add(c)
        s.commit()
        s.refresh(c)
    topic_agent._save_claims(t.id, [_fact(text="Texte reformulé aujourd'hui", refs=["S2"], status="confirme", claim_id=c.id)])
    with session() as s:
        rows = s.exec(select(Claim).where(Claim.topic_id == t.id)).all()
    assert len(rows) == 1 and rows[0].article_ids == [1, 2] and rows[0].status == "confirme"


async def test_single_source_fact_gets_searched_elsewhere(monkeypatch):
    with session() as s:
        t = Topic(name="corrob", prompt="x", languages=["en"])
        s.add(t)
        a1, a2 = Article(url="https://programmez.com/haiku", title="Haiku 5.5", domain="programmez.com", text="Haiku 5.5 annoncé"), Article(url="https://techcrunch.com/haiku", title="Haiku 5.5 launches", domain="techcrunch.com", text="Haiku 5.5 launched")
        s.add(a1)
        s.add(a2)
        s.commit()
        for x in (t, a1, a2):
            s.refresh(x)
    from openmedia.agents.schemas import ExtractedClaim, TriageItem, TriageResult, VerifyResult

    queries = []

    async def find(llm, meter, model, q, since, **kw):
        queries.append(q)
        return [(a2, registry.lookup(a2.domain))]

    monkeypatch.setattr(topic_agent, "find_corroboration", find)
    def item(ref):
        return TriageItem(ref=ref, relevance=0.9, nature="fait", sensationalism=0.0, injection=False, keep=True, reason="ok", claims=[ExtractedClaim(text="Haiku 5.5 est annoncé", kind="annonce", due=None)])

    llm = Recorder({
        "qualify": lambda c: QualifyResult(sources=[]),
        "triage": lambda c: TriageResult(items=[item(f"S{a2.id}")]),
        "verify": lambda c: VerifyResult(facts=[_fact(text="Haiku 5.5 est annoncé", refs=[f"S{a1.id}", f"S{a2.id}"], status="confirme", probe="Claude Haiku 5.5")]),
    })
    meta = {a1.id: (a1, registry.lookup(a1.domain))}
    ctx = {"kept": {a1.id: item(f"S{a1.id}")}, "meta": meta, "vmeta": dict(meta), "tracked": []}
    facts = [_fact(text="Haiku 5.5 est annoncé", refs=[f"S{a1.id}"], probe="Claude Haiku 5.5")]
    out = await topic_agent._corroborate(llm, topic_agent.RunMeter(), "m", topic_agent.Settings(claude_search_fallback=False), t, 1, {"summary": "Claude"}, datetime.now(timezone.utc), facts, ctx)
    assert queries == [{"en": ["Claude Haiku 5.5"]}]
    assert out[0].status == "confirme" and a2.id in ctx["kept"]
    with session() as s:
        link = s.get(topic_agent.TopicArticle, (t.id, a2.id))
    assert link.kept and link.origin == "recoupement"


# ── Nouvelles anciennes ──────────────────────────────────────────────────────


async def test_old_event_date_marks_fact_as_already_reported():
    start = datetime(2026, 10, 19, tzinfo=timezone.utc)
    facts = [_fact(event_date="2026-09-15"), _fact(event_date="2026-10-18"), _fact(event_date="2026-09")]
    await freshness.mark_stale(Recorder({}), topic_agent.RunMeter(), "m", facts, start)
    assert [f.first_reported for f in facts] == ["2026-09-15", None, "2026-09-30"]


async def test_older_headlines_on_the_same_event_age_the_fact(monkeypatch):
    start = datetime(2026, 10, 19, tzinfo=timezone.utc)

    async def search(query, days):
        assert days == freshness.LOOKBACK_DAYS
        return [
            Candidate(url="https://a", title="Anthropic launches Claude Haiku 5.5", origin="gdelt", source_name="The Verge", published_at=datetime(2026, 9, 2, tzinfo=timezone.utc)),
            Candidate(url="https://b", title="Claude Haiku 5.5 rumor", origin="gdelt", source_name="Blog", published_at=datetime(2026, 8, 20, tzinfo=timezone.utc)),
            Candidate(url="https://c", title="Haiku 5.5 : 75 % moins cher", origin="gdelt", source_name="Programmez", published_at=datetime(2026, 10, 19, tzinfo=timezone.utc)),
        ]

    monkeypatch.setattr(freshness.gdelt, "search_any", search)
    seen = {}

    def judge(content):
        seen["content"] = content
        return FreshnessResult(items=[FreshnessVerdict(fact=0, same_event=["H2"]), FreshnessVerdict(fact=1, same_event=[])])

    facts = [_fact(text="Anthropic annonce Haiku 5.5", probe="Claude Haiku 5.5"), _fact(text="Haiku 5.5 arrive dans Claude Code", probe="Haiku 5.5 Claude Code")]
    assert await freshness.mark_stale(Recorder({"freshness": judge}), topic_agent.RunMeter(), "m", facts, start) == 1
    assert facts[0].first_reported == "2026-09-02" and facts[1].first_reported is None
    assert "Programmez" not in seen["content"]  # un titre du jour n'est pas un antécédent


def test_stale_news_leaves_whats_new_for_key_facts():
    facts = [_fact(refs=["S1"]), _fact(refs=["S2", "S3"])]
    facts[0].first_reported = "2026-09-02"
    stale = freshness.stale_index(facts)
    assert stale["refs"] == {"S1": "2026-09-02"}
    content = {
        "whats_new": [{"text": "Haiku 5.5 est annoncé.", "refs": ["S1"], "status": "non_confirme"}, {"text": "Autre chose.", "refs": ["S2"], "status": "non_confirme"}],
        "key_facts": [], "timeline": [], "perspectives": [], "announcements": [], "custom_sections": [], "changes": [], "nothing_new": False,
    }
    out = validate(content, {1: "Haiku", 2: "Autre", 3: "x"}, stale)
    assert [i["text"] for i in out["whats_new"]] == ["Autre chose."]
    assert out["key_facts"][0]["first_reported"] == "2026-09-02"


def test_window_start_is_compared_with_a_margin():
    start = datetime(2026, 10, 19, tzinfo=timezone.utc)
    assert freshness.event_day("2026-10-17") >= (start - freshness.MARGIN).date()
    assert freshness.event_day("nimporte") is None
    assert timedelta(days=3) == freshness.MARGIN


def test_stale_fact_is_recognised_even_when_its_article_also_brings_news():
    old = _fact(text="Selon The Information, Meta a réduit ses utilisateurs de Claude Code de 60 000 à 30 000.", refs=["S5"])
    old.first_reported = "2026-10-05"
    facts = [old, _fact(text="Selon The Information, Meta a dépensé 105 millions de dollars en 28 jours.", refs=["S5"])]
    content = {
        "whats_new": [
            {"text": "Meta a réduit ses utilisateurs de Claude Code de 60 000 à 30 000, selon The Information.", "refs": ["S5"], "status": "non_confirme"},
            {"text": "Meta a dépensé 105 millions de dollars en Claude Code sur 28 jours.", "refs": ["S5"], "status": "non_confirme"},
        ],
        "key_facts": [], "timeline": [], "perspectives": [], "announcements": [], "custom_sections": [], "changes": [], "nothing_new": False,
    }
    out = validate(content, {5: "60 000 30 000 105 millions 28 jours"}, freshness.stale_index(facts))
    assert [i["text"][:14] for i in out["whats_new"]] == ["Meta a dépensé"]
    assert out["key_facts"][0]["first_reported"] == "2026-10-05"
