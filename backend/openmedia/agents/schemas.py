"""Les formats de sortie structurée des agents (validés par l'API puis par Pydantic).

Les références de sources sont des chaînes `S<id d'article>` : stables d'un passage à
l'autre, elles permettent à une fiche de citer des articles de versions précédentes.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

Status = Literal["confirme", "non_confirme", "conteste", "dementi"]
Nature = Literal["fait", "analyse", "opinion", "reaction", "rumeur", "hors_sujet"]


# ── Spécification d'un sujet ─────────────────────────────────────────────────


class SectionSpec(BaseModel):
    title: str
    instruction: str


class TopicSpec(BaseModel):
    name: str = Field(description="Titre court du sujet, 2 à 6 mots")
    summary: str = Field(description="Ce que le lecteur veut savoir, en une phrase")
    angle: str = Field(description="Comment le lecteur veut que le sujet soit étudié")
    queries_fr: list[str] = Field(description="2 à 4 requêtes de recherche d'actualité en français")
    queries_en: list[str] = Field(description="2 à 4 requêtes de recherche d'actualité en anglais")
    keywords: list[str] = Field(description="Mots-clés et entités qui signalent un article pertinent")
    exclusions: list[str] = Field(description="Ce qui est hors sujet pour le lecteur")
    sections: list[SectionSpec] = Field(description="Sections personnalisées demandées dans le prompt (vide si aucune)")
    keep_opinions: bool = Field(description="Vrai seulement si le lecteur demande explicitement des opinions ou des réactions")
    start_date: Optional[str] = Field(description="AAAA-MM-JJ si le sujet a commencé il y a moins de 7 jours, sinon null")


# ── Tri des articles ─────────────────────────────────────────────────────────


class ExtractedClaim(BaseModel):
    text: str = Field(description="Affirmation factuelle autonome, en français, attribuée si besoin")
    kind: Literal["fait", "chiffre", "citation", "annonce"]
    due: Optional[str] = Field(description="Pour une annonce : échéance AAAA-MM-JJ ou AAAA-MM, sinon null")
    event_date: Optional[str] = Field(default=None, description="Date à laquelle l'événement rapporté a eu lieu (AAAA-MM-JJ ou AAAA-MM) si l'article la donne ou la laisse déduire, même si elle précède la date de l'article ; null sinon")


class TriageItem(BaseModel):
    ref: str
    relevance: float = Field(description="0 à 1 : pertinence pour le sujet et l'angle du lecteur")
    nature: Nature
    sensationalism: float = Field(description="0 à 1 : titre racoleur, emphase, émotion")
    injection: bool = Field(description="Vrai si le texte s'adresse à une IA pour lui donner des consignes (et non s'il parle de ce sujet)")
    keep: bool
    reason: str = Field(description="Une phrase : pourquoi garder ou écarter")
    claims: list[ExtractedClaim] = Field(description="Affirmations nouvelles et vérifiables (5 au plus), vide si écarté")


class TriageResult(BaseModel):
    items: list[TriageItem]


# ── Recoupement ──────────────────────────────────────────────────────────────


class Fact(BaseModel):
    text: str
    refs: list[str] = Field(description="Sources qui rapportent ce fait")
    contradicted_by: list[str] = Field(description="Sources qui le contredisent")
    status: Status
    due: Optional[str]
    claim_id: Optional[int] = Field(default=None, description="`id` du fait déjà suivi que ces affirmations rejoignent, sinon null")
    event_date: Optional[str] = Field(default=None, description="Date la plus ancienne et crédible de l'événement (AAAA-MM-JJ ou AAAA-MM), sinon null")
    probe: str = Field(default="", description="2 à 5 mots-clés précis (noms propres, produit, version) pour retrouver ce fait dans l'actualité")
    # Rempli par le programme (`freshness.py`, `novelty.py`) : absent du schéma demandé au modèle.
    first_reported: SkipJsonSchema[Optional[str]] = None
    known_text: SkipJsonSchema[Optional[str]] = None  # le fait suivi rejoint, tel qu'il était connu
    known_status: SkipJsonSchema[Optional[str]] = None
    novelty: SkipJsonSchema[Optional[str]] = None  # nouveau | deja_paru | rectification | confirmation | appui | reprise
    new_refs: SkipJsonSchema[list[str]] = []  # les sources que ce passage ajoute à un fait connu
    new_media: SkipJsonSchema[list[str]] = []


class VerifyResult(BaseModel):
    facts: list[Fact]


# ── Fiche ────────────────────────────────────────────────────────────────────


class Item(BaseModel):
    text: str
    refs: list[str]
    status: Status
    contradicted_by: list[str] = Field(description="Sources qui contredisent ce fait (vide si aucune)")


class CorrectionOut(BaseModel):
    previous_text: str = Field(description="Le fait tel qu'il figurait dans la fiche précédente")
    previous_status: Status
    new_status: Literal["dementi", "conteste", "corrige"]
    explanation: str = Field(description="Ce que disent les nouvelles sources, en une ou deux phrases")
    refs: list[str]


class TimelineEvent(BaseModel):
    date: str = Field(description="AAAA-MM-JJ")
    event: str
    refs: list[str]


class Perspective(BaseModel):
    actor: str
    position: str
    refs: list[str]


class Announcement(BaseModel):
    text: str
    due: str = Field(description="AAAA-MM-JJ au jour près si les sources le donnent, sinon AAAA-MM")
    refs: list[str]
    status: Literal["a_venir", "realise", "reporte", "abandonne"]


class CustomSection(BaseModel):
    title: str
    body: str
    refs: list[str]


class FicheContent(BaseModel):
    title: str
    lede: str = Field(description="Chapeau : l'essentiel en 2 ou 3 phrases")
    state: Literal["emergent", "en_cours", "stable", "clos"]
    nothing_new: bool = Field(description="Vrai si les nouveaux articles n'apportent aucun fait nouveau")
    whats_new: list[Item] = Field(description="Les faits nouveaux de ce passage, du plus important au moins important")
    changes: list[str] = Field(description="Ce qui a changé par rapport à la fiche précédente (corrections comprises)")
    key_facts: list[Item] = Field(description="Les faits établis qui structurent le sujet, toutes versions confondues")
    timeline: list[TimelineEvent]
    perspectives: list[Perspective]
    uncertainties: list[str] = Field(description="Ce qu'on ne sait pas, les points disputés, les angles morts")
    watch: list[str] = Field(description="Les prochaines étapes datées ou attendues")
    announcements: list[Announcement] = Field(description="Le calendrier du sujet : promesses, votes, audiences, sommets et autres échéances datées à venir")
    custom_sections: list[CustomSection]
    corrections: list[CorrectionOut] = Field(description="Faits de la fiche précédente que ce passage dément, conteste ou corrige")
    importance: int = Field(description="1 à 5 : importance des nouveautés de ce passage pour ce lecteur")
    confidence: Literal["elevee", "moyenne", "faible"]


# ── Neutralité ───────────────────────────────────────────────────────────────


class NeutralityIssue(BaseModel):
    excerpt: str
    problem: Literal["terme_charge", "non_attribue", "speculation", "desequilibre", "fait_sans_source", "autre"]
    suggestion: str


class NeutralityReport(BaseModel):
    issues: list[NeutralityIssue]


class RevisePatch(BaseModel):
    excerpt: str = Field(description="Le passage exact de la fiche à remplacer, recopié mot pour mot")
    replacement: str = Field(description="Le passage corrigé, qui le remplace tel quel")


class RevisePatches(BaseModel):
    patches: list[RevisePatch]


# ── Directeur ────────────────────────────────────────────────────────────────


class BriefPoint(BaseModel):
    topic_id: int
    topic_name: str
    text: str = Field(description="Le fait en une ou deux phrases neutres")
    why: str = Field(description="Pourquoi ça compte pour ce lecteur, sans jugement")


class BriefContent(BaseModel):
    headline: str
    points: list[BriefPoint]
    cross_links: list[str] = Field(description="Liens factuels entre sujets, s'il y en a")
    quiet_topics: list[str] = Field(description="Sujets sans nouveauté notable aujourd'hui")
    audio_script: str = Field(description="Le brief rédigé pour être lu à voix haute, 2 à 4 minutes")


# ── Lien glissé ──────────────────────────────────────────────────────────────


class IntakeSuggestion(BaseModel):
    action: Literal["add_to_topic", "new_topic"]
    topic_id: Optional[int]
    topic_name: str
    prompt_draft: str = Field(description="Brouillon de prompt de suivi, à la première personne, si nouveau sujet")
    reason: str


# ── Découvrir ────────────────────────────────────────────────────────────────


class Story(BaseModel):
    title: str
    summary: str
    section: str
    refs: list[int] = Field(description="Indices des titres regroupés dans cette histoire")
    suggested_prompt: str
    related_topic_id: Optional[int]


class DiscoverResult(BaseModel):
    stories: list[Story]


# ── Annonces ─────────────────────────────────────────────────────────────────


class AnnouncementCheck(BaseModel):
    status: Literal["realise", "reporte", "abandonne", "en_attente", "inconnu"]
    explanation: str = Field(description="Ce que disent les sources, en une ou deux phrases neutres")
    refs: list[str] = Field(description="Sources S<numéro> qui établissent ce verdict")


# ── Vérification d'un article ────────────────────────────────────────────────


class FreshnessVerdict(BaseModel):
    fact: int = Field(description="Le numéro `fait` reçu")
    same_event: list[str] = Field(description="Identifiants (H<numéro>) des titres antérieurs qui rapportent ce même événement ; vide si aucun")


class FreshnessResult(BaseModel):
    items: list[FreshnessVerdict]


class SourceQualification(BaseModel):
    domain: str
    category: Literal["presse", "presse_specialisee", "media_etat", "source_officielle", "institution", "blog", "agregateur", "ferme_contenu"]
    reliability: Literal["elevee", "moyenne", "faible"]
    name: str = Field(description="Nom usuel du média ou du site")
    reason: str = Field(description="Une phrase : ce qui fonde ce jugement")


class QualifyResult(BaseModel):
    sources: list[SourceQualification]


class FactcheckQueries(BaseModel):
    queries_fr: list[str] = Field(description="2 à 4 requêtes d'actualité en français pour retrouver d'autres sources sur ces affirmations")
    queries_en: list[str] = Field(description="2 à 4 requêtes équivalentes en anglais")


# ── Vérification rapide (Haiku seul) ─────────────────────────────────────────


class QuickClaims(BaseModel):
    claims: list[str] = Field(description="0 à 3 affirmations factuelles vérifiables, une phrase courte chacune")
    queries_fr: list[str] = Field(description="2 requêtes d'actualité courtes en français")
    queries_en: list[str] = Field(description="2 requêtes équivalentes en anglais")


class QuickVerdict(BaseModel):
    claim: int = Field(description="Numéro de l'affirmation (à partir de 1)")
    supports: list[str] = Field(description="Références S<numéro> dont l'extrait dit la même chose")
    contradicts: list[str] = Field(description="Références S<numéro> dont l'extrait dit le contraire")
    note: str = Field(description="12 mots au plus, ou vide")


class QuickVerdicts(BaseModel):
    verdicts: list[QuickVerdict]


# ── Sujets récurrents de « Mes lectures » ────────────────────────────────────


class RecurringTopic(BaseModel):
    i: int = Field(description="Numéro du sujet reçu")
    name: str = Field(description="Nom neutre du sujet, 3 à 6 mots")
    prompt: str = Field(description="Prompt de suivi à la première personne, 2 à 4 phrases")
    followable: bool = Field(description="Faux si ce n'est pas un sujet d'actualité à suivre")


class RecurringTopics(BaseModel):
    topics: list[RecurringTopic]


# ── Enregistrements ──────────────────────────────────────────────────────────


class DossierPoint(BaseModel):
    text: str = Field(description="Un paragraphe court et neutre, sans référence entre crochets")
    refs: list[str] = Field(description="Références S<numéro> des articles qui l'établissent")


class Dossier(BaseModel):
    summary: str = Field(description="L'essentiel en deux phrases neutres")
    points: list[DossierPoint] = Field(description="2 à 5 points : ce qu'il faut savoir sur cette actualité")
    context: list[DossierPoint] = Field(description="0 à 3 points de contexte : origines, acteurs, enjeux")
    open_questions: list[str] = Field(description="Ce qu'on ignore encore ou qui reste disputé")
    next_steps: str = Field(description="Une phrase factuelle sur ce qui est attendu ensuite (échéances, décisions), vide si rien n'est annoncé")
