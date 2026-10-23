"""Ligne de commande pour tester le moteur sans l'interface.

    uv run openmedia topics
    uv run openmedia add "Suis la réforme des retraites : décisions, chiffres, positions"
    uv run openmedia run 1 --dry          # spec, collecte, tri ; sans fiche
    uv run openmedia run 1                # passage complet
    uv run openmedia fiche 1
    uv run openmedia brief
    uv run openmedia collect "intelligence artificielle"   # collecte brute, sans IA
    uv run openmedia banc --modeles deepseek:deepseek-v4-pro,claude-sonnet-5-5   # banc d'essai
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import timedelta

from sqlmodel import select


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


async def _main(args) -> None:
    from .db import session
    from .models import Fiche, Topic, now

    if args.cmd == "topics":
        with session() as s:
            for t in s.exec(select(Topic)).all():
                print(f"{t.id:>3}  {t.status:<9} {t.name}")
    elif args.cmd == "add":
        from .agents.llm import RunMeter, get_llm
        from .agents.spec import build_spec
        from .config import load_settings

        meter = RunMeter()
        spec = await build_spec(get_llm(), meter, load_settings().models.topic, args.prompt, now())
        with session() as s:
            t = Topic(name=spec.name, prompt=args.prompt, spec=spec.model_dump())
            s.add(t)
            s.commit()
            s.refresh(t)
        from .agents.topic_agent import log_run

        log_run("spec", meter, t.id)
        _print({"id": t.id, "spec": t.spec, "cost_usd": meter.cost_usd})
    elif args.cmd == "run":
        from .agents.topic_agent import run_topic

        _print(await run_topic(args.topic_id, dry=args.dry))
    elif args.cmd == "fiche":
        with session() as s:
            f = s.exec(select(Fiche).where(Fiche.topic_id == args.topic_id).order_by(Fiche.version.desc())).first()
        _print(f.model_dump() if f else "Pas encore de fiche")
    elif args.cmd == "brief":
        from .scheduler import brief_now

        b = await brief_now()
        _print(b.model_dump() if b else "Aucune fiche récente")
    elif args.cmd == "collect":
        from .agents.topic_agent import select_candidates
        from .collect import fronts, gdelt

        cands = await gdelt.search({"fr": [args.query], "en": [args.query]}, 7)
        cands += await fronts.collect(args.query.split(), now() - timedelta(days=7), ["fr", "en"])
        chosen = select_candidates(cands, now() - timedelta(days=7))
        for c in chosen:
            print(f"[{c.origin:<11}] {c.published_at:%d/%m %H:%M} · {c.source_name[:24]:<24} · {c.title[:90]}" if c.published_at else f"[{c.origin}] {c.title}")
        print(f"\n{len(cands)} trouvés, {len(chosen)} retenus après déduplication et diversification")
    elif args.cmd == "banc":
        from .bench import bench

        models = [m.strip() for m in args.modeles.split(",") if m.strip()]
        _, path = await bench(models)
        print(open(path, encoding="utf-8").read())
        print(f"Rapport : {path}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="openmedia")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("topics")
    a = sub.add_parser("add")
    a.add_argument("prompt")
    r = sub.add_parser("run")
    r.add_argument("topic_id", type=int)
    r.add_argument("--dry", action="store_true")
    f = sub.add_parser("fiche")
    f.add_argument("topic_id", type=int)
    sub.add_parser("brief")
    c = sub.add_parser("collect")
    c.add_argument("query")
    b = sub.add_parser("banc", help="compare des modèles sur un même jeu d'articles fictifs")
    b.add_argument("--modeles", required=True, help="identifiants séparés par des virgules (fournisseur:modèle)")
    asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    main()
