"""Complément de collecte quand la collecte ne suffit pas : la recherche web du modèle (Claude,
OpenAI, Gemini, OpenRouter), et sinon Bing Actualités, avec toutes les requêtes du sujet. Ainsi
le complément marche avec n'importe quelle clé, sans clé de recherche en plus. Seules les
adresses trouvées sont reprises : elles passent ensuite par la même extraction et le même tri
que le reste (une page qu'on ne peut pas lire est abandonnée)."""

from __future__ import annotations

from datetime import datetime

from ..agents.llm import LLM, RunMeter
from . import bing_news
from .base import Candidate


async def search(llm: LLM, meter: RunMeter, model: str, subject: str, queries: list[str], since: datetime, max_uses: int = 3, by_lang: dict[str, list[str]] | None = None) -> list[Candidate]:
    """`by_lang` : les requêtes par langue, pour Bing ; à défaut, `queries` et le sujet en français."""
    prompt = (
        f"Trouve des articles de presse publiés depuis le {since:%d/%m/%Y} sur ce sujet : {subject}.\n"
        f"Pistes de recherche : {'; '.join(queries)}.\n"
        "Cherche en français et en anglais, privilégie des médias différents (agences, presse nationale, "
        "presse étrangère, sources officielles). Ne rédige rien d'autre que la liste demandée."
    )
    found = await llm.search(meter, model=model, prompt=prompt, max_uses=max_uses)
    if found:
        return [Candidate(url=r["url"], title=r.get("title") or r["url"], origin="claude_search") for r in found]
    return await fallback(meter, subject, by_lang or {"fr": queries}, since)


async def fallback(meter: RunMeter, subject: str, by_lang: dict[str, list[str]], since: datetime) -> list[Candidate]:
    """Bing Actualités, quand le modèle n'a pas de recherche web ou qu'elle ne trouve rien."""
    if not bing_news.enabled():
        meter.note("recherche complémentaire : pas de recherche web chez ce modèle, et Bing Actualités est coupé")
        return []
    queries = {lang: [q for q in qs if q.strip()] for lang, qs in by_lang.items()}
    first = next(iter(queries), "fr")
    if len(subject.split()) <= 8:  # un nom de sujet court sert de requête ; un résumé, non
        queries[first] = [subject, *queries.get(first, [])]
    found = await bing_news.search(queries, since, per_lang=7)
    meter.note(f"recherche complémentaire par Bing Actualités : {len(found)} article(s) trouvé(s)")
    return found
