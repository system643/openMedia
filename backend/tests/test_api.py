import os

from fastapi.testclient import TestClient

from openmedia.models import Fiche, Topic
from openmedia.server import app
from openmedia.db import session


def client():
    return TestClient(app)


def test_health_and_settings_without_key(monkeypatch):
    monkeypatch.setattr("openmedia.agents.llm.get_api_key", lambda: None)
    with client() as c:
        assert c.get("/health").json()["ok"]
        s = c.get("/settings").json()
        assert s["has_api_key"] is False and s["models"]["director"] == "claude-sonnet-5-5"
        assert s["engine"] == "auto" and "found" in s["claude_code"]
        assert c.patch("/settings", json={"run_hours": ["07:15"]}).json()["run_hours"] == ["07:15"]


def test_token_required(monkeypatch):
    monkeypatch.setenv("OPENMEDIA_TOKEN", "secret")
    with client() as c:
        assert c.get("/health").status_code == 200
        assert c.get("/topics").status_code == 401
        assert c.get("/topics", headers={"X-Token": "secret"}).status_code == 200
        assert c.get("/topics?token=secret").status_code == 200


def test_sources_seeded():
    with client() as c:
        sources = c.get("/sources").json()
        assert len(sources) > 100
        assert any(s["domain"] == "afp.com" and s["kind"] == "agence" for s in sources)


def test_create_topic_without_key_is_a_clear_400(monkeypatch):
    monkeypatch.setattr("openmedia.agents.llm.get_api_key", lambda: None)
    monkeypatch.setattr("openmedia.agents.claude_code.claude_code_info", lambda: {"found": False, "path": None, "version": None})
    with client() as c:
        r = c.post("/topics", json={"prompt": "Suis la réforme"})
        assert r.status_code == 400 and r.json()["code"] == "no_api_key"


def test_fiche_versions_and_catchup():
    with session() as s:
        t = Topic(name="Test", prompt="p")
        s.add(t)
        s.commit()
        s.refresh(t)
        for v, items in [(1, ["a"]), (2, []), (3, ["b", "a"])]:
            s.add(Fiche(topic_id=t.id, version=v, content={"whats_new": [{"text": x, "refs": ["S1"], "status": "confirme"} for x in items], "changes": []}, nothing_new=not items))
        s.commit()
    with client() as c:
        assert [f["version"] for f in c.get(f"/topics/{t.id}/fiches").json()] == [3, 2, 1]
        assert c.get(f"/topics/{t.id}/fiche", params={"version": 1}).json()["version"] == 1
        cu = c.get(f"/topics/{t.id}/catchup", params={"since": "2000-01-01T00:00:00"}).json()
        assert cu["versions"] == 3 and cu["quiet_versions"] == 1
        assert [[i["text"] for i in d["whats_new"]] for d in cu["days"]] == [["a"], ["b"]]
        assert c.delete(f"/topics/{t.id}").json()["ok"]


def test_drafts_lifecycle(monkeypatch):
    with client() as c:
        d = c.post("/drafts", json={"data": {"subject": "  Les négociations   sur le budget  ", "step": 1}}).json()
        assert d["title"] == "Les négociations sur le budget"
        c.put(f"/drafts/{d['id']}", json={"data": {"subject": "Budget 2027", "step": 2, "angle": "court"}})
        [listed] = [x for x in c.get("/drafts").json() if x["id"] == d["id"]]
        assert listed["data"]["angle"] == "court" and listed["title"] == "Budget 2027"
        # un brouillon supprimé ailleurs est recréé à la sauvegarde suivante : rien n'est perdu
        c.delete(f"/drafts/{d['id']}")
        assert c.put(f"/drafts/{d['id']}", json={"data": {"subject": "Budget"}}).json()["id"] == d["id"]
        assert c.delete(f"/drafts/{d['id']}").json()["ok"]
        assert all(x["id"] != d["id"] for x in c.get("/drafts").json())


def test_search_finds_topics_facts_and_articles():
    from openmedia.models import Article

    with session() as s:
        t = Topic(name="Réforme des retraites", prompt="Suis la réforme")
        s.add(t)
        s.commit()
        s.refresh(t)
        s.add(Fiche(topic_id=t.id, version=1, content={"whats_new": [{"text": "Le Sénat adopte l'âge de départ à 64 ans", "refs": ["S1"], "status": "non_confirme"}]}, sources=[{"ref": "S1", "name": "AFP", "title": "t", "url": "u"}]))
        s.add(Article(url="https://x.fr/retraites", title="Retraites : le Sénat vote", domain="x.fr"))
        s.commit()
    with client() as c:
        r = c.get("/search", params={"q": "senat age"}).json()
        assert r["facts"][0]["status"] == "non_confirme" and r["facts"][0]["sources"] == ["AFP"]
        assert c.get("/search", params={"q": "retraites"}).json()["topics"][0]["name"] == "Réforme des retraites"
        assert any("Sénat vote" in a["title"] for a in c.get("/search", params={"q": "senat"}).json()["articles"])


def test_manual_run_without_engine_is_refused_at_once(monkeypatch):
    """« Mettre à jour » avec un moteur indisponible : une erreur claire, pas un « lancé » muet."""
    from openmedia.agents.llm import NoApiKey
    from openmedia.api import routes

    def no_engine():
        raise NoApiKey("Aucun moteur IA : ajoute une clé API dans Réglages.")

    monkeypatch.setattr(routes, "get_llm", no_engine)
    with session() as s:
        t = Topic(name="Sans moteur", prompt="p")
        s.add(t)
        s.commit()
        s.refresh(t)
    with client() as c:
        r = c.post(f"/topics/{t.id}/run")
        assert r.status_code == 400 and r.json()["code"] == "no_api_key"
        assert c.post("/run-all").status_code == 400
