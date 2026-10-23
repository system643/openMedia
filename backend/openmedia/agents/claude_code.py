"""Moteur « Claude Code » : les agents passent par la CLI `claude` installée sur le PC
(et donc par le compte ou l'abonnement avec lequel elle est connectée), sans clé API.

Chaque appel est un `claude -p` verrouillé, qui ne peut rien faire sur le PC : aucun outil
(sauf WebSearch pour la recherche), aucune permission accordée, ni MCP, ni réglages, hooks,
plugins, skills ou CLAUDE.md, pas de session conservée, un dossier de travail vide et un
environnement sans le jeton de l'API locale ni les clés. Le contenu passe par l'entrée
standard (la ligne de commande Windows est limitée à 32 767 caractères) et le prompt système
par un fichier.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from ..config import data_dir, load_settings
from ..security import child_env, valid_claude_path
from .errors import claude_code_message
from .llm import LLM, LLMError, NoApiKey, RunMeter, T, system_text

EFFORTS = {"low", "medium", "high", "xhigh", "max"}
TIMEOUT = 900  # secondes : une synthèse longue peut prendre plusieurs minutes
MAX_BUDGET_USD = "2"  # plafond par appel : une synthèse coûte quelques centimes
# Verrouillage ajouté quand la version installée connaît l'option (voir `lockdown`).
LOCKDOWN = [
    ("--safe-mode", []),  # ni CLAUDE.md, skills, plugins, hooks, MCP ni agents personnels
    ("--restricted", []),  # aucun outil d'exécution ni WebFetch, réglages ignorés
    ("--permission-mode", ["dontAsk"]),  # ce qui n'est pas autorisé est refusé
    ("--permission-prompts", ["none"]),  # personne pour accorder une permission
    ("--disable-slash-commands", []),
    ("--no-chrome", []),
    ("--max-budget-usd", [MAX_BUDGET_USD]),
]
_SHIM_TARGET = re.compile(r'"%dp0%\\([^"]+\.(?:exe|js))"', re.I)
_slots: asyncio.Semaphore | None = None  # chaque appel lance un processus : on en borne le nombre


def _resolve(path: str) -> list[str] | None:
    """La commande à lancer. Les installations npm passent par un `claude.cmd` qu'on évite
    (cmd.exe abîme les guillemets du schéma JSON) en visant directement sa cible."""
    p = Path(path)
    if not p.exists():
        return None
    if p.suffix.lower() in (".cmd", ".bat"):
        match = _SHIM_TARGET.search(p.read_text(encoding="utf-8", errors="ignore"))
        if not match:
            return None
        target = p.parent / match.group(1)
        if not target.exists():
            return None
        return [str(target)] if target.suffix.lower() == ".exe" else [shutil.which("node") or "node", str(target)]
    return [str(p)]


@lru_cache(maxsize=4)
def find_claude(configured: str | None = None) -> list[str] | None:
    # Un chemin réglé à la main n'est suivi que s'il désigne bien Claude Code.
    candidates = [configured] if configured and valid_claude_path(configured) else []
    found = shutil.which("claude")
    if found:
        candidates.append(found)
        candidates.append(str(Path(found).with_suffix(".cmd")))
    home = Path.home()
    candidates += [str(home / ".local" / "bin" / "claude.exe"), str(Path(os.environ.get("APPDATA", home)) / "npm" / "claude.cmd")]
    for c in candidates:
        if c and (cmd := _resolve(c)):
            return cmd
    return None


@lru_cache(maxsize=4)
def _version(cmd: tuple[str, ...]) -> str:
    try:
        out = subprocess.run([*cmd, "--version"], capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return out.stdout.strip().split(" ")[0]
    except (OSError, subprocess.TimeoutExpired):
        return ""


@lru_cache(maxsize=4)
def _help(cmd: tuple[str, ...], version: str) -> str:
    try:
        out = subprocess.run([*cmd, "--help"], capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=child_env())
        return out.stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def lockdown(cmd: list[str]) -> tuple[list[str], list[str]]:
    """(options de verrouillage à passer, options absentes de cette version)."""
    text = _help(tuple(cmd), _version(tuple(cmd)))
    args, missing = [], []
    for flag, values in LOCKDOWN:
        if re.search(rf"(^|[\s,]){re.escape(flag)}\b", text):
            args += [flag, *values]
        else:
            missing.append(flag)
    return args, missing


def claude_code_info() -> dict:
    cmd = find_claude(load_settings().claude_code_path or None)
    if not cmd:
        return {"found": False, "path": None, "version": None}
    _, missing = lockdown(cmd)
    return {"found": True, "path": cmd[-1], "version": _version(tuple(cmd)) or None, "lockdown": "complet" if not missing else "partiel", "lockdown_missing": missing}


def _workdir() -> Path:
    # Un dossier vide : aucun CLAUDE.md ni fichier de projet ne peut s'inviter dans l'appel.
    path = data_dir() / "claude-code"
    path.mkdir(exist_ok=True)
    return path


class ClaudeCodeLLM(LLM):
    name = "claude_code"

    def __init__(self):
        self.cmd = find_claude(load_settings().claude_code_path or None)
        if not self.cmd:
            raise NoApiKey("Claude Code est introuvable sur ce PC.")

    async def _run(self, meter: RunMeter, *, model: str, task: str | None, content: str, effort: str, schema: dict | None = None, tools: list[str] | None = None) -> dict:
        global _slots
        _slots = _slots or asyncio.Semaphore(max(1, load_settings().claude_code_parallel))
        system = system_text(task)
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8", dir=_workdir()) as f:
            f.write(system)
            system_file = f.name
        args = [
            *self.cmd, "-p",
            "--output-format", "json",
            "--model", model,
            "--system-prompt-file", system_file,
            "--no-session-persistence",
            "--strict-mcp-config",
            "--setting-sources", "",
            "--tools", ",".join(tools) if tools else "",
            *lockdown(self.cmd)[0],
        ]
        if tools:
            args += ["--allowedTools", ",".join(tools)]
        if effort in EFFORTS:
            args += ["--effort", effort]
        if schema is not None:
            args += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
        try:
            async with _slots:
                proc = await asyncio.create_subprocess_exec(
                    *args,
                    cwd=_workdir(),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    env=child_env(),
                )
                try:
                    out, err = await asyncio.wait_for(proc.communicate(content.encode("utf-8")), TIMEOUT)
                except TimeoutError:
                    proc.kill()
                    raise LLMError(f"Claude Code n'a pas répondu en {TIMEOUT // 60} minutes.")
        finally:
            os.unlink(system_file)
        try:
            data = json.loads(out.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            detail = (err or out).decode("utf-8", errors="replace").strip()[-400:]
            if re.search(r"log ?in|auth|credential|/login", detail, re.I):
                raise NoApiKey("Claude Code n'est pas connecté : ouvre un terminal, lance « claude » et connecte-toi.")
            raise LLMError(f"Claude Code a échoué : {detail or 'aucune sortie'}")
        meter.add_reported(data.get("usage") or {}, data.get("total_cost_usd") or 0.0, model=model, task=task or "search")
        if data.get("is_error") or data.get("subtype") != "success":
            message = str(data.get("result") or data.get("subtype") or "erreur inconnue")
            if re.search(r"log ?in|authenticat|invalid api key|/login", message, re.I):
                raise NoApiKey("Claude Code n'est pas connecté : ouvre un terminal, lance « claude » et connecte-toi.")
            raise LLMError(claude_code_message(message))
        meter.note(f"{task or 'appel'} · {model} via Claude Code · {(data.get('usage') or {}).get('output_tokens', 0)} tokens en sortie")
        return data

    async def parse(self, meter: RunMeter, *, model: str, task: str, content: str, schema: type[T], effort: str = "medium", max_tokens: int = 16000) -> T:
        data = await self._run(meter, model=model, task=task, content=content, effort=effort, schema=schema.model_json_schema())
        output = data.get("structured_output")
        if output is None:  # repli : la réponse texte contient parfois le JSON
            try:
                output = json.loads(data.get("result") or "")
            except json.JSONDecodeError:
                raise LLMError(f"Claude Code n'a pas rendu de JSON valide pour {schema.__name__}.")
        try:
            return schema.model_validate(output)
        except ValidationError as e:
            raise LLMError(f"Claude Code n'a pas rendu de réponse conforme ({schema.__name__}) : réessaie.") from e

    async def text(self, meter: RunMeter, *, model: str, task: str, content: str, effort: str = "medium", max_tokens: int = 8000) -> str:
        data = await self._run(meter, model=model, task=task, content=content, effort=effort)
        return str(data.get("result") or "").strip()

    async def search(self, meter: RunMeter, *, model: str, prompt: str, max_uses: int = 3) -> list[dict]:
        schema = {
            "type": "object",
            "properties": {"articles": {"type": "array", "items": {"type": "object", "properties": {"url": {"type": "string"}, "title": {"type": "string"}}, "required": ["url", "title"], "additionalProperties": False}}},
            "required": ["articles"],
            "additionalProperties": False,
        }
        content = prompt + f"\n\nFais au plus {max_uses} recherches web, puis rends la liste des articles trouvés (adresse exacte telle que donnée par la recherche, et titre)."
        data = await self._run(meter, model=model, task=None, content=content, effort="low", schema=schema, tools=["WebSearch"])
        articles = (data.get("structured_output") or {}).get("articles") or []
        return [a for a in articles if str(a.get("url", "")).startswith(("http://", "https://"))]
