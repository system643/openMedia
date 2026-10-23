"""Point d'entrée du sidecar : `python -m openmedia.server --port 8765 --token …`.

Le jeton est généré par l'application Tauri à chaque lancement ; toute requête doit le
porter (en-tête X-Token, ou paramètre `token` pour EventSource et les balises <audio>).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import phone, scheduler
from .config import ConsentRequired, load_settings
from .agents.llm import LLMError, NoApiKey, warm_up
from .api.routes import router
from .db import engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    engine()
    warm_up()
    from .agents.readings import prune

    await asyncio.to_thread(prune)  # lectures importées avant un resserrement du filtre
    from .agents.topic_agent import recheck_fiches

    await asyncio.to_thread(recheck_fiches)  # les fiches suivent la règle de confirmation actuelle
    asyncio.get_running_loop().run_in_executor(None, _fetch_ratings)  # jeu ouvert de notation, en fond
    background = []
    if os.environ.get("OPENMEDIA_NO_SCHEDULER") != "1":
        scheduler.start()
        background.append(asyncio.create_task(phone.forward_to_ntfy()))
        if load_settings().phone_listen:
            await phone.start()
    yield
    for task in background:
        task.cancel()
    await phone.stop()
    if scheduler.scheduler.running:
        scheduler.scheduler.shutdown(wait=False)


def _fetch_ratings() -> None:
    from .db import rescore_sources
    from .sources.quality import ensure_dataset

    if ensure_dataset():
        rescore_sources()


app = FastAPI(title="openMedia", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:1427", "http://tauri.localhost", "https://tauri.localhost", "tauri://localhost"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def check_token(request: Request, call_next):
    token = os.environ.get("OPENMEDIA_TOKEN")
    if token and request.method != "OPTIONS" and request.url.path != "/health":
        given = request.headers.get("x-token") or request.query_params.get("token") or ""
        if not secrets.compare_digest(given.encode(), token.encode()):
            return JSONResponse({"detail": "Jeton invalide"}, status_code=401)
    return await call_next(request)


LOCAL_HOSTS = {"127.0.0.1", "localhost", "tauri.localhost", "[::1]"}


def _hostname(header: str) -> str:
    header = header.strip().lower()
    if header.startswith("["):  # IPv6 : [::1]:8765
        return header.split("]")[0] + "]"
    return header.rsplit(":", 1)[0]


@app.middleware("http")
async def check_host(request: Request, call_next):
    """L'API n'écoute que sur 127.0.0.1, mais une page web peut faire pointer son propre nom
    de domaine vers 127.0.0.1 (DNS rebinding) : on refuse tout en-tête Host qui n'est pas local."""
    allowed = LOCAL_HOSTS | set(filter(None, os.environ.get("OPENMEDIA_EXTRA_HOSTS", "").split(",")))
    if _hostname(request.headers.get("host") or "") not in allowed:
        return JSONResponse({"detail": "Hôte refusé"}, status_code=403)
    return await call_next(request)


@app.exception_handler(NoApiKey)
async def _no_key(_request, exc: NoApiKey):
    return JSONResponse({"detail": str(exc), "code": "no_api_key"}, status_code=400)


@app.exception_handler(ConsentRequired)
async def _no_consent(_request, exc: ConsentRequired):
    return JSONResponse({"detail": str(exc), "code": "consent_required"}, status_code=409)


@app.exception_handler(Exception)
async def _unexpected(_request, exc: Exception):
    # Rien de brut ni d'anglais à l'écran : l'erreur est dite, et consignée côté moteur.
    import logging

    logging.getLogger("openmedia").exception("erreur inattendue")
    return JSONResponse({"detail": f"Une erreur inattendue est survenue ({type(exc).__name__}). Réessaie ; si elle revient, signale-la avec le journal du passage.", "code": "internal"}, status_code=500)


@app.exception_handler(LLMError)
async def _llm_error(_request, exc: LLMError):
    return JSONResponse({"detail": str(exc), "code": "llm_error"}, status_code=502)


app.include_router(router)


def watch_parent(pid: int) -> None:
    """S'arrête quand l'application Tauri disparaît, même tuée brutalement : sous Windows, le
    lanceur de l'environnement virtuel et l'exécutable PyInstaller ont chacun un processus
    enfant que la coque ne peut pas arrêter elle-même."""
    import threading

    def wait() -> None:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if handle:
                kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
        else:
            import time

            while os.getppid() == pid:
                time.sleep(2)
        os._exit(0)

    threading.Thread(target=wait, daemon=True).start()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("OPENMEDIA_PORT", 8765)))
    parser.add_argument("--token", default=os.environ.get("OPENMEDIA_TOKEN"))
    parser.add_argument("--parent-pid", type=int, default=None)
    parser.add_argument("--mcp", action="store_true", help="serveur MCP en stdio (pour Claude) au lieu de l'API")
    args = parser.parse_args()
    if args.mcp:
        from .mcp_server import main as mcp_main

        mcp_main()
        return
    if args.token:
        os.environ["OPENMEDIA_TOKEN"] = args.token
    if args.parent_pid:
        watch_parent(args.parent_pid)
    # En exécutable PyInstaller sans console, stdout/stderr valent None.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
