"""Les fournisseurs ajoutés (DeepSeek, Kimi, GLM, Qwen, Grok, compatible OpenAI) : chacun
reçoit la sortie structurée et la réflexion qu'il sait gérer, et le moteur se replie seul
quand un modèle refuse un paramètre. Tous les appels vont à de faux serveurs."""

import json
from datetime import datetime, timezone

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from openmedia.agents.llm import ContentRefused, LLMError, NoApiKey, RouterLLM, RunMeter
from openmedia.agents.providers import catalog, openai_compat
from openmedia.agents.providers.keys import KeyRefused, check_key
from openmedia.agents.providers.openai_compat import LEARNED, OpenAICompatLLM, inline_refs, strict_schema, validate_json
from openmedia.agents.schemas import FicheContent, IntakeSuggestion
from openmedia.config import update_settings

SUGGESTION = {"action": "new_topic", "topic_id": None, "topic_name": "Écoles", "prompt_draft": "Suis le plan", "reason": "nouveau"}


@pytest.fixture(autouse=True)
def _fresh():
    LEARNED.clear()
    yield
    LEARNED.clear()


def _chat(content, finish="stop", usage=None):
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish}], "usage": usage or {"prompt_tokens": 1000, "completion_tokens": 100}}


def _body(route, i=0):
    return json.loads(route.calls[i].request.content)


@respx.mock
async def test_deepseek_gets_json_object_mode_and_its_thinking_switch():
    route = respx.post("https://api.deepseek.com/chat/completions").mock(return_value=httpx.Response(200, json=_chat(json.dumps(SUGGESTION), usage={"prompt_tokens": 1000, "completion_tokens": 100, "prompt_cache_hit_tokens": 600})))
    llm = OpenAICompatLLM("deepseek", api_key="sk-test")
    meter = RunMeter()
    await llm.parse(meter, model="deepseek-flash", task="intake", content="article", schema=IntakeSuggestion, effort="low", max_tokens=800)
    await llm.parse(meter, model="deepseek-v4-pro", task="intake", content="article", schema=IntakeSuggestion, effort="medium", max_tokens=800)
    light, deep = _body(route, 0), _body(route, 1)
    assert light["response_format"] == {"type": "json_object"} and "schéma JSON" in light["messages"][0]["content"] and "JSON" in light["messages"][0]["content"]
    assert light["thinking"] == {"type": "disabled"} and light["max_tokens"] == 800  # pas de réflexion : pas de marge
    assert deep["thinking"] == {"type": "enabled"} and deep["reasoning_effort"] == "high" and deep["max_tokens"] == 800 + openai_compat.THINK_MARGIN
    assert meter.calls[0]["cached"] == 600  # le cache de DeepSeek se lit dans prompt_cache_hit_tokens


def test_deepseek_price_doubles_at_peak_hours():
    off = datetime(2026, 10, 20, 4, 30, tzinfo=timezone.utc)  # mardi, 6 h 30 à Paris : hors pointe
    peak = datetime(2026, 10, 20, 7, 0, tzinfo=timezone.utc)
    weekend = datetime(2026, 10, 24, 7, 0, tzinfo=timezone.utc)
    assert catalog.price("deepseek:deepseek-v4-pro", off) == (0.66, 1.98, 0.022)
    assert catalog.price("deepseek:deepseek-v4-pro", peak) == (1.32, 3.96, 0.044)
    assert catalog.price("deepseek:deepseek-v4-pro", weekend) == (0.66, 1.98, 0.022)


@respx.mock
async def test_kimi_gets_a_schema_without_refs_and_its_own_parameters():
    route = respx.post("https://api.moonshot.ai/v1/chat/completions").mock(return_value=httpx.Response(200, json=_chat(json.dumps(SUGGESTION))))
    await OpenAICompatLLM("moonshot", api_key="sk-test").parse(RunMeter(), model="kimi-k3", task="intake", content="x", schema=IntakeSuggestion, effort="medium", max_tokens=600)
    body = _body(route)
    assert body["response_format"]["type"] == "json_schema" and "$ref" not in json.dumps(body["response_format"])
    assert body["reasoning_effort"] == "high" and body["max_completion_tokens"] == 600 + openai_compat.THINK_MARGIN
    assert "max_tokens" not in body and "temperature" not in body


def test_inline_refs_removes_every_reference():
    schema = inline_refs(strict_schema(FicheContent))
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text
    assert schema["properties"]["whats_new"]["items"]["additionalProperties"] is False


@respx.mock
async def test_glm_thinking_and_answers_wrapped_in_prose_or_think_tags():
    reply = "<think>Je réfléchis…</think>Voici la réponse :\n```json\n" + json.dumps(SUGGESTION) + "\n```"
    route = respx.post("https://api.z.ai/api/paas/v4/chat/completions").mock(return_value=httpx.Response(200, json=_chat(reply)))
    out = await OpenAICompatLLM("zai", api_key="a.b").parse(RunMeter(), model="glm-5.3", task="intake", content="x", schema=IntakeSuggestion, effort="high")
    assert out.topic_name == "Écoles" and _body(route)["thinking"] == {"type": "enabled"}
    assert validate_json(IntakeSuggestion, "Bien sûr ! " + json.dumps(SUGGESTION) + " Bonne journée.").action == "new_topic"


@respx.mock
async def test_qwen_never_thinks_for_structured_output():
    route = respx.post("https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions").mock(return_value=httpx.Response(200, json=_chat(json.dumps(SUGGESTION))))
    llm = OpenAICompatLLM("qwen", api_key="sk-test")
    await llm.parse(RunMeter(), model="qwen-plus", task="intake", content="x", schema=IntakeSuggestion, effort="high")
    route.mock(return_value=httpx.Response(200, json=_chat("Un texte.")))
    await llm.text(RunMeter(), model="qwen-plus", task="audio", content="x", effort="high")
    assert _body(route, 0)["enable_thinking"] is False and _body(route, 0)["response_format"] == {"type": "json_object"}
    assert _body(route, 1)["enable_thinking"] is True


@respx.mock
async def test_unknown_provider_falls_back_from_schema_to_json_object_and_remembers():
    update_settings({"provider_urls": {"compatible": "https://api.exemple-ia.com/v1"}})
    try:
        route = respx.post("https://api.exemple-ia.com/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(400, json={"error": {"message": "response_format.type json_schema is not supported by this model"}}),
                httpx.Response(200, json=_chat(json.dumps(SUGGESTION))),
                httpx.Response(200, json=_chat(json.dumps(SUGGESTION))),
            ]
        )
        llm = OpenAICompatLLM("compatible", api_key="k")
        meter = RunMeter()
        await llm.parse(meter, model="mon-modele", task="intake", content="x", schema=IntakeSuggestion)
        await llm.parse(meter, model="mon-modele", task="intake", content="x", schema=IntakeSuggestion)
        assert _body(route, 0)["response_format"]["type"] == "json_schema"
        assert _body(route, 1)["response_format"] == {"type": "json_object"} and _body(route, 2)["response_format"] == {"type": "json_object"}
        assert route.call_count == 3 and any("refuse un paramètre" in line for line in meter.log)
    finally:
        update_settings({"provider_urls": {"compatible": ""}})


@respx.mock
async def test_refused_thinking_and_output_cap_are_dropped_or_lowered():
    route = respx.post("https://api.deepseek.com/chat/completions").mock(
        side_effect=[
            httpx.Response(400, json={"error": {"message": "Unrecognized request argument supplied: thinking"}}),
            httpx.Response(400, json={"error": {"message": "max_tokens must be less than or equal to 8192"}}),
            httpx.Response(200, json=_chat("ok")),
        ]
    )
    out = await OpenAICompatLLM("deepseek", api_key="sk-test").text(RunMeter(), model="deepseek-ancien", task="audio", content="x", effort="high")
    assert out == "ok"
    assert "thinking" in _body(route, 0) and "thinking" not in _body(route, 1) and _body(route, 2)["max_tokens"] == 8192


@respx.mock
async def test_truncated_thinking_is_retried_once_with_a_double_budget():
    route = respx.post("https://api.moonshot.ai/v1/chat/completions").mock(side_effect=[httpx.Response(200, json=_chat("", finish="length")), httpx.Response(200, json=_chat("fin"))])
    assert await OpenAICompatLLM("moonshot", api_key="sk-test").text(RunMeter(), model="kimi-k3", task="audio", content="x", max_tokens=1000) == "fin"
    assert _body(route, 1)["max_completion_tokens"] == 2 * _body(route, 0)["max_completion_tokens"]
    route.mock(side_effect=[httpx.Response(200, json=_chat("", finish="length"))] * 2)
    with pytest.raises(LLMError, match="limite de longueur"):
        await OpenAICompatLLM("moonshot", api_key="sk-test").text(RunMeter(), model="kimi-k3", task="audio", content="x")


@respx.mock
async def test_empty_answer_is_asked_again_once():
    route = respx.post("https://api.deepseek.com/chat/completions").mock(side_effect=[httpx.Response(200, json=_chat("")), httpx.Response(200, json=_chat(json.dumps(SUGGESTION)))])
    out = await OpenAICompatLLM("deepseek", api_key="sk-test").parse(RunMeter(), model="deepseek-flash", task="intake", content="x", schema=IntakeSuggestion)
    assert out.action == "new_topic" and route.call_count == 2


@respx.mock
async def test_content_filter_moves_the_call_to_another_provider():
    respx.post("https://api.deepseek.com/chat/completions").mock(return_value=httpx.Response(400, json={"error": {"message": "Content Exists Risk", "type": "invalid_request_error"}}))
    zai = respx.post("https://api.z.ai/api/paas/v4/chat/completions").mock(return_value=httpx.Response(200, json=_chat("repris")))
    status = {"engine": None, "providers": {p: {"has_key": p in ("deepseek", "zai")} for p in catalog.PROVIDERS}}
    router = RouterLLM(status)
    router._engines = {"deepseek": OpenAICompatLLM("deepseek", api_key="sk-test"), "zai": OpenAICompatLLM("zai", api_key="a.b")}
    meter = RunMeter()
    assert await router.text(meter, model="deepseek:deepseek-v4-pro", task="audio", content="x") == "repris"
    assert zai.called and "glm-5.3" in json.loads(zai.calls[0].request.content)["model"] and any("filtre de contenu" in line for line in meter.log)
    with pytest.raises(ContentRefused, match="filtre de contenu"):
        await OpenAICompatLLM("deepseek", api_key="sk-test").text(RunMeter(), model="deepseek-v4-pro", task="audio", content="x")


@respx.mock
async def test_credit_errors_are_named_whatever_the_status():
    respx.post("https://api.deepseek.com/chat/completions").mock(return_value=httpx.Response(402, json={"error": {"message": "Insufficient Balance"}}))
    with pytest.raises(LLMError, match="Crédit épuisé chez DeepSeek"):
        await OpenAICompatLLM("deepseek", api_key="sk-test").text(RunMeter(), model="deepseek-flash", task="audio", content="x")
    respx.post("https://api.moonshot.ai/v1/chat/completions").mock(return_value=httpx.Response(429, json={"error": {"message": "Your account is suspended, please check your plan", "type": "exceeded_current_quota_error"}}))
    with pytest.raises(LLMError, match="Crédit épuisé"):
        await OpenAICompatLLM("moonshot", api_key="sk-test").text(RunMeter(), model="kimi-k3", task="audio", content="x")


async def test_compatible_provider_needs_an_https_address():
    with pytest.raises(KeyRefused, match="adresse"):
        await check_key("k", "compatible")
    with pytest.raises(NoApiKey, match="adresse"):
        OpenAICompatLLM("compatible", api_key="k")


def test_provider_addresses_are_validated():
    from openmedia.server import app

    with TestClient(app) as client:
        r = client.patch("/settings", json={"provider_urls": {"compatible": "http://api.exemple-ia.com/v1"}})
        assert r.status_code == 400 and "https" in r.json()["detail"]
        ok = client.patch("/settings", json={"provider_urls": {"compatible": "https://api.exemple-ia.com/v1/"}})
        assert ok.status_code == 200 and ok.json()["providers"]["compatible"]["url"] == "https://api.exemple-ia.com/v1"
        assert client.patch("/settings", json={"provider_urls": {"deepseek": "https://ailleurs.com"}}).status_code == 400
        client.patch("/settings", json={"provider_urls": {"compatible": ""}})


def test_every_new_provider_has_models_tiers_and_a_region():
    for p in ("deepseek", "moonshot", "zai", "qwen", "xai"):
        assert catalog.PROVIDERS[p].region and catalog.tier_model(p, "rapide") and catalog.tier_model(p, "equilibre")
    assert catalog.tier_model("deepseek", "equilibre") == "deepseek:deepseek-v4-pro"  # on monte, jamais l'inverse
    assert catalog.tier_model("moonshot", "rapide") == "moonshot:kimi-k3"
    assert catalog.guess_tier("glm-5.3-flash") == "rapide" and catalog.guess_tier("gemini-9-flash") == "equilibre" and catalog.guess_tier("qwen3.9-max") == "premium"
