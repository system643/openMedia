"""Fournisseurs : reconnaissance des clés, catalogue et prix, moteur compatible OpenAI,
routage par modèle, correctifs de neutralité et mode Économie (lots)."""

import asyncio
import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from openmedia.agents import llm as llm_mod
from openmedia.agents.batching import BatchingLLM
from openmedia.agents.llm import NoApiKey, RouterLLM, RunMeter, token_cost
from openmedia import config
from openmedia.agents.providers import catalog, local
from openmedia.agents.providers.keys import detect_provider
from openmedia.agents.providers.openai_compat import OpenAICompatLLM, strict_schema
from openmedia.agents.schemas import FicheContent, IntakeSuggestion, RevisePatch
from openmedia.agents.synth import apply_patches

SUGGESTION = {"action": "new_topic", "topic_id": None, "topic_name": "Écoles", "prompt_draft": "Suis le plan", "reason": "nouveau"}


def test_detect_provider():
    assert detect_provider("gsk_abc") == ["groq"]
    assert detect_provider("sk-ant-api03-xxx") == ["anthropic"]
    assert detect_provider("sk-or-v1-abc") == ["openrouter"]
    assert detect_provider("AIzaSyD-abc") == ["gemini"]
    assert detect_provider("sk-proj-abc") == ["openai"]
    assert detect_provider("sk-abc") == ["openai", "deepseek", "moonshot", "qwen", "mistral"]
    assert detect_provider("a" * 32) == ["mistral"]
    assert detect_provider("xai-abc") == ["xai"]
    assert detect_provider("sk-" + "0123456789abcdef" * 2) == ["deepseek", "qwen"]
    assert detect_provider("sk-" + "Ab1" * 16) == ["moonshot", "openai"]
    assert detect_provider("0123456789abcdef" * 2 + ".AbCdEfGh12345678") == ["zai"]


def test_catalog_prices_and_tiers():
    assert catalog.price("claude-fable-5-1") == (10.00, 50.00, 0.25)  # n'est plus compté au prix d'Opus
    assert catalog.split("openai:gpt-6.1-sol") == ("openai", "gpt-6.1-sol")
    assert catalog.split("claude-sonnet-5-5") == ("anthropic", "claude-sonnet-5-5")
    assert catalog.tier_model("gemini", "rapide") == "gemini:gemini-3.5-flash-lite"
    assert catalog.tier_model("openai", "premium") == "openai:gpt-6-astra"  # gamme absente : on monte
    assert catalog.tier_model("mistral", "maximum") == "mistral:mistral-large-latest"
    assert catalog.guess_tier("gemini-9-flash-lite") == "rapide"
    # Le rôle qui écrit les faits ne descend jamais sous « équilibré ».
    assert all(p["topic"] in ("equilibre", "premium", "maximum") for p in catalog.PRESETS.values())


def test_meter_ledger_separates_subscription():
    meter = RunMeter()
    meter.record(task="synth", model="claude-sonnet-5-5", fresh=1_000_000, output=100_000)
    assert meter.calls[-1]["cost"] == pytest.approx(3.00)
    meter.record(task="triage", model="openai:modele-inconnu", fresh=1000, output=10)
    assert meter.calls[-1]["cost"] is None  # prix inconnu : signalé, pas inventé
    meter.add_reported({"input_tokens": 10, "output_tokens": 5}, 0.5, model="claude-haiku-5-5", task="triage")
    assert meter.subscription_usd == pytest.approx(0.5) and meter.cost_usd == pytest.approx(3.5)
    assert token_cost("claude-haiku-5-5", fresh=0, output=0, written=1_000_000) == pytest.approx(0.125)


def test_strict_schema_keeps_field_names():
    schema = strict_schema(FicheContent)
    assert "title" in schema["properties"] and "title" not in {k for k, v in schema.items() if isinstance(v, str)}
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])
    item = schema["$defs"]["Item"]
    assert item["additionalProperties"] is False and "contradicted_by" in item["required"]


def _chat(content, cost=None, prompt=1000, completion=200, cached=0):
    usage = {"prompt_tokens": prompt, "completion_tokens": completion, "prompt_tokens_details": {"cached_tokens": cached}}
    if cost is not None:
        usage["cost"] = cost
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": "stop"}], "usage": usage}


@respx.mock
async def test_gemini_parse_retries_once_on_invalid_json():
    route = respx.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions").mock(
        side_effect=[httpx.Response(200, json=_chat("pas du json")), httpx.Response(200, json=_chat(json.dumps(SUGGESTION), cached=400))]
    )
    meter = RunMeter()
    out = await OpenAICompatLLM("gemini", api_key="AIza-test").parse(meter, model="gemini-3.5-flash-lite", task="intake", content="article", schema=IntakeSuggestion, effort="xhigh")
    assert out.topic_name == "Écoles" and route.call_count == 2
    body = json.loads(route.calls[0].request.content)
    assert body["response_format"]["json_schema"]["strict"] is True and body["reasoning_effort"] == "high"
    assert body["messages"][0]["role"] == "system" and body["messages"][0]["content"].startswith("Tu travailles pour openMedia")
    assert len(meter.calls) == 2 and meter.calls[1]["cached"] == 400
    assert meter.calls[1]["cost"] == pytest.approx((600 * 0.30 + 400 * 0.03 + 200 * 2.50) / 1e6)


@respx.mock
async def test_openai_uses_responses_api():
    payload = {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(SUGGESTION)}]}], "usage": {"input_tokens": 500, "output_tokens": 50, "input_tokens_details": {"cached_tokens": 0}}}
    route = respx.post("https://api.openai.com/v1/responses").mock(return_value=httpx.Response(200, json=payload))
    meter = RunMeter()
    out = await OpenAICompatLLM("openai", api_key="sk-proj-test").parse(meter, model="gpt-6-luna", task="intake", content="article", schema=IntakeSuggestion, effort="low")
    assert out.action == "new_topic"
    body = json.loads(route.calls[0].request.content)
    assert body["text"]["format"]["type"] == "json_schema" and body["reasoning"] == {"effort": "low"} and body["store"] is False
    assert meter.calls[0]["model"] == "openai:gpt-6-luna"


@respx.mock
async def test_openrouter_cost_is_reported_and_bad_key_is_clear():
    respx.post("https://openrouter.ai/api/v1/chat/completions").mock(side_effect=[httpx.Response(200, json=_chat("bonjour", cost=0.0042)), httpx.Response(401, json={"error": {"message": "bad"}})])
    meter = RunMeter()
    llm = OpenAICompatLLM("openrouter", api_key="sk-or-test")
    assert await llm.text(meter, model="anthropic/claude-haiku-5.5", task="audio", content="x") == "bonjour"
    assert meter.calls[0]["cost"] == pytest.approx(0.0042)
    with pytest.raises(NoApiKey, match="OpenRouter"):
        await llm.text(meter, model="anthropic/claude-haiku-5.5", task="audio", content="x")


def _status(engine=None, **keys):
    return {"engine": engine, "providers": {p: {"has_key": keys.get(p, False)} for p in catalog.PROVIDERS}}


def test_router_replaces_unavailable_provider_by_same_tier():
    router = RouterLLM(_status(engine=None, gemini=True))
    meter = RunMeter()
    assert router.resolve("claude-sonnet-5-5", meter) == ("gemini", "gemini-3.8-flash")
    assert "même gamme" in meter.log[0]
    assert RouterLLM(_status(engine="claude_code")).resolve("claude-haiku-5-5") == ("anthropic", "claude-haiku-5-5")
    with pytest.raises(NoApiKey):
        RouterLLM(_status()).resolve("openai:gpt-6-luna")


def test_get_llm_accepts_another_provider_alone(monkeypatch):
    monkeypatch.setattr(llm_mod, "get_api_key", lambda: None)
    monkeypatch.setattr("openmedia.agents.claude_code.claude_code_info", lambda: {"found": False, "path": None, "version": None})
    monkeypatch.setattr(llm_mod, "get_key", lambda p: "sk-or-x" if p == "openrouter" else None)
    assert isinstance(llm_mod.get_llm(), RouterLLM)
    monkeypatch.setattr(llm_mod, "get_key", lambda p: None)
    with pytest.raises(NoApiKey):
        llm_mod.get_llm()


def test_apply_patches_only_touches_the_exact_excerpt():
    content = {"lede": "Le ministre a annoncé un plan historique.", "whats_new": [{"text": "Un plan de 2,5 milliards est présenté.", "refs": ["S1"], "status": "confirme"}], "watch": ["Vote prévu.", "Vote prévu."]}
    applied, skipped = apply_patches(content, [
        RevisePatch(excerpt="un plan historique", replacement="un plan"),
        RevisePatch(excerpt="absent de la fiche", replacement="x"),
        RevisePatch(excerpt="Vote prévu.", replacement="Vote attendu."),  # deux fois : ambigu
        RevisePatch(excerpt="2,5 milliards", replacement="3 000 milliards"),  # chiffre ajouté : refusé
        RevisePatch(excerpt="confirme", replacement="dementi"),  # un statut n'est pas de la prose
    ])
    assert applied == 1 and content["lede"] == "Le ministre a annoncé un plan."
    assert content["watch"] == ["Vote prévu.", "Vote prévu."] and "2,5 milliards" in content["whats_new"][0]["text"]
    assert content["whats_new"][0]["status"] == "confirme" and len(skipped) == 4


class FakeEngine:
    def __init__(self):
        self.immediate = []

    async def parse(self, meter, *, model, task, content, schema, **_):
        self.immediate.append(task)
        return schema.model_validate(SUGGESTION)


class FakeRouter:
    def __init__(self):
        self.status = {"engine": "api"}
        self.eng = FakeEngine()

    def resolve(self, model, meter=None):
        return catalog.split(model)

    def engine(self, provider):
        return self.eng


async def test_batching_groups_calls_and_falls_back_to_immediate():
    router = FakeRouter()
    submissions = []

    class TestBatching(BatchingLLM):
        async def _anthropic(self, items):
            submissions.append(len(items))
            for it in items[:-1]:
                it.meter.record(task=it.task, model=it.name, fresh=1_000_000, discount=0.5, via="batch")
                self._settle(it, json.dumps(SUGGESTION))
            # le dernier n'a pas de réponse dans le lot : il sera rejoué en direct

    llm = TestBatching(router, window=0.05, poll=0.01)
    meters = [RunMeter() for _ in range(3)]
    results = await asyncio.gather(*[llm.parse(m, model="claude-haiku-5-5", task="intake", content="x", schema=IntakeSuggestion) for m in meters])
    assert submissions == [3] and all(r.topic_name == "Écoles" for r in results)
    assert router.eng.immediate == ["intake"]
    assert meters[0].calls[0]["cost"] == pytest.approx(0.05) and meters[0].calls[0]["via"] == "batch"
    # Un fournisseur sans lot (Gemini) passe en direct sans attendre.
    await llm.parse(RunMeter(), model="gemini:gemini-3.5-flash-lite", task="triage", content="x", schema=IntakeSuggestion)
    assert router.eng.immediate == ["intake", "triage"] and submissions == [3]


async def test_failed_batch_replays_every_call_with_its_own_task():
    """Le lot entier échoue (erreur du fournisseur) : chaque appel est rejoué en direct, avec sa
    propre consigne (et non le nom d'une tâche asyncio)."""
    router = FakeRouter()

    class Broken(BatchingLLM):
        async def _anthropic(self, items):
            raise RuntimeError("500 du fournisseur")

    llm = Broken(router, window=0.05, poll=0.01)
    await asyncio.gather(*[llm.parse(RunMeter(), model="claude-haiku-5-5", task=t, content="x", schema=IntakeSuggestion) for t in ("intake", "triage")])
    assert sorted(router.eng.immediate) == ["intake", "triage"]


@respx.mock
def test_api_key_detection_models_and_costs():
    from openmedia.server import app

    respx.get("https://generativelanguage.googleapis.com/v1beta/models").mock(return_value=httpx.Response(200, json={"models": []}))
    respx.get("https://api.openai.com/v1/models").mock(return_value=httpx.Response(401, json={"error": {"message": "bad"}}))
    for url in ("https://api.mistral.ai/v1/models", "https://api.deepseek.com/models", "https://api.moonshot.ai/v1/models", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models"):
        respx.get(url).mock(return_value=httpx.Response(401, json={"error": {"message": "bad"}}))
    respx.get("https://openrouter.ai/api/v1/models").mock(return_value=httpx.Response(200, json={"data": [{"id": "anthropic/claude-sonnet-5.5", "pricing": {"prompt": "0.000002", "completion": "0.00001"}}]}))
    respx.route(host="127.0.0.1").mock(side_effect=httpx.ConnectError("refusé"))  # ni Ollama ni LM Studio
    local._detected.update(at=0.0, key=None, value=None)
    catalog._OR_CACHE["at"] = 0
    with TestClient(app) as c:
        r = c.put("/settings/api-key", json={"key": "AIzaSy-test"})
        assert r.status_code == 200 and r.json()["detected"] == "gemini" and r.json()["providers"]["gemini"]["has_key"]
        refused = c.put("/settings/api-key", json={"key": "sk-inconnue"})
        assert refused.status_code == 400 and "refusée" in refused.json()["detail"]
        models = c.get("/models").json()
        assert models["presets"]["equilibre"]["by_provider"]["gemini"]["topic"] == "gemini:gemini-3.8-flash"
        gem = next(m for m in models["models"] if m["id"] == "gemini:gemini-3.8-flash")
        assert gem["usable"] and gem["price"] == [0.75, 3.75, 0.075]
        assert not c.delete("/settings/api-key/gemini").json()["providers"]["gemini"]["has_key"]
        # Sans clé OpenRouter, ses prix ne sont pas lus en ligne (requête non annoncée).
        assert next(m for m in models["models"] if m["id"] == "openrouter:anthropic/claude-sonnet-5.5")["price"] is None
        costs = c.get("/costs").json()
        assert {"month", "projection", "topics", "last_topic_run", "last_brief"} <= set(costs)


@pytest.fixture
def saved_settings():
    path = config._settings_path()
    before = path.read_text(encoding="utf-8") if path.exists() else None
    yield
    if before is not None:
        path.write_text(before, encoding="utf-8")
    local._detected.update(at=0.0, key=None, value=None)


def _ollama_running():
    respx.get("http://127.0.0.1:11434/api/tags").respond(json={"models": [{"name": "qwen3:14b", "details": {"parameter_size": "14.8B"}}]})
    respx.route(host="127.0.0.1", port=1234).mock(side_effect=httpx.ConnectError("refusé"))
    local._detected.update(at=0.0, key=None, value=None)


def test_local_model_ids_keep_their_own_colon():
    assert catalog.split("ollama:qwen3:14b") == ("ollama", "qwen3:14b")
    assert catalog.split("lmstudio:qwen/qwen3-14b") == ("lmstudio", "qwen/qwen3-14b")
    assert catalog.price("ollama:qwen3:14b") == (0.0, 0.0, 0.0) and catalog.is_local("ollama:qwen3:14b")


@respx.mock
def test_roles_mix_this_pc_and_an_online_key(saved_settings):
    """Le tri sur Ollama (gratuit), les fiches chez Grok : chacun chez son moteur, sans Claude."""
    _ollama_running()
    config.update_settings({"engine": "auto", "models": {"triage": "ollama:qwen3:14b", "topic": "xai:grok-4.7", "director": "claude-sonnet-5-5"}})
    router = RouterLLM(_status(engine=None, xai=True))
    meter = RunMeter()
    assert router.resolve("ollama:qwen3:14b", meter) == ("ollama", "qwen3:14b")
    assert router.resolve("xai:grok-4.7", meter) == ("xai", "grok-4.7")
    assert router.resolve("claude-sonnet-5-5", meter) == ("xai", "grok-4.3")
    # Sans aucune clé, un rôle sur l'IA de ce PC suffit, et les modèles imposés (Haiku) y passent.
    alone = RouterLLM(_status(engine=None))
    assert llm_mod.any_engine({**_status(engine=None), "choice": "auto"})
    assert alone.resolve("claude-haiku-5-5") == ("ollama", "qwen3:14b")


@respx.mock
async def test_a_local_role_sends_its_own_model():
    route = respx.post("http://127.0.0.1:11434/api/chat").respond(json={"message": {"content": "ok"}, "prompt_eval_count": 3, "eval_count": 1, "done_reason": "stop"})
    meter = RunMeter()
    assert await local.LocalLLM("ollama").text(meter, model="qwen3:14b", task="intake", content="x") == "ok"
    assert json.loads(route.calls[0].request.content)["model"] == "qwen3:14b" and meter.cost_usd == 0


@respx.mock
def test_first_grok_key_moves_roles_off_claude_even_after_local_mode(saved_settings, monkeypatch):
    _ollama_running()
    monkeypatch.setattr("openmedia.agents.claude_code.claude_code_info", lambda: {"found": False, "path": None, "version": None})
    respx.get("https://api.x.ai/v1/models").respond(json={"data": [{"id": "grok-4.7"}]})
    from openmedia.server import app

    config.update_settings({"engine": "local", "local_provider": "ollama", "local_model": "qwen3:14b", "models": {"triage": "claude-haiku-5-5", "topic": "claude-sonnet-5-5", "director": "claude-sonnet-5-5"}})
    with TestClient(app) as c:
        r = c.put("/settings/api-key", json={"key": "xai-test"}).json()
        assert r["detected"] == "xai" and r["verified"] and r["warning"] == ""
        assert all(m.startswith("xai:") for m in r["models"].values())
        c.patch("/settings", json={"engine": "auto"})
        models = c.get("/models").json()
        ollama = next(p for p in models["providers"] if p["id"] == "ollama")
        assert ollama["usable"] and ollama["local"]
        row = next(m for m in models["models"] if m["id"] == "ollama:qwen3:14b")
        assert row["usable"] and row["price"] == [0.0, 0.0, 0.0] and row["region"] == "sur ce PC"
        assert models["effective"]["topic"].startswith("xai:")
        c.delete("/settings/api-key/xai")
