"""L'IA sur ce PC : un modèle servi par Ollama ou LM Studio. En mode local, TOUS les appels
passent par lui (voir `RouterLLM.resolve`) : rien ne part chez un fournisseur en ligne. Hors de
ce mode, un rôle peut aussi lui être confié (`ollama:qwen3:14b`), à côté d'une IA en ligne.

Ollama passe par son API native (`/api/chat`) : c'est la seule qui accepte la taille du
contexte (`num_ctx`), et les consignes de rédaction dépassent les 4 096 tokens par défaut.
LM Studio passe par son API compatible OpenAI ; la taille du contexte se règle au chargement
du modèle, dans LM Studio.
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from ...security import check_tools
from ..http import shared_client
from ..llm import LLM, LLMError, NoApiKey, RunMeter, T, system_text
from ..errors import http_error
from .openai_compat import strict_schema, validate_json

DEFAULT_URLS = {"ollama": "http://127.0.0.1:11434", "lmstudio": "http://127.0.0.1:1234"}
LABELS = {"ollama": "Ollama", "lmstudio": "LM Studio"}
CONTEXT = 32768  # tokens : la fiche précédente et 25 articles tiennent dedans
_detected: dict = {"at": 0.0, "key": None, "value": None}


def base_url(provider: str, urls: dict[str, str] | None = None) -> str:
    return ((urls or {}).get(provider) or DEFAULT_URLS[provider]).rstrip("/")


def _ollama(url: str, timeout: float) -> list[dict]:
    data = httpx.get(f"{url}/api/tags", timeout=timeout).json()
    return [{"id": m["name"], "size": (m.get("details") or {}).get("parameter_size") or "", "context": None} for m in data.get("models") or [] if m.get("name")]


def _lmstudio(url: str, timeout: float) -> list[dict]:
    try:  # l'API REST de LM Studio donne aussi le type et la taille du contexte chargé
        r = httpx.get(f"{url}/api/v0/models", timeout=timeout)
        r.raise_for_status()
        return [
            {"id": m["id"], "size": m.get("arch") or "", "context": m.get("loaded_context_length") or m.get("max_context_length")}
            for m in r.json().get("data") or []
            if m.get("id") and m.get("type", "llm") in ("llm", "vlm")
        ]
    except (httpx.HTTPStatusError, ValueError, KeyError):  # serveur sans l'API REST : la liste OpenAI
        data = httpx.get(f"{url}/v1/models", timeout=timeout).json()
        return [{"id": m["id"], "size": "", "context": None} for m in data.get("data") or [] if m.get("id") and "embed" not in m["id"]]


def detect(urls: dict[str, str] | None = None, *, fresh: bool = False, timeout: float = 0.6) -> dict:
    """Les serveurs locaux qui répondent, et leurs modèles. Les réglages le lisent à chaque
    affichage : au-delà de 30 s, la valeur gardée est rendue tout de suite et relue en fond,
    pour ne jamais faire attendre l'interface (un port fermé met jusqu'à 2 s à refuser)."""
    key = tuple(sorted((urls or {}).items()))
    if not fresh and _detected["key"] == key and _detected["value"] is not None:
        if time.time() - _detected["at"] >= 30 and not _detected.get("refreshing"):
            _detected["refreshing"] = True
            threading.Thread(target=_refresh, args=(urls, timeout), daemon=True).start()
        return _detected["value"]
    return _probe(urls, timeout)


def _refresh(urls, timeout) -> None:
    try:
        _probe(urls, timeout)
    finally:
        _detected["refreshing"] = False


def _probe(urls: dict[str, str] | None, timeout: float) -> dict:
    key = tuple(sorted((urls or {}).items()))

    def one(provider: str, read) -> dict:
        url = base_url(provider, urls)
        try:
            return {"label": LABELS[provider], "found": True, "url": url, "models": read(url, timeout)}
        except (httpx.HTTPError, ValueError, KeyError, AttributeError):
            return {"label": LABELS[provider], "found": False, "url": url, "models": []}

    # En parallèle : sous Windows, un port fermé met jusqu'à 2 s à refuser la connexion.
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {p: pool.submit(one, p, read) for p, read in (("ollama", _ollama), ("lmstudio", _lmstudio))}
        out = {p: job.result() for p, job in jobs.items()}
    _detected.update(at=time.time(), key=key, value=out)
    return out


_gates: dict[tuple[str, int], asyncio.Semaphore] = {}


def _gate(url: str) -> asyncio.Semaphore:
    """Le verrou d'un serveur local, partagé par tous les passages (chacun crée son `LocalLLM`) ;
    un par boucle d'événements, à laquelle un sémaphore est lié."""
    key = (url, id(asyncio.get_running_loop()))
    return _gates.setdefault(key, asyncio.Semaphore(1))


class LocalLLM(LLM):
    name = "local"

    def __init__(self, provider: str, model: str = "", urls: dict[str, str] | None = None):
        """`model` : le modèle imposé à tous les appels (mode local) ; vide, chaque appel dit le sien."""
        if provider not in DEFAULT_URLS:
            raise NoApiKey(f"Serveur local inconnu : {provider}")
        self.provider, self.model = provider, model
        self.url = base_url(provider, urls)
        self.http = shared_client(httpx.Timeout(900, connect=10))
        self.gate = _gate(self.url)  # un seul appel à la fois : la carte graphique est partagée

    def full(self, model: str) -> str:
        return f"{self.provider}:{model}"

    async def _post(self, path: str, body: dict) -> dict:
        check_tools(body.get("tools"))
        async with self.gate:
            try:
                r = await self.http.post(f"{self.url}{path}", json=body)
            except httpx.TransportError as e:
                raise LLMError(f"{LABELS[self.provider]} ne répond pas ({self.url}) : est-il lancé ?") from e
        if r.status_code >= 400:
            raise http_error(LABELS[self.provider], r.status_code, r.text, local=True)
        return r.json()

    async def _call(self, meter: RunMeter, *, model: str, task: str | None, content: str, max_tokens: int, schema, label: str) -> str:
        model = self.model or model
        if not model:
            raise NoApiKey(f"Aucun modèle choisi pour {LABELS[self.provider]} : choisis-en un dans Réglages › Moteur IA.")
        system = system_text(task)
        if self.provider == "ollama":
            body = {
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
                "stream": False,
                "options": {"num_ctx": CONTEXT, "num_predict": max_tokens},
            }
            if schema is not None:
                body["format"] = strict_schema(schema)
            data = await self._post("/api/chat", body)
            fresh, output = data.get("prompt_eval_count") or 0, data.get("eval_count") or 0
            text = (data.get("message") or {}).get("content") or ""
            truncated = data.get("done_reason") == "length"
        else:
            body = {
                "model": model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
                "max_tokens": max_tokens,
            }
            if schema is not None:
                body["response_format"] = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": strict_schema(schema), "strict": True}}
            data = await self._post("/v1/chat/completions", body)
            usage = data.get("usage") or {}
            fresh, output = usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0
            choice = (data.get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content") or ""
            truncated = choice.get("finish_reason") == "length"
        # Rien n'est facturé : les tokens sont comptés, le coût est nul.
        meter.record(task=label, model=self.full(model), fresh=fresh, output=output, cost=0.0, via="local")
        if truncated:
            raise LLMError(f"{model} a atteint la limite de longueur de réponse.")
        meter.note(f"{label} · {self.full(model)} (sur ce PC) · {output} tokens en sortie")
        return text.strip()

    async def parse(self, meter: RunMeter, *, model: str, task: str, content: str, schema: type[T], effort: str = "medium", max_tokens: int = 16000) -> T:
        raw = await self._call(meter, model=model, task=task, content=content, max_tokens=max_tokens, schema=schema, label=task)
        try:
            return validate_json(schema, raw)
        except LLMError as first:
            meter.note(f"{task} · réponse invalide, nouvelle demande ({first})")
            retry = f"{content}\n\nTa réponse précédente n'était pas conforme ({first}). Rends uniquement l'objet JSON demandé, conforme au schéma."
            raw = await self._call(meter, model=model, task=task, content=retry, max_tokens=max_tokens, schema=schema, label=task)
            return validate_json(schema, raw)

    async def text(self, meter: RunMeter, *, model: str, task: str, content: str, effort: str = "medium", max_tokens: int = 8000) -> str:
        return await self._call(meter, model=model, task=task, content=content, max_tokens=max_tokens, schema=None, label=task)

    async def search(self, meter: RunMeter, *, model: str, prompt: str, max_uses: int = 3) -> list[dict]:
        meter.note("recherche web indisponible avec l'IA sur ce PC")
        return []
