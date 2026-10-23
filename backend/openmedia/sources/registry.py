"""Registre des sources : retrouver le média d'une URL et juger l'indépendance de deux sources."""

from __future__ import annotations

from functools import lru_cache
from urllib.parse import urlsplit

import tldextract
from sqlmodel import select

from ..db import session
from ..models import Source
from .quality import rated

# Liste des suffixes embarquée : aucun appel réseau au démarrage.
_extract = tldextract.TLDExtract(suffix_list_urls=())


def registered_domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
    parts = _extract(host)
    return parts.top_domain_under_public_suffix or host


def lookup(url_or_domain: str) -> Source:
    """Le média le plus précis qui correspond (sous-domaine connu, sinon domaine enregistré)."""
    host = url_or_domain if "/" not in url_or_domain else (urlsplit(url_or_domain).hostname or "")
    host = host.lower().removeprefix("www.")
    known = _known()
    candidates = [host]
    pieces = host.split(".")
    candidates += [".".join(pieces[i:]) for i in range(1, len(pieces) - 1)]
    for c in candidates:
        if c in known:
            return known[c]
    domain = registered_domain("https://" + host)
    if domain in known:
        return known[domain]
    score = rated(domain)
    return Source(domain=domain, name=domain, owner=domain, quality=score, quality_origin="lin2023" if score is not None else "")


def ensure(domain: str, kind: str | None = None) -> Source:
    """Enregistre un domaine inconnu pour que l'utilisateur puisse ensuite le qualifier.
    `kind` qualifie d'office un domaine encore inconnu (archives de recherche, par exemple)."""
    src = lookup(domain)
    if src.domain not in _known() or (kind and src.kind == "unknown"):
        with session() as s:
            row = s.get(Source, src.domain)
            if not row:
                row = src
            if kind and row.kind == "unknown":
                row.kind = kind
            s.add(row)
            s.commit()
            s.refresh(row)
            src = row
        _known.cache_clear()
    return src


def kinds() -> dict[str, str]:
    """{domaine: famille} des médias du registre (le format qu'attend `history.is_news`)."""
    return {domain: src.kind for domain, src in _known().items()}


def owner_key(src: Source) -> str:
    return (src.owner or src.domain).strip().lower()


def is_blocked(domain: str) -> bool:
    return lookup(domain).blocked


@lru_cache(maxsize=1)
def _known() -> dict[str, Source]:
    with session() as s:
        return {src.domain: src for src in s.exec(select(Source)).all()}


def invalidate() -> None:
    _known.cache_clear()
