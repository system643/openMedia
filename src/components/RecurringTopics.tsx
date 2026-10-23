// Les sujets qui reviennent dans « Mes lectures » : trouvés par un algorithme (sans IA) dans les
// titres lus, nommés par Haiku. Un bandeau dans « Mes lectures », une liste dans « Découvrir ».

import { useQuery } from "@tanstack/react-query";
import { Repeat } from "lucide-react";
import { api } from "../lib/api";
import { relative } from "../lib/format";
import { nav } from "../lib/nav";
import type { RecurringTopic } from "../lib/types";
import { Button } from "./ui";

export function useRecurring() {
  return useQuery({ queryKey: ["recurring"], queryFn: () => api<{ topics: RecurringTopic[]; generated_at: string }>("/readings/recurring"), staleTime: 5 * 60_000 });
}

function follow(t: RecurringTopic) {
  if (t.related_topic_id) nav.go({ name: "topic", id: t.related_topic_id });
  else nav.openNewTopic({ prompt: t.prompt, name: t.name.slice(0, 60) });
}

/** Bandeau horizontal de « Mes lectures » : un clic sur une carte filtre ses articles. */
export function RecurringStrip({ active, onPick }: { active: string | null; onPick: (t: RecurringTopic | null) => void }) {
  const q = useRecurring();
  const topics = q.data?.topics ?? [];
  if (!topics.length) return null;
  return (
    <section className="mb-6">
      <h2 className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-ink">
        <Repeat size={14} className="text-accent" /> Tes sujets récurrents
        <span className="font-normal text-ink-3">· d'après ce que tu lis, {topics.length} sujet{topics.length > 1 ? "s" : ""}</span>
      </h2>
      <div className="scroll-area -mx-1 flex gap-2.5 overflow-x-auto px-1 pb-1">
        {topics.map((t) => (
          <article
            key={t.key}
            role="button"
            tabIndex={0}
            onClick={() => onPick(active === t.key ? null : t)}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onPick(active === t.key ? null : t)}
            className={`card flex w-[240px] shrink-0 cursor-pointer flex-col p-3.5 transition-colors ${active === t.key ? "outline-2 -outline-offset-2 outline-accent" : "hover:bg-fill/50"}`}
          >
            <p className="line-clamp-2 text-[14px] font-medium leading-snug text-ink">{t.name}</p>
            <p className="mt-1 text-[12px] leading-snug text-ink-2">{t.reason}</p>
            <p className="mt-0.5 truncate text-[11.5px] text-ink-3">{t.media.slice(0, 3).join(", ")}</p>
            <div className="mt-auto flex items-center pt-2.5">
              <span className="text-[11.5px] text-ink-3">dernier {relative(t.last)}</span>
              <Button
                size="sm"
                variant={t.related_topic_id ? "ghost" : "quiet"}
                className="ml-auto"
                onClick={(e) => {
                  e.stopPropagation();
                  follow(t);
                }}
              >
                {t.related_topic_id ? "Déjà suivi" : "Suivre"}
              </Button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

/** Section de « Découvrir » : les sujets de tes lectures, avant les unes des médias. */
export function RecurringList() {
  const q = useRecurring();
  const topics = q.data?.topics ?? [];
  if (!topics.length) return null;
  return (
    <section className="mt-8">
      <h2 className="flex items-center gap-1.5 text-[15px] font-semibold text-ink">
        <Repeat size={15} className="text-accent" /> D'après tes lectures
      </h2>
      <p className="mt-0.5 text-[13px] text-ink-2">Les sujets qui reviennent dans ton historique, repérés sans IA ; Haiku n'a fait que les nommer et rédiger le suivi.</p>
      <ul className="mt-2 divide-y divide-line">
        {topics.map((t) => (
          <li key={t.key} className="flex gap-6 py-4">
            <div className="min-w-0 flex-1">
              <p className="text-[12px] text-ink-3">{t.reason}</p>
              <h3 className="serif mt-0.5 text-[19px] leading-snug text-ink">{t.name}</h3>
              <p className="mt-1 line-clamp-2 text-[13.5px] leading-[1.55] text-ink-2">{t.titles.slice(0, 2).join(" · ")}</p>
            </div>
            <div className="shrink-0 pt-4">
              <Button variant={t.related_topic_id ? "ghost" : "quiet"} onClick={() => follow(t)}>
                {t.related_topic_id ? "Déjà suivi" : "Suivre"}
              </Button>
            </div>
          </li>
        ))}
      </ul>
      <h2 className="mt-10 text-[15px] font-semibold text-ink">À la une</h2>
    </section>
  );
}
