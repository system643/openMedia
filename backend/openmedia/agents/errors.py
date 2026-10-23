"""Les erreurs des fournisseurs d'IA, dites en français à quelqu'un qui n'est pas développeur :
ce qui se passe, et quoi faire. Une clé refusée devient `NoApiKey` (le moteur est à régler),
le reste `LLMError` (le passage échoue et le dit)."""

from __future__ import annotations

import re

from .llm import LLMError, NoApiKey

CONTEXT = re.compile(r"context|too long|too many tokens|maximum.*tokens|n_ctx|prompt is too long|exceeds", re.I)
# Crédit épuisé, dit autrement selon les fournisseurs (DeepSeek : 402 « Insufficient Balance » ;
# Kimi, GLM, Qwen : 429 ou 400 avec un code de solde ou d'arriéré).
CREDIT = re.compile(r"insufficient.?balance|insufficient.?quota|exceeded_current_quota|balance is not enough|arrearage|account.*(?:overdue|suspended)|余额不足|credit", re.I)
# Le filtre de contenu des fournisseurs : fréquent sur les sujets politiques sensibles pour
# les fournisseurs chinois (DeepSeek « Content Exists Risk », Qwen « data_inspection_failed »,
# GLM code 1301, Kimi « high risk »).
MODERATION = re.compile(r"content exists risk|data_inspection_failed|inappropriate content|high risk|sensitive (?:content|words|information)|content_filter|contentfilter|\b1301\b|moderation|safety system", re.I)


def refused_content(detail: str) -> bool:
    return bool(MODERATION.search(detail or ""))


def http_error(label: str, status: int, detail: str = "", *, local: bool = False) -> Exception:
    """L'exception à lever pour une réponse HTTP en erreur d'un fournisseur (`label` : son nom)."""
    detail = (detail or "").strip()[:200]
    if status in (401, 403) and not CREDIT.search(detail):
        if local:
            return LLMError(f"{label} refuse la demande ({status}) : vérifie son serveur local.")
        return NoApiKey(f"La clé {label} est refusée : vérifie-la ou remplace-la dans Réglages › Moteur IA.")
    if status == 402 or CREDIT.search(detail):
        return LLMError(f"Crédit épuisé chez {label} : recharge ton compte, ou choisis un autre moteur dans Réglages › Moteur IA.")
    if CONTEXT.search(detail) or status == 413:
        if local:
            return LLMError(f"La demande dépasse la mémoire de contexte du modèle de {label} : règle la longueur de contexte à 32 768 tokens au moins (dans LM Studio, au chargement du modèle), ou choisis un modèle plus grand.")
        return LLMError(f"La demande est trop longue pour ce modèle de {label} : choisis un modèle de gamme supérieure dans Réglages › Moteur IA.")
    if status == 404:
        return LLMError(f"Modèle introuvable chez {label}{f' ({detail})' if detail else ''} : choisis-en un autre dans Réglages › Moteur IA.")
    if status in (408, 429):
        return LLMError(f"{label} limite le nombre de demandes (quota ou cadence atteints) : réessaie dans quelques minutes, ou vérifie ton crédit et tes limites chez {label}.")
    if status >= 500:
        return LLMError(f"{label} est surchargé ou indisponible pour le moment : réessaie plus tard.")
    return LLMError(f"{label} a refusé la demande ({status}){f' : {detail}' if detail else ''}.")


def claude_code_message(message: str) -> str:
    """Les messages de Claude Code qu'un lecteur ne saurait pas lire."""
    m = re.search(r"usage limit reached\|(\d{9,})", message, re.I)
    if m or re.search(r"usage limit|rate limit", message, re.I):
        when = ""
        if m:
            from datetime import datetime

            when = f" (jusqu'à {datetime.fromtimestamp(int(m.group(1))):%H:%M})"
        return f"La limite d'utilisation de ton abonnement Claude est atteinte{when} : les passages reprendront ensuite. Pour ne pas en dépendre, ajoute une clé API."
    if "error_max_budget_usd" in message:
        return "Un appel a dépassé le plafond de dépense par appel (2 $) : la demande était trop lourde, réessaie ou réduis le sujet."
    if "error_max_turns" in message:
        return "Claude Code n'a pas terminé dans le nombre d'étapes permis : réessaie."
    return f"Claude Code : {message[:300]}"
