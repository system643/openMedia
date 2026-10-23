"""Que du neuf : chaque passage n'apporte que des nouvelles. Le programme, et non le modèle de
synthèse, décide de ce qui est nouveau.

    reprises (avant le tri) → faits connus (pour le recoupement) → classement de chaque fait
    → fiche : nouveautés rédigées, confirmations écrites par le code, reprises comptées

Un article en retard qui redit un fait connu n'en refait pas une nouveauté :
- le fait avait déjà beaucoup de sources (`SATURATION`) : il est seulement compté (« reprise ») ;
- sinon : sa source s'ajoute au fait (« appui »), ou le confirme (« confirmation ») ;
- il le contredit : c'est une « rectification », qui passe par la synthèse et les corrections.

Sans fait nouveau ni rectification, la fiche est reconduite par le code : ni synthèse, ni
relecture, ni révision, les étapes les plus coûteuses d'un passage."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from rapidfuzz import fuzz
from sqlmodel import select

from ..collect.dedupe import hamming
from ..collect.rss import fold
from ..db import session
from ..models import Article, Claim, Source, TopicArticle
from ..sources import registry
from .material import counts_as_source, independence_key, ref_id
from .recurring import STOP
from .schemas import Fact

SATURATION = 3  # médias indépendants au-delà desquels une reprise n'apprend plus rien
OPEN_DAYS = 14  # un fait à source unique reste ouvert au recoupement deux semaines
KNOWN_DAYS = 45  # un fait établi reste reconnu un mois et demi
MAX_OPEN = 25
MAX_KNOWN = 40
PER_CLAIM = 5  # faits établis proposés au recoupement pour chaque affirmation du jour
SIMILAR = 70  # affirmation du jour et fait connu qui en parlent peut-être (présélection)
ATTACH = 92  # même fait, au mot près ou presque : rattaché sans attendre le modèle
SAME_ITEM = 80  # élément de la fiche et fait connu (comme `freshness.SAME_FACT`)
REPRISE_DAYS = 30
SAME_TITLE = 92  # titre repris tel quel (plus strict que `same_title`, qui accepte un ajout)
SAME_TEXT = 6  # simhash : même texte (comme `dedupe.cluster`)
MAX_NEW_REFS = 6

NEWS = ("nouveau", "rectification")  # ce qui demande une rédaction
UPDATES = ("confirmation", "appui")  # ce que le code écrit lui-même

_WORD = re.compile(r"[\w.]+")
_NAME = re.compile(r"(?<=\S\s)[A-ZÀ-Ý][\w.-]{2,}")  # un mot à majuscule hors début de phrase : un nom


def _stem(word: str) -> str:
    """« écrites », « écrite », « écrits » → « ecrit » : pluriel et féminin, sans plus."""
    for end in ("s", "e"):
        if len(word) > 4 and word.endswith(end):
            word = word[: -len(end)]
    return word


def _words(text: str) -> set[str]:
    """Les mots qui désignent : noms propres (même courts, « Rust »), chiffres, termes de plus
    de quatre lettres."""
    out = {_stem(fold(n).strip(".")) for n in _NAME.findall(text)}
    for w in _WORD.findall(fold(text)):
        w = w.strip(".")
        if any(ch.isdigit() for ch in w) or (len(w) >= 5 and w not in STOP):
            out.add(_stem(w))
    return out


def _similar(a: str, b: str, wa: set[str] | None = None, wb: set[str] | None = None) -> float:
    score = fuzz.token_set_ratio(fold(a), fold(b))
    shared = (wa if wa is not None else _words(a)) & (wb if wb is not None else _words(b))
    numbers = [w for w in shared if any(ch.isdigit() for ch in w)]
    if len(shared) >= 2 or numbers:
        score = max(score, 75 + 5 * min(len(shared), 4))
    return score


# ── Les faits connus, pour le recoupement ────────────────────────────────────


def known_claims(topic_id: int, at: datetime, today: list[str]) -> tuple[list[Claim], dict[int, tuple[Article, Source]]]:
    """Les faits encore ouverts, puis les faits établis qui ressemblent à une affirmation du
    jour (sans IA). Un fait déjà confirmé que redit un article en retard est ainsi reconnu,
    au lieu de repasser pour une nouveauté."""
    with session() as s:
        opened = s.exec(
            select(Claim)
            .where(Claim.topic_id == topic_id, Claim.status.in_(["non_confirme", "conteste"]), Claim.last_seen >= at - timedelta(days=OPEN_DAYS))
            .order_by(Claim.last_seen.desc())
            .limit(MAX_OPEN)
        ).all()
        taken = {c.id for c in opened}
        settled = [c for c in s.exec(select(Claim).where(Claim.topic_id == topic_id, Claim.last_seen >= at - timedelta(days=KNOWN_DAYS)).order_by(Claim.last_seen.desc())).all() if c.id not in taken]
    chosen: dict[int, float] = {}
    if settled and today:
        words = {c.id: _words(c.text) for c in settled}
        for text in today:
            wt = _words(text)
            scored = sorted(((_similar(text, c.text, wt, words[c.id]), c.id) for c in settled), reverse=True)
            for score, cid in scored[:PER_CLAIM]:
                if score >= SIMILAR:
                    chosen[cid] = max(score, chosen.get(cid, 0))
    room = max(0, MAX_KNOWN - len(opened))
    picked = [c for c in settled if c.id in sorted(chosen, key=lambda i: -chosen[i])[:room]]
    claims = list(opened) + picked
    ids = {i for c in claims for i in c.article_ids}
    with session() as s:
        articles = s.exec(select(Article).where(Article.id.in_(ids))).all() if ids else []
    return claims, {a.id: (a, registry.lookup(a.domain)) for a in articles}


def attach(facts: list[Fact], known: list[Claim]) -> None:
    """Rattache d'office un fait qui redit presque mot pour mot un fait connu : le modèle a pu
    oublier son `claim_id`, et le fait perdrait alors ses sources d'hier."""
    taken = {f.claim_id for f in facts if f.claim_id is not None}
    for f in facts:
        if f.claim_id is not None:
            continue
        best = max(((fuzz.token_sort_ratio(fold(f.text), fold(c.text)), c.id) for c in known if c.id not in taken), default=(0, None))
        if best[0] >= ATTACH:
            f.claim_id = best[1]
            taken.add(best[1])


# ── Le classement ────────────────────────────────────────────────────────────


def _keys(ids, meta) -> set[str]:
    return {independence_key(*meta[i]) for i in ids if i in meta and counts_as_source(meta[i][1])}


def classify(facts: list[Fact], meta: dict[int, tuple[Article, Source]], known: list[Claim]) -> dict:
    """Remplit `novelty` de chaque fait ; rend les comptes du passage. `meta` : les articles du
    passage et ceux des faits connus."""
    by_id = {c.id: c for c in known}
    for f in facts:
        claim = by_id.get(f.claim_id)
        if claim is None:
            f.novelty = "deja_paru" if f.first_reported else "nouveau"
            continue
        old = set(claim.article_ids)
        old_keys = _keys(old, meta)
        added = [r for r in f.refs if ref_id(r) not in old and ref_id(r) in meta]
        fresh_keys = _keys([ref_id(r) for r in added], meta) - old_keys
        f.new_refs = [r for r in added if counts_as_source(meta[ref_id(r)][1]) and independence_key(*meta[ref_id(r)]) in fresh_keys][:MAX_NEW_REFS]
        before = f.known_status or claim.status
        disputed = ("conteste", "dementi")
        if f.status != before and (f.status in disputed or before in disputed):
            f.novelty = "rectification"
        elif f.status == "confirme" and before != "confirme":
            f.novelty = "confirmation"
        elif fresh_keys and len(old_keys) < SATURATION:
            f.novelty = "appui"
        else:
            f.novelty = "reprise"
            f.new_refs = added  # les articles du jour qui ne font que redire le fait
        f.new_media = list(dict.fromkeys(meta[ref_id(r)][1].name for r in f.new_refs))
    counts = {k: sum(1 for f in facts if f.novelty == k) for k in ("nouveau", "deja_paru", "rectification", "confirmation", "appui", "reprise")}
    return {"new": counts["nouveau"], "late": counts["deja_paru"], "rectifications": counts["rectification"], "confirmations": counts["confirmation"] + counts["appui"], "reprises": counts["reprise"]}


def has_news(facts: list[Fact]) -> bool:
    return any(f.novelty in NEWS for f in facts)


# ── Les reprises, avant le tri ───────────────────────────────────────────────


def split_reprises(topic_id: int, found: list[tuple[Article, Source, str]], at: datetime) -> tuple[list[tuple[Article, Source, str]], list[tuple[Article, Source, Article]]]:
    """Sépare les articles qui reprennent tel quel un article déjà retenu pour ce sujet (même
    texte, ou même titre) : ils n'apprennent rien et ne passent pas par le tri. Rend (à trier,
    [(reprise, source, article d'origine)])."""
    with session() as s:
        seen = s.exec(select(Article).join(TopicArticle, TopicArticle.article_id == Article.id).where(TopicArticle.topic_id == topic_id, TopicArticle.kept == True)).all()  # noqa: E712
    start = at - timedelta(days=REPRISE_DAYS)

    def recent(a: Article) -> bool:
        p = a.published_at
        return p is None or (p if p.tzinfo else p.replace(tzinfo=at.tzinfo)) >= start

    seen = [a for a in seen if recent(a)]
    if not seen:
        return found, []
    titles = [(a, fold(a.title)) for a in seen]
    keep, reprises = [], []
    for article, source, origin in found:
        if origin == "drop" or article.kind == "recherche":  # un lien glissé par le lecteur est toujours lu
            keep.append((article, source, origin))
            continue
        title = fold(article.title)
        original = next((a for a, t in titles if a.id != article.id and (hamming(article.simhash, a.simhash) <= SAME_TEXT or fuzz.ratio(title, t) >= SAME_TITLE)), None)
        if original is None:
            keep.append((article, source, origin))
        else:
            reprises.append((article, source, original))
    return keep, reprises


# ── La fiche ─────────────────────────────────────────────────────────────────


def updates(facts: list[Fact], meta: dict[int, tuple[Article, Source]], reprises: list[tuple[Article, Source, Article]]) -> dict:
    """Ce que le code écrit lui-même : les confirmations et les appuis, et les reprises comptées."""
    confirmations = [
        {"text": f.known_text or f.text, "before": f.known_status, "status": f.status, "kind": f.novelty, "refs_new": f.new_refs, "media_new": f.new_media}
        for f in facts
        if f.novelty in UPDATES
    ]
    # Un article compte comme reprise s'il ne porte, dans ce passage, que des faits déjà connus.
    useful = {ref_id(r) for f in facts if f.novelty not in ("reprise", *UPDATES) for r in f.refs} | {ref_id(r) for f in facts if f.novelty in UPDATES for r in f.new_refs}
    echoed = [ref_id(r) for f in facts if f.novelty == "reprise" for r in f.new_refs]
    ids = list(dict.fromkeys([i for i in echoed if i not in useful and i in meta] + [a.id for a, _, _ in reprises]))
    names = {i: meta[i][1].name for i in echoed if i in meta} | {a.id: s.name for a, s, _ in reprises}
    return {
        "confirmations": confirmations,
        "reprises": {"articles": len(ids), "media": list(dict.fromkeys(names[i] for i in ids if i in names))[:6]},
        "late": sum(1 for f in facts if f.novelty == "deja_paru"),
    }


def _matches(item: dict, fact: Fact) -> bool:
    text = item.get("text") or item.get("event") or ""
    if not text:
        return False
    return fuzz.token_set_ratio(fold(text), fold(fact.known_text or fact.text)) >= SAME_ITEM


def refresh_statuses(content: dict, facts: list[Fact]) -> int:
    """Les faits de la fiche que ce passage confirme ou appuie prennent leur nouveau statut et
    leurs nouvelles sources. Rend le nombre d'éléments mis à jour."""
    changed = 0
    for f in facts:
        if f.novelty not in UPDATES:
            continue
        for key in ("key_facts", "whats_new", "timeline"):
            for item in content.get(key, []):
                if not _matches(item, f):
                    continue
                if "status" in item and f.status == "confirme" and item["status"] in ("non_confirme", "confirme"):
                    item["status"] = "confirme"
                item["refs"] = list(dict.fromkeys([*item.get("refs", []), *f.new_refs]))
                changed += 1
    return changed


STALE_LEAD = re.compile(r"^\s*(nouveaut[ée]s?|nouveau|derni[èe]re minute|aujourd'hui|ce jour)\s*[:–-]\s*", re.I)
NEW_SECTION = re.compile(r"nouveau|quoi de neuf|derni[èe]res?|du jour|r[ée]cent", re.I)


def carry_forward(previous: dict, facts: list[Fact]) -> dict:
    """La fiche précédente reconduite sans rédaction : rien de neuf, statuts à jour."""
    content = {**previous, "whats_new": [], "changes": [], "corrections": [], "nothing_new": True, "importance": 0}
    content = {k: (v if not isinstance(v, list) else [dict(x) if isinstance(x, dict) else x for x in v]) for k, v in content.items()}
    # Ce qui annonçait la nouveauté de la veille ne la présente plus comme celle du jour.
    content["lede"] = STALE_LEAD.sub("", content.get("lede") or "")
    content["custom_sections"] = [s for s in content.get("custom_sections", []) if not NEW_SECTION.search(s.get("title", ""))]
    refresh_statuses(content, facts)
    return content


def for_synth(facts: list[Fact]) -> tuple[list[Fact], list[dict]]:
    """Ce que reçoit la synthèse : les faits nouveaux et déjà parus, puis les rectifications
    avec ce que la fiche en disait."""
    plain = [f for f in facts if f.novelty in ("nouveau", "deja_paru", None)]
    rectified = [{**f.model_dump(include={"text", "refs", "contradicted_by", "status", "due", "event_date"}), "texte_precedent": f.known_text, "statut_precedent": f.known_status} for f in facts if f.novelty == "rectification"]
    return plain, rectified


def synth_refs(facts: list[Fact]) -> set[int]:
    """Les articles qui portent ce que la synthèse doit rédiger."""
    return {ref_id(r) for f in facts if f.novelty in ("nouveau", "deja_paru", "rectification", None) for r in [*f.refs, *f.contradicted_by] if ref_id(r)}

