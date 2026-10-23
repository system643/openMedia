"""Réseaux sociaux en option, sujet par sujet : Reddit, Hacker News, chaînes Telegram publiques.

Ce sont des signaux (ce dont on parle, ce qui circule) : leurs messages entrent dans le tri
comme les articles, mais ne comptent jamais comme une source indépendante (voir
`agents/material.counts_as_source`). Les articles de presse vers lesquels pointe Hacker News,
eux, sont des articles comme les autres.
"""

from __future__ import annotations

import asyncio
import html
import re
from datetime import datetime
from urllib.parse import quote

import feedparser

from .base import Candidate, client, parse_date
from .rss import matches

_TG_MESSAGE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>.*?<a class="tgme_widget_message_date" href="([^"]+)"><time datetime="([^"]+)"', re.S)
_TAG = re.compile(r"<[^>]+>")


def parse_reddit(xml: str, since: datetime) -> list[Candidate]:
    """Flux Atom de la recherche Reddit (l'API JSON est fermée sans compte développeur)."""
    out = []
    for e in feedparser.parse(xml).entries:
        published = parse_date(e.get("updated_parsed") or e.get("published_parsed"))
        link = e.get("link", "")
        if "/comments/" not in link or (published and published < since):
            continue
        sub = next((t.get("label") or t.get("term") for t in e.get("tags", []) if t.get("term")), "")
        snippet = html.unescape(_TAG.sub(" ", e.get("summary", "")))[:1500]
        out.append(Candidate(url=link, title=e.get("title", ""), origin="reddit", source_name=sub or "Reddit", published_at=published, snippet=snippet))
    return out


def parse_hn(payload: dict) -> list[Candidate]:
    out = []
    for h in payload.get("hits", []):
        item = f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        out.append(Candidate(url=h.get("url") or item, title=h.get("title") or "", origin="hn", source_name="Hacker News", published_at=parse_date(h.get("created_at")), extra={"discussion": item, "points": h.get("points", 0)}))
    return [c for c in out if c.title]


def parse_telegram(page: str, channel: str, keywords: list[str], since: datetime) -> list[Candidate]:
    out = []
    for body, link, when in _TG_MESSAGE.findall(page):
        raw = html.unescape(_TAG.sub("", body.replace("<br/>", "\n")))
        text = "\n".join(" ".join(line.split()) for line in raw.splitlines()).strip()
        published = parse_date(when)
        if not text or (published and published < since) or not matches(text, keywords):
            continue
        out.append(Candidate(url=link, title=text.split("\n")[0][:140], origin="telegram", source_name=f"Telegram @{channel}", published_at=published, snippet=text[:1500]))
    return out


async def collect(options: dict, queries: list[str], keywords: list[str], since: datetime) -> list[Candidate]:
    if not options or not (options.get("reddit") or options.get("hn") or options.get("telegram")):
        return []
    out: list[Candidate] = []
    async with client() as http:
        jobs = []
        for q in queries[:2]:
            if options.get("reddit"):
                jobs.append(("reddit", http.get(f"https://www.reddit.com/search.rss?q={quote(q)}&sort=new&t=week&type=link")))
            if options.get("hn"):
                jobs.append(("hn", http.get(f"https://hn.algolia.com/api/v1/search_by_date?query={quote(q)}&tags=story&numericFilters=created_at_i>{int(since.timestamp())}")))
        for channel in (options.get("telegram") or [])[:10]:
            name = channel.strip().lstrip("@").split("/")[-1]
            if name:
                jobs.append((f"tg:{name}", http.get(f"https://t.me/s/{name}")))
        responses = await asyncio.gather(*[j for _, j in jobs], return_exceptions=True)
    for (kind, _), r in zip(jobs, responses):
        if isinstance(r, Exception) or r.status_code != 200:
            continue
        try:
            if kind == "reddit":
                out += parse_reddit(r.text, since)
            elif kind == "hn":
                out += parse_hn(r.json())
            else:
                out += parse_telegram(r.text, kind[3:], keywords, since)
        except ValueError:
            continue
    return out
