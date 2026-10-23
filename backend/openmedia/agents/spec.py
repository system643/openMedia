"""Transformer le prompt du lecteur en spécification de recherche."""

from __future__ import annotations

from datetime import datetime

from .llm import LLM, RunMeter
from .schemas import TopicSpec


async def build_spec(llm: LLM, meter: RunMeter, model: str, user_prompt: str, now: datetime, kind: str = "actualite", fields: list[str] | None = None) -> TopicSpec:
    content = f"Date du jour : {now:%Y-%m-%d}\n\nPrompt du lecteur :\n<prompt>\n{user_prompt.strip()}\n</prompt>"
    if kind == "recherche":
        content += (
            f"\n\nC'est une veille de RECHERCHE SCIENTIFIQUE (domaines : {', '.join(fields or []) or 'non précisés'}). "
            "Les requêtes interrogeront arXiv, OpenAlex, PubMed et HAL : utilise le vocabulaire des chercheurs, surtout en anglais "
            "(termes techniques, noms de méthodes), pas celui de la presse."
        )
    return await llm.parse(meter, model=model, task="spec", content=content, schema=TopicSpec, effort="low", max_tokens=4000)
