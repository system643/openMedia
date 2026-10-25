"""Les fournisseurs d'IA et leurs modèles, rangés par gamme, avec leurs prix.

Un modèle s'écrit `fournisseur:identifiant` (`openai:gpt-6.1-sol`, `deepseek:deepseek-flash`) ;
un `claude-*` sans préfixe est un modèle Anthropic (clé API ou Claude Code), et
`ollama:qwen3:14b` ou `lmstudio:…` un modèle servi sur ce PC (gratuit, sans clé).

Chaque fournisseur a son profil : comment il rend du JSON structuré, comment on règle sa
réflexion, où partent les données. Le moteur (`openai_compat.py`) s'y adapte, puis se replie
de lui-même si un modèle refuse un paramètre.

Prix en $ par million de tokens : (entrée, sortie, lecture du cache), relevés sur les pages
officielles le 19/10/2026 (Anthropic, OpenAI, Google, Mistral) et le 23/10/2026 (DeepSeek,
Moonshot, Z.ai ; xAI et Groq le 25/10/2026 ; Qwen d'après la liste publique d'OpenRouter). Les modèles d'OpenRouter
prennent leur prix en direct.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

TIERS = ("maximum", "premium", "equilibre", "rapide")
TIER_LABEL = {"maximum": "Maximum", "premium": "Premium", "equilibre": "Équilibré", "rapide": "Rapide"}
# Une gamme absente chez un fournisseur se remplace par la plus proche, en montant d'abord :
# on ne descend jamais en qualité sans le dire.
TIER_FALLBACK = {
    "maximum": ("maximum", "premium", "equilibre"),
    "premium": ("premium", "maximum", "equilibre"),
    "equilibre": ("equilibre", "premium", "maximum"),
    "rapide": ("rapide", "equilibre", "premium", "maximum"),
}


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    base_url: str
    env: tuple[str, ...]
    search: bool  # recherche web disponible
    batch: bool  # API Batch (−50 %) prise en charge par openMedia
    hint: str  # forme de la clé, pour l'interface
    # Sortie structurée : `schema` (schéma JSON strict), `schema_noref` (le même, sans $ref),
    # `object` (mode « objet JSON », le schéma est écrit dans la consigne).
    structured: str = "schema"
    # Réglage de la réflexion : `openai` (API Responses), `gemini`, `openrouter`, `deepseek`
    # (thinking + reasoning_effort), `thinking` (Z.ai), `kimi`, `qwen`, `groq`, ou `none`.
    reasoning: str = "none"
    thinks: bool = False  # peut réfléchir avant de répondre : il lui faut une marge de tokens
    max_tokens_param: str = "max_tokens"
    region: str = ""  # où partent les articles, dit au lecteur avant son accord
    policy_url: str = ""
    url_setting: bool = False  # l'adresse se règle dans Réglages (espace Qwen, autre fournisseur)
    key_check: str = "/models"  # chemin qui vérifie une clé sans rien consommer


PROVIDERS: dict[str, Provider] = {
    p.id: p
    for p in (
        Provider("anthropic", "Anthropic", "https://api.anthropic.com", ("ANTHROPIC_API_KEY",), True, True, "sk-ant-…", region="aux États-Unis", policy_url="https://www.anthropic.com/legal/commercial-terms"),
        Provider("openai", "OpenAI", "https://api.openai.com/v1", ("OPENAI_API_KEY",), True, True, "sk-proj-…", reasoning="openai", thinks=True, region="aux États-Unis", policy_url="https://openai.com/policies/business-terms/"),
        Provider("gemini", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", ("GEMINI_API_KEY", "GOOGLE_API_KEY"), True, False, "AIza…", reasoning="gemini", thinks=True, region="aux États-Unis", policy_url="https://ai.google.dev/gemini-api/terms"),
        Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", ("OPENROUTER_API_KEY",), True, False, "sk-or-…", reasoning="openrouter", thinks=True, region="aux États-Unis, puis chez le fournisseur du modèle choisi", policy_url="https://openrouter.ai/privacy"),
        Provider("mistral", "Mistral", "https://api.mistral.ai/v1", ("MISTRAL_API_KEY",), False, False, "32 caractères", region="en France", policy_url="https://mistral.ai/terms"),
        Provider("deepseek", "DeepSeek", "https://api.deepseek.com", ("DEEPSEEK_API_KEY",), False, False, "sk-…", structured="object", reasoning="deepseek", thinks=True, region="en Chine", policy_url="https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html"),
        Provider("moonshot", "Kimi (Moonshot AI)", "https://api.moonshot.ai/v1", ("MOONSHOT_API_KEY", "KIMI_API_KEY"), False, False, "sk-…", structured="schema_noref", reasoning="kimi", thinks=True, max_tokens_param="max_completion_tokens", region="en Chine", policy_url="https://platform.kimi.ai/docs/agreement/userprivacy"),
        Provider("zai", "GLM (Z.ai)", "https://api.z.ai/api/paas/v4", ("ZAI_API_KEY", "ZHIPU_API_KEY"), False, False, "xxxx.yyyy", structured="object", reasoning="thinking", thinks=True, region="en Chine", policy_url="https://docs.z.ai/legal-agreement/privacy-policy"),
        Provider("qwen", "Qwen (Alibaba Cloud)", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", ("DASHSCOPE_API_KEY", "QWEN_API_KEY"), False, False, "sk-…", structured="object", reasoning="qwen", thinks=True, region="à Singapour", policy_url="https://www.alibabacloud.com/help/en/legal/latest/alibaba-cloud-international-website-privacy-policy", url_setting=True),
        Provider("xai", "Grok (xAI)", "https://api.x.ai/v1", ("XAI_API_KEY",), False, False, "xai-…", thinks=True, region="aux États-Unis", policy_url="https://x.ai/legal/privacy-policy"),
        Provider("groq", "Groq", "https://api.groq.com/openai/v1", ("GROQ_API_KEY",), False, False, "gsk_…", reasoning="groq", thinks=True, max_tokens_param="max_completion_tokens", region="aux États-Unis", policy_url="https://groq.com/privacy-policy/"),
        Provider("compatible", "Autre fournisseur (compatible OpenAI)", "", ("OPENMEDIA_COMPATIBLE_KEY",), False, False, "selon le fournisseur", thinks=True, region="", url_setting=True),
    )
}


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    tier: str
    price: tuple[float, float, float] | None
    featured: bool = True  # le modèle proposé pour sa gamme chez ce fournisseur
    note: str = ""
    peak: tuple[float, float, float] | None = None  # prix aux heures de pointe (DeepSeek)

    @property
    def provider(self) -> str:
        return split(self.id)[0]


DEEPSEEK_PEAK = "Prix doublé en semaine aux heures de pointe de DeepSeek (1 h-4 h et 6 h-10 h UTC) ; le passage du matin par défaut tombe hors pointe."

MODELS: list[ModelInfo] = [
    # Anthropic
    ModelInfo("claude-fable-5-1", "Fable 5.1", "maximum", (10.00, 50.00, 0.25)),
    ModelInfo("claude-opus-5-5", "Opus 5.5", "premium", (4.00, 20.00, 0.20)),
    ModelInfo("claude-sonnet-5-5", "Sonnet 5.5", "equilibre", (2.00, 10.00, 0.20)),
    ModelInfo("claude-haiku-5-5", "Haiku 5.5", "rapide", (0.10, 0.50, 0.01)),
    # OpenAI
    ModelInfo("openai:gpt-6-astra", "GPT-6 Astra", "maximum", (10.00, 50.00, 1.00)),
    ModelInfo("openai:gpt-5.6-sol", "GPT-5.6 Sol", "premium", (4.00, 20.00, 0.40), featured=False),
    ModelInfo("openai:gpt-6.1-sol", "GPT-6.1 Sol", "equilibre", (2.00, 10.00, 0.10)),
    ModelInfo("openai:gpt-6-luna", "GPT-6 Luna", "rapide", (0.10, 0.50, 0.01)),
    ModelInfo("openai:gpt-5.4-mini", "GPT-5.4 mini", "rapide", (0.75, 4.50, 0.075), featured=False),
    # Google
    ModelInfo("gemini:gemini-4-argon", "Gemini 4 Argon", "maximum", (2.00, 10.00, 0.10), note="Prix doublé à partir du 1er décembre 2026."),
    ModelInfo("gemini:gemini-3.1-pro-preview", "Gemini 3.1 Pro (préversion)", "premium", (2.00, 12.00, 0.20), featured=False),
    ModelInfo("gemini:gemini-3.8-flash", "Gemini 3.8 Flash", "equilibre", (0.75, 3.75, 0.075), note="Prix revu au 1er janvier 2027."),
    ModelInfo("gemini:gemini-3.6-flash", "Gemini 3.6 Flash", "equilibre", (0.75, 3.75, 0.075), featured=False),
    ModelInfo("gemini:gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite", "rapide", (0.30, 2.50, 0.03)),
    ModelInfo("gemini:gemini-3.1-flash-lite", "Gemini 3.1 Flash-Lite", "rapide", (0.25, 1.50, 0.025), featured=False),
    # Mistral (alias « latest » : le prix suit la version courante)
    ModelInfo("mistral:mistral-large-latest", "Mistral Large", "premium", (0.68, 2.09, 0.07)),
    ModelInfo("mistral:mistral-medium-latest", "Mistral Medium", "equilibre", (1.50, 7.50, 0.15)),
    ModelInfo("mistral:mistral-small-latest", "Mistral Small", "rapide", (0.15, 0.60, 0.015)),
    # DeepSeek : prix hors pointe, doublés aux heures de pointe
    ModelInfo("deepseek:deepseek-v4-pro", "DeepSeek V4 Pro", "premium", (0.66, 1.98, 0.022), peak=(1.32, 3.96, 0.044), note=DEEPSEEK_PEAK),
    ModelInfo("deepseek:deepseek-flash", "DeepSeek Flash", "rapide", (0.15, 0.60, 0.003), peak=(0.30, 1.20, 0.006), note=DEEPSEEK_PEAK),
    # Moonshot (Kimi) : réfléchit toujours, les tokens de réflexion sont facturés en sortie
    ModelInfo("moonshot:kimi-k3", "Kimi K3", "premium", (3.00, 15.00, 0.30), note="Réfléchit toujours : ses tokens de réflexion sont facturés en sortie."),
    # Z.ai (GLM)
    ModelInfo("zai:glm-5.3", "GLM-5.3", "premium", (1.40, 4.40, 0.26)),
    ModelInfo("zai:glm-5.3-flashx", "GLM-5.3 FlashX", "equilibre", (0.37, 1.25, 0.075)),
    ModelInfo("zai:glm-5.3-flash", "GLM-5.3 Flash", "rapide", (0.15, 0.50, 0.03)),
    # Qwen (alias stables d'Alibaba Cloud ; prix indicatifs de la région Singapour)
    ModelInfo("qwen:qwen-max", "Qwen Max", "premium", (2.00, 6.00, 2.00), note="Prix indicatif : vérifie-le dans ta console Alibaba Cloud."),
    ModelInfo("qwen:qwen-plus", "Qwen Plus", "equilibre", (0.40, 1.60, 0.40), note="Prix indicatif : vérifie-le dans ta console Alibaba Cloud."),
    ModelInfo("qwen:qwen-flash", "Qwen Flash", "rapide", (0.15, 0.47, 0.15), note="Prix indicatif : vérifie-le dans ta console Alibaba Cloud."),
    # xAI (Grok)
    ModelInfo("xai:grok-4.7", "Grok 4.7", "premium", (2.00, 6.00, 0.50)),
    ModelInfo("xai:grok-4.3", "Grok 4.3", "equilibre", (1.25, 2.50, 0.20)),
    ModelInfo("xai:grok-build-0.1", "Grok Build 0.1", "rapide", (1.00, 2.00, 0.20), featured=False),
    # Groq (puces LPU, très rapide) : modèles ouverts ; Llama est facturé sur devis, donc absent
    ModelInfo("groq:openai/gpt-oss-120b", "GPT-OSS 120B (Groq)", "equilibre", (0.15, 0.60, 0.15)),
    ModelInfo("groq:qwen/qwen3.8-27b", "Qwen 3.8 27B (Groq, préversion)", "equilibre", (0.80, 4.00, 0.80), featured=False),
    ModelInfo("groq:openai/gpt-oss-20b", "GPT-OSS 20B (Groq)", "rapide", (0.075, 0.30, 0.075)),
    # OpenRouter : une seule clé pour les modèles des autres ; le prix réel est lu en direct.
    ModelInfo("openrouter:anthropic/claude-fable-5.1", "Fable 5.1 (OpenRouter)", "maximum", None),
    ModelInfo("openrouter:anthropic/claude-opus-5.5", "Opus 5.5 (OpenRouter)", "premium", None),
    ModelInfo("openrouter:anthropic/claude-sonnet-5.5", "Sonnet 5.5 (OpenRouter)", "equilibre", None),
    ModelInfo("openrouter:anthropic/claude-haiku-5.5", "Haiku 5.5 (OpenRouter)", "rapide", None),
    ModelInfo("openrouter:deepseek/deepseek-v4-pro", "DeepSeek V4 Pro (OpenRouter)", "premium", None, featured=False),
    ModelInfo("openrouter:deepseek/deepseek-v4.1-flash", "DeepSeek Flash (OpenRouter)", "rapide", None, featured=False),
    ModelInfo("openrouter:moonshotai/kimi-k3", "Kimi K3 (OpenRouter)", "premium", None, featured=False),
    ModelInfo("openrouter:z-ai/glm-5.3", "GLM-5.3 (OpenRouter)", "premium", None, featured=False),
    ModelInfo("openrouter:z-ai/glm-5.3-flash", "GLM-5.3 Flash (OpenRouter)", "rapide", None, featured=False),
    ModelInfo("openrouter:qwen/qwen3.8-max-0902", "Qwen 3.8 Max (OpenRouter)", "premium", None, featured=False),
    ModelInfo("openrouter:qwen/qwen3.8-flash", "Qwen 3.8 Flash (OpenRouter)", "rapide", None, featured=False),
    ModelInfo("openrouter:x-ai/grok-4.7", "Grok 4.7 (OpenRouter)", "premium", None, featured=False),
    ModelInfo("openrouter:openai/gpt-6.1-sol", "GPT-6.1 Sol (OpenRouter)", "equilibre", None, featured=False),
]
BY_ID = {m.id: m for m in MODELS}

# Les préréglages remplissent les trois rôles. Le rôle « sujet » écrit et recoupe les faits :
# il ne descend jamais sous la gamme « équilibré ».
PRESETS = {
    "economique": {"label": "Économique", "triage": "rapide", "topic": "equilibre", "director": "rapide"},
    "equilibre": {"label": "Équilibrée", "triage": "rapide", "topic": "equilibre", "director": "equilibre"},
    "qualite": {"label": "Qualité", "triage": "equilibre", "topic": "premium", "director": "premium"},
}


# Les serveurs de l'IA de ce PC : on peut leur confier un rôle à côté des fournisseurs en ligne.
LOCAL = {"ollama": "Ollama", "lmstudio": "LM Studio"}


def split(model: str) -> tuple[str, str]:
    """(fournisseur, identifiant chez le fournisseur). Seul le premier `:` sépare : un modèle
    Ollama garde le sien (`ollama:qwen3:14b` → `ollama`, `qwen3:14b`)."""
    prefix, sep, rest = model.partition(":")
    if sep and (prefix in PROVIDERS or prefix in LOCAL):
        return prefix, rest
    return "anthropic", model


def is_local(model: str) -> bool:
    return split(model)[0] in LOCAL


def label(provider: str) -> str:
    return LOCAL[provider] if provider in LOCAL else PROVIDERS[provider].label


def info(model: str) -> ModelInfo | None:
    return BY_ID.get(model)


def tier_of(model: str) -> str | None:
    if m := BY_ID.get(model):
        return m.tier
    return guess_tier(split(model)[1])


def guess_tier(name: str) -> str | None:
    """Gamme devinée d'après le nom, pour les modèles vus en direct mais absents du catalogue."""
    n = name.lower()
    if any(k in n for k in ("fable", "astra", "argon", "mythos", "prime")):
        return "maximum"
    if any(k in n for k in ("opus", "-pro", "large", "-max", "kimi-k3")):
        return "premium"
    if any(k in n for k in ("haiku", "luna", "lite", "nano", "-mini", "small", "ministral", "build")):
        return "rapide"
    if "flashx" in n or ("flash" in n and "gemini" in n):
        return "equilibre"
    if "flash" in n:  # DeepSeek, GLM, Qwen : leur « flash » est le modèle rapide
        return "rapide"
    if any(k in n for k in ("sonnet", "sol", "medium", "terra", "plus", "turbo", "grok", "glm-5", "kimi")):
        return "equilibre"
    return None


def tier_model(provider: str, tier: str) -> str | None:
    """Le modèle proposé pour une gamme chez un fournisseur (ou la gamme la plus proche)."""
    for t in TIER_FALLBACK[tier]:
        for m in MODELS:
            if m.featured and m.tier == t and m.provider == provider:
                return m.id
    return None


def base_url(provider: str) -> str:
    """L'adresse de l'API : celle du fournisseur, ou celle réglée par le lecteur (son espace
    Qwen, un autre fournisseur compatible OpenAI)."""
    from ...config import load_settings

    custom = load_settings().provider_urls.get(provider, "") if PROVIDERS[provider].url_setting else ""
    return (custom or PROVIDERS[provider].base_url).rstrip("/")


def deepseek_peak(at: datetime | None = None) -> bool:
    """Heures de pointe de DeepSeek : en semaine, de 1 h à 4 h et de 6 h à 10 h UTC."""
    at = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return at.weekday() < 5 and (1 <= at.hour < 4 or 6 <= at.hour < 10)


def price(model: str, at: datetime | None = None) -> tuple[float, float, float] | None:
    if (m := BY_ID.get(model)) and m.price:
        return m.peak if m.peak and deepseek_peak(at) else m.price
    provider, name = split(model)
    if provider in LOCAL:
        return (0.0, 0.0, 0.0)
    if provider == "openrouter":
        return _openrouter_prices().get(name)
    return None


# ── OpenRouter : prix en direct (liste publique, mise en cache 24 h) ─────────

_OR_CACHE: dict = {"at": 0.0, "prices": {}, "ids": []}


def _openrouter_prices() -> dict[str, tuple[float, float, float]]:
    if time.time() - _OR_CACHE["at"] > 86400:
        try:
            data = httpx.get("https://openrouter.ai/api/v1/models", timeout=15).json()["data"]
            prices = {}
            for m in data:
                p = m.get("pricing") or {}
                inp, out = float(p.get("prompt") or 0) * 1e6, float(p.get("completion") or 0) * 1e6
                cache = float(p.get("input_cache_read") or 0) * 1e6 or inp
                prices[m["id"]] = (inp, out, cache)
            _OR_CACHE.update(at=time.time(), prices=prices, ids=[m["id"] for m in data])
        except (httpx.HTTPError, KeyError, ValueError):
            _OR_CACHE["at"] = time.time() - 86400 + 600  # nouvel essai dans 10 minutes
    return _OR_CACHE["prices"]


def openrouter_ids() -> list[str]:
    _openrouter_prices()
    return _OR_CACHE["ids"]
