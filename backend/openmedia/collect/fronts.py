"""Les unes des médias, par leurs flux RSS publics : de quoi « Découvrir » les histoires du
moment, et un complément de collecte pour chaque sujet (les titres du jour qui citent ses
mots-clés).

Les flux sont ceux que les éditeurs publient pour la syndication ; leurs liens mènent
directement à l'article (aucun décodage). La liste est équilibrée : des généralistes, autant
de titres classés à gauche qu'à droite, et le service public (voir sources/EQUILIBRE.md).
Vérifiés le 22/10/2026 : réponse 200, entrées présentes, robots.txt qui l'autorise.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from .base import Candidate, client
from .rss import matches, parse

FRONTS: dict[str, list[tuple[str, str]]] = {
    "fr": [
        ("franceinfo", "https://www.francetvinfo.fr/titres.rss"),
        ("Le Monde", "https://www.lemonde.fr/rss/une.xml"),
        ("Le Parisien", "https://feeds.leparisien.fr/leparisien/rss"),
        ("20 Minutes", "https://www.20minutes.fr/feeds/rss-une.xml"),
        ("BFMTV", "https://www.bfmtv.com/rss/news-24-7/"),
        ("La Croix", "https://www.la-croix.com/RSS/UNIVERS"),
        ("Libération", "https://www.liberation.fr/arc/outboundfeeds/rss-all/?outputType=xml"),
        ("L'Humanité", "https://www.humanite.fr/feed"),
        ("Le Figaro", "https://www.lefigaro.fr/rss/figaro_actualites.xml"),
        ("L'Opinion", "https://www.lopinion.fr/index.rss"),
        ("L'Express", "https://www.lexpress.fr/arc/outboundfeeds/rss/alaune.xml"),
        ("Challenges", "https://www.challenges.fr/rss.xml"),
    ],
    "en": [
        ("BBC", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("Deutsche Welle", "https://rss.dw.com/rdf/rss-en-all"),
        ("The Guardian", "https://www.theguardian.com/world/rss"),
        ("The New York Times", "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"),
        ("NPR", "https://feeds.npr.org/1004/rss.xml"),
        ("The Wall Street Journal", "https://feeds.a.dj.com/rss/RSSWorldNews.xml"),
        ("Fox News", "https://moxie.foxnews.com/google-publisher/world.xml"),
        ("New York Post", "https://nypost.com/news/feed/"),
    ],
}
PER_FEED = 25  # les flux très longs (plusieurs centaines d'entrées) sont tronqués
TTL = 900  # les unes sont relues au plus tous les quarts d'heure
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_cache: dict[str, tuple[float, list[Candidate]]] = {}
_lock = asyncio.Lock()


async def headlines(langs: list[str]) -> list[Candidate]:
    """Les titres à la une, toutes dates confondues ; `source_name` porte le nom du média."""
    out: list[Candidate] = []
    async with _lock:
        for lang in langs:
            cached = _cache.get(lang)
            if cached and time.time() - cached[0] < TTL:
                out += cached[1]
                continue
            feeds = FRONTS.get(lang, [])
            async with client() as http:
                responses = await asyncio.gather(*[http.get(url) for _, url in feeds], return_exceptions=True)
            found: list[Candidate] = []
            for (name, _), r in zip(feeds, responses):
                if isinstance(r, Exception) or r.status_code != 200:
                    continue
                for c in parse(r.text, [], since=_EPOCH)[:PER_FEED]:
                    c.origin, c.source_name, c.lang = "une", name, lang
                    found.append(c)
            _cache[lang] = (time.time(), found)
            out += found
    return out


async def collect(keywords: list[str], since, langs: list[str]) -> list[Candidate]:
    """Les titres à la une depuis `since` qui citent un mot-clé du sujet."""
    if not keywords:
        return []
    return [c for c in await headlines(langs) if (c.published_at is None or c.published_at >= since) and matches(f"{c.title} {c.snippet}", keywords)]

