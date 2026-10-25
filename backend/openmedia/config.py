"""Réglages de l'application : dossier de données, préférences de l'utilisateur, clé API.

Les préférences vivent dans `settings.json` du dossier de données ; les clés API, elles, sont
rangées dans le Gestionnaire d'identifiants Windows (keyring) et jamais écrites sur le disque.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

import keyring
from keyring.errors import KeyringError
from pydantic import BaseModel, Field, model_validator

KEYRING_SERVICE = "openMedia"
KEYRING_USER = "anthropic_api_key"  # puis `<fournisseur>_api_key` pour les autres fournisseurs


def data_dir() -> Path:
    base = os.environ.get("OPENMEDIA_DATA") or os.path.join(os.environ.get("APPDATA", str(Path.home())), "openMedia")
    path = Path(base)
    path.mkdir(parents=True, exist_ok=True)
    (path / "audio").mkdir(exist_ok=True)
    return path


class Models(BaseModel):
    """Un modèle par rôle ; chaque sujet peut surcharger `topic`. Un modèle d'un autre
    fournisseur s'écrit `fournisseur:identifiant` (voir agents/providers/catalog.py)."""

    triage: str = "claude-haiku-5-5"
    topic: str = "claude-sonnet-5-5"
    director: str = "claude-sonnet-5-5"  # le Directeur réorganise des faits déjà recoupés


class Settings(BaseModel):
    # Moteur IA : « auto » prend la clé API si elle existe, sinon Claude Code s'il est installé ;
    # « local » sert TOUS les appels par un modèle de ce PC (Ollama ou LM Studio), sans repli en ligne.
    engine: Literal["auto", "api", "claude_code", "local"] = "auto"
    claude_code_path: str = ""  # vide : détection automatique
    local_provider: Literal["ollama", "lmstudio"] = "ollama"
    local_model: str = ""  # identifiant chez le serveur local (`qwen3:14b`)
    local_urls: dict[str, str] = Field(default_factory=dict)  # vide : ports par défaut
    # Adresse de l'API réglée par le lecteur : son espace Qwen, ou un autre fournisseur compatible OpenAI.
    provider_urls: dict[str, str] = Field(default_factory=dict)
    models: Models = Field(default_factory=Models)
    # Le rythme des passages : une ou plusieurs heures locales, tous les `run_every_days` jours
    # (1 à 30) ou, si `run_weekdays` n'est pas vide, certains jours de la semaine (lundi = 0).
    run_hours: list[str] = Field(default_factory=lambda: ["06:30"])
    run_every_days: int = 1
    run_weekdays: list[int] = Field(default_factory=list)
    schedule_anchor: str = ""  # AAAA-MM-JJ : un jour de passage, d'où partent les suivants
    languages: list[str] = Field(default_factory=lambda: ["fr", "en"])
    monthly_budget_usd: float = 30.0
    monthly_token_cap: int = 0  # au-delà, les passages planifiés s'arrêtent (0 : pas de plafond)
    max_parallel_topics: int = Field(default=3, ge=1, le=8)
    economy_batch: bool = False  # passage quotidien par l'API Batch : −50 %, mais plus lent
    claude_search_fallback: bool = True  # web_search Claude quand la couverture est trop faible
    min_independent_sources: int = 3
    rhythm_auto_default: bool = False  # les nouveaux sujets ajustent seuls leur rythme (rythme adaptatif)
    notify_threshold: int = 4  # importance (1–5) à partir de laquelle on notifie
    voice: str = "fr-FR-DeniseNeural"
    theme: Literal["system", "light", "dark"] = "system"
    # Tout ce qui n'est pas le suivi des sujets est une option, coupée tant que le lecteur ne
    # l'a pas activée (tutoriel ou Réglages › Confidentialité).
    detect_page: bool = False  # la languette repère l'article ouvert dans le navigateur
    # « Mes lectures » se met à jour seule : nouvelles visites des navigateurs cochés par le
    # lecteur, et d'eux seuls.
    history_auto: bool = False
    history_sources: list[dict] = Field(default_factory=list)  # [{browser, profile} | {path}]
    history_synced_at: str | None = None
    history_skip_phone: bool = False  # ignorer les visites venues du téléphone (synchronisation)
    readings_ai: bool = False  # les sujets de tes lectures sont nommés par l'IA (quelques titres envoyés)
    discover_enabled: bool = False  # Découvrir : les unes des médias et tes sujets envoyés à l'IA
    brief_audio_auto: bool = False  # le brief est lu chaque jour par la voix de Microsoft (en ligne)
    page_nudge: bool = False  # devant un article, la languette s'ouvre seule pour le proposer
    # Source du suivi : elle reçoit les mots-clés des sujets. (Google News a été retiré : son
    # robots.txt interdit les flux de recherche et le décodage des liens.)
    gdelt: bool = True
    bing_news: bool = True  # Bing Actualités : la recherche datée avec GDELT, sans clé
    # Premier lancement : le tutoriel, et l'accord sur les conditions de fonctionnement (le
    # suivi par une IA). Avant cet accord, le moteur ne fait aucun appel réseau de lui-même.
    onboarding_done: bool = False
    onboarding_step: int = 0
    consent_at: str | None = None
    previous_options: dict[str, bool] = Field(default_factory=dict)  # état d'avant le consentement
    claude_code_parallel: int = 3  # appels Claude Code simultanés (chacun est un processus)
    phone_listen: bool = False  # flux podcast servi sur le réseau local
    podcast_token: str = ""
    ntfy_topic: str = ""  # notifications vers le téléphone via ntfy.sh (vide : désactivé)
    last_visit_at: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _single_hour(cls, data):
        # Réglages d'avant les passages multiples : une seule heure, `run_hour`.
        if isinstance(data, dict) and "run_hours" not in data and data.get("run_hour"):
            data = {**data, "run_hours": [data["run_hour"]]}
        return data


# Les options qui lisent des données personnelles ou envoient des données hors du suivi.
OPTIONS = ("history_auto", "readings_ai", "discover_enabled", "detect_page", "page_nudge", "brief_audio_auto")


class ConsentRequired(RuntimeError):
    pass


def consented(settings: "Settings | None" = None) -> bool:
    """Le lecteur a accepté les conditions de fonctionnement : le moteur peut aller sur Internet."""
    return bool((settings or load_settings()).consent_at)


def require_consent() -> None:
    if not consented():
        raise ConsentRequired("Accepte d'abord les conditions de fonctionnement d'openMedia (le tutoriel de bienvenue).")


def _settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> Settings:
    path = _settings_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Settings.model_validate(_before_consent(data) if isinstance(data, dict) else data)
        except ValueError:
            _set_aside(path)
    return Settings()


def _set_aside(path: Path) -> None:
    """Un settings.json illisible n'est pas écrasé en silence : il est gardé à côté, et le
    lecteur est prévenu (ses choix, accord compris, sont à refaire)."""
    from datetime import datetime

    kept = path.with_name(f"settings.illisible-{datetime.now():%Y%m%d-%H%M%S}.json")
    try:
        path.replace(kept)
    except OSError:
        return
    try:
        from . import events

        events.publish("warning", message=f"Les réglages étaient illisibles : ils repartent de zéro (l'ancien fichier est gardé : {kept.name}).")
    except Exception:  # noqa: BLE001 — au démarrage, personne n'écoute encore
        pass


def _before_consent(data: dict) -> dict:
    """Réglages d'avant le consentement : les options marchaient sans accord (celles qui
    n'avaient pas encore de réglage étaient toujours actives). On les coupe, en gardant leur
    état pour que le tutoriel le rappelle (« tu l'utilisais »)."""
    if "consent_at" in data:
        return data
    previous = {k: bool(data.get(k, True)) for k in OPTIONS}
    return {**data, **{k: False for k in OPTIONS}, "previous_options": previous}


def save_settings(settings: Settings) -> None:
    # Écrit à côté puis remplace : une coupure en pleine écriture ne laisse jamais un fichier tronqué.
    path = _settings_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, path)


def update_settings(patch: dict) -> Settings:
    merged = load_settings().model_dump()
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    settings = Settings.model_validate(merged)
    save_settings(settings)
    return settings


def _keyring_user(provider: str) -> str:
    return KEYRING_USER if provider == "anthropic" else f"{provider}_api_key"


def get_key(provider: str) -> str | None:
    from .agents.providers.catalog import PROVIDERS

    for var in PROVIDERS[provider].env:
        if os.environ.get(var):
            return os.environ[var]
    try:
        return keyring.get_password(KEYRING_SERVICE, _keyring_user(provider))
    except KeyringError:
        return None


def set_key(provider: str, key: str | None) -> None:
    try:
        if key:
            keyring.set_password(KEYRING_SERVICE, _keyring_user(provider), key)
        else:
            keyring.delete_password(KEYRING_SERVICE, _keyring_user(provider))
    except KeyringError:
        pass


def get_api_key() -> str | None:
    """La clé Anthropic."""
    return get_key("anthropic")


def set_api_key(key: str | None) -> None:
    set_key("anthropic", key)


def settings_public() -> dict:
    """Ce que l'interface peut lire : tout sauf les clés, remplacées par des indicateurs."""
    from .agents.llm import engine_status

    status = engine_status()
    return {
        **load_settings().model_dump(),
        "has_api_key": status["has_api_key"],
        "engine_active": status["engine"],
        "claude_code": status["claude_code"],
        "providers": status["providers"],
        "local": status["local"],
    }


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)
