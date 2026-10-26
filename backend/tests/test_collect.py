from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import respx

from openmedia.agents.llm import RunMeter
from openmedia.agents.topic_agent import collect_summary, select_candidates
from openmedia.collect import bing_news, claude_search, fronts, gdelt, news_search, rss
from openmedia.config import update_settings
from openmedia.collect.base import Candidate, parse_date

FEED = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Élection municipale : résultats</title><link>https://ex.fr/a</link><pubDate>Sun, 19 Oct 2026 08:00:00 GMT</pubDate><description>Les résultats du scrutin</description></item>
<item><title>Recette de la tarte</title><link>https://ex.fr/b</link><pubDate>Sun, 19 Oct 2026 08:00:00 GMT</pubDate></item>
<item><title>Vieille élection</title><link>https://ex.fr/c</link><pubDate>Mon, 01 Sep 2026 08:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_fronts_are_balanced_and_filtered(monkeypatch):
    # Autant de titres à gauche qu'à droite dans les unes françaises (voir sources/EQUILIBRE.md).
    names = {n for n, _ in fronts.FRONTS["fr"]}
    assert len(names & {"Libération", "L'Humanité"}) == len(names & {"Le Figaro", "L'Opinion"})
    assert all(url.startswith("https://") for feeds in fronts.FRONTS.values() for _, url in feeds)


def test_gdelt_query_without_language():
    assert "sourcelang" not in gdelt.query_url("budget", None, 90)
    assert "sourcelang%3Afrench" in gdelt.query_url("budget", "fr", 3) and "timespan=3d" in gdelt.query_url("budget", "fr", 3)


def test_gdelt_parse():
    payload = {"articles": [{"url": "https://bbc.com/x", "title": "AI Act", "seendate": "20261018T101500Z", "domain": "bbc.com", "sourcecountry": "United Kingdom"}, {"url": "", "title": "vide"}]}
    [c] = gdelt.parse(payload, "en")
    assert c.published_at == datetime(2026, 10, 18, 10, 15, tzinfo=timezone.utc)
    assert c.extra["country"] == "United Kingdom"


def test_rss_filters_keywords_accents_and_dates():
    since = datetime(2026, 10, 12, tzinfo=timezone.utc)
    out = rss.parse(FEED, ["election"], since)
    assert [c.url for c in out] == ["https://ex.fr/a"]


def test_parse_date_formats():
    assert parse_date("2026-10-18T10:00:00Z").hour == 10
    assert parse_date("Sat, 18 Oct 2026 09:00:00 GMT").day == 18
    assert parse_date("n'importe quoi") is None


def test_select_candidates_prefers_known_sources_and_caps_each():
    at = datetime(2026, 10, 19, tzinfo=timezone.utc)
    since = at - timedelta(days=7)
    cands = [Candidate(url=f"https://blog-obscur.fr/{i}", title=["Pluie", "Soleil", "Neige", "Vent", "Orage", "Brume", "Gel", "Grêle", "Canicule", "Tempête"][i] + f" sur la région {i}", origin="rss", published_at=at) for i in range(10)]
    cands += [Candidate(url="https://www.lemonde.fr/a", title="Article du Monde sur la loi", origin="rss", published_at=at)]
    cands += [Candidate(url="https://www.lemonde.fr/old", title="Ancien article hors fenêtre", origin="rss", published_at=since - timedelta(days=1))]
    out = select_candidates(cands, since)
    assert out[0].url == "https://www.lemonde.fr/a"
    assert sum("blog-obscur" in c.url for c in out) == 3
    assert all("old" not in c.url for c in out)


def test_select_candidates_drops_near_duplicate_titles():
    at = datetime(2026, 10, 19, tzinfo=timezone.utc)
    cands = [
        Candidate(url="https://www.lemonde.fr/a", title="Le Sénat adopte le projet de loi sur l'IA", origin="rss", published_at=at),
        Candidate(url="https://www.lefigaro.fr/b", title="Le Sénat adopte le projet de loi sur l’IA", origin="rss", published_at=at),
    ]
    assert len(select_candidates(cands, at - timedelta(days=1))) == 1


@respx.mock
async def test_gdelt_rests_after_repeated_refusals(monkeypatch):
    monkeypatch.setattr(gdelt.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(gdelt, "_cool_until", 0.0)
    route = respx.get(url__startswith=gdelt.API).respond(429, text="Please limit requests to one every 5 seconds")
    assert await gdelt.search({"fr": ["budget", "écoles"], "en": ["budget"]}, 3) == []
    assert route.call_count == gdelt.TRIES  # tous les essais refusés : GDELT se repose, l'anglais n'est pas envoyé
    assert gdelt.resting()
    monkeypatch.setattr(gdelt, "_cool_until", 0.0)


# GDELT n'échappe pas la barre oblique inverse du titre (relevé le 26/10/2026) : JSON invalide.
GDELT_RAW = '{"articles": [ { "url": "https://ultimateclassicrock.com/peter-gabriel-oi-album/", "title": "Peter Gabriel Announces Details For New Album  o \\ i  ", "seendate": "20261001T190000Z", "domain": "ultimateclassicrock.com", "language": "English", "sourcecountry": "United States" }, { "url": "https://ex.fr/a", "title": "Chemin C:\\\\temp et \\u00e9t\\u00e9", "seendate": "20261002T080000Z", "domain": "ex.fr" } ] }'


def test_gdelt_reads_its_badly_escaped_json():
    import json

    with pytest.raises(ValueError):
        json.loads(GDELT_RAW)
    a, b = gdelt.parse(gdelt.load(GDELT_RAW), "en")
    assert a.title == "Peter Gabriel Announces Details For New Album  o \\ i"
    assert b.title == "Chemin C:\\temp et été"  # les échappements valides restent intacts
    assert gdelt.load("Your query was too short or too long.") == {} and gdelt.load("[]") == {}


@respx.mock
async def test_gdelt_one_query_per_language_by_relevance_retried(monkeypatch):
    monkeypatch.setattr(gdelt.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(gdelt, "_cool_until", 0.0)
    route = respx.get(url__startswith=gdelt.API).mock(side_effect=[respx.MockResponse(429, text="Please limit requests"), respx.MockResponse(200, text=GDELT_RAW), respx.MockResponse(200, text="Phrase too short")])
    found = await gdelt.search({"fr": ["", "Peter Gabriel album", "Peter Gabriel concert"], "en": ["Peter Gabriel new album", "Peter Gabriel tour"]}, 30)
    sent = [str(c.request.url) for c in route.calls]
    assert len(sent) == 3 and "Peter+Gabriel+album" in sent[0] and sent[0] == sent[1] and "new+album" in sent[2]  # un refus réessayé, puis une requête par langue
    assert all("sort" not in u and "maxrecords=100" in u and "timespan=30d" in u for u in sent)  # pertinence (HybridRel), pas DateDesc
    assert len(found) == 2 and not gdelt.resting()


async def _no_sleep(_):
    return None


@respx.mock
async def test_pages_are_read_for_the_reader(monkeypatch):
    """openMedia lit la page pour son lecteur : une réservation TDM ne la ferme plus ; une page
    payante reste fermée (aucun contournement), son titre est gardé."""
    from openmedia.collect import base, extract

    monkeypatch.setattr(extract, "client", lambda guard=False, **kw: base.client(**kw))  # pas de résolution DNS

    body = "<html><body><article>" + "<p>Le conseil municipal a voté le budget des écoles ce mardi soir.</p>" * 5 + "</article></body></html>"
    reserved = respx.get("https://reserve.example/a").respond(200, html=body, headers={"tdm-reservation": "1"})
    respx.get("https://ferme.example/b").respond(402)
    cands = [Candidate(url=u, title="t", origin="gdelt") for u in ("https://reserve.example/a", "https://ferme.example/b")]
    out = await extract.fetch_many(cands)
    assert reserved.called and "budget des écoles" in out[0][1].text
    assert out[1][1] is None


def test_rss_keeps_the_full_text_when_the_feed_has_it():
    article = "<p>" + "Le texte complet de l'article publié dans le flux. " * 40 + "</p>"
    xml = f"""<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
    <item><title>Budget des écoles</title><link>https://ex.fr/a</link><description>Court résumé</description>
    <content:encoded><![CDATA[{article}]]></content:encoded></item></channel></rss>"""
    [c] = rss.parse(xml, ["écoles"], datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert len(c.snippet) > 1500 and "<p>" not in c.snippet


async def test_open_ratings_are_downloaded_only_after_consent(monkeypatch, tmp_path):
    from openmedia.config import update_settings
    from openmedia.sources import quality

    monkeypatch.setattr(quality, "dataset_path", lambda: tmp_path / "domain_quality.csv")
    update_settings({"consent_at": None})
    try:
        assert not quality.ensure_dataset()
        update_settings({"consent_at": "2026-01-01T00:00:00+00:00"})
        body = "domain,pc1\n" + "".join(f"site{i}.org,0.5\n" for i in range(1200))
        with respx.mock:
            respx.get(quality.DATASET_URL).respond(200, text=body)
            assert quality.ensure_dataset()
        assert quality.rated("site7.org") == 0.5
    finally:
        update_settings({"consent_at": "2026-01-01T00:00:00+00:00"})
        quality.dataset.cache_clear()


# ── Bing Actualités : la recherche datée sans clé, quel que soit le moteur IA ──

BING = (Path(__file__).parent / "fixtures" / "bing_news.xml").read_bytes()  # au format exact de Bing (relevé le 25/10/2026), contenu fictif


def test_bing_feed_gives_real_links_dates_and_sources():
    found = bing_news.parse(BING, "fr")
    assert len(found) == 10  # 12 résultats, dont 2 reprises MSN écartées
    assert all(c.origin == "bing" and c.url.startswith("https://") and "bing.com" not in c.url and "msn.com" not in c.url for c in found)
    monde = next(c for c in found if c.source_name == "Le Monde")
    assert monde.url.startswith("https://www.lemonde.fr/") and monde.published_at == datetime(2026, 10, 23, 9, 21, tzinfo=timezone.utc) and monde.snippet
    assert bing_news.real_url("https://ex.fr/direct") == "https://ex.fr/direct"


@pytest.fixture
def bing_on():
    bing_news._cache.clear()
    update_settings({"bing_news": True})
    yield
    update_settings({"bing_news": False})
    bing_news._cache.clear()


@respx.mock
async def test_bing_search_keeps_the_window_and_can_be_switched_off(monkeypatch, bing_on):
    monkeypatch.setattr(bing_news.asyncio, "sleep", _no_sleep)
    route = respx.get(url__startswith=bing_news.API).respond(200, content=BING)
    found = await bing_news.search({"fr": ["budget de la Sécu"]}, datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert found and all(c.published_at >= datetime(2026, 10, 23, tzinfo=timezone.utc) for c in found)
    assert "setlang=fr-FR" in str(route.calls[0].request.url) and "interval" in str(route.calls[0].request.url)
    assert "interval%3D%227%22" in bing_news.query_url("x", "fr", 1) and "interval%3D%228%22" in bing_news.query_url("x", "fr", 3) and "qft" not in bing_news.query_url("x", "fr", 90)
    update_settings({"bing_news": False})
    bing_news._cache.clear()
    assert await bing_news.search({"fr": ["budget"]}, datetime(2026, 10, 1, tzinfo=timezone.utc)) == [] and route.call_count == 1


@respx.mock
async def test_bing_takes_over_when_gdelt_is_saturated(monkeypatch, bing_on):
    monkeypatch.setattr(gdelt.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(bing_news.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(gdelt, "_cool_until", 0.0)
    respx.get(url__startswith=gdelt.API).respond(429, text="Please limit requests to one every 5 seconds")
    respx.get(url__startswith=bing_news.API).respond(200, content=BING)
    found = await news_search.search({"fr": ["budget de la Sécu"]}, 30, per_lang=2)
    assert len(found) == 10 and len({c.url for c in found}) == 10  # deux fois le même flux : chaque article une seule fois
    assert "GDELT 0 (saturé)" in collect_summary(found) and "Bing Actualités 10" in collect_summary(found)
    monkeypatch.setattr(gdelt, "_cool_until", 0.0)


@respx.mock
async def test_complement_search_without_model_search_uses_bing(monkeypatch, bing_on):
    """Groq, Grok, Mistral, DeepSeek… n'ont pas de recherche web : le complément passe par Bing."""
    monkeypatch.setattr(bing_news.asyncio, "sleep", _no_sleep)
    route = respx.get(url__startswith=bing_news.API).respond(200, content=BING)

    class NoSearch:
        async def search(self, meter, *, model, prompt, max_uses=3):
            meter.note("recherche web indisponible chez Groq")
            return []

    meter = RunMeter()
    found = await claude_search.search(NoSearch(), meter, "groq:openai/gpt-oss-120b", "Budget de la Sécu", ["budget Sécu"], datetime(2026, 10, 1, tzinfo=timezone.utc), by_lang={"fr": ["budget Sécu", "PLFSS 2027"], "en": ["French social security budget"]})
    assert found and "Bing Actualités" in meter.log[-1]
    sent = [str(c.request.url) for c in route.calls]
    assert any("Budget+de+la+S" in u for u in sent) and any("setlang=en-US" in u for u in sent)  # le nom court du sujet, et chaque langue
