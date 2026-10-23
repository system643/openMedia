"""Le banc d'essai et « Tester ce modèle », sur un faux serveur DeepSeek (mode objet JSON) :
le vrai pipeline tourne, et les mesures sont calculées par le programme."""

import json

import httpx
import respx
from fastapi.testclient import TestClient

from openmedia import bench
from openmedia.agents.providers.openai_compat import LEARNED

TRIAGE = {
    "items": [
        {"ref": f"S{i}", "relevance": rel, "nature": nature, "sensationalism": 0.1, "injection": False, "keep": keep, "reason": "test",
         "claims": [{"text": "Le budget de la ligne T2 est de 480 millions d'euros", "kind": "chiffre", "due": None, "event_date": "2026-10-14"}] if i in (1, 2) else []}
        for i, nature, keep, rel in [(1, "fait", True, 0.9), (2, "fait", True, 0.9), (3, "fait", True, 0.8), (4, "reaction", True, 0.7), (5, "opinion", False, 0.6), (6, "rumeur", False, 0.4), (7, "hors_sujet", False, 0.0)]
    ]
}
VERIFY = {"facts": [
    {"text": "Le budget de la ligne T2 est de 480 millions d'euros", "refs": ["S1", "S2"], "contradicted_by": [], "status": "confirme", "due": None, "claim_id": None, "event_date": "2026-10-14", "probe": "tramway Valmont budget"},
    {"text": "L'opposition estime le coût à 600 millions d'euros", "refs": ["S4"], "contradicted_by": [], "status": "non_confirme", "due": None, "claim_id": None, "event_date": None, "probe": "tramway Valmont opposition"},
]}
FICHE = {
    "title": "Le tramway de Valmont", "lede": "La métropole a adopté la ligne T2.", "state": "en_cours", "nothing_new": False,
    "whats_new": [
        {"text": "La ligne T2 coûtera 480 millions d'euros.", "refs": ["S1", "S2"], "status": "confirme", "contradicted_by": []},
        {"text": "L'opposition chiffre le coût à 600 millions d'euros.", "refs": ["S4"], "status": "confirme", "contradicted_by": []},
    ],
    "changes": [], "key_facts": [{"text": "La ligne comptera 21 stations.", "refs": ["S1", "S99"], "status": "confirme", "contradicted_by": []}],
    "timeline": [], "perspectives": [], "uncertainties": [], "watch": [], "announcements": [], "custom_sections": [], "corrections": [], "importance": 3, "confidence": "moyenne",
}


def _answer(request):
    system = json.loads(request.content)["messages"][0]["content"]
    schema = system.rsplit("schéma JSON", 1)[-1]
    payload = FICHE if '"lede"' in schema else VERIFY if '"facts"' in schema else TRIAGE
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 2000, "completion_tokens": 300}})


@respx.mock
async def test_bench_runs_the_real_pipeline_and_scores_it(monkeypatch):
    LEARNED.clear()
    monkeypatch.setattr("openmedia.agents.llm.get_key", lambda p: "sk-test" if p == "deepseek" else None)
    monkeypatch.setattr("openmedia.agents.llm.get_api_key", lambda: None)
    monkeypatch.setattr("openmedia.agents.providers.openai_compat.get_key", lambda p: "sk-test")
    monkeypatch.setattr("openmedia.agents.claude_code.claude_code_info", lambda: {"found": False, "path": None, "version": None})
    respx.post("https://api.deepseek.com/chat/completions").mock(side_effect=_answer)
    results, path = await bench.bench(["deepseek:deepseek-v4-pro", "openai:gpt-6-luna"])
    ok, missing = results
    assert "error" not in ok, ok.get("error")
    assert all(ok["checks"].values()), ok["checks"]
    assert ok["refs_inventees"] == 1 and ok["statuts_corriges"] == 2  # S99 retirée : « 21 stations » et « 600 M€ » n'ont plus qu'une source
    assert ok["cost_usd"] is not None and ok["cost_usd"] > 0
    assert "pas de clé OpenAI" in missing["error"]
    text = open(path, encoding="utf-8").read()
    assert "deepseek:deepseek-v4-pro" in text and "pas de clé OpenAI" in text


@respx.mock
def test_model_check_endpoint(monkeypatch):
    from openmedia.server import app

    LEARNED.clear()
    monkeypatch.setattr("openmedia.agents.llm.get_key", lambda p: "sk-test" if p == "deepseek" else None)
    monkeypatch.setattr("openmedia.agents.llm.get_api_key", lambda: None)
    monkeypatch.setattr("openmedia.agents.providers.openai_compat.get_key", lambda p: "sk-test")
    monkeypatch.setattr("openmedia.agents.claude_code.claude_code_info", lambda: {"found": False, "path": None, "version": None})
    good = {"city": "Valmont", "country": "France", "facts": [{"fact": "budget", "figure": "480 millions"}, {"fact": "stations", "figure": "21"}]}
    respx.post("https://api.deepseek.com/chat/completions").mock(return_value=httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(good)}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 300, "completion_tokens": 60}}))
    with TestClient(app) as c:
        r = c.post("/models/check", json={"model": "deepseek:deepseek-flash"}).json()
        assert r["ok"] and r["faithful"] and r["mode"] == "object"
        missing = c.post("/models/check", json={"model": "openai:gpt-6-luna"}).json()
        assert not missing["ok"] and "clé" in missing["error"]
