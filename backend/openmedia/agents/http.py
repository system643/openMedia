"""Un client HTTP par boucle d'événements et par réglage de délai, partagé par les moteurs :
chaque passage crée ses moteurs, mais ne laisse plus derrière lui un client ouvert."""

from __future__ import annotations

import asyncio

import httpx

_clients: dict[tuple[int, str], httpx.AsyncClient] = {}


def shared_client(timeout: httpx.Timeout) -> httpx.AsyncClient:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # hors boucle (un script) : un client à soi
        return httpx.AsyncClient(timeout=timeout)
    key = (id(loop), repr(timeout))
    client = _clients.get(key)
    if client is None or client.is_closed:
        client = _clients[key] = httpx.AsyncClient(timeout=timeout)
    return client
