"""« Mes lectures » : les articles d'actualité retrouvés dans l'historique des navigateurs,
et ce qu'ils disent des habitudes du lecteur (médias lus souvent, concentration)."""

from __future__ import annotations

import math
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from ..collect import history
from ..collect.dedupe import canonical_url
from ..db import session
from ..models import Article, Reading, Source
from ..sources import registry

SUGGEST_MIN_READS = 5  # un média lu au moins 5 fois mérite d'être proposé comme prioritaire
FIRST_SYNC_DAYS = 90  # sans import préalable, la première mise à jour remonte trois mois
_sync_lock = threading.Lock()  # un import à la fois : manuel et automatique ne se croisent pas


def sync_history(max_age_minutes: float = 0) -> dict | None:
    """Mise à jour automatique : relit les nouvelles visites depuis la précédente mise à jour,
    dans les navigateurs cochés par le lecteur, et eux seuls. Rien si elle est désactivée,
    si aucun navigateur n'est coché, déjà en cours, ou faite il y a moins de `max_age_minutes`."""
    from ..config import load_settings, update_settings

    settings = load_settings()
    if not settings.history_auto or not settings.history_sources or not _sync_lock.acquire(blocking=False):
        return None
    try:
        now = datetime.now(timezone.utc)
        last = datetime.fromisoformat(settings.history_synced_at) if settings.history_synced_at else None
        if last and (now - last).total_seconds() < max_age_minutes * 60:
            return None
        choices = settings.history_sources
        # Une journée de recouvrement : une visite d'hier soir peut arriver tard par la synchronisation.
        days = FIRST_SYNC_DAYS if last is None else max(1, math.ceil((now - last).total_seconds() / 86400) + 1)
        result = _import(choices, days, unchanged_since=last)
        update_settings({"history_synced_at": now.isoformat()})
        return result
    finally:
        _sync_lock.release()


def import_history(choices: list[dict], days: int, remember: bool = True) -> dict:
    """Import demandé par le lecteur : ses choix servent ensuite à la mise à jour automatique
    (`remember`)."""
    from ..config import update_settings

    with _sync_lock:
        result = _import(choices, days)
        update_settings({"history_sources": choices, "history_synced_at": datetime.now(timezone.utc).isoformat()} if remember else {"history_synced_at": datetime.now(timezone.utc).isoformat()})
    return result


def _import(choices: list[dict], days: int, unchanged_since: datetime | None = None) -> dict:
    """`choices` : [{browser, profile}] ou [{path}]. Ne garde que les articles d'actualité.
    `unchanged_since` : un historique que le navigateur n'a pas modifié depuis n'est pas relu."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    wanted = {(c["browser"], c["profile"]) for c in choices if c.get("browser") and not c.get("path")}
    profiles = [p for p in history.detect() if (p.browser, p.profile) in wanted]
    errors = [f"{b} ({p}) introuvable : navigateur désinstallé ou profil supprimé." for b, p in sorted(wanted - {(x.browser, x.profile) for x in profiles})]
    for c in choices:
        if c.get("path"):  # fichier d'historique indiqué à la main
            try:
                profiles.append(history.profile_from_file(c["path"]))
            except (OSError, ValueError) as e:
                errors.append(str(e))
    with session() as s:
        sources = s.exec(select(Source)).all()
    known = {src.domain: src.kind for src in sources}
    hidden = {src.domain for src in sources if src.hide_readings}
    from ..config import load_settings

    skip_phone = load_settings().history_skip_phone
    if unchanged_since:
        profiles = [p for p in profiles if not p.path.exists() or datetime.fromtimestamp(p.path.stat().st_mtime, tz=timezone.utc) >= unchanged_since - timedelta(minutes=1)]
    prune()
    seen = kept = 0
    for p in profiles:
        try:
            visits = history.read_visits(p, since)
        except Exception as e:  # base illisible ou format inattendu : on continue avec les autres
            errors.append(f"{p.browser_name} ({p.label}) : {e}")
            continue
        if skip_phone:  # seulement les visites faites sur ce PC
            visits = [v for v in visits if v.synced < v.visits]
        seen += len(visits)
        for v in visits:
            if not history.is_news(v.url, v.title, known) or registry.registered_domain(v.url) in hidden:
                continue
            kept += _store(v, p.browser_name, p.label)
    with session() as s:
        total = len(s.exec(select(Reading.id)).all())
    registry.invalidate()
    return {"profiles": len(profiles), "pages_seen": seen, "articles_kept": kept, "readings_total": total, "errors": errors}


def _device(v: history.Visit) -> str:
    if not v.synced:
        return "ordinateur"
    return "telephone" if v.synced >= v.visits else "les_deux"


def _store(v: history.Visit, browser: str, profile: str, device: str | None = None) -> int:
    url = canonical_url(v.url)
    with session() as s:
        article = s.exec(select(Article).where(Article.url == url)).first()
        if not article:
            article = Article(url=url, title=(v.title or url)[:500], domain=registry.registered_domain(url), published_at=None)
            s.add(article)
            s.commit()
            s.refresh(article)
        reading = s.exec(select(Reading).where(Reading.article_id == article.id)).first()
        if reading:
            reading.visits = max(reading.visits, v.visits)
            reading.last_visit = max(filter(None, [reading.last_visit, v.last_visit]))
            reading.first_visit = min(filter(None, [reading.first_visit, v.first_visit]))
            dev = device or _device(v)
            if reading.device != dev:
                reading.device = "les_deux" if {reading.device, dev} >= {"ordinateur", "telephone"} else (reading.device if reading.device != "ordinateur" else dev)
            new = 0
        else:
            reading = Reading(article_id=article.id, browser=browser, profile=profile, first_visit=v.first_visit, last_visit=v.last_visit, visits=v.visits, device=device or _device(v))
            new = 1
        s.add(reading)
        s.commit()
    if new:
        registry.ensure(registry.registered_domain(url))
    return new


def import_takeout(path: str) -> dict:
    """Export Google Takeout (Chrome et « Mon activité ») : l'historique du téléphone et des autres
    appareils du compte, même sans Chrome sur ce PC."""
    from ..collect import takeout

    visits = takeout.read(path)
    prune()
    with session() as s:
        sources = s.exec(select(Source)).all()
    known = {src.domain: src.kind for src in sources}
    hidden = {src.domain for src in sources if src.hide_readings}
    kept = sum(_store(v, "Compte Google", "Takeout", device="compte_google") for v in visits if history.is_news(v.url, v.title, known) and registry.registered_domain(v.url) not in hidden)
    with session() as s:
        total = len(s.exec(select(Reading.id)).all())
    return {"profiles": 1, "pages_seen": len(visits), "articles_kept": kept, "readings_total": total, "errors": []}


def prune() -> int:
    """Repasse le filtre « actualité » sur les lectures déjà enregistrées : quand le filtre se
    resserre (streaming, jeux…), les pages importées avant ne doivent pas rester dans la liste."""
    with session() as s:
        known = {src.domain: src.kind for src in s.exec(select(Source)).all()}
        removed = 0
        for r, a in s.exec(select(Reading, Article).join(Article, Article.id == Reading.article_id)).all():
            if r.status == "nouveau" and not history.is_news(a.url, a.title or "", known):
                s.delete(r)
                removed += 1
        s.commit()
    return removed


def hidden_domains() -> set[str]:
    with session() as s:
        return {src.domain for src in s.exec(select(Source).where(Source.hide_readings == True)).all()}  # noqa: E712


def set_hidden(domain: str, value: bool, delete: bool = False) -> int:
    """Masque (ou réaffiche) un média dans « Mes lectures » ; `delete` efface aussi ses lectures."""
    registry.ensure(domain)
    with session() as s:
        src = s.get(Source, domain)
        src.hide_readings = value
        s.add(src)
        removed = 0
        if delete:
            for r, a in s.exec(select(Reading, Article).join(Article, Article.id == Reading.article_id).where(Article.domain == domain)).all():
                s.delete(r)
                removed += 1
        s.commit()
    registry.invalidate()
    return removed


def diet() -> dict:
    """Les médias les plus lus, leur propriétaire, et des suggestions de sources prioritaires."""
    hidden = hidden_domains()
    with session() as s:
        rows = [(r, a) for r, a in s.exec(select(Reading, Article).join(Article, Article.id == Reading.article_id).where(Reading.status != "ignore")).all() if a.domain not in hidden]
    by_domain = Counter()
    for r, a in rows:
        by_domain[a.domain] += 1
    total = sum(by_domain.values())
    media = []
    owners = Counter()
    for domain, n in by_domain.most_common():
        src = registry.lookup(domain)
        owners[src.owner or src.domain] += n
        media.append({"domain": src.domain, "name": src.name, "reads": n, "share": round(n / total, 3) if total else 0, "owner": src.owner, "owner_type": src.owner_type or "inconnu", "controller": src.controller, "kind": src.kind, "priority": bool(src.priority)})
    suggestions = [m for m in media if m["reads"] >= SUGGEST_MIN_READS and not m["priority"] and m["kind"] != "unknown"]
    unqualified = [m for m in media if m["reads"] >= SUGGEST_MIN_READS and m["kind"] == "unknown"]
    alerts = []
    if total >= 10:
        top2 = owners.most_common(2)
        share = sum(n for _, n in top2) / total
        if share >= 0.6:
            alerts.append(f"{round(100 * share)} % de tes lectures viennent de {len(top2)} groupe(s) : {', '.join(o for o, _ in top2)}.")
        rich = sum(m["reads"] for m in media if m["owner_type"] == "milliardaire")
        if rich / total >= 0.5:
            names = sorted({m["controller"] for m in media if m["owner_type"] == "milliardaire" and m["controller"]})
            alerts.append(f"{round(100 * rich / total)} % de tes lectures viennent de médias contrôlés par de grandes fortunes" + (f" ({', '.join(names[:4])})." if names else "."))
    devices = Counter(r.device for r, _ in rows)
    return {"total": total, "media": media[:40], "suggestions": suggestions[:8], "unqualified": unqualified[:8], "alerts": alerts, "hidden": sorted(hidden), "devices": dict(devices)}


def set_priority(domain: str, value: bool) -> None:
    with session() as s:
        src = s.get(Source, domain)
        if src:
            src.priority = value
            s.add(src)
            s.commit()
    registry.invalidate()


def clear_all() -> int:
    """Efface les lectures, les articles qu'elles avaient fait entrer en base (ceux qu'aucun
    sujet, enregistrement ni lien glissé n'utilise) et les sujets calculés à partir d'elles."""
    from ..config import data_dir
    from ..models import DroppedLink, Recording, TopicArticle

    with session() as s:
        rows = s.exec(select(Reading)).all()
        ids = {r.article_id for r in rows}
        used = set(s.exec(select(TopicArticle.article_id).where(TopicArticle.article_id.in_(ids))).all()) if ids else set()
        used |= set(s.exec(select(Recording.article_id).where(Recording.article_id.in_(ids))).all()) if ids else set()
        used |= set(s.exec(select(DroppedLink.article_id).where(DroppedLink.article_id.in_(ids))).all()) if ids else set()
        for r in rows:
            s.delete(r)
        s.flush()
        for article_id in ids - used:
            article = s.get(Article, article_id)
            if article:
                s.delete(article)
        s.commit()
    (data_dir() / "recurring.json").unlink(missing_ok=True)
    return len(rows)


def touch(reading_id: int, **fields) -> Reading:
    with session() as s:
        r = s.get(Reading, reading_id)
        for k, v in fields.items():
            setattr(r, k, v)
        s.add(r)
        s.commit()
        s.refresh(r)
    return r

