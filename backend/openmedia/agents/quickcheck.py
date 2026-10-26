"""Vérification rapide d'un article, à quelques dixièmes de centime : Haiku seul, deux appels
au plus, pas de recherche web payante. Haiku relève ce que l'article affirme, GDELT
trouve d'autres médias, le code n'envoie que les phrases utiles de chacun, Haiku dit quels
extraits disent la même chose, et la règle d'indépendance (déterministe) donne le statut."""

from __future__ import annotations

import asyncio

import math
import re
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from ..collect import news_search
from ..collect.dedupe import canonical_url
from ..collect.extract import fetch_teaser
from ..db import session
from ..models import Article, Source, Topic, now
from ..security import MASKED, clean, injection_signals
from ..sources import registry
from .factcheck import NOTHING, UNREADABLE, ensure_text
from .llm import LLM, RunMeter, get_llm
from .material import ref, ref_id
from .proof import build_proof
from .schemas import QuickClaims, QuickVerdicts
from .synth import _digits, missing_numbers, strip_refs

QUICK_MODEL = "claude-haiku-5-5"  # imposé : la vérification rapide doit rester bon marché
FRESH = timedelta(hours=12)  # un résultat plus récent est rendu tel quel, sans appel
MAX_CLAIMS = 3
MAX_SOURCES = 6  # un article par groupe de presse
LEDE = 1500  # caractères de l'article lus pour relever ses affirmations
EXCERPT = 500  # caractères gardés par autre média
FEW = "Pas assez d'autres médias trouvés sur ces faits : rien n'a pu être recoupé."
PAYWALL = "Article réservé aux abonnés : vérifié d'après son titre et son chapô."

_WORD = re.compile(r"[^\W\d_][\w'’-]{3,}")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+|\n+")
_NUMBER = re.compile(r"\d[\d\s .,]*\d|\d")
_STOP = {
    "dans", "pour", "avec", "sans", "sont", "être", "avoir", "cette", "leur", "leurs", "plus", "moins", "selon", "après", "avant", "entre", "dont", "elle", "elles", "ils", "nous", "vous", "mais", "comme", "aussi", "très", "tout", "tous", "toute", "toutes", "fait", "faire", "était", "sera", "ont", "été",
    "that", "this", "with", "from", "have", "were", "will", "their", "they", "said", "says", "about", "after", "before", "which", "would", "could", "been", "into", "than", "more", "most",
}


def _fresh(result: dict) -> bool:
    try:
        at = datetime.fromisoformat(result["checked_at"])
        return now() - (at if at.tzinfo else at.replace(tzinfo=timezone.utc)) < FRESH
    except (KeyError, TypeError, ValueError):
        return False


async def quick_check(article_id: int, llm: LLM | None = None, *, force: bool = False) -> dict:
    """Rend la vérification de l'article ; celle des 12 dernières heures sert telle quelle, et
    deux demandes simultanées (la languette et la fenêtre) n'en paient qu'une."""
    with session() as s:
        article = s.get(Article, article_id)
    if article.quickcheck.get("status") not in (None, "illisible") and not force and _fresh(article.quickcheck):
        return article.quickcheck
    running = _inflight.get(article_id)
    if running and not force:
        return await asyncio.shield(running)
    task = asyncio.ensure_future(_check_and_keep(article, llm))
    _inflight[article_id] = task
    try:
        return await asyncio.shield(task)
    finally:
        if _inflight.get(article_id) is task:
            _inflight.pop(article_id, None)


_inflight: dict[int, asyncio.Future] = {}


async def _check_and_keep(article: Article, llm: LLM | None) -> dict:
    from .topic_agent import log_run  # import local : évite un cycle

    article_id = article.id
    meter = RunMeter()
    try:
        result = await _check(article, llm or get_llm(), meter)
    except Exception as e:  # sans moteur IA, réseau coupé… : le lecteur voit pourquoi, rien n'est gardé
        log_run("quickcheck", meter, status="error", error=str(e))
        return {"status": "erreur", "message": str(e), "claims": [], "sources": [], "checked_at": now().isoformat()}
    log_run("quickcheck", meter)
    if result["status"] == "illisible":
        return result  # souvent passager (page protégée, réseau) : rien n'est gardé, rien n'a été payé
    result |= {"cost_usd": round(meter.cost_usd, 5), "tokens": meter.input_tokens + meter.output_tokens, "subscription": meter.subscription_usd > 0, "model": QUICK_MODEL}
    with session() as s:
        a = s.get(Article, article_id)
        a.quickcheck = result
        s.add(a)
        s.commit()
    return result


async def _check(article: Article, llm: LLM, meter: RunMeter) -> dict:
    article = await ensure_text(article)
    source = registry.lookup(article.domain)
    paywalled = not article.text
    if paywalled:
        # Réservé aux abonnés : on part de ce qui reste lisible (titre, chapô) ; les autres
        # médias retenus, eux, sont lisibles gratuitement.
        title, teaser = await fetch_teaser(article.url)
        title = title or article.title
        if len(_WORD.findall(title)) < 3 or title.strip() == article.url:
            return _result("illisible", UNREADABLE, [], {})
        body = f"<chapo>\n{clean(teaser) or '(chapô indisponible : seul le titre est lisible)'}\n</chapo>\n(Le reste de l'article est réservé aux abonnés.)"
    else:
        title, body = article.title, f"<debut_article>\n{clean(article.text[:LEDE])}\n</debut_article>"

    # 1. Ce que l'article affirme, d'après son titre et son début (ou son chapô)
    content = f"Titre : {clean(title)}\n\n{body}"
    found = await llm.parse(meter, model=QUICK_MODEL, task="quickcheck_claims", content=content, schema=QuickClaims, effort="low", max_tokens=600)
    claims = [c for c in (strip_refs(clean(c)) for c in found.claims) if c and not injection_signals(c)][:MAX_CLAIMS]
    if not claims:
        return _result("rien", NOTHING, [], {article.id: (article, source)}, paywalled)

    # 2. D'autres médias, par les index gratuits seulement
    others = await _others(article, source, {"fr": found.queries_fr[:2], "en": found.queries_en[:2]})
    meta = {article.id: (article, source), **{a.id: (a, s) for a, s in others}}
    if not others:
        return _result("ok", FEW, [_claim(c, article, [], [], "", "") for c in claims], meta, paywalled)

    # 3. Les phrases utiles de chaque média, puis le recoupement
    words = _keywords(claims)
    excerpts = {a.id: _excerpt(a.text, words) for a, _ in others}
    listing = "\n".join(f"{i}. {c}" for i, c in enumerate(claims, 1))
    blocks = "\n".join(_block(a, s, excerpts[a.id]) for a, s in others)
    verdicts = await llm.parse(meter, model=QUICK_MODEL, task="quickcheck", content=f"Affirmations :\n{listing}\n\n<extraits>\n{blocks}\n</extraits>", schema=QuickVerdicts, effort="low", max_tokens=800)
    by_claim = {v.claim: v for v in verdicts.verdicts}
    allowed = {ref(a.id) for a, _ in others}
    checked = []
    for i, text in enumerate(claims, 1):
        v = by_claim.get(i)
        supports = _refs(v.supports if v else [], allowed)
        against = [r for r in _refs(v.contradicts if v else [], allowed) if r not in supports]
        cited = " ".join(f"{meta[ref_id(r)][0].title} {excerpts[ref_id(r)]}" for r in supports)
        checked.append(_claim(text, article, supports, against, (v.note if v else ""), cited))
    return _result("ok", None if len({registry.owner_key(s) for _, s in others}) >= 2 else FEW, checked, meta, paywalled)


async def _others(article: Article, source: Source, queries: dict[str, list[str]]) -> list[tuple[Article, Source]]:
    """Au plus un article lisible par groupe de presse, hors du groupe de l'article vérifié."""
    from .topic_agent import gather_articles, select_candidates  # import local : évite un cycle

    queries = {lang: qs for lang, qs in queries.items() if qs}
    published = article.published_at or now()
    since = (published if published.tzinfo else published.replace(tzinfo=timezone.utc)) - timedelta(days=30)
    days = max(1, math.ceil((now() - since).total_seconds() / 86400))
    pseudo = Topic(id=0, name="vérification rapide", prompt="", languages=list(queries))
    owners, out = {registry.owner_key(source)}, []

    def keep(found, titles_only: bool = False) -> None:
        for a, s, _ in found:
            if len(out) == MAX_SOURCES or a.id == article.id or not (a.text or titles_only) or registry.owner_key(s) in owners:
                continue
            owners.add(registry.owner_key(s))
            out.append((a, s))

    chosen = select_candidates(await news_search.search(queries, days, per_lang=1, tries=1), since, limit=MAX_SOURCES * 2)
    titles = [(c.url, c.title, c.url, c.published_at) for c in chosen]
    keep(await gather_articles(pseudo, {}, since, now(), extra=chosen))
    # Une page illisible (paywall, blocage) : en dernier recours, son titre avec son éditeur.
    if len(out) < 2:
        keep(_title_articles(titles), titles_only=True)
    return out


def _title_articles(rows: list[tuple]) -> list[tuple[Article, Source, str]]:
    """Un titre trouvé dont la page n'a pas pu être lue : l'article est gardé sans texte, sous
    le domaine de son éditeur, et le modèle ne lit que son titre."""
    out = []
    with session() as s:
        for url, title, publisher, published in rows:
            domain = registry.registered_domain(publisher) if publisher else ""
            if not domain or registry.is_blocked(domain):
                continue
            a = s.exec(select(Article).where(Article.url == canonical_url(url))).first()
            if not a:
                a = Article(url=canonical_url(url), title=clean(title)[:500], domain=domain, published_at=published)
                s.add(a)
                s.commit()
                s.refresh(a)
            out.append(a)
    return [(a, registry.ensure(a.domain), "gdelt") for a in out]


def _keywords(claims: list[str]) -> tuple[set[str], set[str]]:
    words = {w.lower() for c in claims for w in _WORD.findall(c)} - _STOP
    numbers = {_digits(n) for c in claims for n in _NUMBER.findall(c) if len(_digits(n)) >= 2}
    return words, numbers


def _excerpt(text: str, keywords: tuple[set[str], set[str]], limit: int = EXCERPT) -> str:
    """Les phrases qui partagent le plus de mots et de chiffres avec les affirmations, dans
    l'ordre du texte : le modèle ne lit pas l'article entier."""
    words, numbers = keywords
    sentences = [s.strip() for s in _SENTENCE.split(text or "") if len(s.strip()) > 20]

    def score(s: str) -> int:
        return sum(w.lower() in words for w in _WORD.findall(s)) + 3 * sum(n in _digits(s) for n in numbers)

    ranked = sorted(range(len(sentences)), key=lambda i: -score(sentences[i]))
    chosen, size = [], 0
    for i in ranked:
        if score(sentences[i]) == 0 or size + len(sentences[i]) > limit and chosen:
            break
        chosen.append(i)
        size += len(sentences[i])
    picked = " ".join(sentences[i] for i in sorted(chosen))
    return (picked or (text or "")[:200])[:limit]


def _block(article: Article, source: Source, excerpt: str) -> str:
    title, text = clean(article.title), clean(excerpt) or "(titre seul : le texte n'a pas pu être lu)"
    suspect = ' suspect="oui"' if injection_signals(f"{title}\n{text}") else ""
    wire = f" · dépêche {clean(article.wire)}" if article.wire else ""
    return f'<extrait ref="{ref(article.id)}"{suspect}>\n{clean(source.name)} · groupe : {clean(source.owner) or "inconnu"}{wire}\nTitre : {title}\n{text}\n</extrait>'


def _refs(values: list[str], allowed: set[str]) -> list[str]:
    """Références connues seulement, sans doublon : une référence inventée est écartée."""
    out = [ref(i) for i in (ref_id(v) for v in values) if i is not None]
    return [r for r in dict.fromkeys(out) if r in allowed]


def _claim(text: str, article: Article, supports: list[str], against: list[str], note: str, cited: str) -> dict:
    """Le statut vient de la règle d'indépendance, pas du modèle. L'article vérifié compte
    pour une source ; un chiffre absent des extraits qui le confirment ne l'est pas."""
    refs = [ref(article.id), *supports]
    proof = build_proof(0, refs, against, readable={article.id})  # ses affirmations viennent de lui
    status = "conteste" if proof["contradicting"] else "confirme" if proof["confirms"] else "non_confirme"
    item = {"text": text, "status": status, "refs": refs, "contradicted_by": against, "explanation": proof["explanation"], "independent": proof["independent"], "note": MASKED if injection_signals(note) else clean(note)}
    if status == "confirme" and missing_numbers(text, cited):
        item |= {"status": "non_confirme", "check": "chiffre_non_retrouve", "explanation": "Le chiffre de l'article n'est pas retrouvé dans les autres médias : à confirmer."}
    return item


def _result(status: str, message: str | None, claims: list[dict], meta: dict[int, tuple[Article, Source]], paywalled: bool = False) -> dict:
    """`reads` : les autres médias à lire, ceux dont le texte a pu être lu (donc sans
    abonnement) en tête ; `open` est faux quand seul leur titre est connu."""
    sources = [{"ref": ref(a.id), "id": a.id, "title": a.title, "url": a.url, "domain": a.domain, "name": s.name, "published_at": a.published_at.isoformat() if a.published_at else None, "country": s.country, "kind": s.kind, "owner_type": s.owner_type or "inconnu"} for a, s in meta.values()]
    reads = sorted(({"name": s.name, "title": a.title, "url": a.url, "open": bool(a.text)} for i, (a, s) in enumerate(meta.values()) if i), key=lambda r: not r["open"])
    if paywalled and status == "ok":
        free = " D'autres médias le traitent en accès libre (ci-dessous)." if any(r["open"] for r in reads) else ""
        message = f"{PAYWALL}{free} {message}" if message else PAYWALL + free
    return {"status": status, "message": message, "claims": claims, "sources": sources, "others": max(0, len(meta) - 1), "paywalled": paywalled, "reads": reads, "checked_at": now().isoformat()}
