"""Le registre de départ couvre l'éventail politique sans pencher d'un côté (voir
openmedia/sources/EQUILIBRE.md). Le classement est indicatif et ne sert qu'à ce contrôle :
openMedia n'étiquette aucun média."""

from pathlib import Path

import yaml

SEED = Path(__file__).parent.parent / "openmedia" / "sources" / "seed_sources.yaml"

LEFT = {
    "FR": {"liberation.fr", "humanite.fr", "mediapart.fr", "nouvelobs.com", "lesinrocks.com", "telerama.fr", "alternatives-economiques.fr", "huffingtonpost.fr", "slate.fr", "reporterre.net"},
    "US": {"nytimes.com", "washingtonpost.com", "cnn.com", "nbcnews.com", "cbsnews.com", "abcnews.go.com", "npr.org", "theatlantic.com", "latimes.com", "propublica.org", "usatoday.com", "politico.com"},
    "GB": {"theguardian.com", "independent.co.uk", "newstatesman.com"},
}
RIGHT = {
    "FR": {"lefigaro.fr", "lopinion.fr", "lejdd.fr", "valeursactuelles.com", "lepoint.fr", "cnews.fr", "europe1.fr", "causeur.fr", "contrepoints.org", "famillechretienne.fr"},
    "US": {"foxnews.com", "nypost.com", "washingtonexaminer.com", "thedispatch.com", "reason.com", "nationalreview.com", "realclearpolitics.com", "city-journal.org", "freebeacon.com", "theamericanconservative.com"},
    "GB": {"telegraph.co.uk", "thetimes.com", "spectator.co.uk"},
}


def test_registry_is_politically_balanced():
    domains = {row["domain"] for row in yaml.safe_load(SEED.read_text(encoding="utf-8"))}
    for country in LEFT:
        left, right = len(LEFT[country] & domains), len(RIGHT[country] & domains)
        # Chaque titre classé doit être au registre : un retrait se voit ici.
        assert left == len(LEFT[country]) and right == len(RIGHT[country]), country
        assert abs(left - right) <= 2, f"{country} : {left} à gauche, {right} à droite"
