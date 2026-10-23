"""Reconnaître le fournisseur d'une clé API collée, puis la vérifier par un appel léger
(la liste des modèles), avant de la ranger dans le Gestionnaire d'identifiants."""

from __future__ import annotations

import re

import httpx

from .catalog import PROVIDERS


class KeyRefused(ValueError):
    pass


def detect_provider(key: str) -> list[str]:
    """Les fournisseurs possibles, du plus probable au moins probable. Une clé n'est essayée
    que chez les fournisseurs dont elle a la forme : on n'envoie pas une clé partout."""
    k = key.strip()
    if k.startswith("sk-ant-"):
        return ["anthropic"]
    if k.startswith("sk-or-"):
        return ["openrouter"]
    if k.startswith("AIza"):
        return ["gemini"]
    if k.startswith("xai-"):
        return ["xai"]
    if k.startswith(("sk-proj-", "sk-svcacct-", "sk-admin-")):
        return ["openai"]
    if re.fullmatch(r"[0-9a-f]{32}\.[A-Za-z0-9]{8,32}", k):  # identifiant.secret
        return ["zai"]
    if re.fullmatch(r"sk-[0-9a-f]{32}", k):
        return ["deepseek", "qwen"]
    if re.fullmatch(r"sk-[A-Za-z0-9]{48}", k):
        return ["openai"] if "T3BlbkFJ" in k else ["moonshot", "openai"]
    if k.startswith("sk-"):
        return ["openai", "deepseek", "moonshot", "qwen", "mistral"]
    if re.fullmatch(r"[A-Za-z0-9]{32}", k):
        return ["mistral"]
    return ["mistral", "openai"]


def _check_request(provider: str, key: str) -> tuple[str, dict]:
    if provider == "anthropic":
        return "https://api.anthropic.com/v1/models", {"x-api-key": key, "anthropic-version": "2023-06-01"}
    if provider == "openrouter":  # la liste des modèles est publique : on vérifie la clé elle-même
        return "https://openrouter.ai/api/v1/key", {"Authorization": f"Bearer {key}"}
    if provider == "gemini":
        return "https://generativelanguage.googleapis.com/v1beta/models", {"x-goog-api-key": key}
    from .catalog import base_url

    return f"{base_url(provider)}{PROVIDERS[provider].key_check}", {"Authorization": f"Bearer {key}"}


async def check_key(key: str, provider: str | None = None) -> tuple[str, bool]:
    """(fournisseur, vérifiée). Lève `KeyRefused` si aucun fournisseur n'accepte la clé.
    Hors ligne, une clé au préfixe sans ambiguïté est acceptée sans vérification."""
    candidates = [provider] if provider else detect_provider(key)
    offline = False
    busy: list[str] = []  # fournisseurs surchargés ou en quota : la clé n'est pas refusée pour autant
    async with httpx.AsyncClient(timeout=15) as http:
        for p in candidates:
            url, headers = _check_request(p, key)
            if not url.startswith("https://"):
                raise KeyRefused(f"Indique d'abord l'adresse de l'API de {PROVIDERS[p].label} (https://…).")
            try:
                r = await http.get(url, headers=headers)
            except httpx.HTTPError:
                offline = True
                continue
            if r.status_code < 400:
                return p, True
            if r.status_code not in (401, 403):
                busy.append(p)
    if busy:
        return busy[0], False
    if offline and len(candidates) == 1:
        return candidates[0], False
    names = " ou ".join(PROVIDERS[p].label for p in candidates)
    raise KeyRefused(f"Clé refusée par {names}." if not offline else f"Impossible de vérifier la clé ({names}) : vérifie ta connexion.")


async def list_live(provider: str, key: str) -> list[str]:
    """Les identifiants de modèles que la clé peut utiliser (texte seulement, au mieux)."""
    if provider == "openrouter":
        url, headers = "https://openrouter.ai/api/v1/models", {}
    else:
        url, headers = _check_request(provider, key)
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.get(url, headers=headers, params={"pageSize": 1000} if provider == "gemini" else None)
        r.raise_for_status()
        data = r.json()
    if provider == "gemini":
        return [m["name"].removeprefix("models/") for m in data.get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]
    ids = [m["id"] for m in data.get("data", [])]
    if provider == "openai":
        skip = ("embedding", "whisper", "tts", "dall-e", "image", "audio", "realtime", "moderation", "transcribe", "search", "davinci", "babbage", "sora")
        ids = [i for i in ids if not any(s in i for s in skip)]
    return sorted(ids)
