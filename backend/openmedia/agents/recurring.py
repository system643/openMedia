"""Les sujets récurrents de « Mes lectures » : un algorithme, sans IA, repère dans les titres lus
les sujets qui reviennent (entités, expressions, mots rares), les regroupe et les classe ;
Haiku ne fait ensuite que les nommer et rédiger un prompt de suivi. Les chiffres, l'ordre et
la raison affichée viennent du code : ils se vérifient en relisant ses lectures."""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from rapidfuzz import fuzz
from sqlmodel import select

from .. import events
from ..collect.rss import fold
from ..config import consented, data_dir, load_settings
from ..db import session
from ..models import Article, Reading, Topic
from ..security import clean
from ..sources import registry
from .llm import LLM, RunMeter, any_engine, engine_status, get_llm
from .material import as_json
from .schemas import RecurringTopics

MODEL = "claude-haiku-5-5"  # imposé : nommer des sujets déjà trouvés ne demande pas plus
WINDOW_DAYS = 90
HALF_LIFE_DAYS = 14  # une lecture d'il y a deux semaines pèse moitié moins qu'aujourd'hui
MAX_TOPICS = 12
MIN_READS, MIN_DAYS, MIN_MEDIA = 3, 2, 2  # en deçà, ce n'est pas un sujet qui revient
GENERIC_SHARE = 0.08  # un mot-clé présent dans plus de 8 % des titres ne distingue rien
SAME_TITLE = 92  # titres quasi identiques (même dépêche lue deux fois) : comptés une fois
SAMPLE_TITLES = 6

STOP = {
    # français
    "les", "des", "une", "dans", "pour", "avec", "sans", "sont", "etre", "avoir", "cette", "leur", "leurs", "plus", "moins", "selon", "apres", "avant", "entre", "dont", "elle", "elles", "ils", "nous", "vous", "mais", "comme", "aussi", "tres", "tout", "tous", "toute", "toutes", "fait", "faire", "etait", "sera", "ont", "ete", "sur", "par", "pas", "qui", "que", "quoi", "est", "son", "ses", "sa", "aux", "au", "du", "de", "la", "le", "un", "et", "ou", "en", "ce", "ces", "il", "on", "se", "ne", "lui", "ca", "va", "peut", "doit", "veut", "deux", "trois", "quand", "comment", "pourquoi", "encore", "deja", "contre", "vers", "chez", "depuis", "pendant", "sous", "notre", "votre", "quel", "quelle", "quels", "quelles", "faut", "fois", "jour", "jours", "ans", "annee", "nouveau", "nouvelle", "nouveaux", "premier", "premiere", "grand", "grande", "petit", "petite", "bien", "mal", "trop", "ici", "voici", "voila", "tout", "rien", "ceux", "celle", "celui", "lors", "alors", "ainsi", "donc", "car", "oui", "non", "dit", "dire", "avait", "aurait", "serait", "font", "mois", "semaine", "heure", "heures",
    # anglais
    "the", "and", "for", "that", "this", "with", "from", "have", "were", "will", "their", "they", "said", "says", "about", "after", "before", "which", "would", "could", "been", "into", "than", "more", "most", "what", "when", "where", "who", "why", "how", "new", "over", "just", "your", "you", "are", "was", "has", "had", "its", "not", "but", "can", "out", "all", "one", "two", "year", "years", "week", "day", "days",
}
# Le vocabulaire des pages de presse elles-mêmes, qui ne dit rien du sujet.
NOISE = {
    "direct", "video", "videos", "photo", "photos", "info", "infos", "exclusif", "exclusive", "breaking", "live", "podcast", "replay", "edito", "editorial", "chronique", "tribune", "analyse", "decryptage", "entretien", "interview", "temoignage", "enquete", "reportage", "newsletter", "abonne", "abonnes", "article", "actualite", "actualites", "actu", "news", "update", "updates", "explique", "explication", "explainer", "opinion", "debat", "revue", "presse", "france", "francais", "francaise", "monde", "mondial", "international",
    # montants et ordres de grandeur : partout, sans désigner une histoire
    "milliard", "milliards", "million", "millions", "euro", "euros", "dollar", "dollars", "pourcent", "record", "chiffre", "chiffres",
}
_TOKEN = re.compile(r"[^\W_][\w'’.-]*", re.UNICODE)
_ELISION = re.compile(r"^(?:[ldjmnstc]|qu|jusqu|lorsqu|puisqu)['’]", re.IGNORECASE)
_PUNCT = re.compile(r"[,;:!?«»\"“”()\[\]|–—…]+|\s-\s")
_SUFFIX = re.compile(r"\s+[-–—|]\s+([^-–—|]{2,40})$")  # « … - Le Monde », « … | Libération », « – Brave »
_NAME_WORD = re.compile(r"^(?:[A-ZÀ-Ý0-9][\w'’.&+-]*|de|du|des|la|le|les|et|en|d['’]\w+|l['’]\w+)$")


@dataclass
class Doc:
    ids: list[int]
    title: str
    keys: set[str]
    entities: set[str]
    weight: float
    days: set[date]
    media: set[str]
    last: datetime
    visits: int


@dataclass
class Found:
    key: str
    label: str
    keys: list[str]
    reading_ids: list[int]
    count: int
    days: int
    media: list[str]
    first: str
    last: str
    score: float
    titles: list[str]
    reason: str
    related_topic_id: int | None = None
    entity: bool = False
    extra: dict = field(default_factory=dict)


def _stem(word: str) -> str:
    """Racinisation légère : « députés » et « député » se rejoignent."""
    if len(word) > 5 and word[-1] in "sx" and word[-2] not in "su":
        return word[:-1]
    return word


def _words(title: str) -> list[tuple[str, str]]:
    """(mot tel qu'écrit, sans élision ; mot plié) ; les élisions « l' », « d' » sont retirées."""
    out = []
    for raw in _TOKEN.findall(title):
        raw = _ELISION.sub("", raw).strip(".-'’")
        if raw:
            out.append((raw, fold(raw)))
    return out


def strip_suffix(title: str) -> str:
    """Retire le nom du média ou du navigateur en fin de titre (« … - Le Monde », « – Brave »)."""
    title = title.strip()
    for _ in range(2):
        m = _SUFFIX.search(title)
        words = m.group(1).split() if m else []
        # Un nom de média ou de navigateur : quatre mots au plus, chacun avec une majuscule
        # (hors liaisons) ; « - le Sénat vote le texte » reste dans le titre.
        if not m or len(words) > 4 or not all(_NAME_WORD.match(w) for w in words) or not words[0][:1].isupper():
            break
        title = title[: m.start()].strip()
    return title


# Forme affichée d'un mot-clé racinisé (« proces » plutôt que « proce ») : la première vue.
display: dict[str, str] = {}


def keywords(title: str, banned: set[str] = frozenset()) -> tuple[set[str], set[str]]:
    """Les mots-clés d'un titre et, parmi eux, les entités (noms propres, sigles)."""
    title = strip_suffix(title)
    words = _words(title)
    keys, entities = set(), set()
    # Entités : suites de mots à majuscule, et chacun de leurs mots (« Nvidia » dans « Nvidia
    # RTX Spark »), plus les sigles. La ponctuation coupe une suite (« ChatGPT, Grok, Claude ») ;
    # le premier mot d'un segment ne compte que s'il est suivi d'un autre nom propre
    # (« Emmanuel Macron annonce… »), car une phrase commence toujours par une majuscule.
    run: list[str] = []

    def add(phrase: str) -> None:
        if phrase not in STOP and phrase not in NOISE and phrase not in banned and len(phrase) > 2:
            keys.add(phrase)
            entities.add(phrase)

    def close():
        if run:
            add(" ".join(run))
            if len(run) > 1:
                for w in run:
                    add(w)
            run.clear()

    for segment in _PUNCT.split(title):
        seg = _words(segment)
        for i, (raw, folded) in enumerate(seg):
            capital = raw[:1].isupper() and not raw.isdigit()
            acronym = raw.isupper() and raw.isalpha() and 2 <= len(raw) <= 6
            first = i == 0 and not (len(seg) > 1 and seg[1][0][:1].isupper())
            if (capital or acronym) and not first and folded not in STOP:
                run.append(folded)
            else:
                close()
        close()
    plain = [f for _, f in words if (f not in STOP and f not in NOISE and len(f) > 2 and not f.isdigit()) or (f.isdigit() and len(f) == 4)]
    pairs = [(_stem(a), _stem(b), f"{a} {b}") for a, b in zip(plain, plain[1:]) if not (a.isdigit() and b.isdigit())]
    for a, b, shown in pairs:
        keys.add(f"{a} {b}")
        display.setdefault(f"{a} {b}", shown)
    for w in plain:
        if len(w) >= 5 and not w.isdigit():
            keys.add(_stem(w))
            display.setdefault(_stem(w), w)
    keys -= banned
    return keys, entities & keys


def _media_words() -> set[str]:
    """Les noms des médias : « le monde », « figaro »… ne sont pas des sujets."""
    out = set()
    for src in registry._known().values():
        name = fold(src.name or "")
        out |= {name, *[w for w in name.split() if len(w) >= 4]}
        out.add(src.domain.split(".")[0])
    return out - {""}


def corpus(at: datetime | None = None) -> list[Doc]:
    """Les lectures des 90 derniers jours, sans les médias masqués ni les lectures écartées ;
    les titres quasi identiques sont fusionnés."""
    from .readings import hidden_domains

    at = at or datetime.now(timezone.utc)
    hidden = hidden_domains()
    banned = _media_words()
    with session() as s:
        rows = s.exec(select(Reading, Article).join(Article, Article.id == Reading.article_id).where(Reading.status != "ignore")).all()
    docs: list[Doc] = []
    for r, a in rows:
        last = r.last_visit or r.imported_at
        last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
        if a.domain in hidden or (at - last).days > WINDOW_DAYS or not a.title or a.title == a.url:
            continue
        keys, entities = keywords(a.title, banned)
        if not keys:
            continue
        age = max(0.0, (at - last).total_seconds() / 86400)
        weight = 0.5 ** (age / HALF_LIFE_DAYS) * (1 + math.log(max(1, r.visits)))
        first = r.first_visit or last
        first = first if first.tzinfo else first.replace(tzinfo=timezone.utc)
        days = {first.date(), last.date()}
        docs.append(Doc([r.id], strip_suffix(a.title), keys, entities, weight, days, {registry.lookup(a.domain).name}, last, r.visits))
    return _merge_same(docs)


def _merge_same(docs: list[Doc]) -> list[Doc]:
    """Une même dépêche lue sur deux sites (ou deux fois) ne compte qu'une fois."""
    docs.sort(key=lambda d: d.last, reverse=True)
    kept: list[Doc] = []
    by_key: dict[str, list[Doc]] = defaultdict(list)
    for d in docs:
        folded = fold(d.title)
        twin = next((k for key in list(d.keys)[:4] for k in by_key[key] if fuzz.ratio(folded, fold(k.title)) >= SAME_TITLE), None)
        if twin:
            twin.ids += d.ids
            twin.weight = max(twin.weight, d.weight)
            twin.days |= d.days
            twin.media |= d.media
            twin.visits += d.visits
            continue
        kept.append(d)
        for key in list(d.keys)[:4]:
            by_key[key].append(d)
    return kept


def _span(first: datetime, last: datetime) -> str:
    days = (last.date() - first.date()).days
    if days <= 1:
        return "en deux jours"
    if days < 14:
        return f"en {days} jours"
    if days < 60:
        return f"en {round(days / 7)} semaines"
    return f"en {round(days / 30)} mois"


def find(docs: list[Doc]) -> list[Found]:
    """Regroupement glouton : le mot-clé le plus fort devient la graine d'un sujet, les mots-clés
    qui vont avec le rejoignent, puis ses lectures sont retirées et l'on recommence."""
    if not docs:
        return []
    index: dict[str, set[int]] = defaultdict(set)
    entity: set[str] = set()
    for i, d in enumerate(docs):
        for k in d.keys:
            index[k].add(i)
        entity |= d.entities
    limit = max(10, GENERIC_SHARE * len(docs))  # un petit historique garde ses sujets
    index = {k: v for k, v in index.items() if len(v) >= MIN_READS and len(v) <= limit}
    remaining = set(range(len(docs)))

    def stats(members: set[int]) -> tuple[float, int, int]:
        days = set().union(*(docs[i].days for i in members)) if members else set()
        media = set().union(*(docs[i].media for i in members)) if members else set()
        return sum(docs[i].weight for i in members), len(days), len(media)

    def score(members: set[int], boost: float = 1.0) -> float:
        w, days, media = stats(members)
        return w * math.log(1 + days) * (1 + 0.2 * media) * boost

    found: list[Found] = []
    tried: set[str] = set()
    while len(found) < MAX_TOPICS:
        best, best_score = None, 0.0
        for k, v in index.items():
            if k in tried:
                continue
            live = v & remaining
            if len(live) < MIN_READS:
                continue
            s = score(live, 1.5 if k in entity else 1.2 if " " in k else 1.0)
            if s > best_score:
                best, best_score = k, s
        if best is None:
            break
        tried.add(best)
        seed = index[best] & remaining
        # Les mots-clés qui accompagnent la graine : présents surtout dans ses lectures.
        near = []
        for k, v in index.items():
            live = v & remaining
            both = len(live & seed)
            # Présent surtout dans les lectures de la graine, et dans une part notable d'entre elles :
            # un mot qui ne touche qu'un recoin du sujet (« gazole » pour « Trump ») n'en est pas.
            if k != best and both >= max(2, 0.15 * len(seed)) and both / min(len(live), len(seed)) >= 0.6:
                near.append((score(live & seed), k))
        near.sort(reverse=True)
        cluster_keys = [best] + [k for _, k in near[:8]]
        members = set(seed)
        # Un nom propre ou une expression désigne un sujet ; un mot seul (« réseau », « bataille »)
        # seulement si ses lectures partagent d'autres mots-clés : c'est la cohésion du sujet.
        # Nom propre : écrit avec une majuscule dans la plupart de ses titres (« Trump »), pas
        # seulement en début de groupe (« la Recherche », « recherche » ailleurs).
        proper = sum(best in docs[i].entities for i in members) >= 0.6 * len(members)
        if not proper and " " not in best:
            others = set(cluster_keys[1:])
            if sum(bool(docs[i].keys & others) for i in members) < 0.5 * len(members):
                continue
        weight, n_days, n_media = stats(members)
        n_reads = sum(len(docs[i].ids) for i in members)
        if n_reads < MIN_READS or n_days < MIN_DAYS or n_media < MIN_MEDIA:
            continue  # la graine seule ne fait pas un sujet : on essaie la suivante
        remaining -= members
        tried |= set(cluster_keys)
        found.append(_describe(best, cluster_keys, members, docs, entity, score(members)))
    found.sort(key=lambda f: f.score, reverse=True)
    return found


def _describe(seed: str, cluster_keys: list[str], members: set[int], docs: list[Doc], entity: set[str], score: float) -> Found:
    items = [docs[i] for i in members]
    label: list[str] = []
    for k in sorted(cluster_keys, key=lambda k: (k not in entity, " " not in k, cluster_keys.index(k))):
        if not any(k in chosen or chosen in k for chosen in label):
            label.append(k)
        if len(label) == 3:
            break
    first = min(min(d.days) for d in items)
    last_doc = max(items, key=lambda d: d.last)
    media = sorted({m for d in items for m in d.media}, key=lambda m: -sum(m in d.media for d in items))
    sample = sorted(items, key=lambda d: (d.last, d.visits), reverse=True)[:SAMPLE_TITLES]
    ids = sorted(i for d in items for i in d.ids)
    first_dt = datetime.combine(first, datetime.min.time(), tzinfo=timezone.utc)
    reason = f"{len(ids)} articles lus {_span(first_dt, last_doc.last)}, dans {len(media)} médias"
    return Found(
        key=" | ".join(sorted(label)),
        label=", ".join(display.get(k, k) for k in label),
        keys=cluster_keys,
        reading_ids=ids,
        count=len(ids),
        days=len(set().union(*(d.days for d in items))),
        media=media[:6],
        first=first.isoformat(),
        last=last_doc.last.isoformat(),
        score=round(score, 3),
        titles=[d.title for d in sample],
        reason=reason,
        entity=seed in entity,
    )


def link_topics(found: list[Found]) -> None:
    """Un sujet récurrent qui recoupe un sujet déjà suivi le signale (« Déjà suivi »)."""
    with session() as s:
        topics = s.exec(select(Topic).where(Topic.status != "archived")).all()
    texts = [(t.id, fold(" ".join([t.name, t.prompt, *((t.spec or {}).get("keywords") or [])]))) for t in topics]
    for f in found:
        for tid, text in texts:
            hits = [k for k in f.keys[:6] if k in text]
            if len(hits) >= 2 or any(" " in k or len(k) >= 6 for k in hits if k == f.keys[0]):
                f.related_topic_id = tid
                break


def compute() -> list[Found]:
    """Toute la partie algorithmique : corpus, regroupement, classement, sujets déjà suivis."""
    found = find(corpus())
    link_topics(found)
    return found


# ── Haiku : nommer et rédiger le prompt de suivi ─────────────────────────────

_lock = asyncio.Lock()


def _path():
    return data_dir() / "recurring.json"


def load() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"names": {}, "result": None}


def _save(state: dict) -> None:
    _path().write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def fallback(f: Found) -> dict:
    """Sans moteur IA : le sujet est nommé par ses mots-clés, avec un prompt générique."""
    parts = list(dict.fromkeys(p.strip() for p in f.label.split(",") if p.strip()))  # « artemis iii, artemis iii » : une fois
    label = ", ".join(parts) or f.label
    return {"name": label[:1].upper() + label[1:], "prompt": f"Suis l'actualité sur {label} : les faits nouveaux, les positions des acteurs et ce qui est attendu ensuite.", "followable": True, "by": "algorithme"}


async def _name(found: list[Found], llm: LLM, meter: RunMeter) -> dict[str, dict]:
    lines = [{"i": i, "mots_cles": f.keys[:6], "articles": f.count, "jours": f.days, "medias": f.media[:4], "titres": [clean(t)[:160] for t in f.titles]} for i, f in enumerate(found)]
    out = await llm.parse(meter, model=MODEL, task="recurring", content=f"<sujets>\n{as_json(lines)}\n</sujets>", schema=RecurringTopics, effort="low", max_tokens=2000)
    named = {}
    for t in out.topics:
        if 0 <= t.i < len(found) and t.name.strip() and t.prompt.strip():
            named[found[t.i].key] = {"name": clean(t.name)[:80], "prompt": clean(t.prompt)[:1200], "followable": t.followable, "by": "haiku"}
    return named


async def refresh(llm: LLM | None = None) -> dict:
    """Recalcule les sujets (gratuit) ; Haiku ne nomme que ceux qu'il n'a jamais vus."""
    from .topic_agent import log_run

    async with _lock:
        found = await asyncio.to_thread(compute)
        state = load()
        names = state.get("names", {})
        missing = [f for f in found if f.key not in names]
        # Des titres lus partent à l'IA : seulement si le lecteur l'a accepté.
        settings = load_settings()
        if missing and settings.readings_ai and consented(settings) and (llm or any_engine(engine_status())):
            meter = RunMeter()
            try:
                names.update(await _name(missing, llm or get_llm(), meter))
            except Exception as e:  # le sujet reste affiché, nommé par ses mots-clés
                events.publish("warning", message=f"Sujets de tes lectures : nommage impossible ({e})")
            finally:
                log_run("recurring", meter)
        topics = []
        for f in found:
            meta = names.get(f.key) or fallback(f)
            if not meta.get("followable", True):
                continue
            topics.append({"key": f.key, "name": meta["name"], "prompt": meta["prompt"], "named_by": meta.get("by", "haiku"), "label": f.label, "keywords": f.keys[:8], "reading_ids": f.reading_ids, "count": f.count, "days": f.days, "media": f.media, "first": f.first, "last": f.last, "reason": f.reason, "titles": f.titles, "related_topic_id": f.related_topic_id})
        result = {"topics": topics, "generated_at": datetime.now(timezone.utc).isoformat()}
        _save({"names": names, "result": result})
    events.publish("recurring", count=len(topics))
    return result


async def latest() -> dict:
    """Le dernier résultat ; calculé s'il n'existe pas encore."""
    result = load().get("result")
    return result if result is not None else await refresh()
