"""Fiabilité des médias, de 0 à 1.

Trois origines, de la plus forte à la plus faible : la note du lecteur, le jeu de données
ouvert de Lin et al. (2023, PNAS Nexus, doi:10.1093/pnasnexus/pgad286), qui agrège six
organismes de notation (NewsGuard, Media Bias/Fact Check, Ad Fontes…) sur 11 520 domaines,
puis la qualification par IA des domaines absents (`agents/qualify.py`).

Sous `LOW`, une source reste lisible et citable mais ne confirme jamais un fait.

Le jeu de Lin et al. n'est pas redistribué avec openMedia (son dépôt ne porte pas de licence) :
il est téléchargé depuis le dépôt de ses auteurs, après l'accord du lecteur, et rangé dans le
dossier de données (`ensure_dataset`). Sans lui, les sources restent notées par l'IA ou par le
lecteur, et seules celles du registre de départ peuvent ancrer une confirmation."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

DATASET_URL = "https://raw.githubusercontent.com/hauselin/domain-quality-ratings/main/data/domain_pc1.csv"


def dataset_path() -> Path:
    from ..config import data_dir

    return data_dir() / "domain_quality.csv"
LOW = 0.4

# Plateformes où chacun publie : la note du domaine ne dit rien de l'auteur.
PLATFORMS = {
    "medium.com", "substack.com", "blogspot.com", "wordpress.com", "github.io", "github.com", "tumblr.com",
    "over-blog.com", "hashnode.dev", "dev.to", "linkedin.com", "youtube.com", "facebook.com", "x.com",
    "twitter.com", "reddit.com", "quora.com", "wixsite.com", "weebly.com", "hubpages.com", "vocal.media",
}

# Qualification IA → note. La catégorie fixe le plafond, la fiabilité jugée module. Une note
# donnée par l'IA reste sous les notes établies (jeu ouvert, lecteur) : au plus 0,6, et elle ne
# suffit jamais seule à confirmer un fait (`agents/material.vetted`).
AI_CAP = 0.6
CATEGORY_SCORES = {
    "presse": {"elevee": 0.6, "moyenne": 0.5, "faible": 0.35},
    "presse_specialisee": {"elevee": 0.6, "moyenne": 0.5, "faible": 0.35},
    "media_etat": {"elevee": 0.45, "moyenne": 0.4, "faible": 0.3},
    "source_officielle": {"elevee": 0.6, "moyenne": 0.55, "faible": 0.45},
    "institution": {"elevee": 0.6, "moyenne": 0.55, "faible": 0.45},
    "blog": {"elevee": 0.55, "moyenne": 0.45, "faible": 0.3},
    "agregateur": {"elevee": 0.3, "moyenne": 0.25, "faible": 0.2},
    "ferme_contenu": {"elevee": 0.2, "moyenne": 0.15, "faible": 0.1},
}

CATEGORY_LABEL = {
    "presse": "presse",
    "presse_specialisee": "presse spécialisée",
    "media_etat": "média d'État",
    "source_officielle": "source officielle",
    "institution": "institution",
    "blog": "blog",
    "agregateur": "agrégateur de reprises",
    "ferme_contenu": "ferme de contenu",
}

# La famille de média que la qualification donne à un domaine encore `unknown`.
CATEGORY_KIND = {
    "presse": "national",
    "presse_specialisee": "specialise",
    "media_etat": "national",
    "source_officielle": "institutionnel",
    "institution": "institutionnel",
    "blog": "blog",
    "agregateur": "blog",
    "ferme_contenu": "blog",
}


@lru_cache(maxsize=1)
def dataset() -> dict[str, float]:
    path = dataset_path()
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return {row["domain"].strip().lower(): float(row["pc1"]) for row in csv.DictReader(f) if row.get("pc1")}


def ensure_dataset() -> bool:
    """Télécharge le jeu ouvert s'il manque (après l'accord seulement). Rend vrai s'il vient
    d'arriver ; les notes du registre sont alors recalculées par l'appelant."""
    from ..config import consented

    if dataset_path().exists() or not consented():
        return False
    import httpx

    try:
        r = httpx.get(DATASET_URL, timeout=30, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError:
        return False
    lines = r.text.splitlines()
    if not lines or lines[0].strip() != "domain,pc1" or len(lines) < 1000:
        return False  # un fichier inattendu n'est pas gardé
    tmp = dataset_path().with_suffix(".csv.tmp")
    tmp.write_text(r.text, encoding="utf-8")
    tmp.replace(dataset_path())
    dataset.cache_clear()
    return True


def rated(domain: str) -> float | None:
    """La note du jeu ouvert pour ce domaine (ou le domaine parent), sauf plateforme ouverte."""
    domain = domain.lower().removeprefix("www.")
    pieces = domain.split(".")
    for i in range(len(pieces) - 1):
        candidate = ".".join(pieces[i:])
        if candidate in PLATFORMS:
            return None
        if candidate in dataset():
            return round(dataset()[candidate], 3)
    return None


def from_category(category: str, reliability: str) -> float:
    return CATEGORY_SCORES.get(category, CATEGORY_SCORES["blog"]).get(reliability, 0.45)


def is_low(quality: float | None) -> bool:
    return quality is not None and quality < LOW


def label(quality: float | None, origin: str = "") -> str:
    """Ce que l'interface affiche : pas de note chiffrée (une décimale de plus ou de moins entre
    deux médias ne dit rien et prête à polémique), seulement ce que la note permet."""
    if quality is None:
        return "non notée"
    if quality < LOW:
        return "faible"
    return "estimée par l'IA" if origin == "ia" else "établie"
