"""Téléchargement des articles (concurrence bornée) et extraction du texte avec trafilatura.

openMedia lit une page pour son lecteur, à sa demande, comme son navigateur le ferait : ce n'est
pas un robot d'indexation, il ne suit aucun lien et ne republie rien. Il ne consulte donc ni
robots.txt ni les réservations de fouille de textes, et ne contourne aucun paywall : une page
fermée garde son titre et le résumé de son flux."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

import trafilatura

from .base import Candidate, client, parse_date

MAX_PAGE = 8_000_000  # octets : au-delà, ce n'est pas un article
MAX_TEXT = 12_000  # caractères gardés par article : assez pour recouper, sans exploser le contexte


@dataclass
class Extracted:
    url: str
    title: str
    text: str
    published_at: datetime | None
    author: str
    sitename: str
    lang: str


def from_html(html: str, url: str) -> Extracted | None:
    doc = trafilatura.bare_extraction(html, url=url, with_metadata=True, include_comments=False, favor_precision=True, as_dict=True)
    if not doc or not doc.get("text"):
        return None
    return Extracted(
        url=doc.get("url") or url,
        title=(doc.get("title") or "").strip(),
        text=doc["text"][:MAX_TEXT],
        published_at=parse_date(doc.get("date")),
        author=doc.get("author") or "",
        sitename=doc.get("sitename") or "",
        lang=doc.get("language") or "",
    )


async def fetch_teaser(url: str) -> tuple[str, str]:
    """Ce qu'une page réservée aux abonnés laisse lire : son titre et son chapô (balises de
    description). Rend ("", "") si la page refuse."""
    try:
        async with client(guard=True) as http:
            r = await http.get(url)
            if r.status_code != 200 or "html" not in r.headers.get("content-type", "html") or len(r.content) > MAX_PAGE:
                return "", ""
            meta = await asyncio.to_thread(trafilatura.extract_metadata, r.text, url)
    except Exception:
        return "", ""
    return ((meta.title or "").strip(), (meta.description or "").strip()[:1000]) if meta else ("", "")


async def fetch_many(candidates: list[Candidate], concurrency: int = 8) -> list[tuple[Candidate, Extracted | None]]:
    """Extrait chaque candidat ; un échec (paywall, page refusée, réseau) rend None et garde le titre."""
    sem = asyncio.Semaphore(concurrency)
    async with client(guard=True) as http:  # adresses venues du web : Internet public seulement

        async def one(c: Candidate):
            async with sem:
                try:
                    r = await http.get(c.url)
                    if r.status_code != 200 or "html" not in r.headers.get("content-type", "html") or len(r.content) > MAX_PAGE:
                        return c, None
                    c.url = str(r.url)
                    return c, await asyncio.to_thread(from_html, r.text, c.url)
                except Exception:
                    return c, None

        return await asyncio.gather(*[one(c) for c in candidates])
