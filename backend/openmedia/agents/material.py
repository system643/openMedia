"""Mise en forme du matériau envoyé aux modèles (articles, sources) et références stables."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import yaml

from ..models import Article, Source
from ..security import clean, clean_deep, injection_signals
from ..sources import quality
from ..sources.registry import owner_key


def ref(article_id: int) -> str:
    return f"S{article_id}"


def ref_id(value: str) -> int | None:
    value = value.strip().lstrip("[").rstrip("]")
    return int(value[1:]) if value[:1] == "S" and value[1:].isdigit() else None


SOCIAL = "reseau_social"


def counts_as_source(source: Source) -> bool:
    """Un message de réseau social est un signal, jamais une confirmation ; une source peu
    fiable (ferme de contenu, site de désinformation) non plus."""
    return source.kind != SOCIAL and not quality.is_low(source.quality)


@lru_cache(maxsize=1)
def _seed_domains() -> frozenset[str]:
    seed = Path(__file__).parent.parent / "sources" / "seed_sources.yaml"
    return frozenset(row["domain"] for row in yaml.safe_load(seed.read_text(encoding="utf-8")))


def vetted(source: Source) -> bool:
    """Une source dont la fiabilité ne vient pas d'une IA : notée par le jeu ouvert (Lin et
    al.) ou par le lecteur, inscrite au registre de départ, ou une archive de recherche. Deux
    sites inconnus, ou qualifiés par l'IA seule, peuvent appartenir au même réseau sans qu'on
    le sache : ils ne suffisent pas à confirmer un fait."""
    return counts_as_source(source) and (source.kind == "recherche" or source.quality_origin in ("lin2023", "lecteur") or source.domain in _seed_domains())


_WORD = re.compile(r"\w+", re.UNICODE)
SHINGLE = 10  # mots : deux articles qui partagent de tels passages recopient le même texte
SHARED = 2  # passages communs au-delà desquels deux textes ne sont plus indépendants


def _shingles(text: str) -> set[tuple[str, ...]]:
    words = _WORD.findall((text or "").lower())
    return {tuple(words[i : i + SHINGLE]) for i in range(len(words) - SHINGLE + 1)}


def source_groups(pairs: list[tuple[Article, Source]]) -> list[set[str]]:
    """Les sources indépendantes : clés d'indépendance (groupe, dépêche), puis fusion des
    articles qui recopient de longs passages du même texte (un communiqué repris tel quel
    par plusieurs sites reste une seule source)."""
    groups: list[tuple[set[str], set]] = []
    for a, s in pairs:
        key, sh = independence_key(a, s), _shingles(a.text)
        hits = [g for g in groups if key in g[0] or len(sh & g[1]) >= SHARED]
        merged_keys, merged_sh = {key}, set(sh)
        for g in hits:
            merged_keys |= g[0]
            merged_sh |= g[1]
            groups.remove(g)
        groups.append((merged_keys, merged_sh))
    return [g[0] for g in groups]


def confirms(pairs: list[tuple[Article, Source]]) -> bool:
    """La règle de confirmation : deux sources indépendantes qui comptent, dont au moins une
    dont la fiabilité est établie hors IA (`vetted`). Un article dont seul le titre est connu
    ne compte pas : on ne sait pas ce qu'il dit vraiment."""
    counted = [(a, s) for a, s in pairs if counts_as_source(s) and ((a.text or "").strip() or getattr(a, "kind", "presse") == "recherche")]
    return len(source_groups(counted)) >= 2 and any(vetted(s) for _, s in counted)


def reliability(source: Source) -> str:
    """La fiabilité telle que le modèle la lit, avec la catégorie quand une IA l'a qualifiée."""
    if source.quality is None:
        return "non notée"
    note = f", {source.quality_note.split(' : ')[0]}" if source.quality_note else ""
    return f"{quality.label(source.quality)} ({source.quality:.2f}{note})"


def independence_key(article: Article, source: Source) -> str:
    """Deux articles ne sont indépendants que s'ils n'ont ni la même dépêche ni le même groupe.
    Pour la recherche, chaque papier est une étude distincte (une équipe, des données)."""
    if getattr(article, "kind", "presse") == "recherche":
        return f"paper:{article.id}"
    return f"wire:{article.wire.lower()}" if article.wire else f"owner:{owner_key(source)}"


def article_block(article: Article, source: Source, max_chars: int) -> str:
    """Un article tel que le modèle le lit. Tout ce qui vient du web est nettoyé (balises,
    caractères invisibles) : un article ne peut ni fermer son bloc ni imiter une autre source.
    Un texte qui s'adresse à une IA porte `suspect="oui"`."""
    title, venue, author = clean(article.title), clean(article.venue or source.name), clean(article.author)
    text = clean((article.text or "").strip()[:max_chars])
    suspect = ' suspect="oui"' if injection_signals(f"{title}\n{text}") else ""
    head = f'<article ref="{ref(article.id)}"{suspect}>\n'
    date = article.published_at.strftime("%Y-%m-%d %H:%M") if article.published_at else "date inconnue"
    wire = f" · reprend une dépêche {clean(article.wire)}" if article.wire else ""
    if getattr(article, "kind", "presse") == "recherche":
        nature = "prépublication non relue" if article.preprint else "publication"
        if article.published_at:
            return f"{head}Papier de recherche ({nature}) · {venue} · auteurs : {author or 'inconnus'}\nDate : {article.published_at:%Y-%m-%d}\nTitre : {title}\n\nRésumé : {text}\n</article>"
        return f"{head}Papier de recherche ({nature}) · {venue}\nTitre : {title}\n\nRésumé : {text}\n</article>"
    body = text or "(texte indisponible : seul le titre est connu)"
    return (
        f"{head}"
        f"Média : {clean(source.name)} ({source.domain}) · groupe : {clean(source.owner) or 'inconnu'} · pays : {source.country} · fiabilité : {reliability(source)}{wire}\n"
        f"Date : {date}\nTitre : {title}\n\n{body}\n</article>"
    )


def as_json(obj) -> str:
    """Matériau en JSON pour un prompt : chaque chaîne est nettoyée (voir `security.clean`)."""
    return json.dumps(clean_deep(obj), ensure_ascii=False, indent=1, default=str)
