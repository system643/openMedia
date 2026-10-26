"""GDELT DOC 2.0 : index mondial ouvert des articles de presse (« unlimited and unrestricted
use […] without fee », citation du GDELT Project demandée : gdeltproject.org). C'est la
recherche datée d'openMedia, avec Bing Actualités, les unes des médias (`fronts`) et tes flux RSS.

Depuis l'été 2026, GDELT est saturé : « our existing legacy search infrastructure is struggling
to handle the ever-growing volume of searches » (billet du 30/06/2026, en attendant sa migration
vers Spanner). Il refuse alors (429) la plupart des requêtes, quel que soit leur espacement :
relevé le 26/10/2026, environ une sur trois aboutit, au hasard. Les fichiers « ngrams » qu'il
propose à la place pèsent plusieurs mégaoctets par minute, hors de portée d'une application de
bureau qui remonte une semaine. openMedia lui demande donc peu : une requête par langue, triée
par pertinence (HybridRel : texte et notoriété du média), réessayée quelques fois à la collecte.
Bing Actualités reçoit les autres requêtes du sujet."""

from __future__ import annotations

import asyncio
import json
import re
import time
from urllib.parse import urlencode

from .base import Candidate, client, parse_date

API = "https://api.gdeltproject.org/api/v2/doc/doc"
LANGS = {"fr": "french", "en": "english"}
_lock = asyncio.Lock()  # GDELT demande une requête toutes les 5 secondes au plus
TRIES = 4  # à la collecte : une requête aboutit environ une fois sur trois
RETRY_WAIT = 15  # secondes entre deux essais, en plus des 5 réglementaires
COOL_DOWN = 300  # secondes de repos quand tous les essais ont été refusés
_cool_until = 0.0
# GDELT n'échappe pas toujours la barre oblique inverse de ses titres (l'album « o\i ») :
# son JSON est alors invalide. Une barre qui n'ouvre pas un échappement valide est doublée.
_ESCAPE = re.compile(r"\\(.?)", re.S)


def _escape(m: re.Match) -> str:
    return m.group(0) if m.group(1) and m.group(1) in '"\\/bfnrtu' else "\\\\" + m.group(1)


def query_url(query: str, lang: str | None, days: int, maxrecords: int = 100) -> str:
    q = f"{query} sourcelang:{LANGS.get(lang, lang)}" if lang else query
    params = {"query": q, "mode": "ArtList", "format": "json", "maxrecords": maxrecords, "timespan": f"{max(1, days)}d"}
    return f"{API}?{urlencode(params)}"


def load(text: str) -> dict:
    """Le JSON de GDELT, même mal échappé ; {} pour une réponse illisible (GDELT répond aussi
    par un message en texte, avec un statut 200, à une requête qu'il juge invalide)."""
    try:
        data = json.loads(_ESCAPE.sub(_escape, text), strict=False)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def parse(payload: dict, lang: str) -> list[Candidate]:
    out = []
    for a in payload.get("articles", []) or []:
        out.append(
            Candidate(
                url=a.get("url", ""),
                title=(a.get("title") or "").strip(),
                origin="gdelt",
                source_name=a.get("domain", ""),
                published_at=parse_date(a.get("seendate")),
                lang=lang,
                extra={"country": a.get("sourcecountry", "")},
            )
        )
    return [c for c in out if c.url and c.title]


def resting() -> bool:
    """GDELT a refusé nos requêtes et se repose : la collecte du moment est partielle."""
    return time.monotonic() < _cool_until


def enabled() -> bool:
    from ..config import load_settings

    return load_settings().gdelt  # coupé par le lecteur (Réglages › Confidentialité)


async def _get(http, url: str, lang: str | None, tries: int = 1) -> list[Candidate]:
    """Une requête, espacée de 5 s de la précédente et essayée `tries` fois. Quand tous les
    essais sont refusés, GDELT est laissé au repos quelques minutes : le reste du passage ne
    l'attend plus (Bing Actualités, les unes et les flux RSS prennent le relais)."""
    global _cool_until
    async with _lock:
        for attempt in range(tries):
            if time.monotonic() < _cool_until:
                return []
            try:
                r = await http.get(url)
            except Exception:
                return []
            finally:
                await asyncio.sleep(5)
            if r.status_code == 429:
                if attempt == tries - 1:
                    _cool_until = time.monotonic() + COOL_DOWN
                else:
                    await asyncio.sleep(RETRY_WAIT)
                continue
            return parse(load(r.text), lang or "") if r.status_code == 200 else []
    return []


async def search(queries: dict[str, list[str]], days: int, tries: int = TRIES) -> list[Candidate]:
    """La première requête de chaque langue, sur `days` jours (GDELT remonte trois mois)."""
    if not enabled():
        return []
    out: list[Candidate] = []
    async with client(timeout=30) as http:
        for lang, qs in queries.items():
            if q := next((q for q in qs if q.strip()), None):
                out += await _get(http, query_url(q, lang, min(days, 90)), lang, tries)
    return out


async def search_any(query: str, days: int, maxrecords: int = 75) -> list[Candidate]:
    """Une seule requête, toutes langues confondues (fraîcheur d'un fait), essayée une fois."""
    if not enabled():
        return []
    async with client(timeout=30) as http:
        return await _get(http, query_url(query, None, min(days, 90), maxrecords), None)
