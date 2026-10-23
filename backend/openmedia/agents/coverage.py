"""Spectre des sources : d'où vient la couverture d'une fiche, et ses angles morts."""

from __future__ import annotations

from collections import Counter

from ..models import Article, Source
from ..sources import quality
from .material import counts_as_source, independence_key


UNKNOWN = {"??", "?", ""}


def coverage(pairs: list[tuple[Article, Source]]) -> dict:
    n = len(pairs)
    if not n:
        return {"articles": 0, "independent": 0, "unreliable": 0, "countries": {}, "kinds": {}, "owners": {}, "langs": {}, "owner_types": {}, "controllers": {}, "alerts": ["Aucune source retenue."]}
    countries = Counter(s.country or "??" for _, s in pairs)
    kinds = Counter(s.kind for _, s in pairs)
    owners = Counter(s.owner or s.domain for _, s in pairs)
    langs = Counter(a.lang or s.lang or "?" for a, s in pairs)
    independent = len({independence_key(a, s) for a, s in pairs if counts_as_source(s)})
    owner_types = Counter((s.owner_type or "inconnu") for _, s in pairs)
    controllers = Counter(s.controller for _, s in pairs if s.owner_type == "milliardaire" and s.controller)
    wires = Counter(a.wire for a, _ in pairs if a.wire)
    unreliable = sum(1 for _, s in pairs if quality.is_low(s.quality))

    alerts = []
    if independent < 2:
        alerts.append("Une seule source indépendante : les faits restent à confirmer.")
    if unreliable and unreliable / n >= 0.5:
        alerts.append(f"{unreliable} article(s) sur {n} viennent de sources peu fiables (fermes de contenu, reprises) : elles ne confirment rien.")
    if n >= 4:
        known = Counter({k: v for k, v in countries.items() if k not in UNKNOWN})
        unknown = n - sum(known.values())
        if known and sum(known.values()) >= 4:
            country, c = known.most_common(1)[0]
            if c / sum(known.values()) >= 0.8:
                alerts.append(f"Couverture concentrée sur un seul pays ({country} : {round(100 * c / sum(known.values()))} % des sources situées).")
        if unknown / n >= 0.5:
            alerts.append(f"Pays inconnu pour {round(100 * unknown / n)} % des sources : la répartition géographique est incomplète.")
        owner, o = owners.most_common(1)[0]
        if o / n >= 0.5:
            alerts.append(f"La moitié des articles ou plus viennent du même groupe ({owner}).")
        if wires and wires.most_common(1)[0][1] / n >= 0.6:
            alerts.append(f"La majorité des articles reprennent une dépêche {wires.most_common(1)[0][0]}.")
        if not (kinds.get("agence") or kinds.get("institutionnel")):
            alerts.append("Aucune source d'agence ni source primaire (institution, document officiel).")
        if len({k for k in langs if k not in UNKNOWN}) == 1 and not any(k in UNKNOWN for k in langs):
            alerts.append("Toutes les sources sont dans la même langue.")
        rich = owner_types.get("milliardaire", 0)
        if rich / n >= 0.5 and controllers:
            names = [c for c, _ in controllers.most_common(4)]
            who = ", ".join(names[:-1]) + f" et {names[-1]}" if len(names) > 1 else names[0]
            alerts.append(f"{round(100 * rich / n)} % de la couverture vient de médias contrôlés par {len(controllers)} grande(s) fortune(s) : {who}.")
    return {
        "articles": n,
        "independent": independent,
        "unreliable": unreliable,
        "countries": dict(countries.most_common()),
        "kinds": dict(kinds.most_common()),
        "owners": dict(owners.most_common(8)),
        "langs": dict(langs.most_common()),
        "owner_types": dict(owner_types.most_common()),
        "controllers": dict(controllers.most_common(6)),
        "alerts": alerts,
    }
