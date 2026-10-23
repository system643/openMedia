"""« Tester ce modèle » : un court appel structuré, pour savoir tout de suite si un modèle
choisi dans Réglages marche avec openMedia (JSON valide, mode retenu, durée, coût)."""

from __future__ import annotations

import time

from pydantic import BaseModel

from .llm import LLMError, NoApiKey, RunMeter, get_llm
from .providers import catalog

TEXT = (
    "Le conseil métropolitain de Valmont (France) a voté mardi le tracé de la ligne T2 du tramway : "
    "12,4 km et 21 stations, pour un budget de 480 millions d'euros. La mise en service est prévue en 2030."
)


class CheckedFact(BaseModel):
    fact: str
    figure: str


class ModelCheck(BaseModel):
    city: str
    country: str
    facts: list[CheckedFact]


async def check_model(model: str) -> dict:
    """Le résultat de l'essai, prêt pour l'interface ; jamais d'exception."""
    from .providers.openai_compat import LEARNED
    from .topic_agent import log_run

    meter = RunMeter()
    started = time.monotonic()
    try:
        llm = get_llm()
        provider, name = llm.resolve(model, meter)
        if provider != "local" and f"{provider}:{name}" != model and name != model:
            return {"ok": False, "error": f"Pas de moteur pour {model} : ajoute la clé de ce fournisseur, ou choisis un autre modèle."}
        out = await llm.parse(meter, model=model, task="check", content=TEXT, schema=ModelCheck, effort="low", max_tokens=1500)
    except (NoApiKey, LLMError) as e:
        log_run("check", meter, status="error", error=str(e))
        return {"ok": False, "error": str(e), "notes": meter.log}
    except Exception as e:  # noqa: BLE001 — l'essai rend toujours une réponse lisible
        log_run("check", meter, status="error", error=str(e))
        return {"ok": False, "error": f"Erreur inattendue : {e}", "notes": meter.log}
    log_run("check", meter)
    figures = " ".join(f.figure for f in out.facts)
    faithful = "480" in figures and "21" in figures and out.city.lower().startswith("valmont")
    mode = LEARNED.get((provider, name), {}).get("structured") or (catalog.PROVIDERS[provider].structured if provider in catalog.PROVIDERS else "schema")
    return {
        "ok": True,
        "faithful": faithful,
        "mode": mode,
        "seconds": round(time.monotonic() - started, 1),
        "cost_usd": round(meter.cost_usd, 5),
        "tokens": meter.input_tokens + meter.output_tokens,
        "notes": meter.log,
    }
