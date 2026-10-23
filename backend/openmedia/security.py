"""Sécurité : les agents d'openMedia n'ont aucun pouvoir sur le PC, et ce qui vient du web
reste une donnée.

Quatre couches :
1. Les agents ne disposent d'aucun outil d'action (au plus la recherche web) : Claude Code est
   lancé verrouillé, avec un environnement expurgé ; les appels API n'envoient aucun autre outil.
2. Le backend ne télécharge que des pages de l'Internet public (pas de 127.0.0.1, de box ou de
   réseau local), même si une adresse vient d'un modèle ou d'un flux.
3. Le texte venu du web est nettoyé avant d'entrer dans un prompt (caractères invisibles,
   balises qui imiteraient le matériau) et les consignes adressées à une IA sont repérées.
4. Ce qui sort vers un autre assistant (serveur MCP) est nettoyé, et les passages suspects
   sont masqués.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from urllib.parse import urlsplit

# ── 1. Agents sans pouvoir ───────────────────────────────────────────────────

# Les seuls outils qu'un moteur API peut recevoir : la recherche web, côté fournisseur.
ALLOWED_TOOL_TYPES = {"web_search_20260209", "web_search", "google_search"}

# Variables jamais transmises au processus Claude Code : jeton de l'API locale, clés des
# autres fournisseurs, et ANTHROPIC_API_KEY (l'abonnement reste la seule facturation).
_SECRET_PREFIXES = ("OPENMEDIA_", "OPENAI_", "GEMINI_", "OPENROUTER_", "MISTRAL_", "DEEPSEEK_", "MOONSHOT_", "KIMI_", "ZAI_", "ZHIPU_", "DASHSCOPE_", "QWEN_", "XAI_", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GOOGLE_API_KEY")
_DROP = {"NODE_OPTIONS", "NODE_PATH", "PYTHONPATH", "PYTHONSTARTUP"}


def child_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.upper().startswith(_SECRET_PREFIXES) and k.upper() not in _DROP}


def check_tools(tools: list[dict] | None) -> None:
    """Refuse tout outil autre que la recherche web : un agent d'openMedia ne peut pas agir."""
    for tool in tools or []:
        kind = tool.get("type") or next(iter(tool), "")
        if kind not in ALLOWED_TOOL_TYPES:
            raise PermissionError(f"Outil refusé pour un agent d'openMedia : {kind}")


CLAUDE_NAMES = {"claude", "claude.exe", "claude.cmd"}


def valid_claude_path(path: str) -> bool:
    """Le chemin indiqué à la main doit désigner Claude Code, rien d'autre."""
    if not path:
        return True
    return os.path.basename(path).lower() in CLAUDE_NAMES and os.path.isfile(path)


# ── 2. Seulement l'Internet public ───────────────────────────────────────────


class BlockedUrl(Exception):
    pass


def _public_ip(ip: str) -> bool:
    addr = ipaddress.ip_address(ip.split("%")[0])
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


async def check_public_url(url: str) -> None:
    """Lève `BlockedUrl` si l'adresse ne mène pas à l'Internet public."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise BlockedUrl(f"adresse refusée : {url[:80]}")
    host = parts.hostname
    try:
        ipaddress.ip_address(host.split("%")[0])
        ips = [host]
    except ValueError:
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa")):
            raise BlockedUrl(f"hôte local refusé : {host}")
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror:
            return  # nom introuvable : la requête échouera d'elle-même
        ips = [info[4][0] for info in infos]
    if not ips or not all(_public_ip(ip) for ip in ips):
        raise BlockedUrl(f"adresse non publique refusée : {host}")


async def guard_request(request) -> None:
    """Crochet httpx : appelé pour chaque requête, redirections comprises."""
    await check_public_url(str(request.url))


# ── 3 et 4. Le contenu venu du web reste une donnée ─────────────────────────

# Invisibles et contrôles de direction : zero-width, bidi, BOM, « tags » Unicode (U+E0000–E007F,
# qui permettent d'écrire du texte invisible lisible par un modèle).
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿\U000e0000-\U000e007f]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Balises qui pourraient fermer ou imiter le matériau (<article>, </fiche>, <system>…).
_TAG = re.compile(r"<(/?\s*[A-Za-z_!?][^<>]{0,200})>")
_SPECIAL_TOKEN = re.compile(r"<\|([^<>|]{0,40})\|>")


def clean(text: str | None) -> str:
    """Texte venu du web, prêt à entrer dans un prompt : sans invisibles ni balises."""
    if not text:
        return ""
    text = _INVISIBLE.sub("", text)
    text = _CONTROL.sub(" ", text)
    text = _SPECIAL_TOKEN.sub(r"‹\1›", text)
    return _TAG.sub(r"‹\1›", text)


def clean_deep(obj):
    """`clean` appliqué à toutes les chaînes d'une structure JSON."""
    if isinstance(obj, str):
        return clean(obj)
    if isinstance(obj, dict):
        return {k: clean_deep(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_deep(v) for v in obj]
    return obj


_SIGNALS = [
    (re.compile(p, re.I | re.M), label)
    for p, label in [
        (r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|your)\b.{0,30}\b(instructions?|prompts?|rules|directions)", "ordre d'ignorer les consignes"),
        (r"\b(ignore[rz]?|oublie[rz]?|néglige[rz]?)\b.{0,40}\b(instructions?|consignes?|règles)\b.{0,30}\b(précédentes?|ci-dessus|antérieures?|initiales?)", "ordre d'ignorer les consignes"),
        (r"\b(system|developer)\s*(prompt|message|instructions?)\s*[:=]", "faux message système"),
        (r"\b(you are now|from now on,? you|act as an? (ai|assistant|llm))\b", "changement de rôle"),
        (r"\b(tu es (désormais|maintenant)|à partir de maintenant,? tu|agis comme (une? )?(ia|assistant))\b", "changement de rôle"),
        (r"^\s*(assistant|system|user)\s*:", "faux tour de conversation"),
        (r"#{2,}\s*(instruction|system|new task|nouvelle tâche)", "fausse section de consignes"),
        (r"\b(note|message|instructions?)\s+(to|for|pour|à l'attention de)\s+(the\s+|l')?(ai|ia|llm|assistant|model|modèle|agent)\b", "message adressé à une IA"),
        (r"\b(run|execute|exécute[rz]?|lance[rz]?)\b.{0,30}\b(command|commande|shell|powershell|bash|script|terminal)\b", "demande d'exécution"),
        (r"\b(reveal|print|show|affiche[rz]?|révèle[rz]?)\b.{0,30}\b(system prompt|api key|clé api|token|jeton|password|mot de passe)\b", "demande de secret"),
    ]
]


def injection_signals(text: str | None) -> list[str]:
    """Les motifs de consignes adressées à une IA trouvés dans un texte (vide : rien)."""
    if not text:
        return []
    found = []
    for pattern, label in _SIGNALS:
        if pattern.search(text) and label not in found:
            found.append(label)
    return found


MASKED = "[passage masqué : il contenait des consignes adressées à une IA]"
