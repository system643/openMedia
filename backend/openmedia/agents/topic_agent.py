"""L'agent de sujet : un passage complet, de la collecte à la nouvelle version de la fiche.

    fenêtre → collecte (GDELT, unes des médias, RSS, liens glissés) → sélection diversifiée
    → extraction → qualification des sources inconnues → tri → [complément web_search]
    → reprises écartées → recoupement (avec les faits connus) → recherche active pour les
    faits à source unique → fraîcheur → nouveauté de chaque fait → synthèse (seulement s'il
    y a du neuf) → garde-fous → spectre des sources → version append-only → rythme
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from .. import events
from ..collect import bing_news, claude_search, fronts, gdelt, news_search, research, rss, social
from ..collect.base import Candidate
from ..collect.dedupe import canonical_url, cluster, detect_wire, same_title, simhash
from ..collect.extract import fetch_many
from ..config import Settings, load_settings
from ..db import session
from ..models import Article, Claim, DroppedLink, Fiche, Run, Source, Topic, TopicArticle, now
from ..security import clean
from ..sources import quality, registry
from . import rhythm
from .announcements import sync_from_fiche
from .corrections import save_corrections, validate_corrections
from .coverage import coverage
from .factcheck import find_corroboration
from .freshness import mark_stale, stale_index
from .llm import LLM, RunMeter, get_llm
from .material import independence_key, ref_id
from .novelty import carry_forward, classify, for_synth, has_news, known_claims, refresh_statuses, split_reprises, synth_refs, updates
from .qualify import qualify_sources
from .spec import build_spec
from .synth import cited_ids, enforce_statuses, neutrality_pass, synthesize, validate
from .triage import triage
from .verify import verify

FIRST_WINDOW_DAYS = 7
WIDE_WINDOW_DAYS = 30  # une fiche encore sans source cherche jusqu'à un mois en arrière
OVERLAP = timedelta(hours=6)
MAX_CANDIDATES = 60
CANDIDATES_PER_EXTRA_DAY = 15  # un sujet espacé ratisse une fenêtre plus longue
MAX_CANDIDATES_SPACED = 100
PER_SOURCE = 3
SLEEP_AFTER_QUIET_RUNS = 5
MAX_CORROBORATE = 4  # faits à source unique cherchés ailleurs à chaque passage
WEB_CORROBORATE = 2  # dont au plus deux par la recherche web du modèle
CORROBORATION_DAYS = 7
CORROBORATION_LINKS = 8  # par fait : autant de pages à télécharger et à lire


def window(topic: Topic, at: datetime, every: int = 1) -> datetime:
    """Début de la fenêtre de collecte : 7 jours au premier passage (moins si le sujet est
    plus récent), sinon depuis le dernier passage avec 6 h de recouvrement. Un sujet espacé
    (`every` jours, ou en veille) remonte jusqu'à son dernier passage : il ne perd rien."""
    if topic.last_run_at:
        last = topic.last_run_at if topic.last_run_at.tzinfo else topic.last_run_at.replace(tzinfo=timezone.utc)
        span = max(FIRST_WINDOW_DAYS, every + 1, 8 if topic.status == "sleeping" else 0)
        return max(last - OVERLAP, at - timedelta(days=span))
    since = at - timedelta(days=FIRST_WINDOW_DAYS)
    if topic.since:
        start = topic.since if topic.since.tzinfo else topic.since.replace(tzinfo=timezone.utc)
        since = max(since, start - timedelta(days=1))
    return since


def _selection_weight(src: Source | None) -> float:
    if src is None:
        return 0.0
    if src.priority:  # le choix du lecteur l'emporte sur la note
        return src.weight + 10.0
    if quality.is_low(src.quality):
        return 0.0
    if src.kind != "unknown":
        return src.weight
    return min(src.quality or 0.0, 0.99)  # derrière les médias du registre


def select_candidates(cands: list[Candidate], since: datetime, limit: int = MAX_CANDIDATES, per_source: int = PER_SOURCE) -> list[Candidate]:
    """Écarte doublons, hors-fenêtre et sources bloquées, puis alterne les médias pour que
    la sélection soit diverse plutôt que dominée par le média le plus prolifique."""
    kept: list[Candidate] = []
    urls: set[str] = set()
    for c in cands:
        if not c.url or not c.title:
            continue
        if c.published_at and c.published_at < since:
            continue
        publisher = c.extra.get("source_url") or c.url
        if publisher and registry.is_blocked(registry.registered_domain(publisher)):
            continue
        key = canonical_url(c.url)
        if key in urls or any(same_title(c.title, k.title) for k in kept):
            continue
        urls.add(key)
        kept.append(c)
    # Médias du registre d'abord (par poids), puis sites inconnus mais bien notés, enfin les
    # autres et les sources peu fiables ; au plus 3 par média.
    by_source: dict[str, list[Candidate]] = defaultdict(list)
    weight: dict[str, float] = {}
    for c in sorted(kept, key=lambda c: c.published_at or since, reverse=True):
        publisher = c.extra.get("source_url") or c.url
        src = registry.lookup(publisher) if publisher else None
        name = (src.domain if src else c.source_name).lower()
        weight[name] = _selection_weight(src)
        if len(by_source[name]) < per_source:
            by_source[name].append(c)
    out: list[Candidate] = []
    for tier in (lambda n: weight[n] > 0, lambda n: weight[n] <= 0):
        names = sorted((n for n in by_source if tier(n)), key=lambda n: -weight[n])
        while len(out) < limit and any(by_source[n] for n in names):
            for n in names:
                if by_source[n] and len(out) < limit:
                    out.append(by_source[n].pop(0))
    return out


async def collect(topic: Topic, spec: dict, since: datetime, at: datetime) -> list[Candidate]:
    days = max(1, math.ceil((at - since).total_seconds() / 86400))
    if topic.kind == "recherche":  # veille scientifique : articles de recherche, jugés sur leur résumé
        qs = spec.get("queries_en", [])[:3] + spec.get("queries_fr", [])[:1]
        return await research.collect(topic.research_fields or [], qs, spec.get("keywords", []), since)
    queries = {}
    if "fr" in topic.languages:
        queries["fr"] = spec.get("queries_fr", [])[:3]
    if "en" in topic.languages:
        queries["en"] = spec.get("queries_en", [])[:3]
    cands = await news_search.search(queries, days)
    cands += await fronts.collect(spec.get("keywords", []), since, list(queries))
    cands += await rss.collect(topic.feeds, spec.get("keywords", []), since)
    cands += await social.collect(topic.social or {}, queries.get("fr", []) + queries.get("en", []), spec.get("keywords", []), since)
    with session() as s:
        drops = s.exec(select(DroppedLink).where(DroppedLink.topic_id == topic.id, DroppedLink.created_at >= since)).all()
    cands += [Candidate(url=d.url, title=d.title or d.url, origin="drop", published_at=None) for d in drops]
    return cands


def _upsert_articles(pairs, since: datetime) -> list[tuple[Article, Source, str]]:
    """Enregistre les articles extraits ; rend (article, source, origine) dans la fenêtre."""
    out = []
    with session() as s:
        for cand, ex in pairs:
            if ex is None and cand.origin == "claude_search":
                continue
            url = canonical_url(ex.url if ex else cand.url)
            published = (ex.published_at if ex else None) or cand.published_at
            if published and published < since - timedelta(days=1) and cand.origin != "drop":
                continue
            article = s.exec(select(Article).where(Article.url == url)).first()
            if not article:
                text = max(ex.text if ex else "", cand.snippet, key=len)
                paper = bool(cand.extra.get("research"))
                article = Article(
                    url=url,
                    title=(ex.title if ex and ex.title else cand.title)[:500],
                    domain=registry.registered_domain(url),
                    published_at=published,
                    lang=(ex.lang if ex else "") or cand.lang,
                    author=(ex.author if ex else "") or ", ".join(cand.extra.get("authors", [])[:6]),
                    text=text or "",
                    simhash=simhash(text) if text else "",
                    wire="" if paper else detect_wire(text or ""),
                    kind="recherche" if paper else "presse",
                    venue=cand.extra.get("venue", ""),
                    preprint=bool(cand.extra.get("preprint")),
                )
                s.add(article)
                s.commit()
                s.refresh(article)
            out.append((article, cand.origin))
    return [(a, registry.ensure(a.domain, kind="recherche" if a.kind == "recherche" else None), origin) for a, origin in out]


ORIGIN_LABEL = {"gdelt": "GDELT", "bing": "Bing Actualités", "une": "unes des médias", "rss": "flux RSS", "reddit": "Reddit", "hn": "Hacker News", "telegram": "Telegram", "drop": "liens glissés", "recherche": "bases de recherche"}


def collect_summary(cands: list[Candidate]) -> str:
    """« Collecte : GDELT 0 (saturé), Bing Actualités 24, unes des médias 3 » : ce que chaque
    source a apporté, pour qu'un sujet vide s'explique."""
    counts: dict[str, int] = defaultdict(int)
    for c in cands:
        counts["recherche" if c.extra.get("research") else c.origin] += 1
    parts = []
    if gdelt.enabled():
        parts.append(f"GDELT {counts.pop('gdelt', 0)}" + (" (saturé)" if gdelt.resting() else ""))
    if bing_news.enabled():
        parts.append(f"Bing Actualités {counts.pop('bing', 0)}")
    parts += [f"{ORIGIN_LABEL.get(o, o)} {n}" for o, n in counts.items() if n]
    return "Collecte : " + ", ".join(parts) if parts else "Collecte : aucune source active"


async def gather_articles(topic: Topic, spec: dict, since: datetime, at: datetime, extra: list[Candidate] | None = None, note=None) -> list[tuple[Article, Source, str]]:
    """`note` : reçoit le bilan de la collecte (« Collecte : … »), pour le journal du passage."""
    cands = extra if extra is not None else await collect(topic, spec, since, at)
    if note is not None and extra is None:
        note(collect_summary(cands))
        if not cands:
            note("Aucune source n'a répondu : vérifie ta connexion à Internet, ou élargis les mots-clés du sujet.")
    with session() as s:
        known = {a.url for a in s.exec(select(Article).join(TopicArticle, TopicArticle.article_id == Article.id).where(TopicArticle.topic_id == topic.id)).all()}
    # Recherche : un serveur comme arXiv héberge des milliers d'équipes, pas un seul « média ».
    research_mode = any(c.extra.get("research") for c in cands)
    days = max(1, math.ceil((at - since).total_seconds() / 86400))
    limit = min(MAX_CANDIDATES_SPACED, MAX_CANDIDATES + CANDIDATES_PER_EXTRA_DAY * (days - 1))
    chosen = select_candidates(cands, since, limit=80 if research_mode else limit, per_source=30 if research_mode else PER_SOURCE)
    chosen = [c for c in chosen if canonical_url(c.url) not in known and not registry.is_blocked(registry.registered_domain(c.url))]
    # Un article déjà extrait pour un autre sujet n'est pas retéléchargé.
    with session() as s:
        cached = {a.url: a for a in s.exec(select(Article).where(Article.url.in_([canonical_url(c.url) for c in chosen]))).all()}
    # Les papiers de recherche ne sont pas téléchargés : titre et résumé suffisent à les juger.
    papers = [(c, None) for c in chosen if c.extra.get("research") and canonical_url(c.url) not in cached]
    to_fetch = [c for c in chosen if canonical_url(c.url) not in cached and not c.extra.get("research")]
    fetched = list(await fetch_many(to_fetch)) + papers
    reused = [(c, None) for c in chosen if canonical_url(c.url) in cached]
    return _upsert_articles(fetched + reused, since)


def _latest_fiche(topic_id: int) -> Fiche | None:
    with session() as s:
        return s.exec(select(Fiche).where(Fiche.topic_id == topic_id).order_by(Fiche.version.desc())).first()


_STOP = {"dans", "pour", "avec", "sans", "sous", "entre", "vers", "chez", "plus", "moins", "leur", "leurs", "cette", "ces", "être", "avoir", "fait", "faits", "sont", "the", "and", "for", "with", "from", "into", "over", "that", "this", "what", "will", "news", "actualite", "actualité"}
_BLOCKED = re.compile(r"verify you are (a )?human|enable javascript|are you a robot|captcha|access denied|just a moment|checking your browser|vérifiez que vous êtes", re.I)


def prefilter(found: list, spec: dict) -> tuple[list, int]:
    """Écarte sans IA, avant le tri, les pages qui ne citent aucun mot du sujet (mots-clés et
    termes des requêtes) et les pages de protection anti-robot. Ne touche jamais à un lien
    glissé par le lecteur ni à une spec sans mots-clés."""
    from ..collect.rss import fold

    words = {fold(w) for phrase in [*spec.get("keywords", []), *spec.get("queries_fr", []), *spec.get("queries_en", [])] for w in re.findall(r"\w{4,}", phrase)} - _STOP
    if not words:
        return found, 0
    kept = []
    for a, s, origin in found:
        text = f"{a.title} {(a.text or '')[:4000]}"
        if origin == "drop":
            kept.append((a, s, origin))
        elif a.text and len(a.text) < 1500 and _BLOCKED.search(a.text):
            continue
        elif any(w in fold(text) for w in words):
            kept.append((a, s, origin))
    return kept, len(found) - len(kept)


def _pair(article_id: int | None) -> tuple[Article, Source] | None:
    """Un article cité par une fiche plus ancienne, avec sa source, pour revérifier un statut."""
    if article_id is None:
        return None
    with session() as s:
        a = s.get(Article, article_id)
    return (a, registry.lookup(a.domain)) if a else None


def recheck_fiches() -> int:
    """Au démarrage : la dernière fiche de chaque sujet repasse la règle de confirmation du code
    (`enforce_statuses`), y compris les fiches rédigées avant qu'elle ne se durcisse. Rend le
    nombre d'éléments ramenés à « non confirmé »."""
    total = 0
    with session() as s:
        topic_ids = s.exec(select(Topic.id)).all()
    for topic_id in topic_ids:
        fiche = _latest_fiche(topic_id)
        if not fiche:
            continue
        content = json.loads(json.dumps(fiche.content))
        changed = enforce_statuses(content, _pair)
        if changed:
            with session() as s:
                row = s.get(Fiche, fiche.id)
                row.content = content
                s.add(row)
                s.commit()
            total += changed
    return total


def _topic_texts(topic_id: int) -> dict[int, tuple[Article, Source]]:
    with session() as s:
        rows = s.exec(select(Article).join(TopicArticle, TopicArticle.article_id == Article.id).where(TopicArticle.topic_id == topic_id, TopicArticle.kept == True)).all()  # noqa: E712
    return {a.id: (a, registry.lookup(a.domain)) for a in rows}


async def ensure_spec(llm: LLM, meter: RunMeter, topic: Topic, settings: Settings) -> dict:
    if topic.spec:
        return topic.spec
    spec = await build_spec(llm, meter, topic.model or settings.models.topic, topic.prompt, now(), kind=topic.kind, fields=topic.research_fields or [])
    with session() as s:
        t = s.get(Topic, topic.id)
        t.spec = spec.model_dump()
        if spec.start_date:
            try:
                t.since = datetime.fromisoformat(spec.start_date).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        s.add(t)
        s.commit()
        topic.spec, topic.since = t.spec, t.since
    return topic.spec


async def run_topic(topic_id: int, *, dry: bool = False, llm: LLM | None = None) -> dict:
    settings = load_settings()
    meter = RunMeter()
    with session() as s:
        topic = s.get(Topic, topic_id)
        if not topic:
            raise ValueError(f"Sujet {topic_id} introuvable")
        run = Run(topic_id=topic_id, kind="topic")
        s.add(run)
        s.commit()
        s.refresh(run)
    try:  # moteur absent ou accord retiré : le passage est consigné en erreur, pas perdu
        llm = llm or get_llm()
    except Exception as e:
        _finish(run.id, meter, "error", str(e))
        events.publish("run", topic_id=topic_id, run_id=run.id, stage="error", message=str(e))
        raise
    model = topic.model or settings.models.topic
    at = now()

    def stage(name: str, message: str) -> None:
        meter.note(message)
        events.publish("run", topic_id=topic_id, run_id=run.id, stage=name, message=message)

    try:
        spec = await ensure_spec(llm, meter, topic, settings)
        research_topic = topic.kind == "recherche"
        meta: dict = {}
        origins: dict = {}
        verdicts: dict = {}
        kept: dict = {}

        async def harvest(since: datetime) -> list:
            """Collecte, tri et recherche complémentaire depuis `since` : complète meta, origins,
            verdicts et kept, rend les reprises. Un article déjà trié à ce passage ne l'est pas deux fois."""
            found = await gather_articles(topic, spec, since, at, note=lambda line: stage("collect", line))
            found = [(a, s, o) for a, s, o in found if a.id not in origins]  # déjà vu à ce passage
            if gdelt.resting():
                stage("collect", "GDELT limite les requêtes en ce moment : collecte partielle (Bing Actualités, unes des médias et flux RSS)")
            origins.update({a.id: o for a, _, o in found})
            # Une reprise telle quelle d'un article déjà retenu n'apprend rien : elle n'est pas triée.
            found, reprises = (found, []) if research_topic else split_reprises(topic_id, found, at)
            stage("extract", f"{len(found)} articles nouveaux extraits" + (f", {len(reprises)} reprise(s) d'articles déjà lus" if reprises else ""))

            if not research_topic:
                found, dropped = prefilter(found, spec)
                if dropped:
                    meter.note(f"préfiltre : {dropped} page(s) sans aucun mot-clé du sujet, ou de protection anti-robot, écartées sans IA")
            meta.update({a.id: (a, s) for a, s, _ in found})
            stage("triage", "Tri : faits, analyses, opinions, réactions")
            found_verdicts = await triage(llm, meter, settings.models.triage, spec, [(a, s) for a, s, _ in found], task="triage_research" if research_topic else "triage")
            verdicts.update(found_verdicts)
            found_kept = {i: v for i, v in found_verdicts.items() if v.keep and v.relevance >= 0.5 and v.nature != "hors_sujet"}
            if not research_topic:  # qualifier les domaines inconnus des seuls articles retenus
                await qualify_sources(llm, meter, model, [meta[i] for i in found_kept])
            kept.update(found_kept)

            independent = {independence_key(*meta[i]) for i in kept}
            if settings.claude_search_fallback and not dry and not research_topic and len(independent) < settings.min_independent_sources:
                stage("search", f"Seulement {len(independent)} source(s) indépendante(s) : recherche complémentaire")
                by_lang = {lang: spec.get(f"queries_{lang}", []) for lang in ("fr", "en") if lang in topic.languages}
                extra = await claude_search.search(llm, meter, model, spec.get("summary", topic.name), spec.get("queries_fr", []) + spec.get("queries_en", []), since, by_lang=by_lang)
                more = await gather_articles(topic, spec, since, at, extra=extra)
                more = [(a, s, o) for a, s, o in more if a.id not in meta]
                meta.update({a.id: (a, s) for a, s, _ in more})
                origins.update({a.id: o for a, _, o in more})
                more_verdicts = await triage(llm, meter, settings.models.triage, spec, [(a, s) for a, s, _ in more])
                verdicts.update(more_verdicts)
                more_kept = {i: v for i, v in more_verdicts.items() if v.keep and v.relevance >= 0.5 and v.nature != "hors_sujet"}
                await qualify_sources(llm, meter, model, [meta[i] for i in more_kept])
                kept.update(more_kept)
            return reprises

        since = window(topic, at, topic.run_every_days or settings.run_every_days or 1)
        stage("collect", f"Collecte depuis le {since:%d/%m %H:%M}")
        reprises = await harvest(since)
        # Une fiche encore sans source (premier passage, ou rien trouvé jusqu'ici) : plutôt qu'une
        # fiche vide, la collecte remonte un mois, le temps de poser l'état du sujet.
        empty_yet = not ((last := _latest_fiche(topic_id)) and last.sources)
        if not kept and empty_yet and not research_topic and not topic.since and since > at - timedelta(days=WIDE_WINDOW_DAYS):
            since = at - timedelta(days=WIDE_WINDOW_DAYS)
            stage("collect", f"Rien de retenu : la fiche n'a pas encore de source, la collecte remonte à {WIDE_WINDOW_DAYS} jours")
            reprises += await harvest(since)

        clusters = {it["id"]: it["cluster"] for it in cluster([{"id": a.id, "title": a.title, "simhash": a.simhash} for a, _ in meta.values()])}
        with session() as s:
            for article_id, v in verdicts.items():
                s.merge(TopicArticle(topic_id=topic_id, article_id=article_id, origin=origins.get(article_id, ""), relevance=v.relevance, nature=v.nature, sensationalism=v.sensationalism, kept=article_id in kept, reason=v.reason, claims=[c.model_dump() for c in v.claims], cluster=clusters.get(article_id, ""), run_id=run.id))
            for a, _src, original in reprises:
                s.merge(TopicArticle(topic_id=topic_id, article_id=a.id, origin=origins.get(a.id, ""), kept=False, reason=f"Reprise de « {original.title[:120]} », déjà retenu : rien de neuf.", run_id=run.id))
            s.commit()

        if dry:
            report = {"spec": spec, "since": since.isoformat(), "reprises": [{"id": a.id, "title": a.title, "source": src.name, "original": o.title} for a, src, o in reprises], "articles": [{"id": a.id, "title": a.title, "source": s.name, "kept": a.id in kept, "nature": verdicts[a.id].nature if a.id in verdicts else None, "reason": verdicts[a.id].reason if a.id in verdicts else "non trié"} for a, s in meta.values()]}
            _finish(run.id, meter, "done")
            return report

        previous = _latest_fiche(topic_id)
        if not kept:
            stage("synth", "Rien de neuf : aucune source retenue")
            upd = updates([], {}, reprises)
            content = {**carry_forward(previous.content, []), "updates": upd} if previous else {}
            novelty = {"new": 0, "late": 0, "confirmations": 0, "rectifications": 0, "reprises": upd["reprises"]["articles"], "synth_skipped": True}
            fiche = _save_fiche(topic, previous, content, nothing_new=True, run_id=run.id, cov=previous.coverage if previous else coverage([]), sources=previous.sources if previous else [], novelty=novelty)
            _finish(run.id, meter, "done")
            _after_run(topic_id)
            return {"fiche_id": fiche.id, "version": fiche.version, "nothing_new": True, "cost_usd": meter.cost_usd}

        stage("verify", f"Recoupement de {sum(len(v.claims) for v in kept.values())} affirmations")
        today_claims = [c.text for v in kept.values() for c in v.claims]
        tracked, tracked_meta = ([], {}) if research_topic else known_claims(topic_id, at, today_claims)
        ctx = {"kept": kept, "meta": meta, "vmeta": {**tracked_meta, **{i: meta[i] for i in kept}}, "tracked": tracked}
        facts = await verify(llm, meter, model, kept, ctx["vmeta"], tracked)
        stale: dict = {}
        if not research_topic:
            if any(f.status == "non_confirme" for f in facts):
                stage("corroborate", "Recherche d'autres sources pour les faits à source unique")
                facts = await _corroborate(llm, meter, model, settings, topic, run.id, spec, since, facts, ctx)
            # Un fait déjà connu n'a pas à être cherché dans l'historique : on sait d'où il vient.
            unknown = [f for f in facts if f.claim_id is None]
            if unknown:
                stage("freshness", "Vérification que les nouveautés sont bien nouvelles")
                weight = {n: max((kept[ref_id(r)].relevance for r in f.refs if ref_id(r) in kept), default=0.0) for n, f in enumerate(unknown)}
                await mark_stale(llm, meter, model, unknown, since, priority=weight)
            stale = stale_index(facts)
        summary = classify(facts, ctx["vmeta"], tracked)
        meter.note(f"nouveauté : {summary['new']} fait(s) nouveau(x), {summary['rectifications']} rectification(s), {summary['confirmations']} confirmation(s) ou appui(s), {summary['reprises']} reprise(s), {summary['late']} déjà paru(s)")
        _save_claims(topic_id, facts)
        upd = updates(facts, ctx["vmeta"], reprises)

        all_texts = _topic_texts(topic_id)
        texts = {i: a.text + " " + a.title for i, (a, _) in all_texts.items()}
        kept_pairs = sorted((meta[i] for i in kept), key=lambda p: -kept[p[0].id].relevance)
        skipped = bool(previous) and not research_topic and not has_news(facts)
        if skipped:
            # Rien à rédiger : la fiche est reconduite par le programme, statuts et sources à jour.
            stage("synth", "Rien de neuf à rédiger : la fiche est reconduite, sans appel au modèle")
            content = carry_forward(previous.content, facts)
        else:
            plain, rectified = for_synth(facts)
            wanted = synth_refs(facts)
            pairs = [p for p in kept_pairs if p[0].id in wanted] or kept_pairs
            stage("synth", "Rédaction de la fiche")
            fiche_model = await synthesize(llm, meter, model, task="synth_research" if research_topic else "synth", spec=spec, previous=previous.content if previous else None, facts=plain, pairs=pairs, alerts=coverage(kept_pairs)["alerts"], today=f"{at:%Y-%m-%d}", rectified=rectified)
            if not fiche_model.nothing_new:  # rien rédigé de neuf : rien à relire
                stage("neutrality", "Relecture de neutralité")
                fiche_model, issues = await neutrality_pass(llm, meter, settings.models.triage, model, fiche_model)
                meter.note(f"neutralité : {len(issues)} correction(s)")
            content = validate(fiche_model.model_dump(), texts, stale)
            content["corrections"] = validate_corrections(content.get("corrections", []), previous.content if previous else None, texts)
            refresh_statuses(content, facts)
        downgraded = enforce_statuses(content, lambda i: all_texts.get(i) or (meta.get(i) if meta else None) or _pair(i))
        if downgraded:
            meter.note(f"rigueur : {downgraded} élément(s) ramené(s) à « non confirmé » (sources insuffisantes)")
        content["updates"] = upd
        # « Rien de neuf » : ni nouveauté ni correction. L'importance est celle des nouveautés.
        nothing_new = bool(content.get("nothing_new")) and not content.get("corrections")
        if nothing_new:
            content.update(whats_new=[], importance=0)
        content["nothing_new"] = nothing_new
        novelty = {"new": len(content.get("whats_new", [])), "late": summary["late"], "confirmations": summary["confirmations"], "rectifications": len(content.get("corrections", [])), "reprises": upd["reprises"]["articles"], "synth_skipped": skipped}
        cited = [all_texts[i] for i in cited_ids(content) if i in all_texts]
        cov = coverage(cited or kept_pairs)
        sources = [{"ref": f"S{a.id}", "id": a.id, "title": a.title, "domain": a.domain, "name": a.venue or s.name, "preprint": a.preprint, "research": a.kind == "recherche", "url": a.url, "published_at": a.published_at.isoformat() if a.published_at else None, "country": s.country, "kind": s.kind, "owner": s.owner, "owner_type": s.owner_type, "quality": s.quality, "quality_origin": s.quality_origin, "quality_note": s.quality_note} for a, s in cited]
        fiche = _save_fiche(topic, previous, content, nothing_new=nothing_new, run_id=run.id, cov=cov, sources=sources, novelty=novelty)
        save_corrections(topic_id, fiche, previous, content.get("corrections", []))
        sync_from_fiche(topic_id, content)
        _finish(run.id, meter, "done")
        stage("done", f"Version {fiche.version} enregistrée")
        _after_run(topic_id)
        if not content.get("nothing_new") and content.get("importance", 0) >= settings.notify_threshold:
            events.publish("notify", topic_id=topic_id, title=topic.name, body=content.get("lede", ""), importance=content.get("importance"))
        return {"fiche_id": fiche.id, "version": fiche.version, "nothing_new": fiche.nothing_new, "cost_usd": meter.cost_usd}
    except Exception as e:
        _finish(run.id, meter, "error", str(e))
        events.publish("run", topic_id=topic_id, run_id=run.id, stage="error", message=str(e))
        raise


def _save_claims(topic_id: int, facts) -> None:
    """Un fait rattaché à un fait suivi (`claim_id`) le met à jour ; sinon, même texte, même fait."""
    with session() as s:
        rows = s.exec(select(Claim).where(Claim.topic_id == topic_id)).all()
        by_id, by_text = {c.id: c for c in rows}, {c.text: c for c in rows}
        for f in facts:
            ids = [int(r[1:]) for r in f.refs]
            c = by_id.get(f.claim_id) or by_text.get(f.text)
            if c:
                # Rapproché par le seul texte, un fait établi ne redescend pas faute de source du jour.
                keep = f.claim_id is None and c.status == "confirme" and f.status == "non_confirme"
                c.status, c.article_ids, c.last_seen = c.status if keep else f.status, sorted(set(c.article_ids) | set(ids)), now()
                c.first_reported = c.first_reported or f.first_reported
            else:
                c = Claim(topic_id=topic_id, text=f.text, status=f.status, article_ids=ids, due=f.due, first_reported=f.first_reported)
            s.add(c)
        s.commit()


async def _corroborate(llm: LLM, meter: RunMeter, model: str, settings: Settings, topic: Topic, run_id: int, spec: dict, since: datetime, facts: list, ctx: dict) -> list:
    """Cherche d'autres médias pour les faits à source unique les plus pertinents, puis
    recoupe à nouveau. `ctx` : kept, meta (articles du passage), vmeta (articles recoupés)
    et tracked ; ils sont complétés par les sources trouvées."""
    kept, meta, vmeta = ctx["kept"], ctx["meta"], ctx["vmeta"]

    def relevance(f) -> float:
        return max((kept[ref_id(r)].relevance for r in f.refs if ref_id(r) in kept), default=0.0)

    singles = sorted((f for f in facts if f.status == "non_confirme" and f.probe.strip()), key=relevance, reverse=True)[:MAX_CORROBORATE]
    if not singles:
        return facts
    langs = [lang for lang in topic.languages if lang in gdelt.LANGS] or ["fr", "en"]
    start = since - timedelta(days=CORROBORATION_DAYS)

    def web(n: int, f) -> str | None:
        if not settings.claude_search_fallback or n >= WEB_CORROBORATE:
            return None
        return f"Trouve des articles de presse ou des sources officielles qui rapportent ce fait : {clean(f.text)}"

    results = await asyncio.gather(*[find_corroboration(llm, meter, model, {lang: [f.probe.strip()] for lang in langs}, start, exclude=set(vmeta), web_prompt=web(n, f), limit=CORROBORATION_LINKS) for n, f in enumerate(singles)])
    found = {a.id: (a, s) for pairs in results for a, s in pairs if a.id not in vmeta}
    meter.note(f"recoupement actif : {len(singles)} fait(s) à source unique, {len(found)} article(s) trouvé(s)")
    if not found:
        return facts
    pairs = list(found.values())
    await qualify_sources(llm, meter, model, pairs)
    listing = clean("\n".join(f"- {f.text}" for f in singles))
    verdicts = await triage(llm, meter, settings.models.triage, {**spec, "summary": f"{spec.get('summary', topic.name)} Faits à recouper :\n{listing}"}, pairs)
    more = {i: v for i, v in verdicts.items() if v.keep and v.relevance >= 0.4 and v.nature != "hors_sujet" and v.claims}
    with session() as s:
        for i, v in verdicts.items():
            link = s.get(TopicArticle, (topic.id, i))
            if link is None:
                s.add(TopicArticle(topic_id=topic.id, article_id=i, origin="recoupement", relevance=v.relevance, nature=v.nature, sensationalism=v.sensationalism, kept=i in more, reason=v.reason, claims=[c.model_dump() for c in v.claims], run_id=run_id))
            elif i in more and not link.kept:
                link.kept, link.reason, link.claims = True, f"Retenu au recoupement : {v.reason}", [c.model_dump() for c in v.claims]
                s.add(link)
        s.commit()
    if not more:
        return facts
    kept.update(more)
    meta.update({i: found[i] for i in more})
    vmeta.update({i: found[i] for i in more})
    facts = await verify(llm, meter, model, kept, vmeta, ctx["tracked"])
    meter.note(f"recoupement actif : {len(more)} source(s) ajoutée(s)")
    return facts


def _save_fiche(topic: Topic, previous: Fiche | None, content: dict, *, nothing_new: bool, run_id: int, cov: dict, sources: list, novelty: dict | None = None) -> Fiche:
    with session() as s:
        fiche = Fiche(topic_id=topic.id, version=(previous.version + 1) if previous else 1, content=content, sources=sources, coverage=cov, nothing_new=nothing_new, novelty=novelty or {}, run_id=run_id)
        s.add(fiche)
        t = s.get(Topic, topic.id)
        t.last_run_at = now()
        if nothing_new:
            t.quiet_runs += 1
            if t.quiet_runs >= SLEEP_AFTER_QUIET_RUNS and t.status == "active" and not rhythm.holds_sleep(t):
                t.status = "sleeping"
                events.publish("topic", topic_id=t.id, status="sleeping", message=f"« {t.name} » ne bouge plus : passage en veille")
        else:
            t.quiet_runs = 0
            if t.status == "sleeping":
                t.status = "active"
                events.publish("topic", topic_id=t.id, status="active", message=f"« {t.name} » repart : sujet réveillé")
        s.add(t)
        s.commit()
        s.refresh(fiche)
        return fiche


def _after_run(topic_id: int) -> None:
    """Le rythme conseillé tient compte du passage (pilote automatique compris)."""
    try:
        rhythm.after_run(topic_id)
    except Exception as e:  # noqa: BLE001 — le rythme ne fait jamais échouer un passage
        events.publish("warning", message=f"Rythme du sujet : calcul impossible ({e})")


def _finish(run_id: int, meter: RunMeter, status: str, error: str = "") -> None:
    with session() as s:
        run = s.get(Run, run_id)
        run.status, run.error, run.finished_at = status, error, now()
        run.input_tokens, run.output_tokens = meter.input_tokens, meter.output_tokens
        run.cache_read_tokens, run.web_searches, run.cost_usd, run.log = meter.cache_read_tokens, meter.web_searches, round(meter.cost_usd, 5), meter.log
        run.subscription_usd, run.calls = round(meter.subscription_usd, 5), meter.calls
        s.add(run)
        s.commit()


def log_run(kind: str, meter: RunMeter, topic_id: int | None = None, status: str = "done", error: str = "") -> None:
    """Consigne après coup les appels d'une action ponctuelle (lien glissé, vérification
    d'article, audio…) : toute dépense compte dans le mois."""
    if not meter.calls:
        return
    with session() as s:
        run = Run(topic_id=topic_id, kind=kind)
        s.add(run)
        s.commit()
        s.refresh(run)
    _finish(run.id, meter, status, error)
