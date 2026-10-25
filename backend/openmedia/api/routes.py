"""L'API locale consommée par l'interface Tauri."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import select
from sse_starlette.sse import EventSourceResponse

from .. import events, phone, scheduler
from ..agents import rhythm
from ..agents.discover import discover
from ..agents.intake import intake
from ..agents.llm import LLM, RunMeter, get_llm
from ..agents.spec import build_spec
from ..agents.topic_agent import _finish, log_run, run_topic
from ..audio.tts import brief_audio, fiche_audio
from ..config import consented, data_dir, get_key, load_settings, set_key, settings_public, update_settings
from ..db import session
from ..models import Announcement, Article, Brief, Claim, Correction, Draft, DroppedLink, Fiche, Run, Source, Topic, TopicArticle, now
from ..sources import registry
from ..sources.quality import rated

router = APIRouter()


def _get(model, key):
    with session() as s:
        row = s.get(model, key)
    if not row:
        raise HTTPException(404, "Introuvable")
    return row


# ── Santé, réglages ──────────────────────────────────────────────────────────


@router.get("/health")
def health():
    return {"ok": True, "data_dir": str(data_dir())}


@router.get("/settings")
def get_settings():
    costs = scheduler.month_costs()
    return {**settings_public(), "month_cost_usd": round(costs["real"], 4), "month_subscription_usd": round(costs["subscription"], 4)}


@router.patch("/settings")
async def patch_settings(patch: dict):
    for key in ("has_api_key", "month_cost_usd", "month_subscription_usd", "engine_active", "claude_code", "providers", "podcast_token", "local", "previous_options"):
        patch.pop(key, None)
    if "local_urls" in patch:
        urls = patch["local_urls"] or {}
        if not isinstance(urls, dict) or any(k not in ("ollama", "lmstudio") or not isinstance(v, str) or (v and not re.match(r"^https?://[^\s/]+(:\d+)?/?$", v.strip())) for k, v in urls.items()):
            raise HTTPException(400, "L'adresse d'un serveur local s'écrit http://hôte:port (par exemple http://127.0.0.1:11434).")
        if any(v and not _private_host(v) for v in urls.values()):
            raise HTTPException(400, "Le serveur d'IA « sur ce PC » doit être sur ce PC ou sur ton réseau local (127.0.0.1, 192.168.x.x…) : une adresse publique enverrait tes sujets en clair sur Internet.")
        patch["local_urls"] = {k: v.strip().rstrip("/") for k, v in urls.items() if v and v.strip()}
    if "provider_urls" in patch:
        from ..agents.providers.catalog import PROVIDERS

        urls = patch["provider_urls"] or {}
        if not isinstance(urls, dict) or any(k not in PROVIDERS or not PROVIDERS[k].url_setting or not isinstance(v, str) for k, v in urls.items()):
            raise HTTPException(400, "Adresse d'API inconnue.")
        for v in urls.values():
            v = v.strip()
            if v and not re.match(r"^https://[^\s/]+(:\d+)?(/[^\s]*)?$", v) and not (re.match(r"^http://[^\s/]+(:\d+)?(/[^\s]*)?$", v) and _private_host(v)):
                raise HTTPException(400, "L'adresse de l'API s'écrit https://… (http:// n'est accepté que sur ce PC ou ton réseau local) : ta clé ne doit jamais circuler en clair.")
        patch["provider_urls"] = {**load_settings().provider_urls, **{k: v.strip().rstrip("/") for k, v in urls.items()}}
    if patch.get("consent_at") is True:  # l'interface accepte : l'heure est celle du moteur
        patch["consent_at"] = now().isoformat()
        from ..server import _fetch_ratings

        asyncio.get_running_loop().run_in_executor(None, _fetch_ratings)  # le jeu ouvert de notation arrive en fond
    if "claude_code_path" in patch:
        from ..agents.claude_code import find_claude
        from ..security import valid_claude_path

        # Le backend lancera ce programme : ce ne peut être que Claude Code.
        patch["claude_code_path"] = str(patch["claude_code_path"] or "").strip()
        if not valid_claude_path(patch["claude_code_path"]):
            raise HTTPException(400, "Ce chemin ne désigne pas Claude Code (claude.exe ou claude.cmd).")
        find_claude.cache_clear()
    if "run_every_days" in patch or "run_weekdays" in patch or "run_hours" in patch:
        _check_cadence(patch)
        if patch.get("run_every_days", 1) is None:
            raise HTTPException(400, "Le rythme général demande un nombre de jours.")
        if "run_hours" in patch and not patch["run_hours"]:
            raise HTTPException(400, "Le rythme général demande au moins une heure de passage.")
        current = load_settings()
        if patch.get("run_every_days", current.run_every_days) != current.run_every_days or patch.get("run_weekdays", current.run_weekdays) != current.run_weekdays:
            # Aujourd'hui devient un jour de passage : changer de rythme ne saute jamais un passage.
            patch["schedule_anchor"] = f"{datetime.now().astimezone():%Y-%m-%d}"
    if "monthly_token_cap" in patch:
        patch["monthly_token_cap"] = max(0, int(patch["monthly_token_cap"] or 0))
    before = load_settings().phone_listen
    update_settings(patch)
    if "phone_listen" in patch and patch["phone_listen"] != before:
        await (phone.start() if patch["phone_listen"] else phone.stop())
    return get_settings()


class ApiKey(BaseModel):
    key: str | None
    provider: str | None = None  # vide : reconnu d'après la clé


@router.put("/settings/api-key")
async def put_api_key(body: ApiKey):
    """Range une clé après avoir reconnu son fournisseur et vérifié qu'il l'accepte.
    `{key: null}` retire la clé du fournisseur indiqué (Anthropic par défaut)."""
    from ..agents.providers.catalog import PROVIDERS
    from ..agents.providers.keys import KeyRefused, check_key

    key = (body.key or "").strip()
    if body.provider and body.provider not in PROVIDERS:
        raise HTTPException(400, "Fournisseur inconnu")
    if not key:
        set_key(body.provider or "anthropic", None)
        return {**get_settings(), "detected": None}
    try:
        provider, verified, warning = await check_key(key, body.provider)
    except KeyRefused as e:
        raise HTTPException(400, str(e))
    set_key(provider, key)
    _default_models_for(provider)
    return {**get_settings(), "detected": provider, "verified": verified, "warning": warning}


def _default_models_for(provider: str) -> None:
    """Première clé d'un autre fournisseur, sans accès à Claude : les rôles encore réglés sur
    Claude passent à la gamme Équilibrée de ce fournisseur. « Sans accès à Claude » : ni clé
    Anthropic ni Claude Code, même si l'IA de ce PC était choisie jusque-là."""
    from ..agents.llm import engine_status
    from ..agents.providers import catalog

    settings = load_settings()
    roles = settings.models.model_dump()
    if provider == "anthropic" or engine_status()["engine"] in ("api", "claude_code") or any(catalog.split(m)[0] != "anthropic" for m in roles.values()):
        return
    preset = catalog.PRESETS["equilibre"]
    update_settings({"models": {role: catalog.tier_model(provider, preset[role]) or model for role, model in roles.items()}})


@router.delete("/settings/api-key/{provider}")
def delete_api_key(provider: str):
    from ..agents.providers.catalog import PROVIDERS

    if provider not in PROVIDERS:
        raise HTTPException(404, "Fournisseur inconnu")
    set_key(provider, None)
    return get_settings()


def _private_host(url: str) -> bool:
    import ipaddress
    from urllib.parse import urlsplit

    host = (urlsplit(url.strip()).hostname or "").lower()
    if host in ("localhost",):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host.endswith((".local", ".lan", ".home"))  # nom d'une machine du réseau local
    return (ip.is_loopback or ip.is_private) and not ip.is_link_local


@router.get("/settings/local")
def local_engines():
    """Ollama et LM Studio sur ce PC (ou aux adresses réglées), et leurs modèles."""
    from ..agents.providers.local import detect

    return detect(load_settings().local_urls, fresh=True)


@router.get("/models")
async def list_models(live: bool = False):
    """Les modèles proposés par gamme, avec leur prix, ceux de l'IA de ce PC (Ollama, LM Studio)
    et (avec `live`) ceux que chaque clé enregistrée peut utiliser. `effective` : le modèle qui
    sert vraiment chaque rôle (un rôle réglé sur un fournisseur absent passe à un autre)."""
    import asyncio

    from ..agents.llm import NoApiKey, RouterLLM, engine_status
    from ..agents.providers import catalog
    from ..agents.providers.keys import list_live
    from ..agents.providers.local import detect

    status = engine_status()
    usable = {p: (status["engine"] in ("api", "claude_code") if p == "anthropic" else info["has_key"]) for p, info in status["providers"].items()}
    servers = await asyncio.to_thread(detect, load_settings().local_urls)
    usable |= {p: servers[p]["found"] for p in catalog.LOCAL}

    def row(model_id: str, label: str, tier: str | None, featured: bool, note: str = "") -> dict:
        provider = catalog.split(model_id)[0]
        known = catalog.info(model_id)
        price = known.price if known else catalog.price(model_id) if provider != "openrouter" else None  # le prix hors pointe pour DeepSeek
        region = "sur ce PC" if provider in catalog.LOCAL else catalog.PROVIDERS[provider].region
        return {"id": model_id, "label": label, "provider": provider, "tier": tier, "tier_label": catalog.TIER_LABEL.get(tier or "", ""), "price": price, "featured": featured, "usable": usable[provider], "note": note, "region": region}

    models = [row(m.id, m.label, m.tier, m.featured, m.note) for m in catalog.MODELS]
    models += [row(f"{p}:{m['id']}", m["id"] + (f" ({m['size']})" if m["size"] else ""), catalog.guess_tier(m["id"]), True) for p in catalog.LOCAL for m in servers[p]["models"]]
    if live:
        known = {m["id"] for m in models}

        async def fetch(provider: str) -> list[str]:
            key = get_key(provider)
            if not key or provider == "anthropic":
                return []
            try:
                return [f"{provider}:{i}" for i in await list_live(provider, key)]
            except Exception:  # noqa: BLE001 — la liste en direct est un bonus
                return []

        for ids in await asyncio.gather(*[fetch(p) for p in catalog.PROVIDERS]):
            models += [row(i, catalog.split(i)[1], catalog.tier_of(i), False) for i in ids if i not in known]
    # Les prix d'OpenRouter sont lus en ligne : pas avant l'accord sur les conditions.
    # et seulement pour qui a une clé OpenRouter (sinon ce serait une requête non annoncée).
    if any(m["provider"] == "openrouter" for m in models) and consented() and get_key("openrouter"):
        prices = await asyncio.to_thread(catalog._openrouter_prices)
        for m in models:
            if m["provider"] == "openrouter":
                m["price"] = prices.get(catalog.split(m["id"])[1])
    presets = {
        key: {"label": p["label"], "by_provider": {prov: {role: catalog.tier_model(prov, p[role]) for role in ("triage", "topic", "director")} for prov in catalog.PROVIDERS}}
        for key, p in catalog.PRESETS.items()
    }
    providers = [{"id": p.id, "label": p.label, "usable": usable[p.id], "has_key": status["providers"][p.id]["has_key"], "search": p.search, "batch": p.batch, "hint": p.hint, "region": p.region, "local": False} for p in catalog.PROVIDERS.values()]
    providers += [{"id": p, "label": label, "usable": usable[p], "has_key": False, "search": False, "batch": False, "hint": "", "region": "sur ce PC", "local": True} for p, label in catalog.LOCAL.items()]
    effective: dict[str, str | None] = {}
    if status["choice"] != "local":
        router = RouterLLM(status)
        for role, model in load_settings().models.model_dump().items():
            provider = catalog.split(model)[0]
            try:
                effective[role] = model if router.available(provider) else router.same_tier(model, exclude=provider)
            except NoApiKey:
                effective[role] = None
    return {"providers": providers, "models": models, "presets": presets, "tiers": catalog.TIER_LABEL, "effective": effective}


class ModelCheckIn(BaseModel):
    model: str


@router.post("/models/check")
async def check_model_route(body: ModelCheckIn):
    """Un court appel structuré au modèle choisi : marche-t-il avec openMedia ?"""
    from ..agents.model_check import check_model

    if not consented():
        raise HTTPException(409, "consent_required")
    return await check_model(body.model.strip())


@router.post("/visit")
def visit():
    """Mémorise la dernière visite (pour « nouveau depuis ta dernière visite »)."""
    previous = load_settings().last_visit_at
    update_settings({"last_visit_at": now().isoformat()})
    return {"previous_visit_at": previous}


# ── Sujets ───────────────────────────────────────────────────────────────────


class TopicIn(BaseModel):
    spec: dict | None = None  # la spécification rendue par l'aperçu, réutilisée telle quelle
    prompt: str
    name: str | None = None
    importance: int = 3
    languages: list[str] = ["fr", "en"]
    feeds: list[str] = []
    run_hour: str | None = None  # ancienne heure unique, reprise dans `run_hours`
    run_hours: list[str] = []  # vide : les heures des réglages
    run_every_days: int | None = None
    run_weekdays: list[int] = []
    follow_deadlines: bool = True
    model: str | None = None
    run_now: bool = True
    draft_id: int | None = None  # le brouillon d'origine, supprimé une fois le sujet créé
    kind: str = "actualite"
    research_fields: list[str] = []
    recording_id: int | None = None  # l'enregistrement d'où vient le sujet, qui passe en « suivi »


HOUR = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
MAX_HOURS = 6


def _check_cadence(data: dict) -> dict:
    """Valide et range les champs de rythme présents (sujet ou réglages). L'ancienne heure
    unique `run_hour` devient une liste d'une heure."""
    if data.get("run_hour") and not data.get("run_hours"):
        data["run_hours"] = [data["run_hour"]]
    every = data.get("run_every_days")
    if every is not None and (not isinstance(every, int) or not 1 <= every <= 30):
        raise HTTPException(400, "Un passage tous les 1 à 30 jours.")
    if "run_weekdays" in data:
        days = sorted(set(data["run_weekdays"] or []))
        if any(not isinstance(d, int) or not 0 <= d <= 6 for d in days):
            raise HTTPException(400, "Jours de la semaine : de 0 (lundi) à 6 (dimanche).")
        data["run_weekdays"] = days
    if "run_hours" in data:
        hours = sorted(set(data["run_hours"] or []))
        if any(not isinstance(h, str) or not HOUR.match(h) for h in hours):
            raise HTTPException(400, "Heures de passage au format HH:MM.")
        if len(hours) > MAX_HOURS:
            raise HTTPException(400, f"{MAX_HOURS} passages par jour au plus.")
        data["run_hours"] = hours
    return data


class TopicPatch(BaseModel):
    prompt: str | None = None
    name: str | None = None
    importance: int | None = None
    languages: list[str] | None = None
    feeds: list[str] | None = None
    # Rythme : `run_every_days` null et `run_weekdays` vide reprennent les jours des réglages,
    # `run_hours` vide leurs heures.
    run_hour: str | None = None
    run_hours: list[str] | None = None
    run_every_days: int | None = None
    run_weekdays: list[int] | None = None
    follow_deadlines: bool | None = None
    model: str | None = None
    status: str | None = None
    social: dict | None = None
    research_fields: list[str] | None = None


def _topic_out(t: Topic) -> dict:
    with session() as s:
        f = s.exec(select(Fiche).where(Fiche.topic_id == t.id).order_by(Fiche.version.desc())).first()
        last_run = s.exec(select(Run).where(Run.topic_id == t.id).order_by(Run.id.desc())).first()
    settings = load_settings()
    when = scheduler.next_run(t, settings, datetime.now().astimezone())
    c = scheduler.cadence(t, settings)
    return {
        **t.model_dump(),
        "running": scheduler.is_running(t.id),
        "next_run": when.isoformat() if when else None,
        "schedule": {"every": c.every, "weekdays": list(c.weekdays), "hours": list(c.hours), "own": bool(t.run_weekdays or t.run_every_days or t.run_hours or t.run_hour)},
        "latest": {"id": f.id, "version": f.version, "created_at": f.created_at, "nothing_new": f.nothing_new, "novelty": f.novelty or {}, "title": f.content.get("title"), "lede": f.content.get("lede"), "state": f.content.get("state"), "importance": f.content.get("importance"), "whats_new": f.content.get("whats_new", [])[:3]} if f else None,
        "last_run": {"status": last_run.status, "error": last_run.error, "cost_usd": last_run.cost_usd} if last_run else None,
    }


@router.get("/topics")
def list_topics(include_archived: bool = False):
    with session() as s:
        q = select(Topic).order_by(Topic.importance.desc(), Topic.created_at)
        if not include_archived:
            q = q.where(Topic.status != "archived")
        return [_topic_out(t) for t in s.exec(q).all()]


@router.post("/topics/preview")
async def preview_topic(body: TopicIn):
    """« Essai à blanc » : la spécification et les sources qui seraient retenues, sans fiche."""
    settings = load_settings()
    llm, meter = get_llm(), RunMeter()
    spec = await build_spec(llm, meter, body.model or settings.models.topic, body.prompt, now())
    log_run("spec", meter)
    from ..collect import news_search

    cands = await news_search.search({"fr": spec.queries_fr[:2], "en": spec.queries_en[:2]}, 7, per_lang=2)
    return {"spec": spec.model_dump(), "cost_usd": round(meter.cost_usd, 4), "sample": [{"title": c.title, "source": c.source_name, "published_at": c.published_at} for c in cands[:20]]}


@router.post("/topics")
async def create_topic(body: TopicIn, background: BackgroundTasks):
    settings = load_settings()
    cadence = _check_cadence(body.model_dump(include={"run_hour", "run_hours", "run_every_days", "run_weekdays"}))
    llm, meter = get_llm(), RunMeter()
    if body.spec and body.kind != "recherche":  # déjà construite par l'aperçu, pour la même consigne
        from ..agents.schemas import TopicSpec

        spec = TopicSpec.model_validate(body.spec)
    else:
        spec = await build_spec(llm, meter, body.model or settings.models.topic, body.prompt, now(), kind=body.kind, fields=body.research_fields)
    since = None
    if spec.start_date:
        try:
            since = datetime.fromisoformat(spec.start_date).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    with session() as s:
        t = Topic(name=body.name or spec.name, prompt=body.prompt, spec=spec.model_dump(), importance=body.importance, languages=body.languages, feeds=body.feeds, run_hours=cadence["run_hours"], run_every_days=cadence["run_every_days"], run_weekdays=cadence["run_weekdays"], follow_deadlines=body.follow_deadlines, model=body.model, since=since, kind=body.kind if body.kind in ("actualite", "recherche") else "actualite", research_fields=body.research_fields, rhythm={"auto": settings.rhythm_auto_default}, run_anchor=datetime.now().astimezone().date().isoformat() if cadence["run_every_days"] else None)
        s.add(t)
        s.commit()
        s.refresh(t)
        run = Run(topic_id=t.id, kind="spec")
        s.add(run)
        s.commit()
        s.refresh(run)
    _finish(run.id, meter, "done")
    if body.draft_id:
        with session() as s:
            if d := s.get(Draft, body.draft_id):
                s.delete(d)
                s.commit()
    if body.recording_id:
        from ..agents import recordings

        recordings.follow(body.recording_id, t.id)
    if body.run_now:
        background.add_task(_safe_run, t.id)
    return _topic_out(t)


async def _safe_run(topic_id: int):
    """Passage lancé en tâche de fond : son erreur est déjà consignée dans le Run et publiée."""
    try:
        await scheduler.run_one(topic_id)
    except Exception as e:  # noqa: BLE001 — rien ne doit tuer la tâche de fond
        events.publish("warning", message=f"Le passage n'a pas pu aboutir : {e}", topic_id=topic_id)


@router.get("/topics/{topic_id}")
def get_topic(topic_id: int):
    return _topic_out(_get(Topic, topic_id))


@router.patch("/topics/{topic_id}")
async def patch_topic(topic_id: int, body: TopicPatch):
    data = _check_cadence(body.model_dump(exclude_unset=True))
    if "run_hours" in data:
        data["run_hour"] = None  # l'ancienne heure unique cède la place à la liste
    for key in ("run_weekdays", "run_hours"):
        if key in data and data[key] is None:
            data[key] = []
    if data.get("follow_deadlines") is None:
        data.pop("follow_deadlines", None)
    with session() as s:
        t = s.get(Topic, topic_id)
        if not t:
            raise HTTPException(404, "Introuvable")
        if "prompt" in data and data["prompt"] != t.prompt:
            settings = load_settings()
            meter = RunMeter()
            spec = await build_spec(get_llm(), meter, data.get("model") or t.model or settings.models.topic, data["prompt"], now(), kind=t.kind, fields=data.get("research_fields") or t.research_fields or [])
            log_run("spec", meter, topic_id)
            t.spec = spec.model_dump()
        rhythm_changed = any(k in data and data[k] != getattr(t, k) for k in ("run_every_days", "run_weekdays"))
        for k, v in data.items():
            setattr(t, k, v)
        if rhythm_changed:
            # Un nouveau rythme part d'aujourd'hui, et le conseil repart d'une observation neuve.
            t.run_anchor = datetime.now().astimezone().date().isoformat() if t.run_every_days else None
            t.rhythm = {**(t.rhythm or {}), "changed_at": now().isoformat(), "dismissed": None}
        if data.get("status") == "active":
            t.quiet_runs = 0
        s.add(t)
        s.commit()
        s.refresh(t)
    return _topic_out(t)


@router.delete("/topics/{topic_id}")
def delete_topic(topic_id: int):
    with session() as s:
        for model in (TopicArticle, Claim, Fiche, DroppedLink, Run, Correction, Announcement):
            for row in s.exec(select(model).where(model.topic_id == topic_id)).all():
                s.delete(row)
        t = s.get(Topic, topic_id)
        if t:
            for brief in s.exec(select(Brief)).all():
                content = brief.content or {}
                if any(p.get("topic_id") == topic_id for p in content.get("points", [])) or t.name in content.get("quiet_topics", []):
                    s.delete(brief)  # un Brief qui parlait du sujet effacé disparaît avec lui
            s.delete(t)
        s.commit()
    from ..agents import recordings

    recordings.forget_topic(topic_id)
    return {"ok": True}


@router.post("/topics/{topic_id}/run")
def run_topic_now(topic_id: int, background: BackgroundTasks):
    _get(Topic, topic_id)
    get_llm()  # moteur indisponible ou accord manquant : l'erreur part tout de suite à l'interface
    if scheduler.is_running(topic_id):
        return {"started": False, "reason": "déjà en cours"}
    background.add_task(_safe_run, topic_id)
    return {"started": True}


@router.post("/topics/{topic_id}/dry-run")
async def dry_run(topic_id: int):
    return await run_topic(topic_id, dry=True)


@router.post("/run-all")
def run_all(background: BackgroundTasks):
    get_llm()
    background.add_task(scheduler.tick, True)
    return {"started": True}


# ── Fiches ───────────────────────────────────────────────────────────────────


@router.get("/topics/{topic_id}/fiches")
def list_fiches(topic_id: int):
    with session() as s:
        rows = s.exec(select(Fiche).where(Fiche.topic_id == topic_id).order_by(Fiche.version.desc())).all()
    return [{"id": f.id, "version": f.version, "created_at": f.created_at, "nothing_new": f.nothing_new, "importance": f.content.get("importance"), "whats_new_count": len(f.content.get("whats_new", [])), "confirmations": (f.novelty or {}).get("confirmations", 0)} for f in rows]


@router.get("/topics/{topic_id}/fiche")
def get_fiche(topic_id: int, version: int | None = None):
    with session() as s:
        q = select(Fiche).where(Fiche.topic_id == topic_id)
        q = q.where(Fiche.version == version) if version else q.order_by(Fiche.version.desc())
        f = s.exec(q).first()
    if not f:
        raise HTTPException(404, "Pas encore de fiche")
    return f.model_dump()


# ── Rythme conseillé ─────────────────────────────────────────────────────────


class RhythmEvery(BaseModel):
    every: int


class RhythmAuto(BaseModel):
    auto: bool | None = None
    min_every: int | None = None
    max_every: int | None = None


@router.get("/topics/{topic_id}/rhythm")
def topic_rhythm(topic_id: int):
    """Le conseil de rythme, la bande d'activité des 30 derniers jours et le pilote automatique."""
    return rhythm.overview(_get(Topic, topic_id))


@router.post("/topics/{topic_id}/rhythm/apply")
def rhythm_apply(topic_id: int, body: RhythmEvery):
    _get(Topic, topic_id)
    if not 1 <= body.every <= 30:
        raise HTTPException(400, "Un passage tous les 1 à 30 jours.")
    advice = rhythm.advise(_get(Topic, topic_id))
    reason = advice["reason"] if advice.get("every") == body.every else ""
    return _topic_out(rhythm.apply(topic_id, body.every, by="user", reason=reason))


@router.post("/topics/{topic_id}/rhythm/dismiss")
def rhythm_dismiss(topic_id: int, body: RhythmEvery):
    _get(Topic, topic_id)
    return _topic_out(rhythm.dismiss(topic_id, body.every))


@router.patch("/topics/{topic_id}/rhythm")
def rhythm_configure(topic_id: int, body: RhythmAuto):
    _get(Topic, topic_id)
    rhythm.configure(topic_id, **body.model_dump(exclude_unset=True))
    return rhythm.overview(_get(Topic, topic_id))


@router.get("/rhythm")
def all_rhythms():
    """Les conseils de tous les sujets, pour « Consommation »."""
    settings = load_settings()
    with session() as s:
        topics = s.exec(select(Topic).where(Topic.status != "archived")).all()
    out = []
    for t in topics:
        advice = rhythm.advise(t, settings)
        out.append({"topic_id": t.id, "name": t.name, "auto": rhythm.state(t)["auto"], "advice": advice})
    return out


@router.get("/topics/{topic_id}/catchup")
def catchup(topic_id: int, since: str | None = None):
    """Rattrapage : toutes les nouveautés publiées depuis une date, version par version."""
    start = datetime.fromisoformat(since) if since else (now() - timedelta(days=7))
    start = start if start.tzinfo else start.replace(tzinfo=timezone.utc)
    with session() as s:
        rows = s.exec(select(Fiche).where(Fiche.topic_id == topic_id, Fiche.created_at > start).order_by(Fiche.version)).all()
    days, seen = [], set()
    for f in rows:
        if f.nothing_new:
            continue
        items = [i for i in f.content.get("whats_new", []) if i["text"] not in seen]
        seen |= {i["text"] for i in items}
        days.append({"version": f.version, "created_at": f.created_at, "whats_new": items, "changes": f.content.get("changes", [])})
    return {"since": start, "versions": len(rows), "quiet_versions": sum(1 for f in rows if f.nothing_new), "days": days}


@router.get("/topics/{topic_id}/articles")
def topic_articles(topic_id: int, kept: bool | None = None, limit: int = 200):
    with session() as s:
        q = select(TopicArticle, Article).join(Article, Article.id == TopicArticle.article_id).where(TopicArticle.topic_id == topic_id)
        if kept is not None:
            q = q.where(TopicArticle.kept == kept)
        rows = s.exec(q.order_by(Article.published_at.desc()).limit(limit)).all()
    out = []
    for ta, a in rows:
        src = registry.lookup(a.domain)
        out.append({"ref": f"S{a.id}", "id": a.id, "title": a.title, "url": a.url, "source": src.name, "country": src.country, "kind": src.kind, "quality": src.quality, "quality_note": src.quality_note, "published_at": a.published_at, "wire": a.wire, "origin": ta.origin, "kept": ta.kept, "nature": ta.nature, "relevance": ta.relevance, "sensationalism": ta.sensationalism, "reason": ta.reason})
    return out


@router.get("/topics/{topic_id}/claims")
def topic_claims(topic_id: int):
    with session() as s:
        return s.exec(select(Claim).where(Claim.topic_id == topic_id).order_by(Claim.last_seen.desc())).all()


@router.post("/fiches/{fiche_id}/audio")
async def make_fiche_audio(fiche_id: int):
    _get(Fiche, fiche_id)
    return {"file": await fiche_audio(fiche_id)}


@router.get("/audio/{name}")
def get_audio(name: str):
    path = (data_dir() / "audio" / name).resolve()
    if path.parent != (data_dir() / "audio").resolve() or not path.exists():
        raise HTTPException(404, "Introuvable")
    return FileResponse(path, media_type="audio/mpeg")


# ── Aujourd'hui, Brief ───────────────────────────────────────────────────────


@router.get("/today")
def today():
    day = f"{datetime.now():%Y-%m-%d}"
    with session() as s:
        brief = s.exec(select(Brief).order_by(Brief.id.desc())).first()
    return {"day": day, "brief": brief.model_dump() if brief else None, "topics": list_topics(), "last_visit_at": load_settings().last_visit_at}


@router.get("/briefs")
def list_briefs(limit: int = 30):
    with session() as s:
        return [{"id": b.id, "day": b.day, "headline": b.content.get("headline"), "audio_path": b.audio_path} for b in s.exec(select(Brief).order_by(Brief.id.desc()).limit(limit)).all()]


@router.get("/briefs/{brief_id}")
def get_brief(brief_id: int):
    return _get(Brief, brief_id).model_dump()


@router.post("/briefs/run")
async def run_brief():
    brief = await scheduler.brief_now()
    if not brief:
        raise HTTPException(400, "Aucune fiche mise à jour dans les dernières 26 heures.")
    return brief.model_dump()


@router.post("/briefs/{brief_id}/audio")
async def make_brief_audio(brief_id: int):
    _get(Brief, brief_id)
    return {"file": await brief_audio(brief_id)}


# ── Lecture, corrections, preuves, annonces ──────────────────────────────────


@router.post("/topics/{topic_id}/seen")
def topic_seen(topic_id: int):
    """La fiche vient d'être affichée : les faits qu'elle contient comptent comme lus."""
    with session() as s:
        t = s.get(Topic, topic_id)
        if not t:
            raise HTTPException(404, "Introuvable")
        t.last_seen_at = now()
        s.add(t)
        s.commit()
    return {"ok": True}


def _sources_for(refs: list[str]) -> list[dict]:
    from ..agents.material import ref_id

    ids = [i for i in (ref_id(r) for r in refs) if i]
    with session() as s:
        arts = s.exec(select(Article).where(Article.id.in_(ids))).all() if ids else []
    out = []
    for a in arts:
        src = registry.lookup(a.domain)
        out.append({"ref": f"S{a.id}", "id": a.id, "title": a.title, "url": a.url, "domain": a.domain, "name": src.name, "published_at": a.published_at, "country": src.country, "kind": src.kind})
    return out


@router.get("/corrections")
def list_corrections(topic_id: int | None = None, unseen: bool = False, limit: int = 100):
    with session() as s:
        q = select(Correction).order_by(Correction.created_at.desc()).limit(limit)
        if topic_id:
            q = q.where(Correction.topic_id == topic_id)
        if unseen:
            q = q.where(Correction.seen_at == None)  # noqa: E711
        rows = s.exec(q).all()
        names = {t.id: t.name for t in s.exec(select(Topic)).all()}
    return [{**c.model_dump(), "topic_name": names.get(c.topic_id, ""), "sources": _sources_for(c.refs)} for c in rows]


class SeenIn(BaseModel):
    ids: list[int] | None = None


@router.post("/corrections/seen")
def corrections_seen(body: SeenIn):
    from ..agents.corrections import mark_seen

    mark_seen(body.ids)
    return {"ok": True}


def _split(value: str) -> list[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


@router.get("/topics/{topic_id}/proof")
def topic_proof(topic_id: int, refs: str = "", against: str = "", status: str | None = None):
    from ..agents.proof import build_proof

    return build_proof(topic_id, _split(refs), _split(against), status)


def _announcement_out(a: Announcement, names: dict[int, str]) -> dict:
    from ..agents.announcements import due_date

    d = due_date(a.due)
    return {**a.model_dump(), "topic_name": names.get(a.topic_id, ""), "due_date": d.isoformat() if d else None, "sources": _sources_for(a.refs), "resolution_sources": _sources_for(a.resolution_refs)}


def _topic_names() -> dict[int, str]:
    with session() as s:
        return {t.id: t.name for t in s.exec(select(Topic)).all()}


@router.get("/topics/{topic_id}/announcements")
def topic_announcements(topic_id: int):
    from ..agents.announcements import due_date

    with session() as s:
        rows = s.exec(select(Announcement).where(Announcement.topic_id == topic_id)).all()
    far = datetime.max.date()
    rows.sort(key=lambda a: (a.status not in ("a_venir", "en_retard"), due_date(a.due) or far))
    names = _topic_names()
    return [_announcement_out(a, names) for a in rows]


@router.get("/announcements/upcoming")
def upcoming_announcements(days: int = 14):
    """En retard, à échéance dans les `days` jours, ou tranchées depuis une semaine."""
    from ..agents.announcements import due_date

    today = datetime.now().date()
    with session() as s:
        rows = s.exec(select(Announcement)).all()
    out = []
    for a in rows:
        d = due_date(a.due)
        recent = a.resolved_at is not None and (now() - a.resolved_at) <= timedelta(days=7)
        if a.status == "en_retard" or (a.status == "a_venir" and d and d <= today + timedelta(days=days)) or recent:
            out.append(a)
    out.sort(key=lambda a: due_date(a.due) or today)
    names = _topic_names()
    return [_announcement_out(a, names) for a in out]


@router.get("/calendar")
def calendar(start: str, end: str, topic_id: int | None = None):
    """Le calendrier, du `start` au `end` compris (AAAA-MM-JJ, 3 mois au plus), d'un sujet ou de
    tous : les échéances relevées dans les fiches (`undated` : celles qui n'ont qu'un mois ou une
    année), les événements de leur chronologie et, pour un sujet, ses passages faits et prévus."""
    from ..agents.announcements import due_date

    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise HTTPException(400, "Dates au format AAAA-MM-JJ.")
    if last < first or (last - first).days > 92:
        raise HTTPException(400, "Trois mois au plus.")
    names = _topic_names()
    one = _get(Topic, topic_id) if topic_id is not None else None
    with session() as s:
        q = select(Announcement)
        if one:
            q = q.where(Announcement.topic_id == one.id)
        announcements = s.exec(q).all()
        topics = [one] if one else s.exec(select(Topic).where(Topic.status != "archived")).all()
        fiches = {t.id: s.exec(select(Fiche).where(Fiche.topic_id == t.id).order_by(Fiche.version.desc())).first() for t in topics}

    deadlines, undated = [], []
    for a in announcements:
        d = due_date(a.due)
        if d is None:
            continue
        if len(a.due.strip()) >= 10:
            if first <= d <= last:
                deadlines.append({**_announcement_out(a, names), "date": d.isoformat()})
        elif date(d.year, d.month, 1) <= last and d >= first:  # le mois (ou l'année) touche la période
            undated.append({**_announcement_out(a, names), "month": f"{d:%Y-%m}"})

    events = []
    for t in topics:
        f = fiches.get(t.id)
        if not f:
            continue
        sources = {src["ref"]: src for src in f.sources or []}
        for e in f.content.get("timeline", []):
            try:
                d = date.fromisoformat(str(e.get("date", ""))[:10])
            except ValueError:
                continue
            if first <= d <= last:
                events.append({"date": d.isoformat(), "text": e.get("event", ""), "topic_id": t.id, "topic_name": t.name, "sources": [sources[r] for r in e.get("refs", []) if r in sources]})

    runs, planned = [], []
    if topic_id is not None:
        local = lambda dt: (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone()  # noqa: E731
        with session() as s:
            for f in s.exec(select(Fiche).where(Fiche.topic_id == topic_id)).all():
                at = local(f.created_at)
                if first <= at.date() <= last:
                    runs.append({"date": f"{at:%Y-%m-%d}", "time": f"{at:%H:%M}", "version": f.version, "nothing_new": f.nothing_new, "news": len(f.content.get("whats_new", [])), "confirmations": (f.novelty or {}).get("confirmations", 0)})
        t = topics[0]
        settings = load_settings()
        at = datetime.now().astimezone()
        begin = max(at, at.replace(year=first.year, month=first.month, day=first.day, hour=0, minute=0, second=0, microsecond=0))
        stop = at.replace(year=last.year, month=last.month, day=last.day, hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        if t.status == "active" and begin < stop:
            c = scheduler.cadence(t, settings)
            for slot in scheduler.slots_between(begin, stop, c):
                planned.append({"date": f"{slot:%Y-%m-%d}", "time": f"{slot:%H:%M}", "deadline": not c.regular(slot.date())})
        elif t.status == "sleeping" and (when := scheduler.next_run(t, settings, at)) and first <= when.date() <= last:
            planned.append({"date": f"{when:%Y-%m-%d}", "time": f"{when:%H:%M}", "deadline": False})
        runs.sort(key=lambda r: (r["date"], r["time"]))
    return {"deadlines": deadlines, "undated": undated, "events": events, "runs": runs, "planned": planned}


@router.post("/announcements/{announcement_id}/check")
async def check_announcement(announcement_id: int):
    from ..agents.announcements import check_one

    _get(Announcement, announcement_id)
    meter = RunMeter()
    a = await check_one(get_llm(), meter, load_settings().models.topic, announcement_id)
    log_run("announcement", meter)
    return _announcement_out(a, _topic_names())


# ── Téléphone et Claude ──────────────────────────────────────────────────────


@router.get("/search")
def search_journal(q: str, limit: int = 12):
    from ..agents.search import search

    return search(q, limit)


@router.get("/research/fields")
def research_fields():
    from ..collect.research import field_options

    return field_options()


@router.get("/phone")
def phone_status():
    return phone.status()


def _mcp_command() -> list[str]:
    import sys

    if getattr(sys, "frozen", False):  # application installée : le même exécutable, en mode MCP
        return [sys.executable, "--mcp"]
    return [sys.executable, "-m", "openmedia.mcp_server"]


@router.get("/mcp")
def mcp_info():
    from ..agents.claude_code import claude_code_info

    quoted = " ".join(f'"{c}"' if " " in c else c for c in _mcp_command())
    return {"command": f"claude mcp add --scope user -e OPENMEDIA_DATA={data_dir()} openmedia -- {quoted}", "claude_code": claude_code_info()["found"]}


@router.post("/mcp/install")
async def mcp_install():
    """Ajoute le serveur MCP d'openMedia à Claude Code (action explicite du lecteur)."""
    import asyncio
    import subprocess

    from ..agents.claude_code import find_claude

    claude = find_claude(load_settings().claude_code_path or None)
    if not claude:
        raise HTTPException(400, "Claude Code est introuvable sur ce PC.")
    args = [*claude, "mcp", "add", "--scope", "user", "-e", f"OPENMEDIA_DATA={data_dir()}", "openmedia", "--", *_mcp_command()]
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out, _ = await asyncio.wait_for(proc.communicate(), 60)
    text = out.decode("utf-8", errors="replace").strip()
    if proc.returncode != 0 and "already exists" not in text:
        raise HTTPException(400, f"Claude Code a refusé l'ajout : {text[-300:]}")
    return {"ok": True, "message": text[-300:]}


# ── Mes lectures (historique des navigateurs) ────────────────────────────────


@router.get("/history/browsers")
def history_browsers():
    """Navigateurs et profils détectés. L'historique n'est pas lu à ce stade."""
    from ..collect.history import detect

    return [p.as_dict() for p in detect()]


class HistoryImport(BaseModel):
    browsers: list[dict]
    days: int = 90
    remember: bool = True  # faux : le tutoriel lit les navigateurs un par un, déjà mémorisés


@router.post("/history/import")
async def history_import(body: HistoryImport):
    import asyncio

    from ..agents.readings import import_history

    return await asyncio.to_thread(import_history, body.browsers, max(1, min(body.days, 730)), body.remember)


@router.post("/history/sync")
async def history_sync(max_age: float = 5):
    """Mise à jour automatique de « Mes lectures », demandée à l'ouverture de la vue : rien si
    elle date de moins de `max_age` minutes ou si elle est désactivée."""
    import asyncio

    from ..agents.readings import sync_history

    from ..agents import recurring

    result = await asyncio.to_thread(sync_history, max_age)
    if result and result["articles_kept"]:
        events.publish("readings", added=result["articles_kept"])
        _background(recurring.refresh())  # de nouvelles lectures : les sujets récurrents bougent peut-être
    return {"synced": result is not None, **(result or {})}


_tasks: set = set()


def _background(coro) -> None:
    """Lance une tâche sans l'attendre, en gardant une référence (sinon elle peut être perdue)."""
    import asyncio

    task = asyncio.get_running_loop().create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


@router.get("/readings/recurring")
async def readings_recurring(force: bool = False):
    """Les sujets qui reviennent dans les lectures (algorithme), nommés par Haiku."""
    from ..agents import recurring

    return await (recurring.refresh() if force else recurring.latest())


@router.get("/readings")
def list_readings(status: str | None = None, domain: str | None = None, q: str | None = None, device: str | None = None, days: int | None = None, ids: str | None = None, offset: int = 0, limit: int = 100):
    from ..agents.readings import hidden_domains
    from ..collect.rss import fold
    from ..models import Reading

    hidden = hidden_domains()
    with session() as s:
        query = select(Reading, Article).join(Article, Article.id == Reading.article_id)
        query = query.where(Reading.status == status) if status else query.where(Reading.status != "ignore")
        if domain:
            query = query.where(Article.domain == domain)
        if device == "telephone":
            query = query.where(Reading.device.in_(["telephone", "les_deux", "compte_google"]))
        elif device == "ordinateur":
            query = query.where(Reading.device.in_(["ordinateur", "les_deux"]))
        if days:
            query = query.where(Reading.last_visit >= now() - timedelta(days=days))
        if ids:  # les lectures d'un sujet récurrent
            query = query.where(Reading.id.in_([int(i) for i in ids.split(",") if i.strip().isdigit()]))
        rows = [(r, a) for r, a in s.exec(query.order_by(Reading.last_visit.desc())).all() if a.domain not in hidden or domain]
    if q:
        words = fold(q).split()
        rows = [(r, a) for r, a in rows if all(w in fold(a.title) for w in words)]
    counts = {"nouveau": 0, "suivi": 0, "ignore": 0}
    out = []
    for r, a in rows[offset : offset + limit]:
        src = registry.lookup(a.domain)
        fc = r.factcheck or {}
        summary = None
        if fc.get("status") == "ok":
            from collections import Counter

            summary = dict(Counter(c["status"] for c in fc.get("claims", [])))
        out.append({**r.model_dump(), "title": a.title, "url": a.url, "domain": a.domain, "media": src.name, "owner": src.owner, "owner_type": src.owner_type or "inconnu", "controller": src.controller, "kind": src.kind, "priority": bool(src.priority), "factcheck_summary": summary})
    with session() as s:
        for st in counts:
            counts[st] = len([1 for r, a in s.exec(select(Reading, Article).join(Article, Article.id == Reading.article_id).where(Reading.status == st)).all() if a.domain not in hidden])
    return {"total": len(rows), "items": out, "counts": counts}


class ReadingPatch(BaseModel):
    status: str | None = None
    topic_id: int | None = None


@router.patch("/readings/{reading_id}")
def patch_reading(reading_id: int, body: ReadingPatch):
    from ..agents.readings import touch

    return touch(reading_id, **body.model_dump(exclude_unset=True))


class ReadingAssign(BaseModel):
    ids: list[int]
    topic_id: int


@router.post("/readings/assign")
def assign_readings(body: ReadingAssign):
    """Range des lectures dans un sujet : elles seront reprises et triées au prochain passage."""
    from ..agents.readings import touch
    from ..models import Reading

    _get(Topic, body.topic_id)
    with session() as s:
        for rid in body.ids:
            r = s.get(Reading, rid)
            if not r:
                continue
            a = s.get(Article, r.article_id)
            s.add(DroppedLink(url=a.url, title=a.title, domain=a.domain, article_id=a.id, topic_id=body.topic_id, suggestion={"action": "add_to_topic", "topic_id": body.topic_id}))
        s.commit()
    for rid in body.ids:
        touch(rid, status="suivi", topic_id=body.topic_id)
    return {"ok": True, "count": len(body.ids)}


@router.post("/readings/{reading_id}/factcheck")
async def factcheck(reading_id: int):
    from ..agents.factcheck import factcheck_reading
    from ..models import Reading

    _get(Reading, reading_id)
    return await factcheck_reading(reading_id)


class MediaHide(BaseModel):
    domain: str
    hidden: bool = True
    delete: bool = False


@router.post("/readings/hide-media")
def hide_media(body: MediaHide):
    """Masque un média de « Mes lectures » (et des imports suivants) ; peut aussi effacer ses lectures."""
    from ..agents.readings import set_hidden

    return {"removed": set_hidden(body.domain, body.hidden, body.delete)}


@router.post("/history/takeout")
async def history_takeout(request: Request):
    """Reçoit l'export Google Takeout (zip ou json) envoyé tel quel par l'interface, l'analyse
    localement puis l'efface."""
    import asyncio
    import tempfile

    from ..agents.readings import import_takeout

    name = request.headers.get("x-filename", "takeout.zip")
    suffix = ".zip" if name.lower().endswith(".zip") else ".json"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        async for chunk in request.stream():
            f.write(chunk)
        tmp = f.name
    try:
        return await asyncio.to_thread(import_takeout, tmp)
    except Exception as e:
        raise HTTPException(400, f"Export illisible : {e}") from e
    finally:
        os.unlink(tmp)


@router.get("/readings/diet")
def readings_diet():
    from ..agents.readings import diet

    return diet()


@router.delete("/readings")
def delete_readings():
    from ..agents.readings import clear_all

    return {"deleted": clear_all()}


# ── Brouillons ───────────────────────────────────────────────────────────────


class DraftIn(BaseModel):
    data: dict


def _draft_title(data: dict) -> str:
    text = " ".join(str(data.get("subject") or data.get("name") or "").split())
    return text[:80] or "Sujet sans titre"


@router.get("/drafts")
def list_drafts():
    with session() as s:
        return s.exec(select(Draft).order_by(Draft.updated_at.desc())).all()


@router.post("/drafts")
def create_draft(body: DraftIn):
    with session() as s:
        d = Draft(title=_draft_title(body.data), data=body.data)
        s.add(d)
        s.commit()
        s.refresh(d)
    return d


@router.put("/drafts/{draft_id}")
def save_draft(draft_id: int, body: DraftIn):
    """Enregistre le brouillon ; le recrée s'il a disparu entre-temps (autre fenêtre, suppression)."""
    with session() as s:
        d = s.get(Draft, draft_id) or Draft(id=draft_id)
        d.title, d.data, d.updated_at = _draft_title(body.data), body.data, now()
        s.add(d)
        s.commit()
        s.refresh(d)
    return d


@router.delete("/drafts/{draft_id}")
def delete_draft(draft_id: int):
    with session() as s:
        if d := s.get(Draft, draft_id):
            s.delete(d)
            s.commit()
    return {"ok": True}


# ── Liens glissés ────────────────────────────────────────────────────────────


class DropIn(BaseModel):
    url: str


@router.post("/drop")
async def drop(body: DropIn):
    url = body.url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Ce n'est pas un lien web.")
    from ..config import require_consent

    require_consent()
    return (await intake(url)).model_dump()


class DropConfirm(BaseModel):
    action: str  # add_to_topic | new_topic
    topic_id: int | None = None
    name: str | None = None
    prompt: str | None = None


@router.post("/drop/{drop_id}/confirm")
async def confirm_drop(drop_id: int, body: DropConfirm, background: BackgroundTasks):
    d = _get(DroppedLink, drop_id)
    if body.action == "add_to_topic" and body.topic_id:
        with session() as s:
            row = s.get(DroppedLink, drop_id)
            row.topic_id = body.topic_id  # repris et trié au prochain passage du sujet
            s.add(row)
            s.commit()
        return {"ok": True, "topic_id": body.topic_id}
    topic = await create_topic(TopicIn(prompt=body.prompt or d.suggestion.get("prompt_draft") or d.title, name=body.name), background)
    with session() as s:
        row = s.get(DroppedLink, drop_id)
        row.topic_id = topic["id"]
        s.add(row)
        s.commit()
    return {"ok": True, "topic_id": topic["id"]}


# ── Enregistrements ──────────────────────────────────────────────────────────


class PageIn(BaseModel):
    url: str
    title: str = ""


def _web_url(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Ce n'est pas un lien web.")
    return url


@router.post("/page/check")
def page_check(body: PageIn):
    """La languette demande si la page ouverte dans le navigateur est un article."""
    from ..agents import recordings

    return recordings.check_page(_web_url(body.url), body.title)


@router.post("/page/quickcheck")
async def page_quickcheck(body: PageIn, force: bool = False):
    """« Vérifier » : recoupement rapide et bon marché (Haiku seul), gardé 12 heures."""
    from ..agents import recordings
    from ..agents.quickcheck import quick_check

    article = recordings.ensure_article(_web_url(body.url), body.title)
    return await quick_check(article.id, force=force)


@router.get("/recordings")
def list_recordings():
    from ..agents import recordings

    return recordings.listing()


@router.post("/recordings")
def create_recording(body: PageIn, background: BackgroundTasks):
    from ..agents import recordings

    rec = recordings.save(_web_url(body.url), body.title)
    if consented():  # la page est téléchargée sur Internet : seulement après l'accord
        background.add_task(recordings.fill_text, rec.id)
    return recordings.get(rec.id)


@router.delete("/recordings/{recording_id}")
def delete_recording(recording_id: int):
    from ..agents import recordings

    recordings.delete(recording_id)
    return {"ok": True}


@router.post("/recordings/{recording_id}/gather")
def gather_recording(recording_id: int, background: BackgroundTasks):
    """Rassemble d'autres sources en tâche de fond (une à trois minutes) ; l'interface suit par SSE."""
    from ..agents import recordings
    from ..models import Recording

    _get(Recording, recording_id)
    if not recordings.mark_gathering(recording_id):
        return {"started": False, "reason": "déjà en cours"}
    background.add_task(recordings.gather, recording_id)
    return {"started": True}


@router.post("/recordings/{recording_id}/quickcheck")
async def quickcheck_recording(recording_id: int, force: bool = False):
    from ..agents.quickcheck import quick_check
    from ..models import Recording

    rec = _get(Recording, recording_id)
    result = await quick_check(rec.article_id, force=force)
    events.publish("recording", id=recording_id)
    return result


class RecordingAssign(BaseModel):
    topic_id: int


@router.post("/recordings/{recording_id}/assign")
def assign_recording(recording_id: int, body: RecordingAssign):
    from ..agents import recordings
    from ..models import Recording

    _get(Recording, recording_id)
    _get(Topic, body.topic_id)
    recordings.follow(recording_id, body.topic_id)
    return recordings.get(recording_id)


# ── Découvrir, sources, coûts, événements ────────────────────────────────────


@router.get("/discover")
async def get_discover(force: bool = False):
    return await discover(force=force)


@router.get("/sources")
def list_sources():
    with session() as s:
        return s.exec(select(Source).order_by(Source.kind, Source.name)).all()


class SourcePatch(BaseModel):
    name: str | None = None
    kind: str | None = None
    country: str | None = None
    owner: str | None = None
    owner_type: str | None = None
    controller: str | None = None
    weight: float | None = None
    priority: bool | None = None
    blocked: bool | None = None
    quality: float | None = None  # note du lecteur, de 0 à 1 ; null rend la main au jeu ouvert ou à l'IA


@router.patch("/sources/{domain}")
def patch_source(domain: str, body: SourcePatch):
    with session() as s:
        src = s.get(Source, domain)
        if not src:
            raise HTTPException(404, "Introuvable")
        changes = body.model_dump(exclude_unset=True)
        if "quality" in changes:
            q = changes.pop("quality")
            if q is None:
                fallback = rated(src.domain)
                src.quality, src.quality_origin, src.quality_note = fallback, "lin2023" if fallback is not None else "", ""
            else:
                src.quality, src.quality_origin, src.quality_note = min(1.0, max(0.0, q)), "lecteur", ""
        for k, v in changes.items():
            setattr(src, k, v)
        s.add(src)
        s.commit()
        s.refresh(src)
    registry.invalidate()
    return src


STAGE_LABEL = {
    "spec": "Spécification", "triage": "Tri", "triage_research": "Tri", "search": "Recherche web", "verify": "Recoupement",
    "synth": "Rédaction", "synth_research": "Rédaction", "neutrality": "Relecture", "revise": "Correctifs", "director": "Brief",
    "audio": "Audio", "intake": "Lien glissé", "discover": "Découvrir", "factcheck_queries": "Vérification", "quickcheck_claims": "Vérification rapide", "quickcheck": "Vérification rapide", "recurring": "Sujets de tes lectures", "announcement_check": "Annonces",
    "qualify": "Qualification des sources", "freshness": "Fraîcheur",
}


def _run_view(run: Run, names: dict[int, str]) -> dict:
    stages: dict[str, dict] = {}
    for c in run.calls or []:
        label = STAGE_LABEL.get(c.get("task"), c.get("task") or "Autre")
        st = stages.setdefault(label, {"stage": label, "models": [], "calls": 0, "in": 0, "out": 0, "cost": 0.0, "unknown_price": False})
        st["calls"] += 1
        st["in"] += c.get("in") or 0
        st["out"] += c.get("out") or 0
        st["cost"] += c.get("cost") or 0.0
        st["unknown_price"] |= c.get("cost") is None
        if c.get("model") and c["model"] not in st["models"]:
            st["models"].append(c["model"])
    return {
        "id": run.id, "kind": run.kind, "topic": names.get(run.topic_id) if run.topic_id else None, "started_at": run.started_at,
        "cost_usd": run.cost_usd, "subscription_usd": run.subscription_usd, "real_usd": round(run.cost_usd - run.subscription_usd, 5),
        "stages": sorted(stages.values(), key=lambda x: -x["cost"]),
    }


WINDOW_DAYS = 84  # douze semaines : un multiple de 7, de 2, de 3, de 4 et de 6


@router.get("/costs")
def costs():
    """Ce que coûtent les passages : le mois, la projection, le détail par étape et par sujet.
    « Réel » : facturé sur une clé API. « Abonnement » : équivalent au tarif public de ce que
    Claude Code a consommé sur l'abonnement."""
    at = now()
    local = datetime.now().astimezone()
    settings = load_settings()
    with session() as s:
        runs = s.exec(select(Run).where(Run.started_at >= at - timedelta(days=30)).order_by(Run.id.desc())).all()
        all_topics = s.exec(select(Topic)).all()
    names = {t.id: t.name for t in all_topics}
    topics = [t for t in all_topics if t.status != "archived"]
    utc = lambda dt: dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt  # noqa: E731
    tokens = lambda r: r.input_tokens + r.output_tokens  # noqa: E731
    week = [r for r in runs if utc(r.started_at) >= at - timedelta(days=7)]

    # Les 30 derniers jours, jour par jour (heure locale), jours sans passage compris.
    days = {f"{local - timedelta(days=i):%Y-%m-%d}": {"topics": 0, "brief": 0, "other": 0} for i in range(29, -1, -1)}
    for r in runs:
        day = f"{utc(r.started_at).astimezone():%Y-%m-%d}"
        if day in days:
            days[day]["topics" if r.kind == "topic" else "brief" if r.kind == "director" else "other"] += tokens(r)

    # Ce que coûte un passage de chaque sujet, et ce que ça donne sur un mois à son rythme : on
    # compte ses créneaux sur les 12 semaines à venir (échéances comprises), ramenés à 30 jours.
    stats: dict[int, dict] = {}
    for r in runs:
        if r.kind == "topic" and r.topic_id and r.status == "done":
            st = stats.setdefault(r.topic_id, {"runs": 0, "tokens": 0, "cost": 0.0})
            st["runs"] += 1
            st["tokens"] += tokens(r)
            st["cost"] += r.cost_usd
    known = [st["tokens"] / st["runs"] for st in stats.values()]
    fallback = sum(known) / len(known) if known else 0
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=WINDOW_DAYS)
    general_slots = scheduler.slots_between(start, end, scheduler.general(settings))
    brief_slots = set(general_slots)
    # Le rythme général est un passage à lui seul : le brief y est rédigé même sans sujet à jour.
    rows, upcoming = [], [s for s in [scheduler.next_slot(local, scheduler.general(settings))] if s]
    for t in topics:
        st = stats.get(t.id)
        c = scheduler.cadence(t, settings)
        if t.status == "sleeping":
            per_month = 30 / 7
        else:
            slots = scheduler.slots_between(start, end, c)
            brief_slots |= set(slots)
            per_month = len(slots) * 30 / WINDOW_DAYS
        avg = st["tokens"] / st["runs"] if st else fallback
        when = scheduler.next_run(t, settings, local)
        if when:
            upcoming.append(when)
        rows.append({
            "topic_id": t.id, "name": t.name, "status": t.status, "runs_per_month": round(per_month, 1),
            "own_schedule": bool(t.run_weekdays or t.run_every_days or t.run_hours or t.run_hour), "follow_deadlines": t.follow_deadlines,
            "schedule": {"every": c.every, "weekdays": list(c.weekdays), "hours": list(c.hours)},
            "runs": st["runs"] if st else 0, "avg_tokens": round(avg), "avg_cost": round(st["cost"] / st["runs"], 4) if st else None,
            "monthly_tokens": round(avg * per_month), "estimated": st is None, "next_run": when.isoformat() if when else None,
        })
    briefs = [tokens(r) for r in runs if r.kind == "director" and r.status == "done"]
    # Le brief suit chaque créneau où au moins un sujet tourne, et ceux du rythme général :
    # les rythmes partagent la même ancre, leurs créneaux communs ne comptent qu'une fois.
    brief_per_month = len(brief_slots) * 30 / WINDOW_DAYS
    brief_avg = sum(briefs) / len(briefs) if briefs else 0
    other = sum(tokens(r) for r in runs if r.kind not in ("topic", "director"))
    # Au rythme réglé : suit aussitôt un changement de fréquence, contrairement à une moyenne passée.
    pace = sum(row["monthly_tokens"] for row in rows) + brief_avg * brief_per_month + other
    month_tok = scheduler.month_tokens()
    first_of_next = (local.replace(day=28) + timedelta(days=4)).replace(day=1).date()
    days_left = (first_of_next - local.date()).days - 1 + (24 - local.hour) / 24

    last_topic = next((r for r in runs if r.kind == "topic" and r.calls), None)
    last_brief = next((r for r in runs if r.kind == "director" and r.calls), None)
    month = scheduler.month_costs()
    return {
        "month": {
            "real": round(month["real"], 4), "subscription": round(month["subscription"], 4), "budget": settings.monthly_budget_usd,
            "tokens": month_tok, "cap": settings.monthly_token_cap,
            "end_estimate": round(month_tok["total"] + pace * days_left / 30),
        },
        "today": {"tokens": sum(days[f"{local:%Y-%m-%d}"].values())},
        "days": [{"day": d, **v} for d, v in days.items()],
        "projection": {
            "real": round(sum(r.cost_usd - r.subscription_usd for r in week) / 7 * 30, 4),
            "subscription": round(sum(r.subscription_usd for r in week) / 7 * 30, 4),
            "tokens": round(pace),
        },
        "general_runs_per_month": round(len(general_slots) * 30 / WINDOW_DAYS, 1),
        "topics": sorted(rows, key=lambda row: -row["monthly_tokens"]),
        "brief": {"runs": len(briefs), "avg_tokens": round(brief_avg), "per_month": round(brief_per_month, 1)},
        "other": {"tokens": other},
        "next_run": min(upcoming).isoformat() if upcoming else None,
        "last_topic_run": _run_view(last_topic, names) if last_topic else None,
        "last_brief": _run_view(last_brief, names) if last_brief else None,
    }


@router.get("/runs")
def list_runs(limit: int = 50):
    with session() as s:
        return s.exec(select(Run).order_by(Run.id.desc()).limit(limit)).all()


@router.get("/events")
async def stream_events():
    async def gen():
        yield {"event": "hello", "data": json.dumps({"ok": True})}
        async for e in events.subscribe():
            yield {"event": "message", "data": json.dumps(e, default=str, ensure_ascii=False)}

    return EventSourceResponse(gen(), ping=15)
