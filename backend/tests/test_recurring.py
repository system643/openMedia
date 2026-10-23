"""Les sujets récurrents de « Mes lectures » : trouvés et classés par un algorithme, nommés par
Haiku une seule fois par sujet."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import select

from openmedia.agents import recurring
from openmedia.agents.schemas import RecurringTopic, RecurringTopics
from openmedia.config import data_dir
from openmedia.db import session
from openmedia.models import Article, Reading, Topic

NOW = datetime.now(timezone.utc)

READS = [
    # Le procès Kessaci : 5 articles, 3 médias, 3 jours (dont la même dépêche sur deux sites)
    ("journal-a.fr", "Procès de l'assassinat du frère d'Amine Kessaci : l'audience s'ouvre à Aix", 1),
    ("journal-b.fr", "Procès de l'assassinat du frère d'Amine Kessaci : l'audience s'ouvre à Aix-en-Provence", 1),
    ("journal-c.fr", "Amine Kessaci face aux accusés, journée tendue au tribunal", 2),
    ("journal-a.fr", "Pour Amine Kessaci, « six années de combat » avant ce procès", 4),
    ("journal-c.fr", "Narcotrafic à Marseille : le témoignage d'Amine Kessaci bouleverse la cour", 5),
    # Le budget 2027 : 4 articles, 2 médias, 2 jours
    ("journal-a.fr", "Budget 2027 : les députés rejettent la taxe sur les holdings", 3),
    ("journal-d.fr", "Budget 2027 : le gouvernement prépare un nouveau 49.3", 3),
    ("journal-d.fr", "Budget 2027 : le Sénat durcit le texte sur les retraites", 8),
    ("journal-a.fr", "Ce que contient le budget 2027 adopté par le Parlement", 9),
    # Un seul média : pas un sujet qui revient
    ("journal-e.fr", "Tour de France 2027 : le parcours dévoilé", 2),
    ("journal-e.fr", "Tour de France 2027 : les favoris", 6),
    ("journal-e.fr", "Tour de France 2027 : la date du départ", 7),
    # Bruit et lectures isolées
    ("journal-b.fr", "Vidéo : les images du jour", 1),
    ("journal-c.fr", "Vidéo : ce qu'il faut retenir", 2),
    ("journal-d.fr", "Recette de la tarte aux pommes de grand-mère", 3),
]


@pytest.fixture
def corpus():
    with session() as s:
        for r in s.exec(select(Reading)).all():
            s.delete(r)
        s.commit()
        for i, (domain, title, days) in enumerate(READS):
            url = f"https://{domain}/recurrent-{i}"
            a = s.exec(select(Article).where(Article.url == url)).first()
            if not a:
                a = Article(url=url, title=title, domain=domain)
                s.add(a)
                s.commit()
                s.refresh(a)
            when = NOW - timedelta(days=days)
            s.add(Reading(article_id=a.id, first_visit=when, last_visit=when))
        s.commit()
    (data_dir() / "recurring.json").unlink(missing_ok=True)
    yield
    (data_dir() / "recurring.json").unlink(missing_ok=True)


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def parse(self, meter, *, model, task, content, schema, **_):
        self.calls.append((model, task, content))
        meter.record(task=task, model=model, fresh=800, output=200)
        assert schema is RecurringTopics
        n = content.count('"i":')
        return RecurringTopics(topics=[RecurringTopic(i=i, name=f"Sujet {i}", prompt=f"Je veux suivre le sujet {i}.", followable=True) for i in range(n)])


def test_algorithm_finds_ranks_and_filters(corpus):
    found = recurring.compute()
    labels = [f.label for f in found]
    assert len(found) == 2, labels
    kessaci, budget = found
    assert "amine kessaci" in kessaci.keys and kessaci.count == 5 and kessaci.days >= 3
    assert any("budget" in k for k in budget.keys) and budget.count == 4
    assert all("tour" not in f.label and "video" not in f.label for f in found)
    assert kessaci.reason.startswith("5 articles lus")


def test_near_identical_titles_count_once_for_weight(corpus):
    docs = recurring.corpus()
    [merged] = [d for d in docs if len(d.ids) > 1]  # les deux titres de la même dépêche
    assert len(merged.ids) == 2 and len(merged.media) == 2 and "Kessaci" in merged.title
    assert recurring.strip_suffix("Le budget est voté - Le Monde") == "Le budget est voté"
    assert recurring.strip_suffix("Mobilisation du 17 octobre : les juges sous pression – Brave") == "Mobilisation du 17 octobre : les juges sous pression"
    assert recurring.strip_suffix("Budget 2027 - le Sénat vote le texte") == "Budget 2027 - le Sénat vote le texte"
    assert recurring.strip_suffix("Procès Kessaci : l'audience s'ouvre à Aix") == "Procès Kessaci : l'audience s'ouvre à Aix"


def test_already_followed_topic_is_linked(corpus):
    with session() as s:
        t = Topic(name="Budget 2027", prompt="Suis le budget 2027 de la France")
        s.add(t)
        s.commit()
        s.refresh(t)
    found = recurring.compute()
    budget = next(f for f in found if any("budget" in k for k in f.keys))
    assert budget.related_topic_id == t.id
    with session() as s:
        s.delete(s.get(Topic, t.id))
        s.commit()


async def test_haiku_names_once_then_cache(corpus):
    from openmedia.config import update_settings

    update_settings({"readings_ai": True})
    llm = FakeLLM()
    first = await recurring.refresh(llm)
    assert len(llm.calls) == 1 and {m for m, _, _ in llm.calls} == {"claude-haiku-5-5"}
    assert [t["name"] for t in first["topics"]] == ["Sujet 0", "Sujet 1"] and first["topics"][0]["named_by"] == "haiku"
    again = await recurring.refresh(llm)
    assert len(llm.calls) == 1 and again["topics"][0]["name"] == "Sujet 0"
    assert (await recurring.latest())["generated_at"] == again["generated_at"]


async def test_not_followable_is_hidden(corpus):
    class Picky(FakeLLM):
        async def parse(self, meter, **kw):
            out = await super().parse(meter, **kw)
            out.topics[1].followable = False
            return out

    result = await recurring.refresh(Picky())
    assert len(result["topics"]) == 1
