"""Les tables SQLite. Les fiches sont append-only : chaque passage ajoute une version."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


def now() -> datetime:
    return datetime.now(timezone.utc)


class Topic(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    prompt: str
    spec: dict = Field(default_factory=dict, sa_column=Column(JSON))
    model: Optional[str] = None  # surcharge du modèle « topic » des réglages
    languages: list = Field(default_factory=lambda: ["fr", "en"], sa_column=Column(JSON))
    feeds: list = Field(default_factory=list, sa_column=Column(JSON))  # flux RSS ajoutés
    # Rythme propre au sujet (sinon celui des réglages) : jours (`run_every_days` ou
    # `run_weekdays`, lundi = 0) et heures (`run_hours` ; `run_hour` : ancienne heure unique).
    run_hour: Optional[str] = None
    run_hours: list = Field(default_factory=list, sa_column=Column(JSON))
    run_every_days: Optional[int] = None
    run_weekdays: list = Field(default_factory=list, sa_column=Column(JSON))
    run_anchor: Optional[str] = None  # AAAA-MM-JJ : départ d'un intervalle propre (sinon l'ancre des réglages)
    # Rythme conseillé : pilote automatique, conseil écarté, journal des changements, pouls.
    rhythm: dict = Field(default_factory=dict, sa_column=Column(JSON))
    follow_deadlines: bool = True  # un passage de plus le jour d'une échéance datée et le lendemain
    importance: int = 3
    status: str = "active"  # active | sleeping | archived
    since: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    quiet_runs: int = 0  # passages consécutifs sans nouveauté (mise en veille auto)
    last_seen_at: Optional[datetime] = None  # dernière ouverture de la fiche par le lecteur
    # Sources « réseaux sociaux » en option : {"reddit": bool, "hn": bool, "telegram": ["canal", …]}
    social: dict = Field(default_factory=dict, sa_column=Column(JSON))
    kind: str = "actualite"  # actualite | recherche
    research_fields: list = Field(default_factory=list, sa_column=Column(JSON))  # ia, biologie, medecine…
    created_at: datetime = Field(default_factory=now)


class Source(SQLModel, table=True):
    domain: str = Field(primary_key=True)
    name: str
    kind: str = "unknown"  # agence | national | regional | international | institutionnel | specialise | blog | reseau_social | unknown
    country: str = "??"
    owner: str = ""
    # conglomerat | milliardaire | public | independant | cooperative | etranger | inconnu
    owner_type: str = "inconnu"
    controller: str = ""  # la personne ou la famille qui contrôle le groupe, quand elle est connue
    lang: str = ""
    weight: float = 1.0
    priority: bool = False  # source prioritaire : passe en tête de la sélection
    hide_readings: bool = False  # masquée de « Mes lectures » à la demande du lecteur
    blocked: bool = False
    # Fiabilité de 0 à 1 (voir `sources/quality.py`) ; sous le seuil, la source ne confirme rien.
    quality: Optional[float] = None
    quality_origin: str = ""  # lin2023 | ia | lecteur
    quality_note: str = ""  # catégorie et raison données par la qualification


class Article(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str = Field(index=True, unique=True)  # URL canonique
    title: str
    domain: str = Field(index=True)
    published_at: Optional[datetime] = None
    lang: str = ""
    author: str = ""
    text: str = ""
    simhash: str = ""
    wire: str = ""  # AFP, Reuters, AP… quand l'article reprend une dépêche
    kind: str = "presse"  # presse | recherche (le texte est alors le résumé du papier)
    venue: str = ""  # revue ou serveur de prépublication
    preprint: bool = False
    fetched_at: datetime = Field(default_factory=now)
    # Vérification rapide (Haiku seul), gardée pour ne pas la payer deux fois
    quickcheck: dict = Field(default_factory=dict, sa_column=Column(JSON))


class TopicArticle(SQLModel, table=True):
    topic_id: int = Field(foreign_key="topic.id", primary_key=True)
    article_id: int = Field(foreign_key="article.id", primary_key=True)
    origin: str = ""  # gdelt | bing | une | rss | drop | claude_search (google_news : avant le 22/10/2026)
    relevance: float = 0.0
    nature: str = ""  # fait | analyse | opinion | reaction | rumeur
    sensationalism: float = 0.0
    kept: bool = False
    reason: str = ""
    claims: list = Field(default_factory=list, sa_column=Column(JSON))
    cluster: str = ""  # même histoire / même dépêche
    run_id: Optional[int] = None


class Claim(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id", index=True)
    text: str
    status: str = "non_confirme"  # confirme | non_confirme | conteste | dementi
    article_ids: list = Field(default_factory=list, sa_column=Column(JSON))
    due: Optional[str] = None  # échéance annoncée (suivi des annonces)
    first_reported: Optional[str] = None  # AAAA-MM-JJ : déjà dans l'actualité avant d'entrer dans le suivi
    first_seen: datetime = Field(default_factory=now)
    last_seen: datetime = Field(default_factory=now)


class Fiche(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id", index=True)
    version: int
    content: dict = Field(default_factory=dict, sa_column=Column(JSON))
    sources: list = Field(default_factory=list, sa_column=Column(JSON))  # [{ref, id, title, domain, url, published_at}]
    coverage: dict = Field(default_factory=dict, sa_column=Column(JSON))
    nothing_new: bool = False
    # Ce que le passage a apporté : {new, late, confirmations, rectifications, reprises, synth_skipped}
    novelty: dict = Field(default_factory=dict, sa_column=Column(JSON))
    audio_path: Optional[str] = None
    run_id: Optional[int] = None
    created_at: datetime = Field(default_factory=now)


class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: Optional[int] = Field(default=None, index=True)  # None = Directeur
    kind: str = "topic"  # topic | director | spec | intake | audio | discover | factcheck | announcement
    status: str = "running"  # running | done | error
    started_at: datetime = Field(default_factory=now)
    finished_at: Optional[datetime] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    web_searches: int = 0
    cost_usd: float = 0.0
    subscription_usd: float = 0.0  # part couverte par l'abonnement Claude Code (non facturée)
    log: list = Field(default_factory=list, sa_column=Column(JSON))
    calls: list = Field(default_factory=list, sa_column=Column(JSON))  # un élément par appel de modèle
    error: str = ""


class Brief(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    day: str = Field(index=True)  # AAAA-MM-JJ
    content: dict = Field(default_factory=dict, sa_column=Column(JSON))
    audio_path: Optional[str] = None
    run_id: Optional[int] = None
    created_at: datetime = Field(default_factory=now)


class DroppedLink(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str
    title: str = ""
    domain: str = ""
    article_id: Optional[int] = None
    suggestion: dict = Field(default_factory=dict, sa_column=Column(JSON))
    topic_id: Optional[int] = None
    created_at: datetime = Field(default_factory=now)


class Draft(SQLModel, table=True):
    """Un sujet en cours de rédaction, enregistré au fil de la frappe pour ne jamais être perdu."""

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = ""
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class Correction(SQLModel, table=True):
    """Un fait d'une version précédente que de nouvelles sources démentent, contestent ou corrigent."""

    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id", index=True)
    fiche_id: Optional[int] = None
    version: int = 0
    previous_text: str
    previous_status: str = ""
    new_status: str  # dementi | conteste | corrige
    explanation: str = ""
    refs: list = Field(default_factory=list, sa_column=Column(JSON))
    read_by_user: bool = False  # le lecteur avait vu la version qui affirmait ce fait
    seen_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=now)


class Announcement(SQLModel, table=True):
    """Une annonce datée, suivie jusqu'à son échéance puis revérifiée automatiquement."""

    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id", index=True)
    text: str
    due: str = ""  # AAAA-MM ou AAAA-MM-JJ
    status: str = "a_venir"  # a_venir | realise | reporte | abandonne | en_retard
    refs: list = Field(default_factory=list, sa_column=Column(JSON))
    resolution: str = ""
    resolution_refs: list = Field(default_factory=list, sa_column=Column(JSON))
    first_seen: datetime = Field(default_factory=now)
    last_checked_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class Reading(SQLModel, table=True):
    """Un article d'actualité retrouvé dans l'historique d'un navigateur du lecteur."""

    id: Optional[int] = Field(default=None, primary_key=True)
    article_id: int = Field(foreign_key="article.id", index=True, unique=True)
    browser: str = ""
    profile: str = ""
    first_visit: Optional[datetime] = None
    last_visit: Optional[datetime] = None
    visits: int = 1
    status: str = "nouveau"  # nouveau | suivi | ignore
    device: str = "ordinateur"  # ordinateur | telephone (synchronisé) | les_deux | compte_google (Takeout)
    topic_id: Optional[int] = None
    factcheck: dict = Field(default_factory=dict, sa_column=Column(JSON))
    imported_at: datetime = Field(default_factory=now)


class Recording(SQLModel, table=True):
    """Un article mis de côté depuis la languette : ni suivi ni trié, en attente de décision."""

    id: Optional[int] = Field(default=None, primary_key=True)
    article_id: int = Field(foreign_key="article.id", index=True, unique=True)
    status: str = "enregistre"  # enregistre | suivi
    topic_id: Optional[int] = None
    # Les sources rassemblées : {status: en_cours | ok | erreur, check, synthesis, …}
    dossier: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=now)
