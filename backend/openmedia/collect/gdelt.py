"""GDELT DOC 2.0 : index mondial ouvert des articles de presse (« unlimited and unrestricted
use […] without fee », citation du GDELT Project demandée : gdeltproject.org). C'est la
recherche datée d'openMedia, avec les unes des médias (`fronts`) et tes flux RSS."""

from __future__ import annotations

import asyncio
import time
from urllib.parse import urlencode

from .base import Candidate, client, parse_date

API = "https://api.gdeltproject.org/api/v2/doc/doc"
LANGS = {"fr": "french", "en": "english"}
_lock = asyncio.Lock()  # GDELT limite à une requête toutes les 5 secondes
COOL_DOWN = 300  # secondes de repos après deux refus de suite
_cool_until = 0.0


def query_url(query: str, lang: str | None, days: int, maxrecords: int = 75) -> str:
    q = f"{query} sourcelang:{LANGS.get(lang, lang)}" if lang else query
    params = {"query": q, "mode": "ArtList", "format": "json", "maxrecords": maxrecords, "sort": "DateDesc", "timespan": f"{max(1, days)}d"}
    return f"{API}?{urlencode(params)}"


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


async def _get(http, url: str, lang: str | None) -> list[Candidate]:
    """Une requête, espacée de 5 s de la précédente. GDELT refuse parfois une adresse pendant
    plusieurs minutes (429) : après un second refus, on le laisse reposer quelques minutes
    plutôt que de bloquer le passage (les unes des médias et les flux RSS prennent le relais)."""
    global _cool_until
    async with _lock:
        for attempt in range(2):
            if time.monotonic() < _cool_until:
                return []
            try:
                r = await http.get(url)
            except Exception:
                return []
            finally:
                await asyncio.sleep(5)
            if r.status_code == 429:
                if attempt:
                    _cool_until = time.monotonic() + COOL_DOWN
                continue
            if r.headers.get("content-type", "").startswith("application/json"):
                return parse(r.json(), lang or "")
            return []
    return []


async def search(queries: dict[str, list[str]], days: int, per_lang: int = 3) -> list[Candidate]:
    """`days` : jusqu'à 90 (GDELT remonte trois mois). GDELT accepte une requête toutes les
    5 secondes : `per_lang` requêtes par langue."""
    if not enabled():
        return []
    out: list[Candidate] = []
    async with client(timeout=30) as http:
        for lang, qs in queries.items():
            for q in qs[:per_lang]:
                out += await _get(http, query_url(q, lang, min(days, 90)), lang)
    return out


async def search_any(query: str, days: int, maxrecords: int = 75) -> list[Candidate]:
    """Une seule requête, toutes langues confondues (fraîcheur d'un fait, pouls d'un sujet)."""
    if not enabled():
        return []
    async with client(timeout=30) as http:
        return await _get(http, query_url(query, None, min(days, 90), maxrecords), None)
