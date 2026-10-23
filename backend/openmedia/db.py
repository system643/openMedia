"""Connexion SQLite (fichier unique dans le dossier de données) et amorçage du registre de sources."""

from __future__ import annotations

import json
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select

from . import models  # noqa: F401 — enregistre les tables
from .config import data_dir

SEED = Path(__file__).parent / "sources" / "seed_sources.yaml"


@lru_cache(maxsize=1)
def engine():
    url = f"sqlite:///{data_dir() / 'openmedia.db'}"
    eng = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    SQLModel.metadata.create_all(eng)
    if "run.subscription_usd" in add_missing_columns(eng):
        # Les passages faits avant ce suivi : ceux de Claude Code étaient couverts par l'abonnement.
        with eng.begin() as conn:
            conn.exec_driver_sql("UPDATE run SET subscription_usd = cost_usd WHERE log LIKE '%via Claude Code%'")
    _seed_sources(eng)
    return eng


@contextmanager
def session():
    with Session(engine(), expire_on_commit=False) as s:
        yield s


def add_missing_columns(eng) -> list[str]:
    """`create_all` crée les nouvelles tables mais n'ajoute pas les colonnes nouvelles aux
    tables existantes : on les ajoute ici (toutes ont une valeur par défaut ou sont nullables)."""
    added = []
    with eng.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            existing = {row[1] for row in conn.exec_driver_sql(f'PRAGMA table_info("{table.name}")')}
            if not existing:
                continue
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = col.type.compile(dialect=eng.dialect)
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                if default is None and col.default is not None and callable(col.default.arg):
                    try:  # default_factory : on prend la valeur produite (liste vide, dictionnaire vide…)
                        produced = col.default.arg(None)
                    except TypeError:
                        produced = col.default.arg()
                    default = json.dumps(produced) if isinstance(produced, (list, dict)) else None
                clause = f" DEFAULT {_sql_literal(default)}" if default is not None else ""
                conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {ddl}{clause}')
                added.append(f"{table.name}.{col.name}")
    return added


def _sql_literal(value) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _seed_sources(eng) -> None:
    """Ajoute les médias du registre absents de la base et complète la propriété des médias
    connus ; ne touche pas à ce que l'utilisateur a modifié (poids, blocage, type déjà qualifié).
    La note du jeu ouvert remplace une qualification IA, jamais une note du lecteur."""
    with Session(eng) as s:
        known = {src.domain: src for src in s.exec(select(models.Source)).all()}
        for row in yaml.safe_load(SEED.read_text(encoding="utf-8")):
            src = known.get(row["domain"])
            if src is None:
                known[row["domain"]] = src = models.Source(**row)
                s.add(src)
            elif src.owner_type in (None, "", "inconnu") and row.get("owner_type"):
                src.owner, src.owner_type, src.controller = row.get("owner", src.owner), row["owner_type"], row.get("controller", "")
                s.add(src)
        _rescore(s, known.values())
        s.commit()


def _rescore(s: Session, sources) -> None:
    """La note du jeu ouvert remplace une qualification IA, jamais une note du lecteur ; les
    notes données par l'IA restent sous les notes établies (plafond relevé le 23/10/2026)."""
    from .sources.quality import AI_CAP, rated

    for src in sources:
        if src.quality_origin == "ia" and src.quality is not None and src.quality > AI_CAP:
            src.quality = AI_CAP
            s.add(src)
        score = rated(src.domain)
        if score is not None and src.quality_origin != "lecteur" and (src.quality, src.quality_origin) != (score, "lin2023"):
            src.quality, src.quality_origin, src.quality_note = score, "lin2023", ""
            s.add(src)


def rescore_sources() -> None:
    """Après le téléchargement du jeu ouvert de notation : chaque source prend sa note."""
    from .sources import registry

    with Session(engine()) as s:
        _rescore(s, s.exec(select(models.Source)).all())
        s.commit()
    registry.invalidate()
