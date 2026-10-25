"""Moteur des fournisseurs autres qu'Anthropic : OpenAI (API Responses), puis tous ceux qui
parlent l'API Chat Completions (Gemini, OpenRouter, Mistral, DeepSeek, Kimi, GLM, Qwen, Grok,
et tout autre fournisseur compatible). Appels en httpx direct : aucun SDK de plus à embarquer.

Chaque fournisseur a son profil (`catalog.Provider`) : la sortie structurée qu'il sait rendre
(schéma JSON strict, le même sans `$ref`, ou simple « objet JSON » avec le schéma écrit dans la
consigne), la façon de régler sa réflexion, le nom de son plafond de sortie. Si un modèle refuse
malgré tout un paramètre, l'appel est rejoué un cran plus simple, et le moteur s'en souvient
pour ce modèle jusqu'au prochain démarrage. Toute réponse passe ensuite la validation Pydantic ;
une réponse invalide est redemandée une fois, avec l'erreur.
"""

from __future__ import annotations

import asyncio
import json
import re
from copy import deepcopy

import httpx
from pydantic import BaseModel, ValidationError

from ...config import get_key
from ...security import check_tools
from ..errors import http_error, refused_content
from ..http import shared_client
from ..llm import LLM, ContentRefused, LLMError, NoApiKey, RunMeter, T, system_text
from . import catalog
from .catalog import PROVIDERS

RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}
OPENAI_SEARCH_PRICE = 10.00 / 1000
GEMINI_SEARCH_PRICE = 14.00 / 1000  # au-delà des 5 000 recherches gratuites du mois
THINK_MARGIN = 16_000  # tokens de réflexion ajoutés au plafond de sortie d'un modèle qui réfléchit

# Ce que le moteur a appris d'un modèle qui refusait un paramètre : (fournisseur, modèle) →
# {"structured": …, "no_reasoning": True, "max_tokens_param": …, "cap": …}.
LEARNED: dict[tuple[str, str], dict] = {}

_STRUCTURED_HINT = re.compile(r"response_format|json_schema|json_object|schema|strict|\$ref|\$defs|definitions", re.I)
_REF_HINT = re.compile(r"\$ref|\$defs|definitions|reference", re.I)
_REASONING_HINT = re.compile(r"thinking|reasoning|enable_thinking", re.I)
_CAP = re.compile(r"(?:<=|less than or equal to|at most|maximum(?: value)?(?: is| of)?|up to|not exceed|exceeds? the limit of|range of \[?\s*\d+\s*,)\s*(\d{3,7})", re.I)
_THINK = re.compile(r"<think>.*?</think>", re.S)


class Rejected(LLMError):
    """Une requête refusée (400 ou 422) : le message est déjà dit en français ; `detail` garde
    la réponse du fournisseur pour décider d'un repli."""

    def __init__(self, message: str, status: int, detail: str):
        super().__init__(message)
        self.status, self.detail = status, detail


class _Truncated(LLMError):
    pass


def strict_schema(model: type[BaseModel]) -> dict:
    """Schéma JSON strict : tous les champs requis, aucun champ en plus, sans `title` ni
    `default` (refusés par certains fournisseurs). Les champs facultatifs restent `null`-ables."""
    schema = deepcopy(model.model_json_schema())

    def walk(node) -> None:
        if isinstance(node, list):
            for x in node:
                walk(x)
            return
        if not isinstance(node, dict):
            return
        if isinstance(node.get("title"), str):
            del node["title"]
        node.pop("default", None)
        if node.get("type") == "object" and isinstance(node.get("properties"), dict):
            node["required"] = list(node["properties"])
            node["additionalProperties"] = False
        for key, value in node.items():
            if key in ("properties", "$defs") and isinstance(value, dict):
                for sub in value.values():  # les clés sont des noms de champs, pas des mots-clés
                    walk(sub)
            else:
                walk(value)

    walk(schema)
    return schema


def inline_refs(schema: dict) -> dict:
    """Le même schéma, chaque `$ref` remplacé par sa définition (pour les fournisseurs qui ne
    suivent pas les références). Les schémas d'openMedia ne sont pas récursifs."""
    defs = schema.get("$defs", {})

    def walk(node, depth: int = 0):
        if depth > 20:
            raise ValueError("schéma trop profond ou récursif")
        if isinstance(node, list):
            return [walk(x, depth) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = deepcopy(defs[node["$ref"].rsplit("/", 1)[-1]])
            extra = {k: v for k, v in node.items() if k != "$ref"}
            return walk({**target, **extra}, depth + 1)
        return {k: walk(v, depth) for k, v in node.items() if k != "$defs"}

    return walk(schema)


def schema_instructions(schema: type[BaseModel]) -> str:
    """La consigne de format pour un fournisseur sans schéma strict : le schéma lui-même,
    compact, et la règle de ne rendre que l'objet JSON."""
    compact = json.dumps(inline_refs(strict_schema(schema)), ensure_ascii=False, separators=(",", ":"))
    return (
        "\n\n## Format de la réponse\nRéponds uniquement par un objet JSON valide : pas de texte avant ni après, "
        f"pas de bloc de code. Il doit respecter exactement ce schéma JSON (tous les champs sont requis ; `null` quand une valeur manque) :\n{compact}"
    )


def _effort(provider: str, effort: str) -> str:
    # Gemini ne connaît que minimal/low/medium/high.
    if provider == "gemini" and effort not in ("minimal", "low", "medium", "high"):
        return "high"
    return effort


def reasoning_params(provider: str, effort: str, structured: bool) -> tuple[dict, bool]:
    """(paramètres de réflexion, le modèle réfléchit-il). L'effort demandé par la tâche (`low`
    pour le tri et les petites tâches, `medium` ou `high` pour écrire et recouper) devient le
    réglage propre à chaque famille."""
    kind = PROVIDERS[provider].reasoning
    light = effort in ("minimal", "low")
    if kind == "gemini":
        return {"reasoning_effort": _effort("gemini", effort)}, True
    if kind == "openrouter":
        return {"reasoning": {"effort": effort}}, True
    if kind == "deepseek":
        return ({"thinking": {"type": "disabled"}}, False) if light else ({"thinking": {"type": "enabled"}, "reasoning_effort": "high"}, True)
    if kind == "thinking":
        return ({"thinking": {"type": "disabled"}}, False) if light else ({"thinking": {"type": "enabled"}}, True)
    if kind == "kimi":  # K3 réfléchit toujours : `low` la raccourcit seulement
        return {"reasoning_effort": "low" if light else "high" if effort == "medium" else "max"}, True
    if kind == "groq":  # GPT-OSS : low/medium/high ; un modèle qui refuse le paramètre le perd (voir `adapt`)
        return {"reasoning_effort": "low" if light else "medium" if effort == "medium" else "high"}, True
    if kind == "qwen":  # en mode réflexion, Qwen ne garantit plus le JSON : pas de réflexion pour une sortie structurée
        on = not light and not structured
        return {"enable_thinking": on}, on
    return {}, PROVIDERS[provider].thinks


class OpenAICompatLLM(LLM):
    name = "openai_compat"

    def __init__(self, provider: str, api_key: str | None = None):
        self.provider = provider
        self.spec = PROVIDERS[provider]
        self.key = api_key or get_key(provider)
        if not self.key:
            raise NoApiKey(f"Aucune clé {self.spec.label} : ajoute-la dans Réglages › Moteur IA.")
        self.base = catalog.base_url(provider)
        if not self.base:
            raise NoApiKey(f"Indique l'adresse de l'API de {self.spec.label} dans Réglages › Moteur IA.")
        self.http = shared_client(httpx.Timeout(600, connect=20))

    def full(self, name: str) -> str:
        return f"{self.provider}:{name}"

    def learned(self, name: str) -> dict:
        return LEARNED.setdefault((self.provider, name), {})

    # ── transport ────────────────────────────────────────────────────────────

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if self.provider == "openrouter":
            h |= {"HTTP-Referer": "https://github.com/openmedia", "X-Title": "openMedia"}
        return h

    async def _post(self, url: str, body: dict, headers: dict | None = None) -> dict:
        check_tools(body.get("tools"))  # au plus la recherche web : jamais d'outil d'action
        for attempt in range(4):
            try:
                r = await self.http.post(url, json=body, headers=headers or self._headers())
            except httpx.TransportError as e:
                if attempt == 3:
                    raise LLMError(f"{self.spec.label} est injoignable : vérifie ta connexion à Internet.") from e
                await asyncio.sleep(2 * 2**attempt)
                continue
            if r.status_code in RETRY_STATUS and attempt < 3 and not refused_content(_error_message(r)):
                wait = r.headers.get("retry-after")
                await asyncio.sleep(min(float(wait), 60) if wait and wait.replace(".", "").isdigit() else 2 * 2**attempt)
                continue
            if r.status_code >= 400:
                detail = _error_message(r)
                if refused_content(detail):
                    raise ContentRefused(f"{self.spec.label} a refusé de traiter ces articles (filtre de contenu du fournisseur). Choisis un autre fournisseur pour ce sujet dans Réglages › Moteur IA.")
                error = http_error(self.spec.label, r.status_code, detail)
                if r.status_code in (400, 422) and not isinstance(error, NoApiKey):
                    raise Rejected(str(error), r.status_code, detail)
                raise error
            try:
                return r.json()
            except ValueError as e:
                raise LLMError(f"{self.spec.label} a rendu une réponse illisible : réessaie plus tard.") from e
        raise LLMError(f"{self.spec.label} ne répond pas : réessaie plus tard.")

    # ── un appel ─────────────────────────────────────────────────────────────

    def _openai_body(self, name: str, task: str | None, content: str, effort: str, max_tokens: int, schema: type[BaseModel] | None) -> dict:
        body = {
            "model": name,
            "instructions": system_text(task),
            "input": content,
            "max_output_tokens": max_tokens + THINK_MARGIN,
            "reasoning": {"effort": effort},
            "store": False,
        }
        if schema is not None:
            body["text"] = {"format": {"type": "json_schema", "name": schema.__name__, "schema": strict_schema(schema), "strict": True}}
        return body

    def chat_body(self, name: str, task: str | None, content: str, effort: str, max_tokens: int, schema: type[BaseModel] | None, boost: int = 1) -> dict:
        """Le corps d'un appel Chat Completions, selon le profil du fournisseur et ce que le
        moteur a appris du modèle."""
        learned = self.learned(name)
        system = system_text(task)
        body: dict = {"model": name}
        if schema is not None:
            mode = learned.get("structured", self.spec.structured)
            if mode in ("schema", "schema_noref"):
                strict = strict_schema(schema)
                body["response_format"] = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": strict if mode == "schema" else inline_refs(strict), "strict": True}}
            else:
                system += schema_instructions(schema)
                if mode == "object":
                    body["response_format"] = {"type": "json_object"}
        body["messages"] = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        if learned.get("no_reasoning"):
            reasons = self.spec.thinks
        else:
            params, reasons = reasoning_params(self.provider, effort, schema is not None)
            body.update(params)
        limit = (max_tokens + (THINK_MARGIN if reasons else 0)) * boost
        if cap := learned.get("cap"):
            limit = min(limit, cap)
        body[learned.get("max_tokens_param", self.spec.max_tokens_param)] = limit
        return body

    def adapt(self, name: str, body: dict, error: Rejected) -> str | None:
        """Le repli après un refus : ce qui change pour ce modèle, ou None si rien ne s'applique."""
        learned = self.learned(name)
        detail = error.detail
        param = learned.get("max_tokens_param", self.spec.max_tokens_param)
        if re.search(r"max_(?:completion_)?tokens|max_output", detail, re.I):
            m = _CAP.search(detail)
            if m and body.get(param, 0) > int(m.group(1)) and learned.get("cap") != int(m.group(1)):
                learned["cap"] = int(m.group(1))
                return f"plafond de sortie ramené à {learned['cap']} tokens"
            other = "max_tokens" if param == "max_completion_tokens" else "max_completion_tokens"
            if other in detail or re.search(r"unknown|unrecognized|not supported|unsupported|invalid", detail, re.I):
                if learned.get("max_tokens_param") != other:
                    learned["max_tokens_param"] = other
                    return f"plafond de sortie passé par `{other}`"
        rf = (body.get("response_format") or {}).get("type")
        if rf and _STRUCTURED_HINT.search(detail):
            current = learned.get("structured", self.spec.structured)
            if rf == "json_schema" and current == "schema" and _REF_HINT.search(detail):
                learned["structured"] = "schema_noref"
            elif rf == "json_schema":
                learned["structured"] = "object"
            else:
                learned["structured"] = "prompt"
            return f"sortie structurée en mode « {learned['structured']} »"
        if not learned.get("no_reasoning") and _REASONING_HINT.search(detail):
            learned["no_reasoning"] = True
            return "réglage de la réflexion retiré"
        return None

    async def _call(self, meter: RunMeter, *, name: str, task: str | None, content: str, effort: str, max_tokens: int, schema: type[BaseModel] | None, label: str) -> str:
        if self.provider == "openai":
            data = await self._post(f"{self.base}/responses", self._openai_body(name, task, content, effort, max_tokens, schema))
            return self.read_responses(meter, name, data, label)
        boost, empty_retried = 1, False
        for _ in range(6):
            body = self.chat_body(name, task, content, effort, max_tokens, schema, boost)
            try:
                data = await self._post(f"{self.base}/chat/completions", body)
            except Rejected as e:
                change = self.adapt(name, body, e)
                if change is None:
                    raise
                meter.note(f"{label} · {self.full(name)} refuse un paramètre : {change}, nouvel essai")
                continue
            try:
                text = self.read_chat(meter, name, data, label)
            except _Truncated:
                if boost > 1:
                    raise LLMError(f"{name} a atteint la limite de longueur de réponse, même avec une marge doublée.") from None
                boost = 2
                meter.note(f"{label} · {self.full(name)} coupé pendant sa réflexion : nouvel essai avec un plafond doublé")
                continue
            if text:
                return text
            if empty_retried:
                raise LLMError(f"{self.spec.label} a rendu une réponse vide deux fois de suite : réessaie plus tard, ou choisis un autre modèle.")
            empty_retried = True
            meter.note(f"{label} · {self.full(name)} a rendu une réponse vide : nouvelle demande")
        raise LLMError(f"{self.spec.label} refuse les réglages de la demande : choisis un autre modèle dans Réglages › Moteur IA.")

    def read_responses(self, meter: RunMeter, name: str, data: dict, label: str, via: str = "api", discount: float = 1.0) -> str:
        usage = data.get("usage") or {}
        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0
        searches = sum(1 for item in data.get("output", []) if item.get("type") == "web_search_call")
        meter.record(task=label, model=self.full(name), fresh=(usage.get("input_tokens") or 0) - cached, cached=cached, output=usage.get("output_tokens") or 0, searches=searches, search_price=OPENAI_SEARCH_PRICE, via=via, discount=discount)
        parts = [c for item in data.get("output", []) if item.get("type") == "message" for c in item.get("content", [])]
        if any(c.get("type") == "refusal" for c in parts):
            raise LLMError(f"{name} a décliné la demande.")
        if data.get("status") == "incomplete":
            reason = (data.get("incomplete_details") or {}).get("reason")
            if reason == "content_filter":
                raise ContentRefused(f"{name} a refusé de traiter ces articles (filtre de contenu d'OpenAI).")
            raise LLMError(f"{name} a atteint la limite de longueur de réponse." if reason == "max_output_tokens" else f"{name} : réponse incomplète ({reason}).")
        meter.note(f"{label} · {self.full(name)} · {usage.get('output_tokens', 0)} tokens en sortie")
        return "".join(c.get("text", "") for c in parts if c.get("type") == "output_text").strip()

    def read_chat(self, meter: RunMeter, name: str, data: dict, label: str, via: str = "api", discount: float = 1.0) -> str:
        """Le texte de la réponse, sans la réflexion du modèle ; "" si la réponse est vide."""
        usage = data.get("usage") or {}
        # Le cache se lit à des endroits différents selon le fournisseur (DeepSeek, Kimi, OpenAI…).
        cached = usage.get("prompt_cache_hit_tokens") or (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or usage.get("cached_tokens") or 0
        searches = (usage.get("server_tool_use") or {}).get("web_search_requests") or 0
        reported = usage.get("cost") if self.provider == "openrouter" else None
        meter.record(task=label, model=self.full(name), fresh=max(0, (usage.get("prompt_tokens") or 0) - cached), cached=cached, output=usage.get("completion_tokens") or 0, searches=searches, cost=float(reported) if reported is not None else None, via=via, discount=discount)
        choices = data.get("choices") or []
        if not choices:
            return ""
        message, finish = choices[0].get("message") or {}, choices[0].get("finish_reason")
        if message.get("refusal"):
            raise LLMError(f"{name} a décliné la demande.")
        if finish in ("content_filter", "sensitive"):
            raise ContentRefused(f"{self.spec.label} a refusé de traiter ces articles (filtre de contenu du fournisseur). Choisis un autre fournisseur pour ce sujet dans Réglages › Moteur IA.")
        content = message.get("content") or ""
        if isinstance(content, list):  # modèles de raisonnement Mistral : une liste de morceaux
            content = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        content = strip_thinking(content)
        if finish == "length":
            raise _Truncated(f"{name} a atteint la limite de longueur de réponse.")
        meter.note(f"{label} · {self.full(name)} · {usage.get('completion_tokens', 0)} tokens en sortie")
        return content

    # ── interface des agents ────────────────────────────────────────────────

    async def parse(self, meter: RunMeter, *, model: str, task: str, content: str, schema: type[T], effort: str = "medium", max_tokens: int = 16000) -> T:
        raw = await self._call(meter, name=model, task=task, content=content, effort=effort, max_tokens=max_tokens, schema=schema, label=task)
        try:
            return validate_json(schema, raw)
        except LLMError as first:
            meter.note(f"{task} · réponse invalide, nouvelle demande ({first})")
            retry = f"{content}\n\nTa réponse précédente n'était pas conforme ({first}). Rends uniquement l'objet JSON demandé, conforme au schéma."
            raw = await self._call(meter, name=model, task=task, content=retry, effort=effort, max_tokens=max_tokens, schema=schema, label=task)
            return validate_json(schema, raw)

    async def text(self, meter: RunMeter, *, model: str, task: str, content: str, effort: str = "medium", max_tokens: int = 8000) -> str:
        return await self._call(meter, name=model, task=task, content=content, effort=effort, max_tokens=max_tokens, schema=None, label=task)

    async def search(self, meter: RunMeter, *, model: str, prompt: str, max_uses: int = 3) -> list[dict]:
        if self.provider == "openai":
            body = {
                "model": model,
                "input": prompt + f"\n\nFais au plus {max_uses} recherches web.",
                "tools": [{"type": "web_search"}],
                "include": ["web_search_call.action.sources"],
                "reasoning": {"effort": "low"},
                "max_output_tokens": 4000 + THINK_MARGIN,
                "store": False,
            }
            data = await self._post(f"{self.base}/responses", body)
            self.read_responses(meter, model, data, "search")
            found = []
            for item in data.get("output", []):
                if item.get("type") == "web_search_call":
                    found += [{"url": s.get("url"), "title": s.get("title") or ""} for s in ((item.get("action") or {}).get("sources") or [])]
                elif item.get("type") == "message":
                    found += [{"url": a.get("url"), "title": a.get("title") or ""} for c in item.get("content", []) for a in c.get("annotations") or [] if a.get("type") == "url_citation"]
            return _unique(found)
        if self.provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]}
            data = await self._post(url, body, headers={"x-goog-api-key": self.key, "Content-Type": "application/json"})
            usage = data.get("usageMetadata") or {}
            candidate = (data.get("candidates") or [{}])[0]
            grounding = candidate.get("groundingMetadata") or {}
            cached = usage.get("cachedContentTokenCount") or 0
            meter.record(task="search", model=self.full(model), fresh=(usage.get("promptTokenCount") or 0) - cached, cached=cached, output=(usage.get("candidatesTokenCount") or 0) + (usage.get("thoughtsTokenCount") or 0), searches=len(grounding.get("webSearchQueries") or []), search_price=GEMINI_SEARCH_PRICE)
            chunks = [c.get("web") or {} for c in grounding.get("groundingChunks") or []]
            return _unique(await self._resolve_redirects([{"url": c.get("uri"), "title": c.get("title") or ""} for c in chunks]))
        if self.provider == "openrouter":
            body = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "plugins": [{"id": "web", "max_results": 5 * max_uses}],
                "reasoning": {"effort": "low"},
                "max_tokens": 4000 + THINK_MARGIN,
            }
            data = await self._post(f"{self.base}/chat/completions", body)
            self.read_chat(meter, model, data, "search")
            message = ((data.get("choices") or [{}])[0]).get("message") or {}
            return _unique([{"url": (a.get("url_citation") or {}).get("url"), "title": (a.get("url_citation") or {}).get("title") or ""} for a in message.get("annotations") or [] if a.get("type") == "url_citation"])
        meter.note(f"recherche web indisponible chez {self.spec.label}")
        return []

    async def _resolve_redirects(self, items: list[dict]) -> list[dict]:
        """Gemini cite ses sources par des liens de redirection : on lit leur destination."""

        async def one(item: dict) -> dict:
            if "grounding-api-redirect" not in (item.get("url") or ""):
                return item
            try:
                r = await self.http.get(item["url"], follow_redirects=False, timeout=15)
                if location := r.headers.get("location"):
                    return {**item, "url": location}
            except httpx.HTTPError:
                pass
            return item

        return await asyncio.gather(*[one(i) for i in items])


def strip_thinking(text: str) -> str:
    """Retire la réflexion que certains modèles laissent dans leur réponse (`<think>…</think>`)."""
    text = _THINK.sub("", text or "")
    if "</think>" in text:  # balise ouvrante absente : la réflexion précède la fermante
        text = text.rsplit("</think>", 1)[1]
    elif text.lstrip().startswith("<think>"):  # réflexion coupée, sans réponse
        text = ""
    return text.strip()


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)


def validate_json(schema: type[T], raw: str) -> T:
    text = strip_thinking(raw)
    candidates = [text]
    if m := _FENCE.search(text):  # certains modèles entourent le JSON d'un bloc de code
        candidates.append(m.group(1).strip())
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:  # ou d'une phrase
        candidates.append(text[start : end + 1])
    conformity: ValidationError | None = None  # du JSON lisible, mais pas au schéma : l'erreur la plus utile
    for candidate in candidates:
        try:
            return schema.model_validate_json(candidate)
        except ValidationError as e:
            if conformity is None and e.errors()[0].get("type") != "json_invalid":
                conformity = e
    if conformity is not None:
        raise LLMError(f"JSON non conforme à {schema.__name__} : {conformity.errors()[0].get('msg', conformity)}")
    raise LLMError(f"pas de JSON valide pour {schema.__name__}")


def _unique(found: list[dict]) -> list[dict]:
    seen, out = set(), []
    for f in found:
        url = f.get("url") or ""
        if url.startswith(("http://", "https://")) and url not in seen:
            seen.add(url)
            out.append(f)
    return out


def _error_message(r: httpx.Response) -> str:
    try:
        data = r.json()
    except ValueError:
        return r.text[:300]
    if isinstance(data, list) and data:
        data = data[0]
    err = data.get("error") if isinstance(data, dict) else None
    if isinstance(err, dict):
        code = err.get("code") or err.get("type") or ""
        return f"{err.get('message') or err} {code}".strip()[:300]
    return str(err or data.get("message") or data)[:300] if isinstance(data, dict) else str(data)[:300]
