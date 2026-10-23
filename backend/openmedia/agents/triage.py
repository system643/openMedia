"""Tri des articles par lots : pertinence, nature (fait/opinion/réaction…), affirmations."""

from __future__ import annotations

import asyncio

from ..config import ConsentRequired
from ..models import Article, Source
from .llm import LLM, LLMError, NoApiKey, RunMeter
from .material import article_block, as_json, ref
from .schemas import TriageItem, TriageResult

BATCH = 10


async def triage(llm: LLM, meter: RunMeter, model: str, spec: dict, pairs: list[tuple[Article, Source]], task: str = "triage") -> dict[int, TriageItem]:
    """Rend {id d'article: verdict}. Un lot en échec ne bloque pas les autres ; mais si aucun
    lot n'aboutit, ou si le moteur manque, le tri échoue : un passage dont l'IA est en panne
    ne doit jamais passer pour un passage « rien de neuf »."""
    sem = asyncio.Semaphore(4)
    head = f"Spécification du sujet :\n{as_json(spec)}\n\nArticles à trier :\n"

    async def batch(chunk):
        async with sem:
            content = head + "\n\n".join(article_block(a, s, 2000) for a, s in chunk)
            try:
                result = await llm.parse(meter, model=model, task=task, content=content, schema=TriageResult, effort="low", max_tokens=16000)
            except (NoApiKey, ConsentRequired):
                raise
            except Exception as e:  # noqa: BLE001 — on garde la trace et on continue
                meter.note(f"triage : lot ignoré ({e})")
                failures.append(e)
                return []
            return result.items

    failures: list[Exception] = []
    chunks = [pairs[i : i + BATCH] for i in range(0, len(pairs), BATCH)]
    results = await asyncio.gather(*[batch(c) for c in chunks])
    if chunks and len(failures) == len(chunks):
        raise LLMError(f"Le tri des articles a échoué : {failures[0]}")
    by_ref = {ref(a.id): a.id for a, _ in pairs}
    verdicts = {by_ref[item.ref]: item for items in results for item in items if item.ref in by_ref}
    # Un texte qui donne des consignes à une IA n'est pas une source : il est écarté, avec ses affirmations.
    trapped = [v for v in verdicts.values() if v.injection]
    for v in trapped:
        v.keep, v.claims, v.reason = False, [], f"Écarté : le texte contient des consignes adressées à une IA. {v.reason}".strip()
    if trapped:
        meter.note(f"sécurité : {len(trapped)} article(s) écarté(s), consignes adressées à une IA")
    return verdicts
