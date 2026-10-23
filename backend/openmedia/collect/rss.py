"""Flux RSS ajoutés par l'utilisateur à un sujet, filtrés par mots-clés et par date."""

from __future__ import annotations

import asyncio
import html
import re
import unicodedata
from datetime import datetime

import feedparser

from .base import Candidate, client, parse_date

_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
MAX_SNIPPET = 12_000  # certains flux portent l'article entier : il sert si la page refuse


def fold(text: str) -> str:
    """Minuscules sans accents, pour comparer « Élection » et « election »."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def matches(text: str, keywords: list[str]) -> bool:
    folded = fold(text)
    return not keywords or any(fold(k) in folded for k in keywords if k.strip())


def parse(xml: str, keywords: list[str], since: datetime) -> list[Candidate]:
    feed = feedparser.parse(xml)
    out = []
    for e in feed.entries:
        title = html.unescape(e.get("title", "")).strip()
        full = max((c.get("value", "") for c in e.get("content", []) or []), key=len, default="")
        snippet = _SPACES.sub(" ", html.unescape(_TAG.sub(" ", full if len(full) > len(e.get("summary", "")) else e.get("summary", "")))).strip()
        published = parse_date(e.get("published_parsed") or e.get("updated_parsed"))
        if published and published < since:
            continue
        if not matches(f"{title} {snippet}", keywords):
            continue
        out.append(Candidate(url=e.get("link", ""), title=title, origin="rss", published_at=published, snippet=snippet[:MAX_SNIPPET]))
    return [c for c in out if c.url]


async def collect(feeds: list[str], keywords: list[str], since: datetime) -> list[Candidate]:
    if not feeds:
        return []
    async with client() as http:
        responses = await asyncio.gather(*[http.get(f) for f in feeds], return_exceptions=True)
    out = []
    for r in responses:
        if not isinstance(r, Exception) and r.status_code == 200:
            out += parse(r.text, keywords, since)
    return out
