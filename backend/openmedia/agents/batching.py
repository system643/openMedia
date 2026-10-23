"""Mode Économie : le passage quotidien passe par l'API Batch des fournisseurs (−50 %).

`BatchingLLM` enveloppe le moteur habituel sans que les agents le sachent. Les appels qui
arrivent dans une courte fenêtre (tous sujets confondus) partent ensemble en un lot ; on
relève le lot jusqu'à ce qu'il soit traité. Un appel que le lot n'a pas pu servir (refus,
erreur, délai dépassé) est rejoué tout de suite par l'API normale : le brief sort quand même.

Lots pris en charge : Anthropic (clé API) et OpenAI. Les autres fournisseurs, Claude Code et
la recherche web restent en appel immédiat.
"""

from __future__ import annotations

import asyncio
import io
import json
import time
from dataclasses import dataclass, field
from itertools import count

from pydantic import BaseModel

from .llm import LLM, ApiLLM, LLMError, RouterLLM, RunMeter, T, system_text
from .providers.openai_compat import strict_schema, validate_json

DISCOUNT = 0.5
_ids = count(1)


class BatchFailed(RuntimeError):
    pass


@dataclass
class Pending:
    provider: str
    name: str
    task: str
    content: str
    schema: type[BaseModel] | None
    effort: str
    max_tokens: int
    meter: RunMeter
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_running_loop().create_future())
    id: str = field(default_factory=lambda: f"om-{next(_ids)}")


class BatchingLLM(LLM):
    name = "batch"

    def __init__(self, router: RouterLLM, *, window: float = 3.0, poll: float = 30.0, deadline: float = 6 * 3600):
        self.router = router
        self.window, self.poll, self.deadline = window, poll, deadline
        self.started = time.monotonic()
        self.queue: dict[str, list[Pending]] = {}
        self.collecting: set[str] = set()  # fournisseurs dont la fenêtre de collecte est ouverte
        self.tasks: set[asyncio.Task] = set()
        self.submitted = 0

    def batchable(self, provider: str) -> bool:
        if provider == "anthropic":
            return self.router.status["engine"] == "api"
        return provider == "openai"

    async def _queued(self, meter: RunMeter, *, model: str, task: str, content: str, schema, effort: str, max_tokens: int):
        provider, name = self.router.resolve(model, meter)
        engine = self.router.engine(provider)
        if not self.batchable(provider) or time.monotonic() - self.started > self.deadline:
            if schema is None:
                return await engine.text(meter, model=name, task=task, content=content, effort=effort, max_tokens=max_tokens)
            return await engine.parse(meter, model=name, task=task, content=content, schema=schema, effort=effort, max_tokens=max_tokens)
        item = Pending(provider, name, task, content, schema, effort, max_tokens, meter)
        self.queue.setdefault(provider, []).append(item)
        if provider not in self.collecting:
            self.collecting.add(provider)
            flush = asyncio.create_task(self._flush(provider))
            self.tasks.add(flush)
            flush.add_done_callback(self.tasks.discard)
        try:
            return await item.future
        except BatchFailed as e:
            meter.note(f"{task} : lot indisponible ({e}), appel immédiat")
            if schema is None:
                return await engine.text(meter, model=name, task=task, content=content, effort=effort, max_tokens=max_tokens)
            return await engine.parse(meter, model=name, task=task, content=content, schema=schema, effort=effort, max_tokens=max_tokens)

    async def parse(self, meter: RunMeter, *, model: str, task: str, content: str, schema: type[T], effort: str = "medium", max_tokens: int = 16000) -> T:
        return await self._queued(meter, model=model, task=task, content=content, schema=schema, effort=effort, max_tokens=max_tokens)

    async def text(self, meter: RunMeter, *, model: str, task: str, content: str, effort: str = "medium", max_tokens: int = 8000) -> str:
        return await self._queued(meter, model=model, task=task, content=content, schema=None, effort=effort, max_tokens=max_tokens)

    async def search(self, meter: RunMeter, *, model: str, prompt: str, max_uses: int = 3) -> list[dict]:
        return await self.router.search(meter, model=model, prompt=prompt, max_uses=max_uses)

    # ── un lot ──────────────────────────────────────────────────────────────

    async def _flush(self, provider: str) -> None:
        await asyncio.sleep(self.window)
        self.collecting.discard(provider)  # les appels suivants ouvriront un nouveau lot
        items, self.queue[provider] = self.queue.get(provider, []), []
        if not items:
            return
        self.submitted += 1
        try:
            run = self._anthropic if provider == "anthropic" else self._openai
            remaining = self.deadline - (time.monotonic() - self.started)
            await asyncio.wait_for(run(items), timeout=max(60.0, remaining))
        except TimeoutError:
            self._fail(items, "délai dépassé")
        except Exception as e:  # noqa: BLE001 — le lot entier repasse en appel immédiat
            self._fail(items, str(e)[:200])
        self._fail(items, "réponse absente du lot")  # sans effet sur les appels déjà servis

    @staticmethod
    def _fail(items: list[Pending], reason: str) -> None:
        for it in items:
            if not it.future.done():
                it.future.set_exception(BatchFailed(reason))

    @staticmethod
    def _settle(item: Pending, raw: str) -> None:
        if item.future.done():
            return
        try:
            item.future.set_result(raw if item.schema is None else validate_json(item.schema, raw))
        except LLMError as e:
            item.future.set_exception(BatchFailed(str(e)))

    async def _anthropic(self, items: list[Pending]) -> None:
        client = self.router.engine("anthropic").client
        requests = []
        for it in items:
            output_config: dict = {"effort": it.effort}
            if it.schema is not None:
                output_config["format"] = {"type": "json_schema", "schema": strict_schema(it.schema)}
            requests.append({
                "custom_id": it.id,
                "params": {"model": it.name, "max_tokens": it.max_tokens, "system": ApiLLM._system(it.task), "messages": [{"role": "user", "content": it.content}], "output_config": output_config},
            })
        batch = await client.messages.batches.create(requests=requests)
        while (await client.messages.batches.retrieve(batch.id)).processing_status != "ended":
            await asyncio.sleep(self.poll)
        by_id = {it.id: it for it in items}
        async for row in await client.messages.batches.results(batch.id):
            it = by_id.get(row.custom_id)
            if it is None:
                continue
            if row.result.type != "succeeded":
                self._fail([it], f"requête {row.result.type}")
                continue
            message = row.result.message
            it.meter.add(it.name, message.usage, task=it.task, discount=DISCOUNT, via="batch")
            if message.stop_reason in ("refusal", "max_tokens"):
                self._fail([it], message.stop_reason)
                continue
            it.meter.note(f"{it.task} · {it.name} · lot · {message.usage.output_tokens} tokens en sortie")
            self._settle(it, "".join(b.text for b in message.content if b.type == "text"))

    async def _openai(self, items: list[Pending]) -> None:
        engine = self.router.engine("openai")
        lines = []
        for it in items:
            body = {"model": it.name, "instructions": system_text(it.task), "input": it.content, "max_output_tokens": it.max_tokens, "reasoning": {"effort": it.effort}, "store": False}
            if it.schema is not None:
                body["text"] = {"format": {"type": "json_schema", "name": it.schema.__name__, "schema": strict_schema(it.schema), "strict": True}}
            lines.append(json.dumps({"custom_id": it.id, "method": "POST", "url": "/v1/responses", "body": body}, ensure_ascii=False))
        base, headers = engine.spec.base_url, {"Authorization": f"Bearer {engine.key}"}
        payload = io.BytesIO("\n".join(lines).encode("utf-8"))
        r = await engine.http.post(f"{base}/files", headers=headers, data={"purpose": "batch"}, files={"file": ("openmedia.jsonl", payload, "application/jsonl")})
        r.raise_for_status()
        r = await engine.http.post(f"{base}/batches", headers=headers, json={"input_file_id": r.json()["id"], "endpoint": "/v1/responses", "completion_window": "24h"})
        r.raise_for_status()
        batch = r.json()
        while batch.get("status") not in ("completed", "failed", "expired", "cancelled"):
            await asyncio.sleep(self.poll)
            r = await engine.http.get(f"{base}/batches/{batch['id']}", headers=headers)
            r.raise_for_status()
            batch = r.json()
        by_id = {it.id: it for it in items}
        for key in ("output_file_id", "error_file_id"):
            if not batch.get(key):
                continue
            r = await engine.http.get(f"{base}/files/{batch[key]}/content", headers=headers)
            r.raise_for_status()
            for line in r.text.splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                it = by_id.get(row.get("custom_id"))
                response = row.get("response") or {}
                if it is None:
                    continue
                if response.get("status_code") != 200:
                    self._fail([it], f"erreur {response.get('status_code')}")
                    continue
                try:
                    raw = engine.read_responses(it.meter, it.name, response["body"], it.task, via="batch", discount=DISCOUNT)
                except LLMError as e:
                    self._fail([it], str(e))
                    continue
                self._settle(it, raw)
