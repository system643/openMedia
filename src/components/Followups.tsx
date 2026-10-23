// Ce qu'openMedia suit après coup : les annonces jusqu'à leur échéance, et les faits publiés
// puis démentis, contestés ou corrigés.

import * as Tooltip from "@radix-ui/react-tooltip";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { api } from "../lib/api";
import { STATUS_LABEL, relative, shortDate } from "../lib/format";
import type { Announcement, AnnouncementStatus, Correction, SourceRef } from "../lib/types";
import { SourceChip } from "./Facts";
import { Button } from "./ui";

const ANN_LABEL: Record<AnnouncementStatus, string> = { a_venir: "À venir", realise: "Réalisé", reporte: "Reporté", abandonne: "Abandonné", en_retard: "En retard" };
const ANN_TONE: Record<AnnouncementStatus, string> = { a_venir: "non_confirme", realise: "confirme", reporte: "conteste", abandonne: "dementi", en_retard: "dementi" };
const ANN_COLOR: Record<AnnouncementStatus, string> = { a_venir: "text-ink-3", realise: "text-ok", reporte: "text-contest", abandonne: "text-deny", en_retard: "text-deny" };

function Chips({ sources }: { sources: SourceRef[] }) {
  return (
    <Tooltip.Provider>
      <span className="inline-flex flex-wrap gap-1 align-middle">
        {sources.map((s) => (
          <SourceChip key={s.ref} refId={s.ref} source={s} />
        ))}
      </span>
    </Tooltip.Provider>
  );
}

export function AnnouncementList({ items, showTopic, onOpenTopic }: { items: Announcement[]; showTopic?: boolean; onOpenTopic?: (id: number) => void }) {
  return (
    <ul className="space-y-4">
      {items.map((a) => (
        <AnnouncementRow key={a.id} a={a} showTopic={showTopic} onOpenTopic={onOpenTopic} />
      ))}
    </ul>
  );
}

function AnnouncementRow({ a, showTopic, onOpenTopic }: { a: Announcement; showTopic?: boolean; onOpenTopic?: (id: number) => void }) {
  const qc = useQueryClient();
  const check = useMutation({
    mutationFn: () => api<Announcement>(`/announcements/${a.id}/check`, { method: "POST" }),
    onSettled: () => qc.invalidateQueries({ queryKey: ["announcements"] }),
  });
  const due = a.due_date ? shortDate(a.due_date) + (a.due.length === 7 ? " (fin de mois)" : "") : a.due;
  return (
    <li className="rail" data-status={ANN_TONE[a.status]}>
      {showTopic && (
        <button onClick={() => onOpenTopic?.(a.topic_id)} className="text-[12px] font-medium text-accent hover:underline">
          {a.topic_name}
        </button>
      )}
      <p className="text-[14.5px] leading-[1.55] text-ink">{a.text}</p>
      <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px]">
        <span className={`font-medium ${ANN_COLOR[a.status]}`}>{ANN_LABEL[a.status]}</span>
        <span className="text-ink-3">échéance {due}</span>
        <Chips sources={a.sources} />
      </div>
      {a.resolution && (
        <p className="mt-1.5 text-[13px] text-ink-2">
          {a.resolution} <Chips sources={a.resolution_sources} />
        </p>
      )}
      <div className="mt-1 flex items-center gap-2 text-[12px] text-ink-3">
        {a.last_checked_at ? `Vérifié ${relative(a.last_checked_at)}` : "Pas encore revérifié"}
        {(a.status === "a_venir" || a.status === "en_retard") && (
          <button onClick={() => check.mutate()} disabled={check.isPending} className="inline-flex items-center gap-1 text-ink-2 hover:text-accent disabled:opacity-50">
            <RefreshCw size={11} className={check.isPending ? "animate-spin" : ""} /> {check.isPending ? "Vérification…" : "Vérifier maintenant"}
          </button>
        )}
        {check.error && <span className="text-deny">{check.error.message}</span>}
      </div>
    </li>
  );
}

const CORR_LABEL = { dementi: "Démenti", conteste: "Contesté", corrige: "Corrigé" } as const;

export function CorrectionList({ items, showTopic, onOpenTopic, onSeen }: { items: Correction[]; showTopic?: boolean; onOpenTopic?: (id: number) => void; onSeen?: (ids: number[]) => void }) {
  return (
    <ul className="space-y-6">
      {items.map((c) => (
        <li key={c.id} className="rail" data-status={c.new_status === "corrige" ? "conteste" : c.new_status}>
          <div className="flex flex-wrap items-center gap-x-2 text-[12px]">
            {showTopic && (
              <button onClick={() => onOpenTopic?.(c.topic_id)} className="font-medium text-accent hover:underline">
                {c.topic_name}
              </button>
            )}
            <span className="text-ink-3">{relative(c.created_at)}</span>
            {c.read_by_user && <span className="font-medium text-ink">Tu l'avais lu</span>}
            {!c.seen_at && <span className="rounded bg-accent-soft px-1.5 text-accent">nouveau</span>}
          </div>
          <p className="mt-1 text-[14px] text-ink-3 line-through decoration-ink-3/60">{c.previous_text}</p>
          <p className="text-[12px] text-ink-3">{c.previous_status ? `Présenté comme « ${STATUS_LABEL[c.previous_status]} » en version ${c.version - 1}` : ""}</p>
          <p className="mt-1.5 text-[14.5px] leading-[1.55] text-ink">
            <span className={`font-semibold ${c.new_status === "dementi" ? "text-deny" : "text-contest"}`}>{CORR_LABEL[c.new_status]}.</span> {c.explanation}
          </p>
          <div className="mt-1">
            <Chips sources={c.sources} />
          </div>
        </li>
      ))}
      {onSeen && items.some((c) => !c.seen_at) && (
        <li>
          <Button variant="ghost" onClick={() => onSeen(items.filter((c) => !c.seen_at).map((c) => c.id))}>
            Marquer comme lues
          </Button>
        </li>
      )}
    </ul>
  );
}
