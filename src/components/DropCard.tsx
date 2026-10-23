import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import type { Drop, Topic } from "../lib/types";
import { Button, inputClass } from "./ui";

/** Un lien vient d'être déposé : l'article, la suggestion de l'IA, et la décision du lecteur. */
export function DropCard({ drop, onDone, onOpenTopic }: { drop: Drop; onDone: () => void; onOpenTopic: (id: number) => void }) {
  const topics = useQuery({ queryKey: ["topics"], queryFn: () => api<Topic[]>("/topics") });
  const sug = drop.suggestion;
  const [mode, setMode] = useState<"add_to_topic" | "new_topic">(sug.action);
  const [topicId, setTopicId] = useState<number | null>(sug.topic_id ?? topics.data?.[0]?.id ?? null);
  const [prompt, setPrompt] = useState(sug.prompt_draft);

  const confirm = useMutation({
    mutationFn: () => api<{ ok: boolean; topic_id: number }>(`/drop/${drop.id}/confirm`, { method: "POST", body: mode === "add_to_topic" ? { action: mode, topic_id: topicId } : { action: mode, prompt, name: sug.topic_name } }),
    onSuccess: (r) => {
      onOpenTopic(r.topic_id);
      onDone();
    },
  });

  return (
    <div className="flex h-full flex-col">
      <p className="text-[12px] text-ink-3">{drop.domain}</p>
      <p className="mt-0.5 line-clamp-2 text-[14px] font-medium leading-snug text-ink">{drop.title}</p>

      <div className="mt-3 inline-flex rounded-lg bg-line p-0.5 text-[12.5px]">
        {(["add_to_topic", "new_topic"] as const).map((m) => (
          <button key={m} onClick={() => setMode(m)} disabled={m === "add_to_topic" && !topics.data?.length} className={`flex-1 rounded-md px-2.5 py-1 disabled:opacity-40 ${mode === m ? "bg-surface font-medium text-ink shadow-sm" : "text-ink-2"}`}>
            {m === "add_to_topic" ? "Ajouter à un sujet" : "Nouveau sujet"}
          </button>
        ))}
      </div>

      <div className="mt-3 min-h-0 flex-1">
        {mode === "add_to_topic" ? (
          <select className={inputClass} value={topicId ?? ""} onChange={(e) => setTopicId(Number(e.target.value))}>
            {topics.data?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        ) : (
          <textarea className={`${inputClass} h-full min-h-[84px] resize-none text-[13px] leading-snug`} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
        )}
        {sug.reason && mode === sug.action && <p className="mt-1.5 line-clamp-2 text-[11.5px] text-ink-3">{sug.reason}</p>}
      </div>

      {confirm.error && <p className="mt-2 text-[12px] text-deny">{confirm.error.message}</p>}
      <div className="mt-3 flex justify-end gap-2">
        <Button variant="ghost" onClick={onDone}>
          Ignorer
        </Button>
        <Button variant="primary" busy={confirm.isPending} disabled={mode === "add_to_topic" ? !topicId : prompt.trim().length < 5} onClick={() => confirm.mutate()}>
          {mode === "add_to_topic" ? "Ajouter" : "Suivre"}
        </Button>
      </div>
    </div>
  );
}

/** Extrait un lien web d'un glisser-déposer venu d'un navigateur. */
export function urlFromDrop(dt: DataTransfer): string | null {
  const candidates = [dt.getData("text/uri-list"), dt.getData("text/x-moz-url"), dt.getData("URL"), dt.getData("text/plain")];
  for (const raw of candidates) {
    const line = raw?.split(/\r?\n/).find((l) => /^https?:\/\//.test(l.trim()));
    if (line) return line.trim();
  }
  return null;
}
