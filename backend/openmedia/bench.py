"""Le banc d'essai des modèles : le vrai pipeline (tri, recoupement, rédaction de la fiche,
garde-fous) rejoué sur un même jeu d'articles fictifs, pour comparer des modèles sur pièces.

    python -m openmedia banc --modeles deepseek:deepseek-v4-pro,zai:glm-5.3,claude-sonnet-5-5

Chaque modèle tient tous les rôles. Les mesures sont calculées par le programme, pas jugées
par une IA : tri conforme à ce qu'on attend, fait chiffré bien recoupé, références inventées,
chiffres introuvables, statuts « confirmé » corrigés par le code, réponses à redemander,
paramètres refusés, tokens, coût et durée. Le rapport est écrit dans le dossier de données.

Le sujet, les médias et les articles sont inventés (la ville de Valmont n'existe pas) : aucun
média réel n'est cité, et rien ne dépend de l'actualité du jour.
"""

from __future__ import annotations

import copy
import time
from datetime import datetime, timezone

from .agents.llm import LLMError, NoApiKey, RunMeter, get_llm
from .agents.providers import catalog
from .agents.synth import enforce_statuses, synthesize, validate
from .agents.triage import triage
from .agents.verify import verify
from .config import ConsentRequired, data_dir
from .models import Article, Source

SPEC = {
    "name": "Le tramway de Valmont",
    "summary": "Le projet de deuxième ligne de tramway (T2) de la métropole de Valmont : décisions, financement, calendrier, oppositions.",
    "angle": "Les décisions votées, les chiffres officiels et le calendrier ; les positions des élus et des riverains.",
    "keywords": ["tramway", "Valmont", "ligne T2"],
    "queries_fr": ["tramway Valmont", "ligne T2 Valmont"],
    "queries_en": [],
}


def _source(domain: str, name: str, owner: str, quality: float, origin: str, kind: str = "regional") -> Source:
    return Source(domain=domain, name=name, owner=owner, kind=kind, country="FR", quality=quality, quality_origin=origin)


SOURCES = {
    "gazette": _source("gazette-valmont.example", "La Gazette de Valmont", "Groupe Gazette", 0.8, "lecteur"),
    "courrier": _source("courrier-du-val.example", "Le Courrier du Val", "Éditions du Val", 0.8, "lecteur"),
    "radio": _source("radio-valmont.example", "Radio Valmont", "Radio Valmont SA", 0.75, "lecteur"),
    "flash": _source("valmont-flash.example", "Valmont Flash", "Valmont Flash", 0.5, "ia", kind="blog"),
    "tribune": _source("regard-citoyen.example", "Regard citoyen", "Association Regard citoyen", 0.5, "ia", kind="blog"),
    "rumeurs": _source("echos-du-net.example", "Les Échos du net", "inconnu", 0.2, "ia", kind="blog"),
    "sport": _source("valmont-sport.example", "Valmont Sport", "Groupe Gazette", 0.7, "lecteur"),
}

_DAY = datetime(2026, 10, 14, 18, 0, tzinfo=timezone.utc)

# (clé de source, titre, texte, dépêche, nature attendue)
ARTICLES = [
    ("gazette", "Tramway : le tracé de la ligne T2 adopté par la métropole",
     "Le conseil métropolitain de Valmont a adopté mardi soir le tracé définitif de la ligne T2 du tramway, par 64 voix contre 18. "
     "La ligne mesurera 12,4 kilomètres et desservira 21 stations, de la gare centrale au quartier des Tanneurs. Le budget est fixé à 480 millions d'euros. "
     "Les travaux doivent commencer au premier trimestre 2027, pour une mise en service annoncée en 2030. La présidente de la métropole, Hélène Marchal, "
     "a salué « un vote historique ». L'opposition a voté contre, en dénonçant un coût sous-estimé.", "", "fait"),
    ("courrier", "Valmont vote sa deuxième ligne de tramway, 480 millions d'euros sur la table",
     "C'est fait : après deux ans de concertation, les élus métropolitains ont validé mardi la ligne T2, longue de 12,4 km. Elle comptera 21 arrêts. "
     "Le financement de 480 millions d'euros repose sur la métropole, la région et l'État, qui apportera 96 millions d'euros au titre de l'appel à projets "
     "pour les transports collectifs. Premier coup de pioche prévu début 2027, premiers voyageurs attendus en 2030.", "", "fait"),
    ("flash", "Valmont : feu vert pour la ligne T2 du tramway",
     "(AFP) Le conseil métropolitain de Valmont a approuvé mardi la création d'une deuxième ligne de tramway de 12,4 km et 21 stations, "
     "pour un coût de 480 millions d'euros, a-t-on appris auprès de la métropole. La mise en service est prévue en 2030.", "AFP", "fait"),
    ("radio", "Tramway T2 : l'opposition chiffre le coût réel à 600 millions",
     "Au lendemain du vote, le chef de l'opposition métropolitaine, Bruno Lacaze, affirme que le coût réel de la ligne T2 « dépassera 600 millions d'euros » "
     "en raison de la hausse du prix de l'acier. La métropole maintient son estimation de 480 millions et rappelle qu'une provision pour aléas de 8 % est incluse.", "", "reaction"),
    ("tribune", "Tribune : ce tramway est une folie",
     "Une fois de plus, nos élus engloutissent l'argent public dans un projet pharaonique. Ce tramway défigurera le centre historique et ne servira à rien : "
     "les Valmontais veulent des bus, pas des rails. Il est encore temps de renoncer à cette folie.", "", "opinion"),
    ("rumeurs", "EXCLUSIF : la présidente de la métropole prête à démissionner ?",
     "Selon des sources qui préfèrent rester anonymes, Hélène Marchal envisagerait de quitter son poste après le vote du tramway. "
     "Rien n'est confirmé, mais les rumeurs vont bon train dans les couloirs.", "", "rumeur"),
    ("sport", "Football : le FC Valmont s'impose 2-0 face à Rivebelle",
     "Le FC Valmont a battu Rivebelle 2-0 samedi, grâce à un doublé de son attaquant. Le club remonte à la quatrième place du classement.", "", "hors_sujet"),
]


def material() -> tuple[list[tuple[Article, Source]], dict[int, str]]:
    pairs, expected = [], {}
    for i, (key, title, text, wire, nature) in enumerate(ARTICLES, start=1):
        source = SOURCES[key]
        pairs.append((Article(id=i, url=f"https://{source.domain}/article-{i}", title=title, domain=source.domain, published_at=_DAY, lang="fr", text=text, wire=wire), source))
        expected[i] = nature
    return pairs, expected


async def run_model(model: str) -> dict:
    """Le pipeline complet pour un modèle, et ses mesures. Jamais d'exception."""
    llm = get_llm()
    provider = catalog.split(model)[0]
    if provider not in ("local",) and not llm.available(provider):
        return {"model": model, "error": f"pas de clé {catalog.PROVIDERS[provider].label}"}
    pairs, expected = material()
    meta = {a.id: (a, s) for a, s in pairs}
    meter = RunMeter()
    started = time.monotonic()
    result: dict = {"model": model}
    try:
        verdicts = await triage(llm, meter, model, SPEC, pairs)
        kept = {i: v for i, v in verdicts.items() if v.keep and v.relevance >= 0.5 and v.nature != "hors_sujet"}
        result["triage"] = {i: v.nature for i, v in verdicts.items()}
        checks = {
            "hors sujet écarté": 7 not in kept,
            "rumeur écartée ou signalée": 6 not in kept or verdicts[6].nature == "rumeur",
            "tribune lue comme opinion": 5 in verdicts and verdicts[5].nature == "opinion",
            "faits du vote gardés": all(i in kept for i in (1, 2)),
        }
        facts = await verify(llm, meter, model, kept, meta)
        budget = [f for f in facts if "480" in f.text.replace(" ", "")]
        checks["480 M€ confirmé par deux sources indépendantes"] = any(f.status == "confirme" for f in budget)
        checks["600 M€ non confirmé (une seule source)"] = not any("600" in f.text and f.status == "confirme" for f in facts)
        fiche = await synthesize(llm, meter, model, spec=SPEC, previous=None, facts=facts, pairs=[meta[i] for i in kept], alerts=[], today="2026-10-15")
        raw = fiche.model_dump()
        refs_before = _count_refs(raw)
        content = validate(copy.deepcopy(raw), {i: (meta[i][0].text or "") for i in kept})
        result["refs_inventees"] = refs_before - _count_refs(content)
        result["chiffres_introuvables"] = sum(1 for key in ("whats_new", "key_facts") for item in content.get(key, []) if item.get("check") == "chiffre_non_retrouve")
        result["statuts_corriges"] = enforce_statuses(content, lambda i: meta.get(i))
        result["checks"] = checks
        result["fiche"] = content
    except (NoApiKey, ConsentRequired, LLMError) as e:
        result["error"] = str(e)
    except Exception as e:  # noqa: BLE001 — un modèle en échec ne bloque pas le banc
        result["error"] = f"erreur inattendue : {e}"
    result["reprises"] = sum(1 for line in meter.log if "réponse invalide" in line or "réponse vide" in line)
    result["replis"] = [line for line in meter.log if "refuse un paramètre" in line or "coupé pendant" in line or "filtre de contenu" in line]
    result["seconds"] = round(time.monotonic() - started, 1)
    result["cost_usd"] = round(meter.cost_usd, 4) if all(c["cost"] is not None for c in meter.calls) else None
    result["tokens"] = meter.input_tokens + meter.output_tokens
    return result


def _count_refs(content: dict) -> int:
    return sum(len(item.get("refs", [])) for key in ("whats_new", "key_facts", "timeline", "perspectives") for item in content.get(key, []) if isinstance(item, dict))


def report(results: list[dict]) -> str:
    lines = [f"# Banc d'essai openMedia · {datetime.now():%d/%m/%Y %H:%M}", "", "Sujet fictif : le tramway de Valmont, 7 articles inventés (2 sources indépendantes, une dépêche reprise, une réaction, une tribune, une rumeur, un hors-sujet).", ""]
    lines += ["| Modèle | Contrôles réussis | Réf. inventées | Chiffres introuvables | « Confirmé » corrigés | Reprises | Replis | Coût | Durée |", "|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        if r.get("error") and "checks" not in r:
            lines.append(f"| `{r['model']}` | échec : {r['error']} | | | | | | | |")
            continue
        passed = sum(r["checks"].values())
        cost = f"{r['cost_usd']:.4f} $" if r.get("cost_usd") is not None else "prix inconnu"
        lines.append(f"| `{r['model']}` | {passed}/{len(r['checks'])} | {r['refs_inventees']} | {r['chiffres_introuvables']} | {r['statuts_corriges']} | {r['reprises']} | {len(r['replis'])} | {cost} | {r['seconds']} s |")
    for r in results:
        if "checks" in r:
            lines += ["", f"## `{r['model']}`", ""]
            lines += [f"- {'✓' if ok else '✗'} {name}" for name, ok in r["checks"].items()]
            lines += [f"- repli : {line}" for line in r["replis"]]
            if r.get("error"):
                lines.append(f"- erreur : {r['error']}")
            fiche = r.get("fiche") or {}
            if fiche.get("lede"):
                lines += ["", f"> {fiche['lede']}"]
    lines += ["", "Lecture : « Réf. inventées » compte les références retirées par le programme ; « « Confirmé » corrigés », les faits que le modèle disait confirmés et que la règle des deux sources indépendantes a rétrogradés. Plus ces nombres sont bas, plus le modèle est fiable pour openMedia."]
    return "\n".join(lines) + "\n"


async def bench(models: list[str]) -> tuple[list[dict], str]:
    results = []
    for model in models:
        print(f"… {model}", flush=True)
        results.append(await run_model(model))
    text = report(results)
    path = data_dir() / f"banc-{datetime.now():%Y%m%d-%H%M}.md"
    path.write_text(text, encoding="utf-8")
    return results, str(path)


__all__ = ["bench", "material", "report", "run_model"]
