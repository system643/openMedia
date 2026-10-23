"""Consentement et IA sur ce PC : les options coupées par défaut, la migration des anciens
réglages, rien avant l'accord, et le mode local qui ne laisse rien partir en ligne."""

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from openmedia import config, scheduler
from openmedia.agents import discover as discover_mod
from openmedia.agents import llm as llm_mod
from openmedia.agents.llm import RouterLLM, RunMeter
from openmedia.agents.providers import local
from openmedia.agents.schemas import IntakeSuggestion
from openmedia.collect import gdelt
from openmedia.config import OPTIONS, ConsentRequired, Settings, load_settings, update_settings
from openmedia.server import app

CONSENT = "2026-01-01T00:00:00+00:00"


@pytest.fixture
def restore_settings():
    path = config._settings_path()
    before = path.read_text(encoding="utf-8")
    yield
    path.write_text(before, encoding="utf-8")
    local._detected.update(at=0.0, key=None, value=None)


def test_options_are_off_by_default():
    s = Settings()
    assert not any(getattr(s, k) for k in OPTIONS)
    assert s.gdelt  # source du suivi : active, mais désactivable
    assert s.consent_at is None and not s.onboarding_done


def test_old_settings_lose_their_options_but_keep_their_memory(restore_settings):
    old = {"history_auto": True, "detect_page": True, "page_nudge": False, "theme": "dark"}
    config._settings_path().write_text(json.dumps(old), encoding="utf-8")
    s = load_settings()
    assert not s.history_auto and not s.detect_page and not s.brief_audio_auto
    # Ce qui n'avait pas de réglage marchait toujours : l'audio, Découvrir, le nommage par l'IA.
    assert s.previous_options["history_auto"] and s.previous_options["brief_audio_auto"]
    assert s.previous_options["page_nudge"] is False and s.theme == "dark"
    config.save_settings(s)
    update_settings({"consent_at": CONSENT, "history_auto": True})
    assert load_settings().history_auto  # après l'accord, plus de migration


def test_nothing_before_consent(restore_settings, monkeypatch):
    update_settings({"consent_at": None})
    monkeypatch.setattr(llm_mod, "get_api_key", lambda: "sk-ant-test")
    with pytest.raises(ConsentRequired):
        llm_mod.get_llm()
    ran = []
    monkeypatch.setattr(scheduler, "run_many", lambda *a, **k: ran.append(a))
    import asyncio

    asyncio.run(scheduler.tick(force_all=True))
    assert ran == []
    with TestClient(app) as c:
        r = c.post("/topics", json={"prompt": "Suis la mission Artemis III"})
        assert r.status_code == 409 and r.json()["code"] == "consent_required"
        assert c.patch("/settings", json={"consent_at": True}).json()["consent_at"]


async def test_switched_off_sources_send_nothing(restore_settings):
    update_settings({"gdelt": False})
    with respx.mock(assert_all_mocked=True) as mock:  # toute requête lèverait une erreur
        assert await gdelt.search({"fr": ["budget"]}, 1) == []
        assert await gdelt.search_any("budget", 90) == []
        assert not mock.calls
    update_settings({"gdelt": True, "discover_enabled": False})
    assert (await discover_mod.discover())["disabled"] == "option"


def test_local_mode_never_goes_online(restore_settings):
    status = {"engine": "local", "choice": "local", "local_model": "qwen3:14b", "local": {"found": True, "ready": True}, "providers": {}}
    router = RouterLLM(status)
    meter = RunMeter()
    assert router.resolve("claude-haiku-5-5", meter) == ("local", "qwen3:14b")
    assert router.resolve("openai:gpt-6.1-sol", meter) == ("local", "qwen3:14b")
    assert any("servi par l'IA de ce PC" in line for line in meter.log)
    assert llm_mod.any_engine(status)
    assert not llm_mod.any_engine({**status, "engine": None})  # local injoignable : pas de repli en ligne


@respx.mock
def test_detect_local_servers():
    respx.get("http://127.0.0.1:11434/api/tags").respond(json={"models": [{"name": "qwen3:14b", "details": {"parameter_size": "14.8B"}}]})
    respx.get("http://127.0.0.1:1234/api/v0/models").mock(side_effect=httpx.ConnectError("refusé"))
    respx.get("http://127.0.0.1:1234/v1/models").mock(side_effect=httpx.ConnectError("refusé"))
    found = local.detect(fresh=True)
    assert found["ollama"]["found"] and found["ollama"]["models"][0] == {"id": "qwen3:14b", "size": "14.8B", "context": None}
    assert not found["lmstudio"]["found"]


@respx.mock
async def test_ollama_call_sets_context_and_schema():
    route = respx.post("http://127.0.0.1:11434/api/chat").respond(
        json={"message": {"content": json.dumps({"action": "new_topic", "topic_id": None, "topic_name": "Écoles", "prompt_draft": "Suis", "reason": "nouveau"})}, "prompt_eval_count": 120, "eval_count": 30, "done_reason": "stop"}
    )
    engine = local.LocalLLM("ollama", "qwen3:14b")
    meter = RunMeter()
    out = await engine.parse(meter, model="claude-haiku-5-5", task="intake", content="x", schema=IntakeSuggestion)
    body = json.loads(route.calls[0].request.content)
    assert out.topic_name == "Écoles" and body["model"] == "qwen3:14b"
    assert body["options"]["num_ctx"] == local.CONTEXT and body["format"]["type"] == "object" and body["stream"] is False
    assert meter.cost_usd == 0 and meter.input_tokens == 120


def test_local_urls_are_checked(restore_settings):
    with TestClient(app) as c:
        assert c.patch("/settings", json={"local_urls": {"ollama": "file:///etc/passwd"}}).status_code == 400
        assert c.patch("/settings", json={"local_urls": {"ollama": "http://192.168.1.20:11434/"}}).json()["local_urls"] == {"ollama": "http://192.168.1.20:11434"}


def test_clearing_readings_forgets_everything_they_brought():
    from sqlmodel import select

    from openmedia.agents import readings
    from openmedia.db import session
    from openmedia.models import Article, Reading, Topic, TopicArticle

    with session() as s:
        alone = Article(url="https://exemple.fr/lu-seulement", title="Lu seulement", domain="exemple.fr")
        shared = Article(url="https://exemple.fr/aussi-suivi", title="Aussi suivi", domain="exemple.fr")
        topic = Topic(name="Effacement", prompt="p")
        s.add_all([alone, shared, topic])
        s.commit()
        s.add_all([Reading(article_id=alone.id), Reading(article_id=shared.id), TopicArticle(topic_id=topic.id, article_id=shared.id)])
        s.commit()
        alone_id, shared_id = alone.id, shared.id
    (config.data_dir() / "recurring.json").write_text("{}", encoding="utf-8")
    readings.clear_all()
    with session() as s:
        assert s.get(Article, alone_id) is None and s.get(Article, shared_id) is not None
        assert not s.exec(select(Reading)).all()
    assert not (config.data_dir() / "recurring.json").exists()


async def test_local_server_gets_one_call_at_a_time_across_runs():
    """Trois passages en parallèle sur l'IA de ce PC : jamais plus d'un appel en vol."""
    import asyncio

    in_flight, peak = 0, 0

    async def slow(request):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return httpx.Response(200, json={"message": {"content": "ok"}, "prompt_eval_count": 1, "eval_count": 1, "done_reason": "stop"})

    with respx.mock:
        respx.post("http://127.0.0.1:11434/api/chat").mock(side_effect=slow)
        engines = [local.LocalLLM("ollama", "qwen3:14b") for _ in range(3)]
        await asyncio.gather(*[e.text(RunMeter(), model="m", task="intake", content="x") for e in engines])
    assert peak == 1


def test_withdrawn_consent_stops_calls_mid_run(restore_settings):
    status = {"engine": "local", "choice": "local", "local_model": "qwen3:14b", "local": {"found": True, "ready": True}, "providers": {}}
    router = RouterLLM(status)
    assert router.resolve("claude-haiku-5-5") == ("local", "qwen3:14b")
    update_settings({"consent_at": None})
    with pytest.raises(ConsentRequired):
        router.resolve("claude-haiku-5-5")


def test_deleting_a_topic_deletes_the_briefs_that_mention_it():
    from openmedia.db import session
    from openmedia.models import Brief, Topic

    with session() as s:
        t = Topic(name="Sujet effacé", prompt="p")
        s.add(t)
        s.commit()
        s.refresh(t)
        b = Brief(day="2026-10-22", content={"points": [{"topic_id": t.id, "topic_name": "Sujet effacé", "text": "x", "why": "y"}], "quiet_topics": []})
        s.add(b)
        s.commit()
        bid = b.id
    with TestClient(app) as c:
        assert c.delete(f"/topics/{t.id}").json()["ok"]
    with session() as s:
        assert s.get(Brief, bid) is None


def test_unreadable_settings_are_set_aside_not_overwritten(restore_settings):
    path = config._settings_path()
    path.write_text("{ ceci n'est pas du JSON", encoding="utf-8")
    s = load_settings()
    assert s.consent_at is None  # repart de zéro…
    kept = list(path.parent.glob("settings.illisible-*.json"))
    assert kept and "ceci n'est pas" in kept[-1].read_text(encoding="utf-8")  # …mais l'ancien fichier est gardé
    for k in kept:
        k.unlink()
    config.save_settings(Settings(consent_at=CONSENT))
    assert not path.with_suffix(".json.tmp").exists() and load_settings().consent_at == CONSENT


def test_local_ai_address_must_stay_private(restore_settings):
    with TestClient(app) as c:
        assert c.patch("/settings", json={"local_urls": {"ollama": "http://93.184.216.34:11434"}}).status_code == 400
        assert c.patch("/settings", json={"local_urls": {"ollama": "http://169.254.169.254"}}).status_code == 400
        assert c.patch("/settings", json={"local_urls": {"lmstudio": "http://localhost:1234"}}).status_code == 200


def test_stale_local_detection_never_blocks(monkeypatch):
    import time

    local._detected.update(at=time.time() - 120, key=(), value={"ollama": {"found": True}}, refreshing=False)
    started = []
    monkeypatch.setattr(local.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: started.append(1)})())
    t0 = time.perf_counter()
    assert local.detect()["ollama"]["found"] and time.perf_counter() - t0 < 0.05 and started
    local._detected.update(at=0.0, key=None, value=None, refreshing=False)
