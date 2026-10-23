"""Complément de collecte par la recherche web de Claude, quand GDELT et les unes des médias ne
suffisent pas. Seules les adresses trouvées sont reprises : elles passent ensuite par la même
extraction et le même tri que le reste (une page qu'on ne peut pas lire est abandonnée)."""

from __future__ import annotations

from datetime import datetime

from ..agents.llm import LLM, RunMeter
from .base import Candidate


async def search(llm: LLM, meter: RunMeter, model: str, subject: str, queries: list[str], since: datetime, max_uses: int = 3) -> list[Candidate]:
    prompt = (
        f"Trouve des articles de presse publiés depuis le {since:%d/%m/%Y} sur ce sujet : {subject}.\n"
        f"Pistes de recherche : {'; '.join(queries)}.\n"
        "Cherche en français et en anglais, privilégie des médias différents (agences, presse nationale, "
        "presse étrangère, sources officielles). Ne rédige rien d'autre que la liste demandée."
    )
    found = await llm.search(meter, model=model, prompt=prompt, max_uses=max_uses)
    return [Candidate(url=r["url"], title=r.get("title") or r["url"], origin="claude_search") for r in found]
