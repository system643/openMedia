"""Bing Actualités : la recherche datée d'openMedia avec GDELT, sans clé et quel que soit le
moteur IA. Bing publie ses résultats d'actualité en RSS (`format=rss`) ; sa licence les réserve
à « un agrégateur RSS pour votre usage personnel et non commercial », ce qu'est openMedia, et
son robots.txt n'interdit pas `/news/search` (vérifié le 25/10/2026).

Les liens de Bing passent par `apiclick.aspx` : la vraie adresse est dans son paramètre `url`,
lue sans aucune requête. Les reprises par MSN (des pages JavaScript qu'on ne sait pas lire)
sont écartées : l'original est presque toujours dans les résultats.
"""

from __future__ import annotations

import asyncio
import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit

from .base import Candidate, client, parse_date

API = "https://www.bing.com/news/search"
MARKETS = {"fr": ("fr-FR", "FR"), "en": ("en-US", "US")}
# Le filtre de date de Bing : 24 heures, 7 jours, 30 jours. Sans lui, les résultats sont triés
# par pertinence et ceux du jour sont rares (relevé le 25/10/2026 : 1 sur 12, contre 6 sur 6).
INTERVALS = ((1, "7"), (7, "8"), (30, "9"))
TTL = 900  # une même requête est relue au plus tous les quarts d'heure
_TAG = re.compile(r"<[^>]+>")
_lock = asyncio.Lock()  # une requête à la fois, espacées d'une seconde
_cache: dict[str, tuple[float, list[Candidate]]] = {}


def enabled() -> bool:
    from ..config import load_settings

    return load_settings().bing_news  # coupé par le lecteur (Réglages › Confidentialité)


def query_url(query: str, lang: str, days: float | None = None) -> str:
    setlang, cc = MARKETS.get(lang, MARKETS["fr"])
    params = {"q": query, "format": "rss", "setlang": setlang, "cc": cc}
    # Deux heures de tolérance : une fenêtre « depuis hier à la même heure » reste sur 24 heures.
    if days is not None and (interval := next((v for limit, v in INTERVALS if days <= limit + 1 / 12), None)):
        params["qft"] = f'interval="{interval}"'
    return f"{API}?{urlencode(params)}"


def real_url(link: str) -> str:
    """L'adresse de l'article derrière le lien `apiclick` de Bing."""
    if "apiclick.aspx" not in link:
        return link
    return (parse_qs(urlsplit(link).query).get("url") or [""])[0]


def parse(xml: str | bytes, lang: str) -> list[Candidate]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for item in root.iter("item"):
        url = real_url(item.findtext("link") or "")
        host = (urlsplit(url).hostname or "").lower()
        if not url.startswith("http") or host == "msn.com" or host.endswith(".msn.com"):
            continue
        source = next((c.text or "" for c in item if c.tag.endswith("Source")), "")
        snippet = html.unescape(_TAG.sub(" ", item.findtext("description") or "")).strip()
        out.append(
            Candidate(
                url=url,
                title=html.unescape(item.findtext("title") or "").strip(),
                origin="bing",
                source_name=html.unescape(source).strip(),
                published_at=parse_date(item.findtext("pubDate")),
                lang=lang,
                snippet=snippet,
            )
        )
    return [c for c in out if c.title]


async def _get(http, query: str, lang: str, days: float | None) -> list[Candidate]:
    url = query_url(query, lang, days)
    async with _lock:
        cached = _cache.get(url)
        if cached and time.time() - cached[0] < TTL:
            return cached[1]
        try:
            r = await http.get(url)
        except Exception:
            return []
        finally:
            await asyncio.sleep(1)
        found = parse(r.content, lang) if r.status_code == 200 else []
        _cache[url] = (time.time(), found)
        return found


async def search(queries: dict[str, list[str]], since: datetime, per_lang: int = 3) -> list[Candidate]:
    """Les articles parus depuis `since` pour les premières requêtes de chaque langue."""
    if not enabled():
        return []
    days = (datetime.now(timezone.utc) - since).total_seconds() / 86400
    out: list[Candidate] = []
    async with client(timeout=20) as http:
        for lang, qs in queries.items():
            for q in [q for q in qs if q.strip()][:per_lang]:
                out += [c for c in await _get(http, q, lang, days) if c.published_at is None or c.published_at >= since]
    return out
