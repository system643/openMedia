import * as Tooltip from "@radix-ui/react-tooltip";
import { openUrl } from "@tauri-apps/plugin-opener";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { api, inTauri } from "../lib/api";
import { LOW_QUALITY, QUALITY_ORIGIN, STATUS_LABEL, qualityLabel, shortDate } from "../lib/format";
import type { Item, Proof, SourceRef, Status } from "../lib/types";
import { Spinner } from "./ui";

/** Ouvre une source dans le navigateur : seulement une adresse web (jamais `javascript:`,
 * `file:` ou un programme), puisque l'adresse vient d'un article. */
export function openLink(url: string) {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return;
  }
  if (parsed.protocol !== "https:" && parsed.protocol !== "http:") return;
  if (inTauri) void openUrl(parsed.href);
  else window.open(url, "_blank", "noopener");
}

/** Un fait : rail coloré selon sa vérification, texte, puis les médias qui le rapportent. */
export function Fact({ item, sources, size = "md", topicId }: { item: Pick<Item, "text" | "refs" | "check" | "contradicted_by" | "first_reported"> & { status?: Status }; sources: Map<string, SourceRef>; size?: "md" | "lg"; topicId?: number }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rail list-none" data-status={item.status}>
      <p className={size === "lg" ? "serif text-[19px] leading-[1.45] text-ink" : "text-[14.5px] leading-[1.6] text-ink"}>{item.text}</p>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {item.status && <StatusLabel status={item.status} />}
        {item.first_reported && (
          <span className="text-[12px] text-ink-3" title="Les articles du jour relatent une nouvelle déjà parue : elle n'est pas comptée comme une nouveauté.">
            déjà parue le {shortDate(item.first_reported)}
          </span>
        )}
        {item.refs.map((r) => (
          <SourceChip key={r} source={sources.get(r)} refId={r} />
        ))}
        {item.check === "chiffre_non_retrouve" && (
          <span className="inline-flex items-center gap-1 text-[12px] text-warn" title="Un chiffre de cette phrase n'a pas été retrouvé tel quel dans les articles cités.">
            <AlertTriangle size={12} /> chiffre à vérifier
          </span>
        )}
        {item.check === "contenu_suspect" && (
          <span className="inline-flex items-center gap-1 text-[12px] text-warn" title="Cette phrase contient des formules adressées à une IA : elle est masquée pour les autres assistants (serveur MCP).">
            <AlertTriangle size={12} /> contenu suspect
          </span>
        )}
        {topicId !== undefined && item.refs.length > 0 && (
          <button onClick={() => setOpen(!open)} aria-expanded={open} className="inline-flex items-center gap-0.5 text-[12px] text-ink-3 hover:text-accent">
            {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />} Preuve
          </button>
        )}
      </div>
      {open && topicId !== undefined && <ProofPanel topicId={topicId} refs={item.refs} against={item.contradicted_by ?? []} status={item.status} />}
    </li>
  );
}

export function StatusLabel({ status }: { status: Status }) {
  const color = { confirme: "text-ok", non_confirme: "text-warn", conteste: "text-contest", dementi: "text-deny" }[status];
  return <span className={`text-[12px] font-medium ${color}`}>{STATUS_LABEL[status]}</span>;
}

export function SourceChip({ source, refId }: { source?: SourceRef; refId: string }) {
  if (!source) return <span className="text-[12px] text-ink-3">{refId}</span>;
  const low = source.quality != null && source.quality < LOW_QUALITY;
  return (
    <Tooltip.Root delayDuration={250}>
      <Tooltip.Trigger asChild>
        <button onClick={() => openLink(source.url)} className="rounded-md bg-line px-1.5 py-[1px] text-[12px] text-ink-2 transition-colors hover:bg-accent-soft hover:text-accent">
          {source.name}
          {source.preprint && <span className="ml-1 text-warn" title="Prépublication non relue par les pairs">·&nbsp;prépubli</span>}
          {low && <span className="ml-1 text-warn">·&nbsp;peu fiable</span>}
        </button>
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Content side="top" sideOffset={6} className="glass anim-pop z-50 max-w-[340px] rounded-[10px] px-3 py-2 text-[12.5px] leading-snug text-ink">
          <div className="font-medium">{source.title}</div>
          <div className="mt-1 text-ink-3">
            {source.name}
            {source.preprint ? " (prépublication non relue)" : ""}, {shortDate(source.published_at) || "date inconnue"} · ouvrir dans le navigateur
          </div>
          {source.quality !== undefined && (
            <div className={`mt-1 ${low ? "text-warn" : "text-ink-3"}`}>
              Fiabilité {qualityLabel(source.quality, source.quality_origin)}
              {source.quality_note ? ` : ${source.quality_note}` : ""}
              {low ? ". Ne compte pas comme confirmation." : ""}
            </div>
          )}
        </Tooltip.Content>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}

export function FactList({ items, sources, size, topicId }: { items: Item[]; sources: Map<string, SourceRef>; size?: "md" | "lg"; topicId?: number }) {
  return (
    <ul className="space-y-5">
      {items.map((it, i) => (
        <Fact key={i} item={it} sources={sources} size={size} topicId={topicId} />
      ))}
    </ul>
  );
}

const NATURE: Record<string, string> = { fait: "faits", analyse: "analyse", opinion: "opinion", reaction: "réaction", rumeur: "rumeur", hors_sujet: "hors sujet" };

/** Pourquoi ce fait a ce statut : les médias, regroupés par source réellement indépendante. */
function ProofPanel({ topicId, refs, against, status }: { topicId: number; refs: string[]; against: string[]; status?: Status }) {
  const params = new URLSearchParams({ refs: refs.join(","), against: against.join(","), ...(status ? { status } : {}) });
  const q = useQuery({ queryKey: ["proof", topicId, params.toString()], queryFn: () => api<Proof>(`/topics/${topicId}/proof?${params}`) });
  if (q.isLoading) return <div className="mt-3"><Spinner size={14} /></div>;
  if (!q.data) return null;
  const p = q.data;
  return (
    <div className="mt-3 rounded-lg border border-line bg-paper px-4 py-3 text-[13px]">
      <p className="font-medium text-ink">{p.explanation}</p>
      <ul className="mt-2.5 space-y-1">
        {p.groups.map((g, i) => (
          <li key={i} className={g.counts ? "text-ink-2" : "text-ink-3"}>
            <span className="font-medium text-ink">{g.counts ? `Source ${i + 1}` : "Signal"}</span> · {g.label}
            {g.media.length > 1 || g.label !== g.media[0] ? ` : ${g.media.join(", ")}` : ""}
          </li>
        ))}
      </ul>
      <ul className="mt-3 divide-y divide-line">
        {p.supporting.map((a) => (
          <ProofRow key={a.ref} a={a} />
        ))}
      </ul>
      {p.contradicting.length > 0 && (
        <>
          <p className="mt-3 font-medium text-contest">Ce qui le contredit</p>
          <ul className="divide-y divide-line">
            {p.contradicting.map((a) => (
              <ProofRow key={a.ref} a={a} />
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function ProofRow({ a }: { a: Proof["supporting"][number] }) {
  return (
    <li className="py-2">
      <button onClick={() => openLink(a.url)} className="text-left font-medium leading-snug text-ink hover:text-accent">
        {a.title}
      </button>
      <p className="mt-0.5 text-[12px] text-ink-3">
        {a.media}, {shortDate(a.published_at) || "date inconnue"}. Groupe : {a.owner}
        {a.controller ? ` (${a.controller})` : ""}, {a.owner_type_label}.{a.wire ? ` Reprend une dépêche ${a.wire}.` : ""}
        {a.nature ? ` Classé « ${NATURE[a.nature] ?? a.nature} ».` : ""}
        {!a.counts && (a.kind === "reseau_social" ? " Réseau social : ne compte pas comme confirmation." : " Source peu fiable : ne compte pas comme confirmation.")}
      </p>
      <p className={`mt-0.5 text-[12px] ${a.counts ? "text-ink-3" : "text-warn"}`}>
        Fiabilité {a.quality_label}
        {a.quality !== null ? ` (${QUALITY_ORIGIN[a.quality_origin] ?? a.quality_origin})` : ""}
        {a.quality_note ? ` : ${a.quality_note}` : ""}.
      </p>
    </li>
  );
}
