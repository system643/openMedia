"""Recoupement : le modèle regroupe les affirmations, puis une règle déterministe vérifie
qu'un fait « confirmé » repose bien sur deux sources indépendantes.

Les faits connus des passages précédents (`tracked` : encore ouverts, ou établis et proches
d'une affirmation du jour, voir `novelty.known_claims`) sont fournis au modèle : une
affirmation du jour qui en rejoint un ajoute sa source à celles d'hier. Le fait peut enfin
être confirmé au lieu de rester « une seule source », et un fait établi redit par un article
en retard est reconnu au lieu de repasser pour une nouveauté."""

from __future__ import annotations

from ..models import Article, Claim, Source
from .llm import LLM, RunMeter
from .novelty import attach
from .material import as_json, confirms, ref, ref_id, reliability
from .schemas import Fact, TriageItem, VerifyResult


def enforce_independence(facts: list[Fact], meta: dict[int, tuple[Article, Source]]) -> list[Fact]:
    out = []
    for f in facts:
        f.refs = [r for r in f.refs if ref_id(r) in meta]
        f.contradicted_by = [r for r in f.contradicted_by if ref_id(r) in meta]
        if not f.refs:
            continue
        enough = confirms([meta[ref_id(r)] for r in f.refs])
        if f.status == "confirme" and not enough:
            f.status = "non_confirme"
        # Un fait déjà suivi que rejoint une nouvelle source indépendante est confirmé.
        if f.claim_id is not None and f.status == "non_confirme" and enough and not f.contradicted_by:
            f.status = "confirme"
        # Un fait établi ne redescend pas faute de source du jour : seule une contradiction le change.
        if f.known_status in ("conteste", "dementi") and f.status in ("confirme", "non_confirme") and not f.contradicted_by:
            f.status = f.known_status
        if f.status in ("confirme", "non_confirme") and f.contradicted_by:
            f.status = "conteste"
        out.append(f)
    return out


def _merge_tracked(facts: list[Fact], tracked: list[Claim]) -> None:
    """Rattache chaque fait à son fait suivi : sources d'hier ajoutées, date de première
    apparition reprise. Un `claim_id` inconnu est ignoré."""
    by_id = {c.id: c for c in tracked}
    for f in facts:
        claim = by_id.get(f.claim_id)
        if claim is None:
            f.claim_id = None
            continue
        f.refs = list(dict.fromkeys([*f.refs, *(ref(i) for i in claim.article_ids)]))
        f.first_reported = f.first_reported or claim.first_reported
        f.known_text, f.known_status = claim.text, claim.status


def _date(article: Article) -> str | None:
    return article.published_at.strftime("%Y-%m-%d") if article.published_at else None


async def verify(llm: LLM, meter: RunMeter, model: str, verdicts: dict[int, TriageItem], meta: dict[int, tuple[Article, Source]], tracked: list[Claim] | None = None) -> list[Fact]:
    """`meta` doit aussi contenir les articles des faits suivis (`tracked`)."""
    tracked = [c for c in tracked or [] if any(i in meta for i in c.article_ids)]
    rows = []
    for article_id, item in verdicts.items():
        article, source = meta[article_id]
        for claim in item.claims:
            rows.append({"ref": ref(article_id), "media": source.name, "groupe": source.owner or source.domain, "fiabilite": reliability(source), "depeche": article.wire or None, "date_article": _date(article), "date_evenement": claim.event_date, "type": claim.kind, "echeance": claim.due, "affirmation": claim.text})
    if not rows:
        return []
    content = f"Affirmations extraites :\n{as_json(rows)}"
    if tracked:
        known = [{"id": c.id, "fait": c.text, "statut": c.status, "refs": [ref(i) for i in c.article_ids if i in meta], "medias": sorted({meta[i][1].name for i in c.article_ids if i in meta}), "connu_depuis": f"{c.first_seen:%Y-%m-%d}"} for c in tracked]
        content += f"\n\nFaits déjà suivis (passages précédents) :\n{as_json(known)}"
    result = await llm.parse(meter, model=model, task="verify", content=content, schema=VerifyResult, effort="low", max_tokens=12000)
    attach(result.facts, tracked)
    _merge_tracked(result.facts, tracked)
    return enforce_independence(result.facts, meta)
