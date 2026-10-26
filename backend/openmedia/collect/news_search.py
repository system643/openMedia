"""La recherche datée d'articles de presse : GDELT et Bing Actualités ensemble, sans clé et quel
que soit le moteur IA. GDELT est souvent saturé : Bing prend alors le relais, et quand les deux
répondent, leurs résultats se complètent (un même article n'est gardé qu'une fois)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from . import bing_news, gdelt
from .base import Candidate
from .dedupe import canonical_url


async def search(queries: dict[str, list[str]], days: int, per_lang: int = 3, tries: int = gdelt.TRIES) -> list[Candidate]:
    """`tries` : essais accordés à GDELT. Une recherche faite pendant que le lecteur attend
    (aperçu d'un sujet, vérification rapide, recoupement) n'en fait qu'un."""
    since = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    # GDELT, saturé, ne reçoit que la première requête de chaque langue ; Bing les reçoit toutes.
    found = await asyncio.gather(gdelt.search(queries, days, tries=tries), bing_news.search(queries, since, per_lang=per_lang))
    out, seen = [], set()
    for c in [c for batch in found for c in batch]:
        key = canonical_url(c.url)
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out
