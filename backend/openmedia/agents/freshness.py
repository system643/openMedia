"""Fraîcheur : un article du jour peut relater un événement vieux de plusieurs semaines (un
lancement repris tardivement, un dossier republié). Un fait déjà dans l'actualité avant
la fenêtre du passage n'est pas une nouveauté : il reçoit `first_reported`, sa date de
première apparition, et la fiche le sort de « Quoi de neuf » (`synth.validate`).

Deux indices : la date de l'événement que donnent les sources (`event_date`), puis
l'historique de GDELT sur 90 jours, où un modèle dit si les titres plus anciens
rapportent bien le même événement (et pas seulement le même sujet)."""

from __future__ import annotations

import asyncio
import calendar
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from rapidfuzz import fuzz

from ..collect import gdelt
from ..collect.base import Candidate
from ..collect.dedupe import same_title
from ..collect.rss import fold
from .llm import LLM, RunMeter
from .material import as_json
from .schemas import Fact, FreshnessResult

LOOKBACK_DAYS = 90
MARGIN = timedelta(days=3)
MAX_FACTS = 8
MAX_DAYS = 5
PER_DAY = 2
SAME_FACT = 80  # similarité (rapidfuzz) entre un élément de la fiche et un fait ancien qu'il cite


def event_day(value: str | None) -> date | None:
    """AAAA-MM-JJ, ou AAAA-MM pris au dernier jour du mois (on ne vieillit jamais un fait à tort)."""
    if not value:
        return None
    try:
        if len(value) == 7:
            y, m = int(value[:4]), int(value[5:7])
            return date(y, m, calendar.monthrange(y, m)[1])
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _tokens(text: str) -> list[str]:
    return [t for t in (w.strip(".") for w in re.split(r"[^\w.]+", fold(text))) if len(t) >= 2]


def _matches(title: str, probe: list[str]) -> bool:
    """Le titre porte tous les mots-clés chiffrés (une version, un montant) et la moitié des autres."""
    words = set(_tokens(title))
    numbered = [t for t in probe if any(ch.isdigit() for ch in t)]
    others = [t for t in probe if t not in numbered]
    return all(t in words for t in numbered) and sum(t in words for t in others) * 2 >= len(others)


def _older_headlines(cands: list[Candidate], before: datetime, probe: str) -> list[tuple[Candidate, int]]:
    """Les titres antérieurs, regroupés par jour. Un lancement se voit à son pic de couverture
    plutôt qu'aux rumeurs qui le précèdent : on garde les jours les plus couverts, deux titres
    chacun, avec le nombre d'articles parus ce jour-là."""
    keys = _tokens(probe)
    by_day: dict[date, list[Candidate]] = defaultdict(list)
    for c in sorted((c for c in cands if c.published_at and c.published_at < before and c.title), key=lambda c: c.published_at):
        if _matches(c.title, keys):
            by_day[c.published_at.date()].append(c)
    days = sorted(by_day, key=lambda d: (-len(by_day[d]), d))[:MAX_DAYS]
    out: list[tuple[Candidate, int]] = []
    for d in sorted(days):
        heads: list[Candidate] = []
        for c in by_day[d]:
            if len(heads) < PER_DAY and not any(same_title(c.title, h.title) for h in heads):
                heads.append(c)
        out += [(c, len(by_day[d])) for c in heads]
    return out


async def _history(probe: str, before: datetime) -> list[tuple[Candidate, int]]:
    try:
        cands = await gdelt.search_any(probe, LOOKBACK_DAYS)
    except Exception:  # noqa: BLE001 — sans historique, le fait garde le bénéfice du doute
        return []
    return _older_headlines(cands, before, probe)


async def mark_stale(llm: LLM, meter: RunMeter, model: str, facts: list[Fact], window_start: datetime, priority: dict[int, float] | None = None) -> int:
    """Remplit `first_reported` des faits déjà rapportés avant la fenêtre ; rend leur nombre.
    `priority` : {indice du fait: importance} pour choisir les faits à vérifier en ligne."""
    before = window_start - MARGIN
    for f in facts:
        day = event_day(f.event_date)
        if not f.first_reported and day and day < before.date():
            f.first_reported = day.isoformat()

    todo = [i for i, f in enumerate(facts) if not f.first_reported and f.probe.strip() and f.status != "dementi"]
    todo = sorted(todo, key=lambda i: -(priority or {}).get(i, 0.0))[:MAX_FACTS]
    histories = await asyncio.gather(*[_history(facts[i].probe.strip(), before) for i in todo])
    found = {i: h for i, h in zip(todo, histories) if h}
    if found:
        rows, ids = [], {}
        for i, heads in found.items():
            listing = []
            for c, count in heads:
                key = f"H{len(ids) + 1}"
                ids[key] = (i, c)
                listing.append({"id": key, "date": c.published_at.strftime("%Y-%m-%d"), "articles_ce_jour": count, "media": c.source_name, "titre": c.title})
            rows.append({"fait": i, "texte": facts[i].text, "titres_anterieurs": listing})
        try:
            result = await llm.parse(meter, model=model, task="freshness", content=f"Faits du jour et titres plus anciens :\n{as_json(rows)}", schema=FreshnessResult, effort="low", max_tokens=4000)
        except Exception as e:  # noqa: BLE001
            meter.note(f"fraîcheur : vérification ignorée ({e})")
            result = FreshnessResult(items=[])
        for v in result.items:
            dates = [ids[k][1].published_at for k in v.same_event if k in ids and ids[k][0] == v.fact]
            if dates:
                facts[v.fact].first_reported = min(dates).date().isoformat()
    stale = sum(1 for f in facts if f.first_reported)
    if stale:
        meter.note(f"fraîcheur : {stale} fait(s) déjà rapporté(s) avant ce passage")
    return stale


def stale_index(facts: list[Fact]) -> dict:
    """Ce qu'il faut pour reconnaître, dans la fiche rédigée, un élément qui reprend une
    nouvelle ancienne : `refs` {référence: première apparition} pour les articles qui ne
    portent que des faits anciens, et `facts` [(texte, références, première apparition)]."""
    fresh = {r for f in facts if not f.first_reported for r in f.refs}
    refs: dict[str, str] = {}
    for f in facts:
        if f.first_reported:
            for r in f.refs:
                if r not in fresh:
                    refs[r] = min(refs.get(r, f.first_reported), f.first_reported)
    return {"refs": refs, "facts": [(f.text, set(f.refs), f.first_reported) for f in facts if f.first_reported]}


def first_reported(text: str, refs: list[str], index: dict) -> str | None:
    """La date de première apparition si l'élément reprend une nouvelle ancienne : toutes ses
    sources ne portent que des faits anciens, ou il redit un fait ancien qu'il cite."""
    if not index or not refs:
        return None
    if all(r in index["refs"] for r in refs):
        return min(index["refs"][r] for r in refs)
    days = [day for fact, frefs, day in index["facts"] if frefs & set(refs) and fuzz.token_set_ratio(fold(text), fold(fact)) >= SAME_FACT]
    return min(days) if days else None
