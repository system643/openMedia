"""Écouter sur son téléphone : un flux podcast privé, servi sur le réseau local seulement quand
le lecteur l'active, et des notifications relayées par ntfy s'il a choisi un sujet ntfy.

Le serveur « téléphone » est séparé de l'API : il n'expose que le flux et les fichiers mp3,
derrière un jeton secret dans l'adresse.
"""

from __future__ import annotations

import asyncio
import secrets
import socket
from email.utils import format_datetime
from xml.sax.saxutils import escape

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from sqlmodel import select

from . import events
from .config import data_dir, load_settings, update_settings
from .db import session
from .models import Brief, Fiche, Topic

PORT = 8790
_server: uvicorn.Server | None = None
_task: asyncio.Task | None = None


def lan_ip() -> str:
    """L'adresse de ce PC sur le réseau local (aucun paquet n'est envoyé)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def token() -> str:
    settings = load_settings()
    if not settings.podcast_token:
        update_settings({"podcast_token": secrets.token_urlsafe(18)})
        settings = load_settings()
    return settings.podcast_token


def feed_url() -> str:
    return f"http://{lan_ip()}:{PORT}/podcast/{token()}.xml"


def build_feed(base: str, tok: str) -> str:
    """Flux RSS des briefs et des fiches qui ont une version audio, du plus récent au plus ancien."""
    with session() as s:
        briefs = s.exec(select(Brief).where(Brief.audio_path != None).order_by(Brief.id.desc()).limit(30)).all()  # noqa: E711
        fiches = s.exec(select(Fiche).where(Fiche.audio_path != None).order_by(Fiche.id.desc()).limit(60)).all()  # noqa: E711
        names = {t.id: t.name for t in s.exec(select(Topic)).all()}
    items = [(b.created_at, f"Le Brief du {b.day}", b.content.get("headline", ""), b.audio_path) for b in briefs]
    items += [(f.created_at, f"{names.get(f.topic_id, 'Sujet')} — version {f.version}", f.content.get("lede", ""), f.audio_path) for f in fiches]
    items.sort(key=lambda i: i[0], reverse=True)
    entries = []
    for when, title, summary, audio in items:
        path = data_dir() / "audio" / audio
        size = path.stat().st_size if path.exists() else 0
        entries.append(
            f"<item><title>{escape(title)}</title><description>{escape(summary or '')}</description>"
            f"<pubDate>{format_datetime(when)}</pubDate><guid isPermaLink=\"false\">{escape(audio)}</guid>"
            f"<enclosure url=\"{base}/podcast/{tok}/audio/{escape(audio)}\" length=\"{size}\" type=\"audio/mpeg\"/></item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        "<title>openMedia</title><description>Ton journal personnel, à écouter.</description><language>fr</language>"
        + "".join(entries)
        + "</channel></rss>"
    )


phone_app = FastAPI(title="openMedia — téléphone", docs_url=None, redoc_url=None, openapi_url=None)


def _check(tok: str) -> None:
    if not secrets.compare_digest(tok, load_settings().podcast_token or "\0"):
        raise HTTPException(404)


@phone_app.get("/podcast/{tok}.xml")
def podcast(tok: str):
    _check(tok)
    return Response(build_feed(f"http://{lan_ip()}:{PORT}", tok), media_type="application/rss+xml")


@phone_app.get("/podcast/{tok}/audio/{name}")
def podcast_audio(tok: str, name: str):
    _check(tok)
    folder = (data_dir() / "audio").resolve()
    path = (folder / name).resolve()
    if path.parent != folder or not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="audio/mpeg")


async def start() -> None:
    global _server, _task
    if _server is not None:
        return
    token()
    _server = uvicorn.Server(uvicorn.Config(phone_app, host="0.0.0.0", port=PORT, log_level="warning"))
    _task = asyncio.create_task(_server.serve())


async def stop() -> None:
    global _server, _task
    if _server is None:
        return
    _server.should_exit = True
    if _task:
        await _task
    _server, _task = None, None


def status() -> dict:
    import segno

    enabled = load_settings().phone_listen
    if not enabled:
        return {"enabled": False}
    url = feed_url()
    return {"enabled": True, "running": _server is not None, "url": url, "qr_svg": segno.make(url, error="m").svg_inline(scale=5, dark="#16181d", light="#ffffff")}


# ── Notifications vers le téléphone (ntfy) ───────────────────────────────────

FORWARDED = {"correction", "announcement", "brief", "notify"}


async def forward_to_ntfy() -> None:
    """Relaie les événements importants vers ntfy.sh/<sujet choisi par le lecteur>."""
    async with httpx.AsyncClient(timeout=10) as http:
        async for e in events.subscribe():
            topic = load_settings().ntfy_topic.strip()
            if not topic or e.get("type") not in FORWARDED:
                continue
            title = e.get("title") or ("Le Brief est prêt" if e["type"] == "brief" else "openMedia")
            body = e.get("body") or e.get("headline") or ""
            try:
                await http.post("https://ntfy.sh/", json={"topic": topic, "title": title, "message": body or title, "tags": ["newspaper"]})
            except httpx.HTTPError:
                pass
