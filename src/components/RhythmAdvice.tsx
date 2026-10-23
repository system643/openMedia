// Le rythme conseillé d'un sujet : un conseil chiffré (espacer, resserrer, contrôle par
// semaine), le pilote automatique, la bande d'activité des 30 derniers jours et le journal.
// Tout est calculé sans IA, d'après ce que chaque passage a réellement apporté.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Gauge } from "lucide-react";
import { api } from "../lib/api";
import { relative, tokens } from "../lib/format";
import type { RhythmAdvice, RhythmDay, RhythmLogEntry, RhythmOverview, Topic } from "../lib/types";
import { Button, Row, Segmented, Toggle } from "./ui";

export function everyLabel(every: number): string {
  return every === 1 ? "chaque jour" : every === 7 ? "une fois par semaine" : `1 jour sur ${every}`;
}

const days = (n: number) => `${String(n).replace(".", ",")} jour${n >= 2 ? "s" : ""}`;

export function useRhythm(topicId: number) {
  return useQuery({ queryKey: ["rhythm", topicId], queryFn: () => api<RhythmOverview>(`/topics/${topicId}/rhythm`), staleTime: 60_000 });
}

function useRhythmActions(topicId: number) {
  const qc = useQueryClient();
  const refresh = () => {
    for (const key of ["topics", "rhythm", "costs", "calendar"]) void qc.invalidateQueries({ queryKey: [key] });
  };
  return {
    apply: useMutation({ mutationFn: (every: number) => api<Topic>(`/topics/${topicId}/rhythm/apply`, { method: "POST", body: { every } }), onSuccess: refresh }),
    dismiss: useMutation({ mutationFn: (every: number) => api<Topic>(`/topics/${topicId}/rhythm/dismiss`, { method: "POST", body: { every } }), onSuccess: refresh }),
    configure: useMutation({ mutationFn: (body: { auto?: boolean; min_every?: number; max_every?: number }) => api<RhythmOverview>(`/topics/${topicId}/rhythm`, { method: "PATCH", body }), onSuccess: refresh }),
  };
}

/** Le conseil en une phrase chiffrée, rédigée par le code. */
export function adviceText(a: RhythmAdvice): { title: string; body: string } {
  const sim = a.simulation;
  const label = everyLabel(a.every ?? 1);
  const saved = sim ? Math.abs(Math.round(sim.runs_saved)) : 0;
  const cost = sim && sim.tokens_saved ? ` (≈ ${tokens(Math.abs(sim.tokens_saved))} tokens)` : "";
  if (a.direction === "resserrer") return { title: "Ce sujet s'accélère.", body: `${a.reason} À ${label}, tu suivrais au plus près, pour ≈ ${saved} passage${saved > 1 ? "s" : ""} de plus par mois${cost}.` };
  const delay = sim && sim.mean_delay > 0 ? `avec ${days(sim.mean_delay)} de retard en moyenne` : "sans retard";
  if (a.direction === "veille") return { title: "Ce sujet ne bouge plus.", body: `${a.reason} Un passage par semaine suffirait : ≈ ${saved} passage${saved > 1 ? "s" : ""} de moins par mois${cost}.` };
  return { title: "Ce sujet bouge peu.", body: `${a.reason} À ${label}, tu aurais eu les mêmes nouvelles ${delay}, pour ≈ ${saved} passage${saved > 1 ? "s" : ""} de moins par mois${cost}.` };
}

/** La carte de conseil : en tête de la fiche et dans l'onglet Agent, tant qu'elle n'est pas écartée. */
export function RhythmCard({ topic, overview }: { topic: Topic; overview?: RhythmOverview }) {
  const { apply, dismiss, configure } = useRhythmActions(topic.id);
  const a = overview?.advice;
  if (!a?.direction || a.dismissed || !a.every || topic.status === "archived") return null;
  const { title, body } = adviceText(a);
  const busy = apply.isPending || dismiss.isPending || configure.isPending;
  return (
    <section className="card mt-6 flex gap-3.5 p-4" aria-label="Rythme conseillé">
      <span className="grid size-8 shrink-0 place-items-center rounded-full bg-accent-soft text-accent">
        <Gauge size={16} aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-[14px] leading-snug text-ink">
          <span className="font-semibold">{title}</span> {body}
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button variant="primary" size="sm" busy={apply.isPending} disabled={busy} onClick={() => apply.mutate(a.every!)}>
            Passer à {everyLabel(a.every)}
          </Button>
          {!overview?.auto && (
            <Button size="sm" disabled={busy} onClick={() => configure.mutate({ auto: true })}>
              Laisser l'app ajuster
            </Button>
          )}
          <Button variant="ghost" size="sm" disabled={busy} onClick={() => dismiss.mutate(a.every!)}>
            Pas maintenant
          </Button>
        </div>
        <p className="mt-2 text-[12px] leading-snug text-ink-3">
          {a.direction === "resserrer"
            ? "Le rythme revient de lui-même quand le sujet se calme, si le rythme adaptatif est activé."
            : "Les jours d'échéance gardent leur passage, et le pouls avance le passage si le sujet s'emballe."}
          {a.confidence === "faible" && ` Conseil fondé sur ${a.observed} passages seulement.`}
        </p>
      </div>
    </section>
  );
}

const BOUNDS = ["2", "3", "4", "7"] as const;

/** Le pilote automatique, la bande d'activité et le journal : dans l'onglet Agent, sous le rythme. */
export function AdaptiveRhythm({ topic }: { topic: Topic }) {
  const q = useRhythm(topic.id);
  const { apply, configure } = useRhythmActions(topic.id);
  const o = q.data;
  if (!o) return null;
  const last = o.log.find((e) => e.by !== "pulse" && e.from != null && e.to != null && e.from !== e.to);
  return (
    <div className="mt-3 space-y-3">
      <RhythmCard topic={topic} overview={o} />
      <div className="card overflow-hidden [&>*+*]:border-t [&>*+*]:border-line">
        <Row label="Rythme adaptatif" hint="L'app espace ce sujet quand il bouge peu, et revient au rythme le plus serré dès qu'il repart. Elle te prévient à chaque changement.">
          <Toggle label="Rythme adaptatif" checked={o.auto} onChange={(auto) => configure.mutate({ auto })} />
        </Row>
        {o.auto && (
          <Row label="Jamais plus espacé que" hint={`Entre ${everyLabel(o.min_every)} et ${everyLabel(o.max_every)}.`}>
            <Segmented
              label="Rythme le plus espacé"
              value={String(o.max_every) as (typeof BOUNDS)[number]}
              onChange={(v) => configure.mutate({ max_every: Number(v) })}
              options={BOUNDS.map((b) => ({ value: b, label: b === "7" ? "1 sem." : `1 j/${b}` }))}
            />
          </Row>
        )}
        <div className="px-4 py-3.5">
          <ActivityStrip strip={o.strip} />
          {!o.advice.direction && o.advice.reason && <p className="mt-2.5 text-[12px] text-ink-2">{o.advice.reason}</p>}
        </div>
      </div>
      {o.log.length > 0 && (
        <div>
          <span className="mb-1.5 block text-[13px] font-medium text-ink">Journal du rythme</span>
          <ul className="divide-y divide-line text-[13px]">
            {o.log.slice(0, 6).map((e, i) => (
              <li key={i} className="flex items-start justify-between gap-4 py-2">
                <span className="text-ink-2">
                  <span className="text-ink">{logTitle(e)}</span> · {relative(e.at)}
                  {e.reason && <span className="block text-[12px] text-ink-3">{e.reason}</span>}
                </span>
                {e === last && e.from != null && (
                  <Button variant="ghost" size="sm" busy={apply.isPending} onClick={() => apply.mutate(e.from!)}>
                    Revenir à {everyLabel(e.from)}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function logTitle(e: RhythmLogEntry): string {
  if (e.by === "pulse") return "Passage avancé par le pouls";
  const who = e.by === "auto" ? "Rythme adaptatif" : "Toi";
  return `${who} : ${everyLabel(e.from ?? 1)} → ${everyLabel(e.to ?? 1)}`;
}

const dayFmt = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short" });

/** Ce qu'un jour a apporté, pour l'infobulle et la lecture d'écran. */
function dayLabel(d: RhythmDay): string {
  const parts = [dayFmt.format(new Date(`${d.day}T12:00:00`))];
  if (!d.runs.length) parts.push("pas de passage");
  for (const r of d.runs) {
    const bits = [r.new ? `${r.new} nouveauté${r.new > 1 ? "s" : ""}` : "rien de neuf"];
    if (r.confirmations) bits.push(`${r.confirmations} confirmation${r.confirmations > 1 ? "s" : ""}`);
    if (r.reprises) bits.push(`${r.reprises} reprise${r.reprises > 1 ? "s" : ""}`);
    if (r.skipped) bits.push("sans rédaction");
    parts.push(`passage : ${bits.join(", ")}`);
  }
  if (d.pulse != null) parts.push(`pouls : ${d.pulse} titre${d.pulse > 1 ? "s" : ""} nouveau${d.pulse > 1 ? "x" : ""}${d.pulse_media ? `, ${d.pulse_media} média${d.pulse_media > 1 ? "s" : ""}` : ""}`);
  if (d.advanced) parts.push("passage avancé");
  return parts.join(" · ");
}

function runTone(d: RhythmDay): string | null {
  if (!d.runs.length) return null;
  if (d.runs.some((r) => r.new > 0)) return "bg-accent";
  if (d.runs.some((r) => r.confirmations > 0)) return "bg-accent/40";
  return "bg-ink-3/50";
}

/** Trente jours : un point par jour de passage (plein = du neuf, atténué = des confirmations,
 *  gris = rien), et sous lui une barre pour le pouls (titres nouveaux relevés ce jour-là). */
export function ActivityStrip({ strip }: { strip: RhythmDay[] }) {
  const peak = Math.max(1, ...strip.map((d) => d.pulse ?? 0));
  const hasPulse = strip.some((d) => d.pulse != null);
  const runs = strip.filter((d) => d.runs.length).length;
  const fresh = strip.filter((d) => d.runs.some((r) => r.new > 0)).length;
  return (
    <figure>
      <figcaption className="mb-2 flex items-center gap-1.5 text-[13px] text-ink">
        <Activity size={13} className="text-ink-3" aria-hidden />
        Les 30 derniers jours
        <span className="text-[12px] text-ink-2">
          · {runs} jour{runs > 1 ? "s" : ""} de passage, dont {fresh} avec du neuf
        </span>
      </figcaption>
      <div className="grid grid-cols-[repeat(30,minmax(0,1fr))] gap-[2px]" role="list">
        {strip.map((d) => {
          const tone = runTone(d);
          const h = d.pulse ? Math.max(3, Math.round((d.pulse / peak) * 22)) : 0;
          return (
            <div key={d.day} role="listitem" aria-label={dayLabel(d)} title={dayLabel(d)} className="group flex h-[40px] flex-col items-center justify-between rounded-[3px] py-[3px] hover:bg-fill">
              <span className={`size-[7px] rounded-full ${tone ?? ""} ${d.advanced ? "ring-2 ring-warn/60" : ""}`} />
              <span className="flex h-[22px] w-full items-end justify-center">
                {h > 0 && <span className="w-[60%] max-w-[8px] rounded-t-[2px] bg-ink-3/35 group-hover:bg-ink-3/60" style={{ height: h }} />}
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[11.5px] text-ink-3">
        <span>il y a 30 jours</span>
        <span className="flex flex-wrap gap-3">
          <Legend className="size-2 rounded-full bg-accent">Du neuf</Legend>
          <Legend className="size-2 rounded-full bg-accent/40">Confirmations</Legend>
          <Legend className="size-2 rounded-full bg-ink-3/50">Rien de neuf</Legend>
          {hasPulse && <Legend className="h-2 w-1.5 rounded-t-[1px] bg-ink-3/35">Pouls</Legend>}
        </span>
        <span>aujourd'hui</span>
      </div>
    </figure>
  );
}

function Legend({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-1">
      <span className={className} />
      {children}
    </span>
  );
}
