"""Les garde-fous journalistiques : indépendance des sources, références, chiffres, fenêtre."""

from datetime import datetime, timedelta, timezone

from openmedia.agents.coverage import coverage
from openmedia.agents.material import independence_key
from openmedia.agents.schemas import Fact
from openmedia.agents.synth import validate
from openmedia.agents.topic_agent import window
from openmedia.agents.verify import enforce_independence
from openmedia.collect.dedupe import canonical_url, cluster, detect_wire, hamming, simhash
from openmedia.models import Article, Source, Topic

DEPECHE = "PARIS (AFP) - Le gouvernement a présenté mercredi un plan de 2,5 milliards d'euros pour la rénovation des écoles, selon un communiqué. " * 3


def _art(i, domain, text=DEPECHE, wire=None):
    return Article(id=i, url=f"https://{domain}/{i}", title=f"t{i}", domain=domain, text=text, wire=wire if wire is not None else detect_wire(text))


def _src(domain, owner, country="FR", kind="national"):
    return Source(domain=domain, name=domain, owner=owner, country=country, kind=kind)


def test_canonical_url_strips_tracking_and_amp():
    a = canonical_url("https://www.lemonde.fr/politique/article/x/amp/?utm_source=tw&id=3#top")
    assert a == "https://lemonde.fr/politique/article/x?id=3"


def test_simhash_close_for_reprints():
    a = simhash(DEPECHE)
    b = simhash(DEPECHE + " Mis à jour à 14h.")
    c = simhash("Le match de football s'est terminé sur un score nul après prolongations, devant un stade comble.")
    assert hamming(a, b) <= 6 < hamming(a, c)


def test_wire_detection():
    assert detect_wire(DEPECHE) == "AFP"
    assert detect_wire("Notre enquête exclusive menée pendant six mois.") == ""


def test_five_afp_reprints_count_as_one_source():
    domains = ["lemonde.fr", "lefigaro.fr", "ouest-france.fr", "sudouest.fr", "20minutes.fr"]
    pairs = [(_art(i, d), _src(d, f"groupe {i}")) for i, d in enumerate(domains, 1)]
    assert len({independence_key(a, s) for a, s in pairs}) == 1
    cov = coverage(pairs)
    assert cov["independent"] == 1
    assert any("dépêche AFP" in a for a in cov["alerts"])


def test_same_owner_is_not_independent_and_confirmation_is_downgraded():
    meta = {
        1: (_art(1, "leparisien.fr", "Enquête maison", wire=""), _src("leparisien.fr", "LVMH")),
        2: (_art(2, "lesechos.fr", "Enquête maison bis", wire=""), _src("lesechos.fr", "LVMH")),
        3: (_art(3, "liberation.fr", "Autre enquête", wire=""), _src("liberation.fr", "Presse indépendante SAS")),
    }
    facts = [
        Fact(text="A", refs=["S1", "S2"], contradicted_by=[], status="confirme", due=None),
        Fact(text="B", refs=["S1", "S3"], contradicted_by=[], status="confirme", due=None),
        Fact(text="C", refs=["S1", "S3"], contradicted_by=["S2"], status="confirme", due=None),
        Fact(text="D", refs=["S99"], contradicted_by=[], status="non_confirme", due=None),
    ]
    out = {f.text: f.status for f in enforce_independence(facts, meta)}
    assert out == {"A": "non_confirme", "B": "confirme", "C": "conteste"}


def test_validate_drops_unknown_refs_and_flags_missing_numbers():
    content = {
        "whats_new": [
            {"text": "Un plan de 2,5 milliards d'euros est présenté.", "refs": ["S1", "S42"], "status": "confirme"},
            {"text": "Le coût atteindrait 7 300 000 euros.", "refs": ["S1"], "status": "non_confirme"},
            {"text": "Fait inventé sans source.", "refs": ["S77"], "status": "confirme"},
        ],
        "key_facts": [],
        "timeline": [{"date": "2026-10-15", "event": "Présentation du plan", "refs": ["S1"]}],
        "perspectives": [],
        "announcements": [],
        "custom_sections": [{"title": "Chiffres", "body": "…", "refs": ["S1", "S9"]}],
        "changes": [],
        "nothing_new": False,
    }
    out = validate(content, {1: DEPECHE})
    assert [i["refs"] for i in out["whats_new"]] == [["S1"], ["S1"]]
    assert "check" not in out["whats_new"][0]
    assert out["whats_new"][1]["check"] == "chiffre_non_retrouve"
    assert out["custom_sections"][0]["refs"] == ["S1"]


def test_window_first_run_is_seven_days_or_less():
    at = datetime(2026, 10, 19, 6, 30, tzinfo=timezone.utc)
    assert window(Topic(name="x", prompt="x"), at) == at - timedelta(days=7)
    recent = Topic(name="x", prompt="x", since=datetime(2026, 10, 17))
    assert window(recent, at) == datetime(2026, 10, 16, tzinfo=timezone.utc)


def test_window_next_runs_overlap_six_hours():
    at = datetime(2026, 10, 19, 6, 30, tzinfo=timezone.utc)
    t = Topic(name="x", prompt="x", last_run_at=datetime(2026, 10, 18, 6, 30))
    assert window(t, at) == datetime(2026, 10, 18, 0, 30, tzinfo=timezone.utc)


def test_cluster_groups_reprints():
    items = cluster([{"id": 1, "title": "Plan écoles", "simhash": simhash(DEPECHE)}, {"id": 2, "title": "Rénovation : l'État débloque des fonds", "simhash": simhash(DEPECHE + " fin")}, {"id": 3, "title": "Match nul au stade", "simhash": simhash("Le match s'est terminé sur un score nul après prolongations.")}])
    assert items[0]["cluster"] == items[1]["cluster"] != items[2]["cluster"]


def test_coverage_alerts_on_single_country():
    pairs = [(_art(i, f"site{i}.fr", f"texte {i}", wire=""), _src(f"site{i}.fr", f"g{i}")) for i in range(5)]
    alerts = coverage(pairs)["alerts"]
    assert any("un seul pays" in a for a in alerts)
    assert any("primaire" in a for a in alerts)


def test_two_unknown_sites_never_confirm_alone():
    """Deux domaines inconnus (ou qualifiés par l'IA seule) peuvent venir du même réseau : il
    faut au moins une source dont la fiabilité est établie hors IA pour confirmer."""
    unknown = Source(domain="actu-alpha.info", name="actu-alpha.info", owner="actu-alpha.info", kind="national", quality=0.75, quality_origin="ia")
    other = Source(domain="infos-beta.net", name="infos-beta.net", owner="infos-beta.net", kind="unknown")
    seeded = _src("liberation.fr", "Presse indépendante SAS")  # au registre de départ
    meta = {
        1: (_art(1, "actu-alpha.info", "Un texte original A", wire=""), unknown),
        2: (_art(2, "infos-beta.net", "Un texte original B", wire=""), other),
        3: (_art(3, "liberation.fr", "Un texte original C", wire=""), seeded),
    }
    facts = [
        Fact(text="réseau", refs=["S1", "S2"], contradicted_by=[], status="confirme", due=None),
        Fact(text="ancré", refs=["S1", "S3"], contradicted_by=[], status="confirme", due=None),
    ]
    out = {f.text: f.status for f in enforce_independence(facts, meta)}
    assert out == {"réseau": "non_confirme", "ancré": "confirme"}


RELEASE = "La coopérative Verger annonce aujourd'hui avoir levé 40 millions d'euros auprès de trois fonds européens pour accélérer le développement de ses vergers biologiques dans ses exploitations de la Drôme et de l'Ardèche. "


def test_fiche_status_is_recomputed_by_the_code():
    """Le statut « confirmé » d'un élément de fiche ne vient pas du modèle : un élément porté par
    des sources notées par l'IA seule, par un titre seul, ou qui se dit lui-même non confirmé,
    redevient « non confirmé »."""
    from openmedia.agents.synth import enforce_statuses

    ia = Source(domain="site-a.info", name="a", owner="a", kind="national", quality=0.75, quality_origin="ia")
    ib = Source(domain="site-b.info", name="b", owner="b", kind="national", quality=0.75, quality_origin="ia")
    pairs = {
        1: (_art(1, "site-a.info", "Texte original A sur le plan.", wire=""), ia),
        2: (_art(2, "site-b.info", "Texte original B sur le plan.", wire=""), ib),
        3: (_art(3, "liberation.fr", "Texte original C sur le plan.", wire=""), _src("liberation.fr", "Presse indépendante SAS")),
        4: (_art(4, "lemonde.fr", "", wire=""), _src("lemonde.fr", "Groupe Le Monde")),  # titre seul
    }
    content = {"whats_new": [
        {"text": "IA seule", "refs": ["S1", "S2"], "status": "confirme"},
        {"text": "Ancré", "refs": ["S1", "S3"], "status": "confirme"},
        {"text": "Titre seul", "refs": ["S3", "S4"], "status": "confirme"},
        {"text": "Selon un seul blog, ce point n'est pas confirmé", "refs": ["S1", "S3"], "status": "confirme"},
    ]}
    assert enforce_statuses(content, pairs.get) == 3
    assert [i["status"] for i in content["whats_new"]] == ["non_confirme", "confirme", "non_confirme", "non_confirme"]


def test_a_press_release_copied_by_several_sites_is_one_source():
    from openmedia.agents.material import confirms, source_groups

    pairs = [
        (_art(1, "liberation.fr", "Selon un communiqué. " + RELEASE, wire=""), _src("liberation.fr", "Presse indépendante SAS")),
        (_art(2, "site-x.fr", RELEASE + "Le dirigeant se félicite.", wire=""), _src("site-x.fr", "x")),
    ]
    assert len(source_groups(pairs)) == 1 and not confirms(pairs)
    other = (_art(3, "lemonde.fr", "Une enquête distincte sur la levée de fonds de Verger et ses investisseurs.", wire=""), _src("lemonde.fr", "Groupe Le Monde"))
    assert confirms([*pairs, other])


def test_a_quiet_day_does_not_announce_yesterday_news():
    from openmedia.agents.novelty import carry_forward

    previous = {"lede": "Nouveauté : Bobine sort en version 2.", "whats_new": [{"text": "x", "refs": ["S1"], "status": "confirme"}], "custom_sections": [{"title": "Faits nouveaux", "body": "Bobine 2", "refs": []}, {"title": "Contexte", "body": "…", "refs": []}]}
    out = carry_forward(previous, [])
    assert out["lede"] == "Bobine sort en version 2." and out["whats_new"] == []
    assert [s["title"] for s in out["custom_sections"]] == ["Contexte"]


def test_unknown_countries_are_not_a_blind_spot():
    pairs = [(_art(i, f"site{i}.info", f"Texte {i}", wire=""), Source(domain=f"site{i}.info", name="s", owner=f"o{i}", country="??", kind="national")) for i in range(1, 6)]
    alerts = coverage(pairs)["alerts"]
    assert not any("seul pays" in a for a in alerts) and any("Pays inconnu" in a for a in alerts)


def test_a_patch_never_breaks_a_sentence():
    from openmedia.agents.schemas import RevisePatch
    from openmedia.agents.synth import apply_patches

    content = {"lede": "Le logiciel reprend les fonctions de Word, puis celles d'Excel via un module."}
    applied, skipped = apply_patches(content, [RevisePatch(excerpt="reprend les fonctions de Word", replacement="Aucune vérification indépendante n'est rapportée.")])
    assert applied == 0 and "phrase" in skipped[0] and content["lede"].startswith("Le logiciel reprend")


def test_existing_fiches_are_rechecked_at_startup():
    from openmedia.agents.topic_agent import recheck_fiches
    from openmedia.db import session
    from openmedia.models import Article as ArticleRow, Fiche, Topic as TopicRow, Source as SourceRow

    with session() as s:
        for d in ("vieux-a.info", "vieux-b.info"):
            if not s.get(SourceRow, d):
                s.add(SourceRow(domain=d, name=d, owner=d, kind="national", quality=0.6, quality_origin="ia"))
        a = ArticleRow(url="https://vieux-a.info/1", title="A", domain="vieux-a.info", text="Texte A.")
        b = ArticleRow(url="https://vieux-b.info/1", title="B", domain="vieux-b.info", text="Texte B.")
        t = TopicRow(name="Ancienne fiche", prompt="p")
        s.add_all([a, b, t])
        s.commit()
        f = Fiche(topic_id=t.id, version=1, content={"whats_new": [{"text": "x", "refs": [f"S{a.id}", f"S{b.id}"], "status": "confirme"}]})
        s.add(f)
        s.commit()
        fid = f.id
    from openmedia.sources import registry

    registry._known.cache_clear()
    assert recheck_fiches() >= 1
    with session() as s:
        assert s.get(Fiche, fid).content["whats_new"][0]["status"] == "non_confirme"
