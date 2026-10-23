"""Rédaction de la nouvelle version de la fiche, puis garde-fous : références valides,
chiffres retrouvés dans les sources, relecture de neutralité et une révision au plus, par
correctifs ciblés (la fiche n'est jamais réécrite en entier à cette étape)."""

from __future__ import annotations

import re

from ..models import Article, Source
from ..security import MASKED, clean_deep, injection_signals
from .llm import LLM, RunMeter
from .freshness import first_reported
from .material import article_block, as_json, confirms, ref_id
from .schemas import Fact, FicheContent, NeutralityReport, RevisePatch, RevisePatches

SOURCED_LISTS = ("whats_new", "key_facts", "timeline", "perspectives", "announcements")
_NUMBER = re.compile(r"\d[\d\s  .,]*\d|\d")


def _digits(text: str) -> str:
    return re.sub(r"[\s  .,]", "", text)


def _meaningful_numbers(text: str) -> list[str]:
    out = []
    for raw in _NUMBER.findall(text):
        d = _digits(raw)
        if len(d) <= 2 or (len(d) == 4 and 1900 <= int(d) <= 2100):
            continue  # jours, mois, années : trop ambigus pour être vérifiés ainsi
        out.append(d)
    return out


def missing_numbers(body: str, cited: str) -> list[str]:
    """Les chiffres de `body` introuvables dans le texte des articles cités."""
    digits = _digits(cited)
    return [n for n in _meaningful_numbers(body) if n not in digits]


_INLINE_REFS = re.compile(r"\s*[\[(]\s*S\d+(?:\s*[,;]\s*S\d+)*\s*[\])]")


def strip_refs(text: str) -> str:
    return _INLINE_REFS.sub("", text).strip()


TEXT_FIELDS = ("text", "event", "position", "body")


def strip_inline_refs(content: dict) -> dict:
    """Les références vont dans `refs` ; on retire celles que le modèle aurait laissées dans le texte."""
    for key in ("lede",):
        if isinstance(content.get(key), str):
            content[key] = _INLINE_REFS.sub("", content[key]).strip()
    for key in (*SOURCED_LISTS, "custom_sections"):
        for item in content.get(key, []):
            for field in TEXT_FIELDS:
                if isinstance(item.get(field), str):
                    item[field] = _INLINE_REFS.sub("", item[field]).strip()
    for key in ("changes", "uncertainties", "watch"):
        content[key] = [_INLINE_REFS.sub("", x).strip() for x in content.get(key, [])]
    return content


def apply_freshness(content: dict, stale: dict) -> dict:
    """Une « nouveauté » qui reprend une nouvelle déjà parue avant ce passage quitte
    `whats_new` pour les faits clés, datée de sa première apparition (le modèle en a la
    consigne ; ceci la garantit). `stale` : voir `freshness.stale_index`."""
    if not stale or not stale.get("facts"):
        return content
    moved, fresh = [], []
    for item in content.get("whats_new", []):
        day = first_reported(item.get("text", ""), item.get("refs", []), stale)
        if day:
            item["first_reported"] = day
            moved.append(item)
        else:
            fresh.append(item)
    content["whats_new"] = fresh
    known = {tuple(sorted(i.get("refs", []))) for i in content.get("key_facts", [])}
    content["key_facts"] = content.get("key_facts", []) + [i for i in moved if tuple(sorted(i["refs"])) not in known]
    for item in content["key_facts"]:
        day = first_reported(item.get("text", ""), item.get("refs", []), stale)
        if day:
            item["first_reported"] = day
    return content


def validate(content: dict, texts: dict[int, str], stale: dict | None = None) -> dict:
    """Retire les références inconnues et les éléments devenus sans source ; signale les
    chiffres introuvables dans les articles cités, et les passages qui s'adressent à une IA
    (`contenu_suspect`, masqués pour les autres assistants). `texts` : {id d'article: texte}.
    `stale` : les nouvelles déjà parues avant ce passage (`apply_freshness`)."""
    content.update(clean_deep(content))  # pas de balise ni de caractère invisible dans une fiche
    strip_inline_refs(content)
    apply_freshness(content, stale or {})
    if injection_signals(content.get("lede")):
        content["lede"] = MASKED
    for key in SOURCED_LISTS:
        kept = []
        for item in content.get(key, []):
            item["refs"] = [r for r in item.get("refs", []) if ref_id(r) in texts]
            if not item["refs"]:
                continue
            if "contradicted_by" in item:
                item["contradicted_by"] = [r for r in item["contradicted_by"] if ref_id(r) in texts]
            body = item.get("text") or item.get("event") or item.get("position") or ""
            if missing_numbers(body, " ".join(texts[ref_id(r)] for r in item["refs"])):
                item["check"] = "chiffre_non_retrouve"
            if injection_signals(body):
                item["check"] = "contenu_suspect"
            kept.append(item)
        content[key] = kept
    for section in content.get("custom_sections", []):
        section["refs"] = [r for r in section.get("refs", []) if ref_id(r) in texts]
    if not content.get("whats_new"):
        content["nothing_new"] = content.get("nothing_new", True) or not content.get("changes")
    return content


# Un élément dont le texte dit lui-même qu'il n'est pas établi ne peut pas porter « confirmé ».
DOUBT = re.compile(r"non[- ]confirm|pas (encore )?confirm|non[- ]vérifi|pas (été )?vérifi|selon [^.;]{0,60}\bseule?s?\b|une seule source|unconfirmed|not (been )?(independently )?(confirmed|verified)", re.I)


def enforce_statuses(content: dict, pairs_of) -> int:
    """Le statut « confirmé » d'un élément n'est pas celui que le modèle recopie : le code le
    recalcule sur ses références (`material.confirms`). `pairs_of(id)` rend (article, source)
    ou None. Rend le nombre d'éléments rétrogradés en « non confirmé »."""
    downgraded = 0
    for key in SOURCED_LISTS:
        for item in content.get(key, []):
            if item.get("status") != "confirme":
                continue
            pairs = [p for p in (pairs_of(ref_id(r)) for r in item.get("refs", [])) if p]
            if not confirms(pairs) or DOUBT.search(item.get("text") or item.get("event") or ""):
                item["status"] = "non_confirme"
                downgraded += 1
    return downgraded


def cited_ids(content: dict) -> set[int]:
    ids = set()
    for key in (*SOURCED_LISTS, "custom_sections", "corrections"):
        for item in content.get(key, []):
            ids |= {ref_id(r) for r in [*item.get("refs", []), *item.get("contradicted_by", [])] if ref_id(r)}
    return ids


async def synthesize(
    llm: LLM,
    meter: RunMeter,
    model: str,
    *,
    task: str = "synth",
    spec: dict,
    previous: dict | None,
    facts: list[Fact],
    pairs: list[tuple[Article, Source]],
    alerts: list[str],
    today: str,
    rectified: list[dict] | None = None,
) -> FicheContent:
    articles = "\n\n".join(article_block(a, s, 1500) for a, s in pairs[:25])
    hidden = {"probe", "claim_id", "known_text", "known_status", "novelty", "new_refs", "new_media"}
    fresh = [f.model_dump(exclude=hidden | {"first_reported"}) for f in facts if not f.first_reported]
    old = [f.model_dump(exclude=hidden) for f in facts if f.first_reported]
    content = (
        f"Date du jour : {today}\n\n"
        f"<specification>\n{as_json(spec)}\n</specification>\n\n"
        f"<fiche_precedente>\n{as_json(previous) if previous else 'Aucune : premier passage.'}\n</fiche_precedente>\n\n"
        f"<faits_recoupes>\n{as_json(fresh)}\n</faits_recoupes>\n\n"
        + (f"<faits_deja_parus>\n{as_json(old)}\n</faits_deja_parus>\n\n" if old else "")
        + (f"<faits_rectifies>\n{as_json(rectified)}\n</faits_rectifies>\n\n" if rectified else "")
        + f"<angles_morts>\n{as_json(alerts)}\n</angles_morts>\n\n"
        f"<articles>\n{articles}\n</articles>"
    )
    return await llm.parse(meter, model=model, task=task, content=content, schema=FicheContent, effort="medium", max_tokens=16000)


# Champs de la fiche qui ne sont pas de la prose : un correctif n'y touche jamais.
NOT_PROSE = {"refs", "contradicted_by", "status", "state", "confidence", "date", "due", "new_status", "previous_status", "check", "first_reported"}


def _prose(node):
    """(conteneur, clé) de chaque texte rédigé de la fiche."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in NOT_PROSE:
                continue
            if isinstance(v, str):
                yield node, k
            else:
                yield from _prose(v)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            if isinstance(v, str):
                yield node, i
            else:
                yield from _prose(v)


def _closes(text: str) -> bool:
    return text.strip().rstrip("»\"' )").endswith((".", "!", "?", "…"))


def apply_patches(content: dict, patches: list[RevisePatch]) -> tuple[int, list[str]]:
    """Applique les correctifs dont l'extrait figure exactement une fois dans la fiche et qui
    n'introduisent ni chiffre ni référence absents de l'extrait. Rend (appliqués, écartés)."""
    applied, skipped = 0, []
    for patch in patches:
        excerpt = patch.excerpt.strip()
        if not excerpt:
            continue
        spots = [(c, k) for c, k in _prose(content) if excerpt in c[k]]
        hits = sum(c[k].count(excerpt) for c, k in spots)
        if hits != 1:
            skipped.append(f"« {excerpt[:60]} » {'introuvable' if hits == 0 else 'ambigu'}")
            continue
        if set(_meaningful_numbers(patch.replacement)) - set(_meaningful_numbers(excerpt)) or set(re.findall(r"S\d+", patch.replacement)) - set(re.findall(r"S\d+", excerpt)):
            skipped.append(f"« {excerpt[:60]} » : le correctif ajoute un chiffre ou une source")
            continue
        if _closes(excerpt) != _closes(patch.replacement):
            # Une phrase entière collée dans un fragment (ou l'inverse) casse la phrase d'accueil.
            skipped.append(f"« {excerpt[:60]} » : le correctif ne remplace pas une phrase par une phrase")
            continue
        container, key = spots[0]
        container[key] = container[key].replace(excerpt, patch.replacement.strip())
        applied += 1
    return applied, skipped


async def neutrality_pass(llm: LLM, meter: RunMeter, review_model: str, write_model: str, fiche: FicheContent) -> tuple[FicheContent, list[dict]]:
    report = await llm.parse(meter, model=review_model, task="neutrality", content=f"<fiche>\n{fiche.model_dump_json(indent=1)}\n</fiche>", schema=NeutralityReport, effort="low", max_tokens=4000)
    issues = [i.model_dump() for i in report.issues]
    if not issues:
        return fiche, []
    result = await llm.parse(
        meter,
        model=write_model,
        task="revise",
        content=f"<fiche>\n{fiche.model_dump_json(indent=1)}\n</fiche>\n\n<problemes>\n{as_json(issues)}\n</problemes>",
        schema=RevisePatches,
        effort="low",
        max_tokens=4000,
    )
    content = fiche.model_dump()
    applied, skipped = apply_patches(content, result.patches)
    meter.note(f"révision : {applied} correctif(s) appliqué(s)" + (f", écartés : {'; '.join(skipped)}" if skipped else ""))
    return FicheContent.model_validate(content), issues
