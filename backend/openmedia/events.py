"""Bus d'événements en mémoire, relayé à l'interface par SSE (progression, notifications)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

_subscribers: set[asyncio.Queue] = set()


def publish(kind: str, **data) -> None:
    event = {"type": kind, "at": datetime.now(timezone.utc).isoformat(), **data}
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass


async def subscribe():
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.add(q)
    try:
        while True:
            yield await q.get()
    finally:
        _subscribers.discard(q)
