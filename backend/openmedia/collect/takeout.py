"""Import d'un export Google Takeout : l'historique Chrome synchronisé (téléphone compris) et
« Mon activité » (Chrome, Google Actualités, Discover).

Le lecteur l'obtient sur takeout.google.com en ne cochant que « Chrome » et « Mon activité »
(format JSON). On accepte l'archive .zip, le dossier décompressé ou un fichier .json seul.
"""

from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .base import parse_date
from .history import Visit

# « Visited … » en anglais, « A consulté … » en français, etc. : le titre suit le verbe.
_VERB = re.compile(r"^(Visited|A consulté|Visité|Visitó|Besucht|Ha visitato|Viewed|A regardé)\s+", re.I)


def _from_browser_history(data: dict) -> list[Visit]:
    out = []
    for e in data.get("Browser History", []):
        url = e.get("url", "")
        when = datetime.fromtimestamp(int(e.get("time_usec", 0)) / 1_000_000, tz=timezone.utc)
        out.append(Visit(url=url, title=(e.get("title") or "").strip(), visits=1, first_visit=when, last_visit=when, synced=1))
    return out


def _from_activity(items: list) -> list[Visit]:
    out = []
    for e in items:
        url = e.get("titleUrl") or ""
        if not url.startswith("http"):
            continue
        # Les liens passent parfois par une redirection Google : on garde la destination.
        m = re.search(r"[?&](?:q|url)=(https?[^&]+)", url) if "google.com/url" in url else None
        if m:
            from urllib.parse import unquote

            url = unquote(m.group(1))
        when = parse_date(e.get("time")) or datetime.now(timezone.utc)
        out.append(Visit(url=url, title=_VERB.sub("", e.get("title", "")).strip(), visits=1, first_visit=when, last_visit=when, synced=1))
    return out


def _parse(name: str, raw: bytes) -> list[Visit]:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        return []
    if isinstance(data, dict) and "Browser History" in data:
        return _from_browser_history(data)
    if isinstance(data, list):
        return _from_activity(data)
    return []


def _merge(visits: list[Visit]) -> list[Visit]:
    by_url: dict[str, Visit] = {}
    for v in visits:
        cur = by_url.get(v.url)
        if not cur:
            by_url[v.url] = v
        else:
            cur.visits += 1
            cur.synced += v.synced
            cur.first_visit = min(cur.first_visit, v.first_visit)
            cur.last_visit = max(cur.last_visit, v.last_visit)
            cur.title = cur.title or v.title
    return list(by_url.values())


def read(path: str) -> list[Visit]:
    p = Path(path)
    visits: list[Visit] = []
    if p.is_file() and zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            for info in z.infolist():
                if info.filename.lower().endswith(".json") and info.file_size < 400_000_000:
                    visits += _parse(info.filename, z.read(info))
    elif p.is_dir():
        for f in p.rglob("*.json"):
            visits += _parse(f.name, f.read_bytes())
    elif p.is_file():
        visits += _parse(p.name, p.read_bytes())
    else:
        raise FileNotFoundError(f"Introuvable : {path}")
    return _merge(visits)
