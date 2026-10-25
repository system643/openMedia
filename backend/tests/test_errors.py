"""Les erreurs des fournisseurs, dites en français à un non-développeur."""

import httpx
import pytest
import respx

from openmedia.agents import llm as llm_mod
from openmedia.agents.errors import claude_code_message, http_error
from openmedia.agents.llm import LLMError, NoApiKey, RunMeter
from openmedia.agents.providers.keys import KeyRefused, check_key
from openmedia.agents.providers.openai_compat import OpenAICompatLLM
from openmedia.agents.schemas import IntakeSuggestion


def test_http_errors_are_actionable():
    assert isinstance(http_error("OpenAI", 401), NoApiKey)
    assert "quelques minutes" in str(http_error("OpenAI", 429, "Rate limit reached"))
    assert "Réglages › Moteur IA" in str(http_error("Mistral", 404, "model not found"))
    assert "surchargé" in str(http_error("Anthropic", 529))
    tpm = str(http_error("Groq", 413, "Request too large for model `openai/gpt-oss-120b` in organization `org_x` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Requested 12000"))
    assert "offre Groq" in tpm and "Réglages" in tpm
    local = str(http_error("LM Studio", 400, "The number of tokens to keep from the initial prompt is greater than the context length", local=True))
    assert "32 768" in local and "contexte" in local


def test_claude_code_messages_are_readable():
    assert "abonnement Claude" in claude_code_message("Claude AI usage limit reached|1761200000")
    assert "2 $" in claude_code_message("error_max_budget_usd")


@respx.mock
async def test_openai_compatible_quota_is_explained():
    respx.post("https://api.openai.com/v1/responses").respond(429, json={"error": {"message": "Rate limit reached"}})
    engine = OpenAICompatLLM("openai", "sk-proj-test")

    async def instant(_):
        return None

    import openmedia.agents.providers.openai_compat as oc

    oc.asyncio.sleep, original = instant, oc.asyncio.sleep
    try:
        with pytest.raises(LLMError, match="quelques minutes"):
            await engine.parse(RunMeter(), model="gpt-6-luna", task="intake", content="x", schema=IntakeSuggestion)
    finally:
        oc.asyncio.sleep = original


@respx.mock
async def test_a_busy_provider_does_not_refuse_the_key():
    respx.get("https://api.openai.com/v1/models").respond(503)
    assert await check_key("sk-proj-abc", "openai") == ("openai", False, "")
    respx.get("https://api.mistral.ai/v1/models").respond(401)
    with pytest.raises(KeyRefused):
        await check_key("a" * 32, "mistral")


@respx.mock
async def test_a_key_without_credit_is_kept_and_explained():
    route = respx.get("https://api.x.ai/v1/models")
    route.respond(403, json={"code": "The caller does not have permission to execute the specified operation", "error": "Your newly created team doesn't have any credits or licenses yet. You can purchase credits on https://console.x.ai."})
    check = await check_key("xai-abc")
    assert check.provider == "xai" and not check.verified and "crédit" in check.warning
    # xAI répond 400 (et non 401) à une clé fausse : c'est un refus, pas une surcharge.
    route.respond(400, json={"code": "Client specified an invalid argument", "error": "Incorrect API key provided: xa***bc."})
    with pytest.raises(KeyRefused, match="Grok"):
        await check_key("xai-abc")


def test_anthropic_sdk_errors_are_translated():
    sdk = llm_mod.sdk()
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    err = sdk.RateLimitError("rate", response=httpx.Response(429, request=request), body={"error": {"message": "Number of request tokens has exceeded your per-minute rate limit"}})
    out = llm_mod._anthropic_error(err)
    assert isinstance(out, LLMError) and "quelques minutes" in str(out)
    denied = sdk.PermissionDeniedError("no", response=httpx.Response(403, request=request), body=None)
    assert isinstance(llm_mod._anthropic_error(denied), NoApiKey)
    assert "injoignable" in str(llm_mod._anthropic_error(sdk.APIConnectionError(request=request)))
