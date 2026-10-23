"""Le type commun à tous les collecteurs et le client HTTP partagé."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

# openMedia se présente pour ce qu'il est, et non comme un navigateur.
USER_AGENT = "Mozilla/5.0 (compatible; openMedia/0.2; lecteur de presse personnel, open source)"


@dataclass
class Candidate:
    """Un lien trouvé par un collecteur, avant extraction du texte."""

    url: str
    title: str
    origin: str  # gdelt | une | rss | drop | claude_search (google_news : avant le 22/10/2026)
    source_name: str = ""
    published_at: datetime | None = None
    lang: str = ""
    snippet: str = ""
    extra: dict = field(default_factory=dict)


def client(timeout: float = 20.0, guard: bool = False) -> httpx.AsyncClient:
    """`guard` : seulement l'Internet public, redirections comprises (les adresses viennent
    alors du web ou d'un modèle, et ne doivent jamais mener au PC ni au réseau local)."""
    from ..security import guard_request

    return httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8"},
        timeout=timeout,
        follow_redirects=True,
        max_redirects=8,
        event_hooks={"request": [guard_request]} if guard else None,
    )


def parse_date(value) -> datetime | None:
    """RFC 822 (RSS), ISO 8601, struct_time de feedparser ou AAAAMMJJTHHMMSSZ (GDELT)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if hasattr(value, "tm_year"):
        return datetime(*value[:6], tzinfo=timezone.utc)
    text = str(value).strip()
    for parse in (
        lambda t: parsedate_to_datetime(t),
        lambda t: datetime.fromisoformat(t.replace("Z", "+00:00")),
        lambda t: datetime.strptime(t, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc),
    ):
        try:
            dt = parse(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError, IndexError):
            continue
    return None
