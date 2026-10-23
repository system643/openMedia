import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { CadencePicker } from "../components/CadencePicker";
import { ModelSelect } from "../components/ModelSelect";
import { AdaptiveRhythm } from "../components/RhythmAdvice";
import { Button, Field, Row, SectionTitle, Segmented, Toggle, inputClass } from "../components/ui";
import { api } from "../lib/api";
import { euros, parse, relative, tokens, upcoming } from "../lib/format";
import { nav } from "../lib/nav";
import type { Cadence, Run, Settings, Topic } from "../lib/types";
import { cadenceLabel, generalCadence, perMonth, useCosts } from "../lib/usage";

/** Ce que l'agent a reçu comme consigne, ce qu'il en a compris, et ce qu'il a coûté. */
export function AgentPanel({ topic }: { topic: Topic }) {
  const qc = useQueryClient();
  const [prompt, setPrompt] = useState(topic.prompt);
  const [feeds, setFeeds] = useState(topic.feeds.join("\n"));
  useEffect(() => {
    setPrompt(topic.prompt);
    setFeeds(topic.feeds.join("\n"));
  }, [topic.id, topic.prompt, topic.feeds]);
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<Settings>("/settings") });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api<Run[]>("/runs?limit=200") });
  const costs = useCosts();

  const patch = useMutation({
    mutationFn: (body: Partial<Topic>) => api<Topic>(`/topics/${topic.id}`, { method: "PATCH", body }),
    onSuccess: (_data, body) => {
      void qc.invalidateQueries({ queryKey: ["topics"] });
      if (["run_every_days", "run_weekdays", "run_hours", "follow_deadlines", "status"].some((k) => k in body)) {
        void qc.invalidateQueries({ queryKey: ["costs"] });
        void qc.invalidateQueries({ queryKey: ["calendar"] });
      }
    },
  });
  const remove = useMutation({
    mutationFn: () => api(`/topics/${topic.id}`, { method: "DELETE" }),
    onSuccess: () => {
      nav.go({ name: "today" });
      void qc.invalidateQueries();
    },
  });
  const dry = useMutation({
    mutationFn: () => api<{ since: string; articles: { id: number; title: string; source: string; kept: boolean; nature: string | null; reason: string }[] }>(`/topics/${topic.id}/dry-run`, { method: "POST" }),
  });
  const [confirmDelete, setConfirmDelete] = useState(false);

  const spec = topic.spec;
  const topicRuns = runs.data?.filter((r) => r.topic_id === topic.id) ?? [];
  const spent = topicRuns.reduce((n, r) => n + r.cost_usd, 0);
  const used = topicRuns.reduce((n, r) => n + r.input_tokens + r.output_tokens, 0);
  const usage = costs.data?.topics.find((t) => t.topic_id === topic.id);
  const rhythmHint =
    topic.status === "sleeping"
      ? "En veille : un contrôle par semaine, quel que soit le rythme."
      : `${usage ? `${perMonth(usage.runs_per_month)}, échéances comprises · ≈ ${tokens(usage.avg_tokens)} tokens par passage${usage.estimated ? " (estimé)" : ""}, ≈ ${tokens(usage.monthly_tokens)} par mois. ` : ""}Prochain passage : ${upcoming(topic.next_run)}.`;

  return (
    <div>
      <SectionTitle>Ta consigne</SectionTitle>
      <textarea className={`${inputClass} min-h-[120px] resize-y leading-relaxed`} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
      <div className="mt-2 flex items-center gap-3">
        <Button variant="primary" disabled={prompt.trim() === topic.prompt.trim()} busy={patch.isPending} onClick={() => patch.mutate({ prompt })}>
          Enregistrer la consigne
        </Button>
        <span className="text-[12px] text-ink-3">L'agent recalcule ses requêtes ; la fiche suit au prochain passage.</span>
      </div>
      {patch.error && <p className="mt-2 text-[13px] text-deny">{patch.error.message}</p>}

      <SectionTitle>Ce que l'agent a compris</SectionTitle>
      <dl className="grid grid-cols-[160px_1fr] gap-x-6 gap-y-3 text-[14px]">
        <dt className="text-ink-2">Le sujet</dt>
        <dd className="text-ink">{spec.summary}</dd>
        <dt className="text-ink-2">L'angle</dt>
        <dd className="text-ink">{spec.angle}</dd>
        <dt className="text-ink-2">Recherches</dt>
        <dd className="text-ink">{[...(spec.queries_fr ?? []), ...(spec.queries_en ?? [])].join(" ; ")}</dd>
        <dt className="text-ink-2">Repères</dt>
        <dd className="text-ink">{spec.keywords?.join(", ")}</dd>
        {!!spec.exclusions?.length && (
          <>
            <dt className="text-ink-2">Hors sujet</dt>
            <dd className="text-ink">{spec.exclusions.join(", ")}</dd>
          </>
        )}
        {!!spec.sections?.length && (
          <>
            <dt className="text-ink-2">Tes sections</dt>
            <dd className="text-ink">{spec.sections.map((s) => s.title).join(", ")}</dd>
          </>
        )}
        <dt className="text-ink-2">Opinions</dt>
        <dd className="text-ink">{spec.keep_opinions ? "Gardées, à ta demande" : "Écartées"}</dd>
      </dl>
      <div className="mt-4">
        <Button busy={dry.isPending} onClick={() => dry.mutate()}>
          Essai à blanc
        </Button>
        <span className="ml-3 text-[12px] text-ink-3">Collecte et tri sans rédiger de fiche.</span>
      </div>
      {dry.error && <p className="mt-2 text-[13px] text-deny">{dry.error.message}</p>}
      {dry.data && (
        <ul className="mt-4 space-y-2 text-[13.5px]">
          {dry.data.articles.map((a) => (
            <li key={a.id} className="rail" data-status={a.kept ? "confirme" : "dementi"}>
              <span className="text-ink">{a.title}</span> <span className="text-ink-3">({a.source}) {a.reason}</span>
            </li>
          ))}
          {dry.data.articles.length === 0 && <li className="text-ink-3">Aucun article nouveau dans la fenêtre.</li>}
        </ul>
      )}

      <SectionTitle>Réglages du sujet</SectionTitle>
      <div className="space-y-5">
        <Field label="Importance pour toi" hint="Le Directeur s'en sert pour hiérarchiser ton brief.">
          <Segmented value={String(topic.importance)} onChange={(v) => patch.mutate({ importance: Number(v) })} options={["1", "2", "3", "4", "5"].map((v) => ({ value: v, label: v }))} />
        </Field>
        <Field label="Langues des sources">
          <Segmented
            value={topic.languages.join("+")}
            onChange={(v) => patch.mutate({ languages: v.split("+") })}
            options={[
              { value: "fr+en", label: "Français et anglais" },
              { value: "fr", label: "Français" },
              { value: "en", label: "Anglais" },
            ]}
          />
        </Field>
        <Rhythm topic={topic} general={generalCadence(settings.data)} hint={rhythmHint} onPatch={(body) => patch.mutate(body)} />
        <Field label="Modèle de l'agent">
          <ModelSelect value={topic.model ?? ""} defaultLabel="Par défaut (réglage général)" onChange={(v) => patch.mutate({ model: v || null })} />
        </Field>
        {topic.kind === "recherche" ? (
          <ResearchFields topic={topic} onChange={(research_fields) => patch.mutate({ research_fields })} />
        ) : (
          <SocialSources topic={topic} onChange={(social) => patch.mutate({ social })} />
        )}
        <Field label="Flux RSS à surveiller en plus" hint="Une adresse par ligne. Seuls les articles qui touchent au sujet sont repris.">
          <textarea className={`${inputClass} min-h-[72px] font-mono text-[12.5px]`} value={feeds} onChange={(e) => setFeeds(e.target.value)} onBlur={() => patch.mutate({ feeds: feeds.split("\n").map((s) => s.trim()).filter(Boolean) })} />
        </Field>
      </div>

      <SectionTitle aside={<span className="text-[12px] text-ink-3">{tokens(used)} tokens · {euros(spent)} au total</span>}>Passages</SectionTitle>
      <ul className="divide-y divide-line text-[13px]">
        {topicRuns.slice(0, 8).map((r) => (
          <li key={r.id} className="flex justify-between gap-4 py-2">
            <span className={r.status === "error" ? "text-deny" : "text-ink-2"}>
              {r.kind === "spec" ? "Préparation" : "Mise à jour"} {relative(r.started_at)}
              {r.finished_at && r.kind === "topic" && `, en ${duration(r.started_at, r.finished_at)}`}
              {r.error && ` : ${r.error}`}
            </span>
            <span className="shrink-0 tabular-nums text-ink-3">
              {tokens(r.input_tokens + r.output_tokens)} tokens · {euros(r.cost_usd)}
            </span>
          </li>
        ))}
      </ul>

      <SectionTitle>Cycle de vie</SectionTitle>
      <div className="flex flex-wrap gap-2">
        {topic.status === "active" && <Button onClick={() => patch.mutate({ status: "sleeping" })}>Mettre en veille</Button>}
        {topic.status !== "active" && <Button onClick={() => patch.mutate({ status: "active" })}>Réactiver</Button>}
        {topic.status !== "archived" && <Button onClick={() => patch.mutate({ status: "archived" })}>Archiver</Button>}
        {confirmDelete ? (
          <Button variant="danger" busy={remove.isPending} onClick={() => remove.mutate()}>
            Supprimer définitivement le sujet et ses fiches
          </Button>
        ) : (
          <Button variant="danger" onClick={() => setConfirmDelete(true)}>
            Supprimer
          </Button>
        )}
      </div>
      <p className="mt-2 text-[12px] text-ink-3">Un sujet sans nouveauté pendant cinq passages se met en veille tout seul (avec le rythme adaptatif, une fois espacé au plus) et se réveille quand l'actualité repart.</p>
    </div>
  );
}

/** Le rythme du sujet : celui des réglages, ou le sien ; plus, s'il le veut, ses jours d'échéance. */
function Rhythm({ topic, general, hint, onPatch }: { topic: Topic; general: Cadence; hint: string; onPatch: (body: Partial<Topic>) => void }) {
  const own = topic.schedule.own;
  const write = (c: Cadence) => onPatch({ run_every_days: c.weekdays.length ? null : c.every, run_weekdays: c.weekdays, run_hours: c.hours });
  return (
    <div>
      <span className="mb-1.5 block text-[13px] font-medium text-ink">Rythme des passages</span>
      <div className="card overflow-hidden [&>*+*]:border-t [&>*+*]:border-line">
        <Row label="Rythme propre à ce sujet" hint={own ? undefined : `Suit le rythme général : ${cadenceLabel(general).toLowerCase()}.`}>
          <Toggle label="Rythme propre à ce sujet" checked={own} onChange={(v) => (v ? write(general) : onPatch({ run_every_days: null, run_weekdays: [], run_hours: [] }))} />
        </Row>
        {own && (
          <div className="px-4 py-3.5">
            <CadencePicker value={{ every: topic.schedule.every, weekdays: topic.schedule.weekdays, hours: topic.schedule.hours }} onChange={write} />
          </div>
        )}
        <Row label="Passer aussi les jours d'échéance" hint="Le jour de chaque échéance datée et le lendemain, pour en lire l'issue. Elles s'affichent dans l'onglet Calendrier.">
          <Toggle label="Passer aussi les jours d'échéance" checked={topic.follow_deadlines} onChange={(v) => onPatch({ follow_deadlines: v })} />
        </Row>
      </div>
      <p className="mt-1.5 text-[12px] leading-snug text-ink-2">{hint}</p>
      {topic.kind !== "recherche" && <AdaptiveRhythm topic={topic} />}
    </div>
  );
}

function duration(start: string, end: string): string {
  const s = Math.round(((parse(end)?.getTime() ?? 0) - (parse(start)?.getTime() ?? 0)) / 1000);
  return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")}`;
}

/** Réseaux sociaux : des signaux de ce qui circule, jamais comptés comme confirmation. */
function SocialSources({ topic, onChange }: { topic: Topic; onChange: (social: NonNullable<Topic["social"]>) => void }) {
  const social = topic.social ?? {};
  const [channels, setChannels] = useState((social.telegram ?? []).join(", "));
  const toggle = (key: "reddit" | "hn") => onChange({ ...social, [key]: !social[key] });
  return (
    <Field label="Réseaux sociaux" hint="Ce qui circule, pour repérer tôt une affaire. Ces messages ne comptent jamais comme une source qui confirme un fait.">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented value={social.reddit ? "on" : "off"} onChange={() => toggle("reddit")} options={[{ value: "off", label: "Sans Reddit" }, { value: "on", label: "Avec Reddit" }]} />
        <Segmented value={social.hn ? "on" : "off"} onChange={() => toggle("hn")} options={[{ value: "off", label: "Sans Hacker News" }, { value: "on", label: "Avec Hacker News" }]} />
      </div>
      <input
        className={`${inputClass} mt-2`}
        placeholder="Chaînes Telegram publiques, séparées par des virgules (ex. : afpfr, LeMondefr)"
        value={channels}
        onChange={(e) => setChannels(e.target.value)}
        onBlur={() => onChange({ ...social, telegram: channels.split(",").map((c) => c.trim().replace(/^@/, "")).filter(Boolean) })}
      />
    </Field>
  );
}

/** Domaines d'une veille de recherche : ils déterminent les archives interrogées. */
function ResearchFields({ topic, onChange }: { topic: Topic; onChange: (fields: string[]) => void }) {
  const options = useQuery({ queryKey: ["research-fields"], queryFn: () => api<{ id: string; label: string }[]>("/research/fields"), staleTime: Infinity });
  const fields = topic.research_fields ?? [];
  return (
    <Field label="Domaines de recherche" hint="arXiv, OpenAlex, PubMed, bioRxiv et medRxiv, HAL. Les papiers sont jugés sur leur titre et leur résumé.">
      <div className="flex flex-wrap gap-2">
        {options.data?.map((f) => {
          const on = fields.includes(f.id);
          return (
            <button key={f.id} type="button" aria-pressed={on} onClick={() => onChange(on ? fields.filter((x) => x !== f.id) : [...fields, f.id])} className={`rounded-full px-3 py-1 text-[13px] ${on ? "bg-accent-fill text-white" : "bg-fill text-ink hover:bg-fill-strong"}`}>
              {f.label}
            </button>
          );
        })}
      </div>
    </Field>
  );
}
