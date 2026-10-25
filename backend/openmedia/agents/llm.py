"""Le point de contact avec les modèles : l'API Claude (cache de prompt, repli en cas de
refus), Claude Code, et les autres fournisseurs par `RouterLLM`. Chaque appel passe un
`RunMeter` qui note les tokens et le coût, appel par appel ; le total est enregistré dans la
table `Run` et détaillé dans Réglages → Coûts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from ..config import get_api_key, get_key
from ..security import check_tools
from .providers import catalog

PROMPTS = Path(__file__).parent.parent / "prompts"

WEB_SEARCH_PRICE = 10.00 / 1000

# Haiku 5.5 n'a pas de repli côté serveur : le paramètre `fallbacks` ne lui est pas envoyé.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
NO_FALLBACK = {"claude-haiku-5-5"}

T = TypeVar("T", bound=BaseModel)


class NoApiKey(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


class ContentRefused(LLMError):
    """Le filtre de contenu d'un fournisseur refuse la demande : un autre fournisseur peut
    la traiter."""


def token_cost(model: str, *, fresh: int, output: int, cached: int = 0, written: int = 0) -> float | None:
    """Coût au tarif public, ou None si le prix du modèle est inconnu. Écriture du cache :
    1,25 × l'entrée (Anthropic) ; les autres fournisseurs ne la facturent pas à part."""
    p = catalog.price(model)
    if p is None:
        return None
    price_in, price_out, price_cache = p
    return (fresh * price_in + written * price_in * 1.25 + cached * price_cache + output * price_out) / 1e6


@dataclass
class RunMeter:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    web_searches: int = 0
    cost_usd: float = 0.0
    # Part du coût couverte par un abonnement (Claude Code) : un équivalent, pas une facture.
    subscription_usd: float = 0.0
    log: list[str] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    def record(self, *, task: str, model: str, fresh: int = 0, output: int = 0, cached: int = 0, written: int = 0, searches: int = 0, search_price: float = WEB_SEARCH_PRICE, cost: float | None = None, via: str = "api", discount: float = 1.0) -> None:
        """Un appel. `cost` : coût rapporté par le fournisseur ; sinon calculé au tarif public
        (None si le prix est inconnu). `via` : « api » (facturé), « batch » (facturé, −50 %)
        ou « claude_code » (couvert par l'abonnement)."""
        if cost is None:
            cost = token_cost(model, fresh=fresh, output=output, cached=cached, written=written)
            if cost is not None:
                cost = cost * discount + searches * search_price
        self.input_tokens += fresh + cached + written
        self.output_tokens += output
        self.cache_read_tokens += cached
        self.web_searches += searches
        self.cost_usd += cost or 0.0
        if via == "claude_code":
            self.subscription_usd += cost or 0.0
        self.calls.append({"task": task, "model": model, "via": via, "in": fresh + cached + written, "cached": cached, "out": output, "searches": searches, "cost": round(cost, 6) if cost is not None else None})

    def add(self, model: str, usage, task: str = "appel", discount: float = 1.0, via: str = "api") -> None:
        """Usage d'une réponse de l'API Claude."""
        self.record(
            task=task,
            model=model,
            fresh=usage.input_tokens or 0,
            output=usage.output_tokens or 0,
            cached=getattr(usage, "cache_read_input_tokens", 0) or 0,
            written=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            searches=getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0,
            discount=discount,
            via=via,
        )

    def add_reported(self, usage: dict, cost_usd: float, model: str = "", task: str = "appel") -> None:
        """Usage tel que Claude Code le rapporte (dictionnaire), coût déjà calculé par lui."""
        self.record(
            task=task,
            model=model,
            fresh=usage.get("input_tokens") or 0,
            output=usage.get("output_tokens") or 0,
            cached=usage.get("cache_read_input_tokens") or 0,
            written=usage.get("cache_creation_input_tokens") or 0,
            searches=(usage.get("server_tool_use") or {}).get("web_search_requests") or 0,
            cost=cost_usd or 0.0,
            via="claude_code",
        )

    def note(self, line: str) -> None:
        self.log.append(line)


@lru_cache(maxsize=1)
def sdk():
    """Le SDK importe près de 3 000 modules (plus de 10 s sous Windows) : on le charge à la
    première utilisation, ou en tâche de fond au démarrage du serveur (`warm_up`)."""
    import anthropic

    return anthropic


def warm_up() -> None:
    import threading

    threading.Thread(target=sdk, daemon=True).start()


@lru_cache(maxsize=None)
def prompt(name: str) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8").strip()


def system_text(task: str | None) -> str:
    """La charte puis la consigne de la tâche : un préfixe stable, que les fournisseurs
    mettent en cache d'un appel à l'autre."""
    return prompt("charte") + ("\n\n" + prompt(task) if task else "")


class LLM:
    """Ce que les agents attendent d'un moteur : une réponse structurée, du texte, une
    recherche web. Moteurs : l'API Claude (clé), Claude Code installé sur le PC, les autres
    fournisseurs (`OpenAICompatLLM`), et `RouterLLM` qui choisit selon le modèle demandé."""

    name = "base"

    async def parse(self, meter: RunMeter, *, model: str, task: str, content: str, schema: type[T], effort: str = "medium", max_tokens: int = 16000) -> T:
        raise NotImplementedError

    async def text(self, meter: RunMeter, *, model: str, task: str, content: str, effort: str = "medium", max_tokens: int = 8000) -> str:
        raise NotImplementedError

    async def search(self, meter: RunMeter, *, model: str, prompt: str, max_uses: int = 3) -> list[dict]:
        """Recherche web : rend [{url, title}]. Les pages passent ensuite par l'extraction."""
        raise NotImplementedError


class ApiLLM(LLM):
    name = "api"

    def __init__(self, api_key: str | None = None):
        key = api_key or get_api_key()
        if not key:
            raise NoApiKey("Aucune clé API Anthropic : ajoute-la dans Réglages.")
        self.client = sdk().AsyncAnthropic(api_key=key, max_retries=3, timeout=600)

    @staticmethod
    def _system(task: str | None) -> list[dict]:
        # La charte, identique pour tous les appels, puis la consigne de la tâche : deux
        # préfixes stables, mis en cache séparément.
        blocks = [{"type": "text", "text": prompt("charte"), "cache_control": {"type": "ephemeral"}}]
        if task:
            blocks.append({"type": "text", "text": prompt(task), "cache_control": {"type": "ephemeral"}})
        return blocks

    @staticmethod
    def _fallback(model: str) -> dict:
        if model in NO_FALLBACK:
            return {}
        return {"betas": [FALLBACK_BETA], "fallbacks": "default"}

    @staticmethod
    def _check(message, model: str) -> None:
        if message.stop_reason == "refusal":
            category = getattr(getattr(message, "stop_details", None), "category", None)
            raise LLMError(f"{model} a décliné la demande (catégorie : {category}).")
        if message.stop_reason == "max_tokens":
            raise LLMError(f"{model} a atteint la limite de longueur de réponse.")

    async def parse(self, meter: RunMeter, *, model: str, task: str, content: str, schema: type[T], effort: str = "medium", max_tokens: int = 16000) -> T:
        from pydantic import ValidationError

        for attempt in range(2):
            try:
                message = await self.client.beta.messages.parse(
                    model=model,
                    max_tokens=max_tokens,
                    system=self._system(task),
                    messages=[{"role": "user", "content": content}],
                    output_format=schema,
                    output_config={"effort": effort},
                    **self._fallback(model),
                )
            except ValidationError as e:  # le SDK valide la réponse : un JSON non conforme lève ici
                if attempt:
                    raise LLMError(f"{model} n'a pas rendu de réponse conforme ({schema.__name__}), même à la seconde demande.") from e
                meter.note(f"{task} · réponse invalide, nouvelle demande")
                content = f"{content}\n\nTa réponse précédente n'était pas conforme au schéma. Rends uniquement l'objet JSON demandé."
                continue
            except Exception as e:  # noqa: BLE001 — erreurs du SDK, traduites
                raise _anthropic_error(e) from e
            meter.add(model, message.usage, task=task)
            self._check(message, model)
            if message.parsed_output is not None:
                meter.note(f"{task} · {model} · {message.usage.output_tokens} tokens en sortie")
                return message.parsed_output
            if attempt:
                raise LLMError(f"{model} n'a pas rendu de JSON valide pour {schema.__name__}.")
        raise LLMError(f"{model} n'a pas rendu de JSON valide pour {schema.__name__}.")

    async def text(self, meter: RunMeter, *, model: str, task: str, content: str, effort: str = "medium", max_tokens: int = 8000) -> str:
        message = await self.raw(meter, model=model, prompt=content, task=task, effort=effort, max_tokens=max_tokens)
        return "".join(b.text for b in message.content if b.type == "text").strip()

    async def search(self, meter: RunMeter, *, model: str, prompt: str, max_uses: int = 3) -> list[dict]:
        # On ne lit pas la réponse rédigée : seuls les résultats bruts de l'outil comptent.
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_uses}]
        message = await self.raw(meter, model=model, prompt=prompt, tools=tools, effort="low", max_tokens=2000, label="search")
        out = []
        for block in message.content:
            if block.type != "web_search_tool_result" or not isinstance(block.content, list):
                continue  # un objet (et non une liste) signale une erreur de l'outil
            out += [{"url": r.url, "title": r.title or ""} for r in block.content if getattr(r, "type", "") == "web_search_result"]
        return out

    async def raw(self, meter: RunMeter, *, model: str, prompt: str, task: str | None = None, tools: list | None = None, effort: str = "medium", max_tokens: int = 8000, label: str | None = None):
        """Appel libre (outils serveur compris). Reprend un tour mis en pause (`pause_turn`)."""
        check_tools(tools)  # un agent d'openMedia ne reçoit jamais d'outil d'action
        messages: list = [{"role": "user", "content": prompt}]
        extra = {"tools": tools} if tools else {}
        for _ in range(4):
            try:
                message = await self.client.beta.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=self._system(task),
                    messages=messages,
                    output_config={"effort": effort},
                    **extra,
                    **self._fallback(model),
                )
            except Exception as e:  # noqa: BLE001 — erreurs du SDK, traduites
                raise _anthropic_error(e) from e
            meter.add(model, message.usage, task=label or task or "appel")
            if message.stop_reason != "pause_turn":
                self._check(message, model)
                return message
            messages = [messages[0], {"role": "assistant", "content": message.content}]
        return message


def _anthropic_error(e: Exception) -> Exception:
    """Une erreur du SDK Anthropic, dite en français (voir `agents/errors.py`)."""
    from .errors import http_error

    status = getattr(e, "status_code", None)
    if isinstance(status, int):
        body = getattr(e, "body", None)
        detail = ((body or {}).get("error") or {}).get("message", "") if isinstance(body, dict) else str(e)
        return http_error("Anthropic", status, detail)
    if isinstance(e, sdk().APIConnectionError):
        return LLMError("Anthropic est injoignable : vérifie ta connexion à Internet.")
    if isinstance(e, (LLMError, NoApiKey)):
        return e
    return LLMError(f"Anthropic : {e}")


class RouterLLM(LLM):
    """Oriente chaque appel vers le moteur du modèle demandé : les `claude-*` vers l'API Claude
    ou Claude Code (selon le réglage), les `fournisseur:modèle` vers ce fournisseur, les
    `ollama:…` et `lmstudio:…` vers l'IA de ce PC (on peut ainsi mélanger, rôle par rôle). Un
    modèle dont le fournisseur n'est pas disponible est remplacé par le modèle de même gamme
    d'un fournisseur disponible, et le passage le note."""

    name = "router"

    def __init__(self, status: dict | None = None):
        self.status = status or engine_status()
        self._engines: dict[str, LLM] = {}
        self._substituted: set[str] = set()

    def available(self, provider: str) -> bool:
        if provider == "anthropic":
            return self.status["engine"] in ("api", "claude_code")
        if provider in catalog.LOCAL:
            return local_found(provider)
        return self.status["providers"][provider]["has_key"]

    def engine(self, provider: str) -> LLM:
        if provider not in self._engines:
            if provider == "local" or provider in catalog.LOCAL:
                from ..config import load_settings
                from .providers.local import LocalLLM

                s = load_settings()
                if provider == "local":  # tout sur ce PC : un seul modèle pour tout
                    self._engines[provider] = LocalLLM(s.local_provider, s.local_model, s.local_urls)
                else:  # un rôle confié à l'IA de ce PC : le modèle vient de l'appel
                    self._engines[provider] = LocalLLM(provider, "", s.local_urls)
            elif provider == "anthropic":
                if self.status["engine"] == "api":
                    self._engines[provider] = ApiLLM()
                else:
                    from .claude_code import ClaudeCodeLLM

                    self._engines[provider] = ClaudeCodeLLM()
            else:
                from .providers.openai_compat import OpenAICompatLLM

                self._engines[provider] = OpenAICompatLLM(provider)
        return self._engines[provider]

    def resolve(self, model: str, meter: RunMeter | None = None) -> tuple[str, str]:
        """(fournisseur, identifiant chez ce fournisseur) du moteur qui servira `model`.
        En mode local, c'est toujours le modèle de ce PC : aucun appel ne part en ligne, même
        pour un modèle demandé par son nom (le tri rapide, les sujets de lectures…).
        L'accord sur les conditions est revérifié à chaque appel : le retirer arrête aussi un
        passage en cours."""
        from ..config import require_consent

        require_consent()
        if self.status["engine"] == "local":
            if meter is not None and model not in self._substituted:
                self._substituted.add(model)
                meter.note(f"{model} servi par l'IA de ce PC ({self.status['local_model']})")
            return "local", self.status["local_model"]
        provider, name = catalog.split(model)
        if self.available(provider):
            return provider, name
        if alt := self.same_tier(model, exclude=provider):
            if meter is not None:
                meter.note(f"{model} indisponible (pas de moteur {catalog.label(provider)}) : remplacé par {alt}, de même gamme")
            return catalog.split(alt)
        if provider in catalog.LOCAL:
            raise NoApiKey(f"{catalog.label(provider)} ne répond pas sur ce PC : lance-le, ou choisis un autre modèle pour ce rôle dans Réglages › Moteur IA.")
        raise NoApiKey(f"Aucun moteur pour {model} : ajoute une clé {catalog.label(provider)} dans Réglages, ou choisis un autre modèle.")

    def same_tier(self, model: str, exclude: str) -> str | None:
        """Le modèle de même gamme chez un autre fournisseur disponible ; à défaut, le modèle de
        ce PC qu'un rôle utilise déjà."""
        tier = catalog.tier_of(model) or "equilibre"
        for other in catalog.PROVIDERS:
            if other != exclude and self.available(other) and (alt := catalog.tier_model(other, tier)):
                return alt
        from ..config import load_settings

        for role_model in load_settings().models.model_dump().values():
            if (p := catalog.split(role_model)[0]) in catalog.LOCAL and p != exclude and self.available(p):
                return role_model
        return None

    async def _with_fallback(self, meter: RunMeter, model: str, call):
        """Un appel, et si le filtre de contenu du fournisseur le refuse (fréquent sur les sujets
        politiques chez les fournisseurs chinois), le même appel chez un autre fournisseur de
        même gamme, s'il y en a un."""
        provider, name = self.resolve(model, meter)
        try:
            return await call(self.engine(provider), name)
        except ContentRefused:
            if provider == "local" or not (alt := self.same_tier(f"{provider}:{name}" if provider != "anthropic" else name, exclude=provider)):
                raise
            meter.note(f"{catalog.label(provider)} a refusé ces articles (filtre de contenu) : appel repris par {alt}")
            other, alt_name = catalog.split(alt)
            return await call(self.engine(other), alt_name)

    async def parse(self, meter: RunMeter, *, model: str, task: str, content: str, schema: type[T], effort: str = "medium", max_tokens: int = 16000) -> T:
        return await self._with_fallback(meter, model, lambda engine, name: engine.parse(meter, model=name, task=task, content=content, schema=schema, effort=effort, max_tokens=max_tokens))

    async def text(self, meter: RunMeter, *, model: str, task: str, content: str, effort: str = "medium", max_tokens: int = 8000) -> str:
        return await self._with_fallback(meter, model, lambda engine, name: engine.text(meter, model=name, task=task, content=content, effort=effort, max_tokens=max_tokens))

    async def search(self, meter: RunMeter, *, model: str, prompt: str, max_uses: int = 3) -> list[dict]:
        provider, name = self.resolve(model, meter)
        return await self.engine(provider).search(meter, model=name, prompt=prompt, max_uses=max_uses)


def engine_status() -> dict:
    """Le moteur Claude effectivement utilisé, selon le réglage et ce qui est disponible, et
    les clés des autres fournisseurs."""
    from ..config import load_settings
    from .claude_code import claude_code_info

    settings = load_settings()
    choice = settings.engine
    has_key = bool(get_api_key())
    cc = claude_code_info()
    local = None
    if choice == "local":
        from .providers.local import detect

        found = detect(settings.local_urls)[settings.local_provider]
        ready = found["found"] and any(m["id"] == settings.local_model for m in found["models"])
        engine = "local" if ready else None
        local = {"provider": settings.local_provider, "model": settings.local_model, "found": found["found"], "ready": ready, "url": found["url"]}
    elif choice == "api":
        engine = "api" if has_key else None
    elif choice == "claude_code":
        engine = "claude_code" if cc["found"] else None
    else:  # automatique : la clé si elle existe, sinon Claude Code s'il est installé
        engine = "api" if has_key else "claude_code" if cc["found"] else None
    providers = {
        p.id: {"label": p.label, "has_key": has_key if p.id == "anthropic" else bool(get_key(p.id)), "search": p.search, "batch": p.batch, "hint": p.hint, "region": p.region, "policy_url": p.policy_url, "url_setting": p.url_setting, "url": settings.provider_urls.get(p.id, "") if p.url_setting else ""}
        for p in catalog.PROVIDERS.values()
    }
    return {"engine": engine, "choice": choice, "has_api_key": has_key, "claude_code": cc, "providers": providers, "local": local, "local_model": settings.local_model}


def local_found(provider: str) -> bool:
    """Ollama ou LM Studio répond-il sur ce PC ? (détection gardée 30 s, voir `local.detect`)"""
    from ..config import load_settings
    from .providers.local import detect

    return detect(load_settings().local_urls)[provider]["found"]


def any_engine(status: dict) -> bool:
    if status["choice"] == "local":  # l'IA de ce PC, ou rien : jamais de repli en ligne
        return status["engine"] == "local"
    if status["engine"] is not None or any(p["has_key"] for k, p in status["providers"].items() if k != "anthropic"):
        return True
    from ..config import load_settings  # un rôle confié à l'IA de ce PC suffit

    return any((p := catalog.split(m)[0]) in catalog.LOCAL and local_found(p) for m in load_settings().models.model_dump().values())


def get_llm() -> LLM:
    status = engine_status()
    if not any_engine(status):
        if status["choice"] == "local":
            local = status["local"] or {}
            if not local.get("found"):
                raise NoApiKey("L'IA de ce PC ne répond pas : lance Ollama ou LM Studio, ou choisis un autre moteur dans Réglages.")
            raise NoApiKey("Le modèle choisi pour l'IA de ce PC est introuvable : choisis-en un dans Réglages › Moteur IA.")
        if status["choice"] == "claude_code":
            raise NoApiKey("Claude Code est introuvable : installe-le (npm install -g @anthropic-ai/claude-code) ou indique son chemin dans Réglages.")
        raise NoApiKey("Aucun moteur IA : ajoute une clé API (Anthropic, OpenAI, DeepSeek, Gemini, Mistral, Kimi, GLM, Qwen, Grok ou OpenRouter), choisis l'IA de ce PC ou installe Claude Code, dans Réglages › Moteur IA.")
    from ..config import require_consent

    require_consent()  # aucun envoi à une IA avant l'accord sur les conditions de fonctionnement
    return RouterLLM(status)
