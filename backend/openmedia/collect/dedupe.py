"""Déduplication : URL canonique, empreinte simhash du texte, titres voisins, reprises de dépêches.

Une dépêche AFP reprise par cinq journaux reste UNE source : c'est la règle qui empêche de
prendre l'écho pour une confirmation.
"""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from rapidfuzz import fuzz

from .rss import fold

TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|xtor|at_|ref|cmp|ns_|igshid|ocid|sr_share)", re.I)

# Des crédits de dépêche, pas de simples mentions : « interrogé par l'AFP » ou « a indiqué
# l'Agence France-Presse » ne font pas d'un article de rédaction une reprise.
WIRES = {
    "AFP": re.compile(r"\(AFP\)|\bAFP\s*[-–—]|avec AFP\b|\(Agence France-Presse\)", re.I),
    "Reuters": re.compile(r"\(Reuters\)|\bReuters\s*[-–—]|avec Reuters\b|\(Reuters\s", re.I),
    "AP": re.compile(r"\(AP\)|\(Associated Press\)", re.I),
    "Belga": re.compile(r"\(Belga\)|avec Belga\b", re.I),
}


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("amp.")
    path = re.sub(r"/amp/?$|\.amp$", "", parts.path).rstrip("/") or "/"
    query = urlencode(sorted((k, v) for k, v in parse_qsl(parts.query) if not TRACKING.match(k)))
    return urlunsplit(("https", host, path, query, ""))


def _shingles(text: str, k: int = 4) -> list[str]:
    words = re.findall(r"\w+", fold(text))
    return [" ".join(words[i : i + k]) for i in range(max(1, len(words) - k + 1))]


def simhash(text: str) -> str:
    """Empreinte 64 bits ; deux textes quasi identiques ne diffèrent que de quelques bits."""
    weights = [0] * 64
    for sh in _shingles(text):
        h = int.from_bytes(hashlib.blake2b(sh.encode(), digest_size=8).digest(), "big")
        for i in range(64):
            weights[i] += 1 if h >> i & 1 else -1
    value = sum(1 << i for i, w in enumerate(weights) if w > 0)
    return f"{value:016x}"


def hamming(a: str, b: str) -> int:
    if not a or not b:
        return 64
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def detect_wire(text: str) -> str:
    head = text[:600] + " " + text[-400:]
    for name, pattern in WIRES.items():
        if pattern.search(head):
            return name
    return ""


def same_title(a: str, b: str) -> bool:
    return fuzz.token_set_ratio(fold(a), fold(b)) >= 88


def cluster(items: list[dict]) -> list[dict]:
    """Attribue `cluster` à chaque élément ({id, title, simhash, wire}).

    Même cluster = même texte (simhash proche) ou même titre : c'est la même histoire
    racontée par la même plume (reprise de dépêche, syndication, mise à jour).
    """
    groups: list[dict] = []
    for it in items:
        for g in groups:
            if hamming(it.get("simhash", ""), g["simhash"]) <= 6 or same_title(it["title"], g["title"]):
                it["cluster"] = g["id"]
                break
        else:
            gid = f"c{len(groups) + 1}"
            groups.append({"id": gid, "simhash": it.get("simhash", ""), "title": it["title"]})
            it["cluster"] = gid
    return items
