"""Qualification des sources que le jeu de notation ouvert ne couvre pas : un appel groupé
par passage, une seule fois par domaine (la note est gardée dans le registre)."""

from __future__ import annotations

import asyncio

from ..config import ConsentRequired
from ..db import session
from ..models import Article, Source
from ..security import clean
from ..sources import registry
from ..sources.quality import CATEGORY_KIND, CATEGORY_LABEL, from_category
from .llm import LLM, NoApiKey, RunMeter
from .material import SOCIAL, as_json
from .schemas import QualifyResult

BATCH = 25  # domaines par appel
MAX_DOMAINS = 75  # par passage ; les suivants attendent le prochain


def _pending(pairs: list[tuple[Article, Source]]) -> dict[str, list[Article]]:
    todo: dict[str, list[Article]] = {}
    for article, source in pairs:
        if source.quality is None and source.quality_origin != "lecteur" and source.kind not in (SOCIAL, "recherche") and article.kind != "recherche":
            todo.setdefault(source.domain, []).append(article)
    return dict(list(todo.items())[:MAX_DOMAINS])


async def qualify_sources(llm: LLM, meter: RunMeter, model: str, pairs: list[tuple[Article, Source]]) -> int:
    """Note les domaines encore sans note parmi `pairs`, en base et dans les `Source` reçues
    (le reste du passage les lit). Rend le nombre de domaines qualifiés ; un échec n'arrête rien."""
    todo = _pending(pairs)
    if not todo:
        return 0
    rows = [{"domaine": d, "articles": [{"titre": a.title, "debut": (a.text or "")[:300]} for a in arts[:3]]} for d, arts in todo.items()]

    async def batch(chunk: list[dict]):
        try:
            result = await llm.parse(meter, model=model, task="qualify", content=f"Domaines à qualifier :\n{as_json(chunk)}", schema=QualifyResult, effort="low", max_tokens=6000)
            return result.sources
        except (NoApiKey, ConsentRequired):
            raise
        except Exception as e:  # noqa: BLE001 — sans note, la source garde simplement son statut actuel
            meter.note(f"qualification des sources : lot ignoré ({e})")
            return []

    results = await asyncio.gather(*[batch(rows[i : i + BATCH]) for i in range(0, len(rows), BATCH)])
    verdicts = {q.domain.strip().lower().removeprefix("www."): q for qs in results for q in qs}
    done: dict[str, dict] = {}
    with session() as s:
        for domain in todo:
            q = verdicts.get(domain)
            row = s.get(Source, domain)
            if not q or not row or row.quality is not None or row.quality_origin == "lecteur":
                continue
            values = {"quality": from_category(q.category, q.reliability), "quality_origin": "ia", "quality_note": f"{CATEGORY_LABEL[q.category]} : {clean(q.reason)}"[:300]}
            if row.kind == "unknown":
                values["kind"] = CATEGORY_KIND[q.category]
            if row.name == row.domain and clean(q.name).strip():
                values["name"] = clean(q.name).strip()[:80]
            for k, v in values.items():
                setattr(row, k, v)
            s.add(row)
            done[domain] = values
        s.commit()
    registry.invalidate()
    for _, source in pairs:
        for k, v in done.get(source.domain, {}).items():
            setattr(source, k, v)
    if done:
        meter.note(f"qualification : {len(done)} source(s) notée(s)")
    return len(done)
