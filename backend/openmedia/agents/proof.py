"""La preuve d'un fait : quelles sources le portent, lesquelles sont vraiment indépendantes,
et pourquoi il a reçu son statut. Entièrement déterministe : aucune IA, tout est vérifiable."""

from __future__ import annotations

from collections import OrderedDict

from sqlmodel import select

from ..db import session
from ..models import Article, TopicArticle
from ..sources import registry
from ..sources import quality
from .material import SOCIAL, confirms, counts_as_source, independence_key, ref, ref_id, vetted

OWNER_LABEL = {
    "milliardaire": "grande fortune",
    "conglomerat": "groupe industriel ou financier",
    "public": "public",
    "independant": "indépendant",
    "cooperative": "coopérative, fondation ou association",
    "inconnu": "propriétaire non qualifié",
}


def _article_view(article: Article, link: TopicArticle | None) -> dict:
    src = registry.lookup(article.domain)
    return {
        "ref": ref(article.id),
        "title": article.title,
        "url": article.url,
        "media": src.name,
        "domain": src.domain,
        "kind": src.kind,
        "country": src.country,
        "owner": src.owner or src.domain,
        "owner_type": src.owner_type or "inconnu",
        "owner_type_label": OWNER_LABEL.get(src.owner_type or "inconnu", src.owner_type),
        "controller": src.controller,
        "wire": article.wire,
        "published_at": article.published_at,
        "nature": link.nature if link else "",
        "reason": link.reason if link else "",
        "claims": [c.get("text", "") for c in (link.claims if link else [])][:5],
        "counts": counts_as_source(src),
        "vetted": vetted(src),
        "quality": src.quality,
        "quality_label": quality.label(src.quality, src.quality_origin),
        "quality_origin": src.quality_origin,
        "quality_note": src.quality_note,
    }


def _group_label(key: str, members: list[dict]) -> str:
    if key.startswith("wire:"):
        return f"Dépêche {members[0]['wire']}"
    if members[0]["kind"] == SOCIAL:
        return "Réseau social (ne compte pas)"
    if key.startswith("faible:"):
        return "Source peu fiable (ne compte pas)"
    return members[0]["owner"]


def _counted(key: str) -> bool:
    return not key.startswith(("social:", "faible:"))


def _excluded_key(view: dict) -> str:
    return f"social:{view['domain']}" if view["kind"] == SOCIAL else f"faible:{view['domain']}"


def build_proof(topic_id: int, refs: list[str], against: list[str] | None = None, status: str | None = None, readable: set[int] | None = None) -> dict:
    """`readable` : des articles dont on sait ce qu'ils disent même sans texte en base (l'article
    vérifié, lu par son chapô)."""
    against = against or []
    ids = [i for i in (ref_id(r) for r in refs + against) if i]
    with session() as s:
        articles = {a.id: a for a in s.exec(select(Article).where(Article.id.in_(ids))).all()}
        links = {ta.article_id: ta for ta in s.exec(select(TopicArticle).where(TopicArticle.topic_id == topic_id, TopicArticle.article_id.in_(ids))).all()}

    supporting = [_article_view(articles[i], links.get(i)) for i in (ref_id(r) for r in refs) if i in articles]
    contradicting = [_article_view(articles[i], links.get(i)) for i in (ref_id(r) for r in against) if i in articles]

    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    for view in supporting:
        a = articles[ref_id(view["ref"])]
        key = independence_key(a, registry.lookup(a.domain)) if view["counts"] else _excluded_key(view)
        groups.setdefault(key, []).append(view)
    independent = sum(1 for k in groups if _counted(k))
    unreliable = sum(len(m) for k, m in groups.items() if k.startswith("faible:"))
    anchored = any(v["vetted"] for v in supporting)

    group_views = [{"label": _group_label(k, m), "counts": _counted(k), "media": [v["media"] for v in m]} for k, m in groups.items()]
    return {
        "independent": independent,
        "anchored": anchored,
        "confirms": confirms([(_readable(articles[ref_id(v["ref"])], readable), registry.lookup(articles[ref_id(v["ref"])].domain)) for v in supporting]),
        "articles": len(supporting),
        "groups": group_views,
        "supporting": supporting,
        "contradicting": contradicting,
        "explanation": explain(independent, len(supporting), group_views, len(contradicting), status, unreliable, anchored),
    }


def _readable(article: Article, readable: set[int] | None) -> Article:
    if article.text or article.id not in (readable or set()):
        return article
    return article.model_copy(update={"text": article.title})


def explain(independent: int, articles: int, groups: list[dict], contradictions: int, status: str | None, unreliable: int = 0, anchored: bool = True) -> str:
    """La règle appliquée, en clair."""
    repeats = [g for g in groups if g["counts"] and len(g["media"]) > 1]
    detail = ""
    if repeats:
        g = max(repeats, key=lambda g: len(g["media"]))
        detail = f" {len(g['media'])} articles ne comptent que pour une source ({g['label']} : {', '.join(g['media'])})."
    if unreliable:
        detail += f" {unreliable} article(s) de sources peu fiables ne comptent pas."
    if contradictions:
        return f"Contesté : {contradictions} source(s) affirment le contraire.{detail}"
    if status == "dementi":
        return f"Démenti par l'acteur concerné ou par une source primaire.{detail}"
    if independent >= 2 and not anchored:
        return f"Recoupé seulement par des sources peu connues ({independent}) : aucune n'a de fiabilité établie hors IA, ce fait reste à confirmer.{detail}"
    if independent >= 2:
        return f"Confirmé : {independent} sources indépendantes sur {articles} article(s).{detail}"
    if independent == 1:
        return f"Une seule source indépendante : ce fait reste à confirmer.{detail}"
    if unreliable:
        return f"Aucune source fiable : {unreliable} article(s) de sources peu fiables, qui ne confirment rien."
    return "Aucune source indépendante : seulement des signaux de réseaux sociaux."
