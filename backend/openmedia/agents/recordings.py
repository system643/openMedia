"""« Enregistrements » : les articles mis de côté depuis la languette, sans les suivre. On
peut ensuite rassembler d'autres sources pour comprendre le sujet, le suivre ou l'oublier."""

from __future__ import annotations

from datetime import date

from sqlmodel import select

from .. import events
from ..collect import history
from ..collect.dedupe import canonical_url
from ..db import session
from ..models import Article, DroppedLink, Recording, now
from ..security import MASKED, clean, clean_deep, injection_signals
from ..sources import registry
from .factcheck import check_article, ensure_text
from .llm import LLM, RunMeter, get_llm
from .material import article_block, as_json, ref_id
from .schemas import Dossier
from .synth import enforce_statuses, missing_numbers, strip_refs


def _find(url: str) -> tuple[Article | None, Recording | None]:
    with session() as s:
        article = s.exec(select(Article).where(Article.url == canonical_url(url))).first()
        rec = s.exec(select(Recording).where(Recording.article_id == article.id)).first() if article else None
    return article, rec


def check_page(url: str, title: str) -> dict:
    """La page ouverte dans le navigateur est-elle un article de presse ? Sans réseau ni modèle."""
    src = registry.lookup(url)
    article, rec = _find(url)
    is_article = history.is_news(url, title, registry.kinds()) and not src.blocked
    return {"is_article": is_article, "media": src.name, "domain": src.domain, "recording_id": rec.id if rec else None, "status": rec.status if rec else None, "topic_id": rec.topic_id if rec else None, "quickcheck": (article.quickcheck or None) if article else None}


def ensure_article(url: str, title: str = "") -> Article:
    """L'article d'une page, créé s'il n'est pas encore en base (sans texte ni enregistrement)."""
    final = canonical_url(url)
    article, _ = _find(final)
    if article and article.title == article.url and clean(title):
        with session() as s:  # enregistrée sans titre : celui du navigateur sert à la vérifier
            row = s.get(Article, article.id)
            row.title = clean(title)[:500]
            s.add(row)
            s.commit()
            s.refresh(row)
            return row
    if article:
        return article
    with session() as s:
        article = Article(url=final, title=(clean(title) or final)[:500], domain=registry.registered_domain(final))
        s.add(article)
        s.commit()
        s.refresh(article)
    registry.ensure(article.domain)
    return article


def save(url: str, title: str = "") -> Recording:
    """Enregistre une page ; une page déjà enregistrée rend l'enregistrement existant."""
    final = canonical_url(url)
    article, rec = _find(final)
    if rec:
        return rec
    article = article or ensure_article(final, title)
    with session() as s:
        rec = Recording(article_id=article.id)
        s.add(rec)
        s.commit()
        s.refresh(rec)
    registry.ensure(article.domain)
    return rec


async def fill_text(recording_id: int) -> None:
    """Lit le texte de l'article enregistré (titre exact et date au passage)."""
    with session() as s:
        rec = s.get(Recording, recording_id)
        article = s.get(Article, rec.article_id) if rec else None
    if article and not article.text:
        await ensure_text(article)
        events.publish("recording", id=recording_id)


def listing() -> list[dict]:
    with session() as s:
        rows = s.exec(select(Recording, Article).join(Article, Article.id == Recording.article_id).order_by(Recording.created_at.desc())).all()
    return [out(r, a) for r, a in rows]


def out(rec: Recording, article: Article) -> dict:
    src = registry.lookup(article.domain)
    return {
        **rec.model_dump(),
        "title": article.title,
        "url": article.url,
        "domain": article.domain,
        "published_at": article.published_at,
        "readable": bool(article.text),
        "media": src.name,
        "owner": src.owner,
        "owner_type": src.owner_type or "inconnu",
        "controller": src.controller,
        "kind": src.kind,
        "quickcheck": article.quickcheck or None,
    }


def get(recording_id: int) -> dict | None:
    with session() as s:
        rec = s.get(Recording, recording_id)
        article = s.get(Article, rec.article_id) if rec else None
    return out(rec, article) if rec else None


def delete(recording_id: int) -> None:
    with session() as s:
        if rec := s.get(Recording, recording_id):
            s.delete(rec)
            s.commit()


def follow(recording_id: int, topic_id: int) -> None:
    """Range l'article dans un sujet : il sera repris et trié au prochain passage."""
    with session() as s:
        rec = s.get(Recording, recording_id)
        if not rec:
            return
        a = s.get(Article, rec.article_id)
        s.add(DroppedLink(url=a.url, title=a.title, domain=a.domain, article_id=a.id, topic_id=topic_id, suggestion={"action": "add_to_topic", "topic_id": topic_id}))
        rec.status, rec.topic_id = "suivi", topic_id
        s.add(rec)
        s.commit()


def forget_topic(topic_id: int) -> None:
    """Le sujet est supprimé : ses enregistrements redeviennent de simples enregistrements."""
    with session() as s:
        for rec in s.exec(select(Recording).where(Recording.topic_id == topic_id)).all():
            rec.status, rec.topic_id = "enregistre", None
            s.add(rec)
        s.commit()


def _set_dossier(recording_id: int, dossier: dict) -> None:
    with session() as s:
        rec = s.get(Recording, recording_id)
        if rec:
            rec.dossier = dossier
            s.add(rec)
            s.commit()
    events.publish("recording", id=recording_id)


def mark_gathering(recording_id: int) -> bool:
    """Marque le dossier « en cours » ; faux s'il l'était déjà."""
    with session() as s:
        rec = s.get(Recording, recording_id)
        if rec.dossier.get("status") == "en_cours":
            return False
    _set_dossier(recording_id, {**rec.dossier, "status": "en_cours", "started_at": now().isoformat()})
    return True


async def gather(recording_id: int, llm: LLM | None = None) -> dict:
    """Rassemble d'autres sources : la couverture par d'autres médias, les faits recoupés, puis
    une synthèse neutre de ce qu'il faut savoir pour décider de suivre le sujet ou non."""
    from ..config import load_settings
    from .topic_agent import log_run

    llm = llm or get_llm()
    meter = RunMeter()
    with session() as s:
        rec = s.get(Recording, recording_id)
    try:
        check, pairs = await check_article(rec.article_id, llm, meter, coverage_anyway=True)
        readable = [(a, src) for a, src in pairs if a.text]
        synthesis = None
        if readable:
            content = (
                f"Date du jour : {date.today().isoformat()}\n\n"
                f"<article_enregistre>\n{article_block(*pairs[0], 4000)}\n</article_enregistre>\n\n"
                f"<faits_recoupes>\n{as_json(check['claims'])}\n</faits_recoupes>\n\n"
                f"<autres_articles>\n{chr(10).join(article_block(a, src, 1500) for a, src in pairs[1:16])}\n</autres_articles>"
            )
            draft = await llm.parse(meter, model=load_settings().models.topic, task="dossier", content=content, schema=Dossier, effort="medium", max_tokens=8000)
            synthesis = validate(draft.model_dump(), {a.id: a.text for a, _ in readable})
            by_id = {a.id: (a, src) for a, src in pairs}
            enforce_statuses(synthesis, by_id.get)
        dossier = {"status": "ok", "check": check, "synthesis": synthesis, "cost_usd": round(meter.cost_usd, 4), "gathered_at": now().isoformat()}
        log_run("dossier", meter)
    except Exception as e:  # sans moteur IA, réseau coupé… : le lecteur voit pourquoi
        log_run("dossier", meter)
        dossier = {"status": "erreur", "message": str(e), "gathered_at": now().isoformat()}
    _set_dossier(recording_id, dossier)
    return dossier


def validate(content: dict, texts: dict[int, str]) -> dict:
    """Mêmes garde-fous que la fiche : références connues seulement, chiffres retrouvés dans les
    articles cités, passages qui s'adressent à une IA masqués."""
    content = clean_deep(content)
    for key in ("points", "context"):
        kept = []
        for item in content.get(key, []):
            item["refs"] = [r for r in item.get("refs", []) if ref_id(r) in texts]
            if not item["refs"]:
                continue  # un point sans source n'est pas gardé
            item["text"] = strip_refs(item["text"])
            if missing_numbers(item["text"], " ".join(texts[ref_id(r)] for r in item["refs"])):
                item["check"] = "chiffre_non_retrouve"
            if injection_signals(item["text"]):
                item["text"], item["check"] = MASKED, "contenu_suspect"
            kept.append(item)
        content[key] = kept
    for key in ("summary", "next_steps"):
        content[key] = MASKED if injection_signals(content.get(key)) else strip_refs(content.get(key) or "")
    content["open_questions"] = [strip_refs(q) for q in content.get("open_questions", []) if not injection_signals(q)]
    return content
