import * as Tooltip from "@radix-ui/react-tooltip";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, History, RefreshCw, Repeat } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AudioButton } from "../components/AudioButton";
import { Calendar } from "../components/Calendar";
import { AnnouncementList, CorrectionList } from "../components/Followups";
import { FactList, SourceChip, StatusLabel, openLink } from "../components/Facts";
import { RhythmCard, everyLabel, useRhythm } from "../components/RhythmAdvice";
import { Spectrum } from "../components/Spectrum";
import { TableOfContents } from "../components/TableOfContents";
import { Button, Empty, Page, PageHeader, SectionTitle, Segmented, Spinner, Toggle } from "../components/ui";
import { api } from "../lib/api";
import { pushToast } from "../lib/events";
import { usePageChrome } from "../lib/chrome";
import type { TopicTab } from "../lib/nav";
import { STATE_LABEL, parse, relative, shortDate } from "../lib/format";
import type { Announcement, Article, Correction, FactUpdate, Fiche, FicheUpdates, Item, SourceRef, Topic } from "../lib/types";
import { usePreviousVisit } from "../lib/visit";
import { AgentPanel } from "./AgentPanel";

type Tab = TopicTab;

export function TopicView({ id, tab: initialTab = "fiche" }: { id: number; tab?: Tab }) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>(initialTab);
  useEffect(() => setTab(initialTab), [id, initialTab]);
  const [version, setVersion] = useState<number | null>(null);
  const topic = useQuery({ queryKey: ["topics", id], queryFn: () => api<Topic>(`/topics/${id}`), refetchInterval: (q) => (q.state.data?.running ? 3000 : false) });
  const versions = useQuery({ queryKey: ["fiches", id], queryFn: () => api<{ id: number; version: number; created_at: string; nothing_new: boolean; whats_new_count: number; confirmations?: number }[]>(`/topics/${id}/fiches`) });
  const fiche = useQuery({
    queryKey: ["fiche", id, version],
    queryFn: () => api<Fiche>(`/topics/${id}/fiche${version ? `?version=${version}` : ""}`),
    retry: false,
  });
  // La dernière version affichée compte comme lue : c'est ce qui permet de prévenir le
  // lecteur si l'un de ces faits est démenti plus tard.
  const latestShown = !!fiche.data && version === null;
  useEffect(() => {
    if (latestShown) void api(`/topics/${id}/seen`, { method: "POST" });
  }, [latestShown, id, fiche.data?.version]);
  const run = useMutation({
    mutationFn: () => api(`/topics/${id}/run`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["topics"] }),
    onError: (e: Error) => pushToast(e.message, "error"),
  });
  const t = topic.data;
  const f = fiche.data;

  usePageChrome(
    t?.name ?? "",
    t ? (
      <>
        <Segmented<Tab> label="Vue du sujet" value={tab} onChange={setTab} options={[{ value: "fiche", label: "Fiche" }, { value: "calendrier", label: "Calendrier" }, { value: "sources", label: "Sources" }, { value: "agent", label: "Agent" }]} />
        {f && <AudioButton key={f.id} file={f.audio_path} generatePath={`/fiches/${f.id}/audio`} compact />}
        <Button variant="primary" size="sm" icon={<RefreshCw size={13} />} busy={t.running || run.isPending} onClick={() => run.mutate()} title="Mettre à jour (Ctrl R)">
          {t.running ? "Mise à jour" : "Mettre à jour"}
        </Button>
      </>
    ) : null,
    [t?.running, run.isPending, tab, f?.id, f?.audio_path],
  );

  if (topic.isLoading) return <div className="grid h-[60vh] place-items-center"><Spinner /></div>;
  if (!t) return <Empty title="Ce sujet n'existe plus." />;

  return (
    <Page wide={tab === "calendrier"} aside={tab === "fiche" && f ? <TableOfContents watch={`${f.id}-${tab}`} /> : undefined}>
      <PageHeader
        serif
        title={t.name}
        subtitle={
          <>
            {t.running ? "Mise à jour en cours…" : f ? `${f.content.state ? STATE_LABEL[f.content.state] + " · " : ""}Version ${f.version} · ${relative(f.created_at)} · rédigée par une IA, vérifie les sources qui comptent` : "Pas encore de fiche"}
            {t.kind === "recherche" && " · Veille de recherche"}
            {t.status === "sleeping" && " · En veille : contrôle une fois par semaine"}
            {t.status === "active" && t.rhythm?.auto && ` · Rythme adaptatif : ${everyLabel(t.schedule.weekdays.length ? 1 : t.schedule.every)}`}
            {t.last_run?.status === "error" && <span className="block text-deny">Dernier passage en échec : {t.last_run.error}</span>}
          </>
        }
      />

      {tab === "fiche" && (
        <>
          {t.kind !== "recherche" && <FicheRhythm topic={t} />}
          {versions.data && versions.data.length > 1 && <VersionBar versions={versions.data} current={f?.version ?? null} onPick={setVersion} topicId={id} />}
          {fiche.isLoading ? (
            <div className="py-20"><Spinner /></div>
          ) : f ? (
            <FicheBody fiche={f} />
          ) : (
            <Empty icon={<RefreshCw size={22} />} title={t.running ? "L'agent rédige la première fiche." : "Pas encore de fiche."}>
              {t.running ? "Collecte, tri, recoupement puis rédaction : compte quelques minutes." : "Lance une mise à jour pour la créer."}
            </Empty>
          )}
        </>
      )}
      {tab === "calendrier" && (
        <Calendar
          topicId={id}
          header={<DeadlineRuns topic={t} />}
          onOpenVersion={(v) => {
            setVersion(v === versions.data?.[0]?.version ? null : v);
            setTab("fiche");
          }}
        />
      )}
      {tab === "sources" && <SourcesTab topicId={id} />}
      {tab === "agent" && <AgentPanel topic={t} />}
    </Page>
  );
}

/** Le conseil de rythme, en tête de la fiche tant qu'il n'est pas écarté. */
function FicheRhythm({ topic }: { topic: Topic }) {
  const q = useRhythm(topic.id);
  return <RhythmCard topic={topic} overview={q.data} />;
}

/** Les jours d'échéance donnent un passage de plus : le réglage vit aussi dans l'onglet Agent. */
function DeadlineRuns({ topic }: { topic: Topic }) {
  const qc = useQueryClient();
  const patch = useMutation({
    mutationFn: (follow_deadlines: boolean) => api<Topic>(`/topics/${topic.id}`, { method: "PATCH", body: { follow_deadlines } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["topics"] });
      void qc.invalidateQueries({ queryKey: ["calendar"] });
      void qc.invalidateQueries({ queryKey: ["costs"] });
    },
  });
  return (
    <div className="mb-4 flex items-center justify-between gap-6 rounded-[var(--r-card)] bg-fill px-4 py-2.5">
      <div className="min-w-0">
        <p className="text-[13.5px] text-ink">Passer aussi les jours d'échéance</p>
        <p className="mt-0.5 text-[12px] leading-snug text-ink-2">Le jour de chaque échéance datée au jour près, et le lendemain pour en lire l'issue. Les échéances se remplissent au fil des passages, d'après les sources.</p>
      </div>
      <Toggle label="Passer aussi les jours d'échéance" checked={topic.follow_deadlines} onChange={(v) => patch.mutate(v)} />
    </div>
  );
}

function VersionBar({ versions, current, onPick, topicId }: { versions: { version: number; created_at: string; nothing_new: boolean; whats_new_count: number; confirmations?: number }[]; current: number | null; onPick: (v: number | null) => void; topicId: number }) {
  const previous = usePreviousVisit();
  const [catchup, setCatchup] = useState(false);
  const since = previous ? versions.filter((v) => (parse(v.created_at)?.getTime() ?? 0) > previous.getTime()) : [];
  const latest = versions[0].version;
  return (
    <div className="mt-8">
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
        <History size={14} className="mr-1 shrink-0 text-ink-3" />
        {versions.slice(0, 14).map((v) => (
          <button
            key={v.version}
            onClick={() => onPick(v.version === latest ? null : v.version)}
            title={v.nothing_new ? (v.confirmations ? `Rien de neuf, ${v.confirmations} confirmation(s)` : "Rien de neuf") : `${v.whats_new_count} nouveauté(s)`}
            className={`shrink-0 rounded-md px-2 py-1 text-[12px] transition-colors ${v.version === current ? "bg-ink text-paper" : v.nothing_new ? "text-ink-3 hover:bg-line" : "text-ink-2 hover:bg-line"}`}
          >
            {shortDate(v.created_at)}
          </button>
        ))}
      </div>
      {since.filter((v) => !v.nothing_new).length > 1 && (
        <div className="mt-3 rounded-lg bg-accent-soft px-4 py-3 text-[13.5px] text-ink">
          {since.filter((v) => !v.nothing_new).length} mises à jour depuis ta dernière visite.{" "}
          <button className="font-medium text-accent hover:underline" onClick={() => setCatchup(!catchup)}>
            {catchup ? "Masquer le rattrapage" : "Tout rattraper d'un coup"}
          </button>
          {catchup && previous && <Catchup topicId={topicId} since={previous} />}
        </div>
      )}
    </div>
  );
}

function Catchup({ topicId, since }: { topicId: number; since: Date }) {
  const q = useQuery({
    queryKey: ["catchup", topicId, since.toISOString()],
    queryFn: () => api<{ days: { version: number; created_at: string; whats_new: Item[]; changes: string[] }[] }>(`/topics/${topicId}/catchup?since=${encodeURIComponent(since.toISOString())}`),
  });
  return (
    <div className="mt-4 space-y-4">
      {q.data?.days.map((d) => (
        <div key={d.version}>
          <p className="text-[12px] font-medium text-ink-2">{shortDate(d.created_at)}</p>
          <ul className="mt-1.5 space-y-2">
            {d.whats_new.map((it, i) => (
              <li key={i} className="rail text-[14px]" data-status={it.status}>
                {it.text}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function FicheBody({ fiche }: { fiche: Fiche }) {
  const c = fiche.content;
  const sources = useMemo(() => new Map<string, SourceRef>(fiche.sources.map((s) => [s.ref, s])), [fiche.sources]);
  const chips = (refs: string[]) => refs.map((r) => <SourceChip key={r} refId={r} source={sources.get(r)} />);

  return (
    <Tooltip.Provider>
      <div className="reading">
        {c.lede && <p className="serif mt-8 text-[21px] leading-[1.5] text-ink">{c.lede}</p>}

        <SectionTitle id="nouveautes" aside={c.importance && !fiche.nothing_new ? <span className="text-[12px] text-ink-3">Importance {c.importance} sur 5</span> : null}>Nouveautés</SectionTitle>
        {fiche.nothing_new || !c.whats_new?.length ? (
          <p className="text-ink-2">
            Rien de neuf à ce passage{quietSummary(c.updates)}. La fiche ci-dessous reste valable.
          </p>
        ) : (
          <FactList items={c.whats_new} sources={sources} size="lg" topicId={fiche.topic_id} />
        )}

        {!!c.updates?.confirmations.length && (
          <>
            <SectionTitle id="confirme">Confirmé depuis le dernier passage</SectionTitle>
            <Confirmations items={c.updates.confirmations} sources={sources} />
          </>
        )}
        <TopicCorrections topicId={fiche.topic_id} version={fiche.version} />
        {!!c.updates?.reprises.articles && <Reprises reprises={c.updates.reprises} />}

        {!!c.changes?.length && (
          <>
            <SectionTitle id="changements">Ce qui a changé</SectionTitle>
            <ul className="list-disc space-y-1.5 pl-5 text-[14.5px] text-ink">{c.changes.map((x, i) => <li key={i}>{x}</li>)}</ul>
          </>
        )}

        {c.custom_sections?.map((s) => (
          <div key={s.title}>
            <SectionTitle id={`section-${s.title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`}>{s.title}</SectionTitle>
            <p className="whitespace-pre-line text-[14.5px] leading-[1.65] text-ink">{s.body}</p>
            <div className="mt-2 flex flex-wrap gap-1.5">{chips(s.refs)}</div>
          </div>
        ))}

        {!!c.key_facts?.length && (
          <>
            <SectionTitle id="etabli">Ce qui est établi</SectionTitle>
            <FactList items={c.key_facts} sources={sources} topicId={fiche.topic_id} />
          </>
        )}

        {!!c.timeline?.length && (
          <>
            <SectionTitle id="chronologie">Chronologie</SectionTitle>
            <ol className="space-y-3">
              {[...c.timeline].sort((a, b) => b.date.localeCompare(a.date)).map((e, i) => (
                <li key={i} className="grid grid-cols-[92px_1fr] gap-4">
                  <span className="pt-[2px] text-[12.5px] tabular-nums text-ink-3">{shortDate(e.date) || e.date}</span>
                  <div>
                    <span className="text-[14.5px] text-ink">{e.event}</span>
                    <span className="ml-2 inline-flex flex-wrap gap-1 align-middle">{chips(e.refs)}</span>
                  </div>
                </li>
              ))}
            </ol>
          </>
        )}

        {!!c.perspectives?.length && (
          <>
            <SectionTitle id="positions">Les positions</SectionTitle>
            <ul className="space-y-4">
              {c.perspectives.map((p, i) => (
                <li key={i}>
                  <p className="text-[14.5px] leading-[1.6] text-ink">
                    <span className="font-semibold">{p.actor}.</span> {p.position}
                  </p>
                  <div className="mt-1 flex flex-wrap gap-1.5">{chips(p.refs)}</div>
                </li>
              ))}
            </ul>
          </>
        )}

        <TopicAnnouncements topicId={fiche.topic_id} />

        {!!c.uncertainties?.length && (
          <>
            <SectionTitle id="inconnues">Ce qu'on ne sait pas</SectionTitle>
            <ul className="space-y-2">{c.uncertainties.map((x, i) => <li key={i} className="rail text-[14.5px] text-ink" data-status="non_confirme">{x}</li>)}</ul>
          </>
        )}

        {!!c.watch?.length && (
          <>
            <SectionTitle id="surveiller">À surveiller</SectionTitle>
            <ul className="list-disc space-y-1.5 pl-5 text-[14.5px] text-ink">{c.watch.map((x, i) => <li key={i}>{x}</li>)}</ul>
          </>
        )}

        {fiche.coverage?.articles !== undefined && (
          <>
            <SectionTitle id="spectre" aside={c.confidence ? <span className="text-[12px] text-ink-3">Confiance {{ elevee: "élevée", moyenne: "moyenne", faible: "faible" }[c.confidence]}</span> : null}>Spectre des sources</SectionTitle>
            <Spectrum coverage={fiche.coverage} />
          </>
        )}

        <p className="mt-12 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-ink-3">
          Légende :
          {(["confirme", "non_confirme", "conteste", "dementi"] as const).map((s) => (
            <StatusLabel key={s} status={s} />
          ))}
        </p>
      </div>
    </Tooltip.Provider>
  );
}

/** « · 2 faits confirmés · 5 reprises » : ce que le passage a quand même vu. */
function quietSummary(u: FicheUpdates | undefined): string {
  if (!u) return "";
  const parts = [];
  const n = u.confirmations.length;
  if (n) parts.push(`${n} fait${n > 1 ? "s" : ""} confirmé${n > 1 ? "s" : ""} ou appuyé${n > 1 ? "s" : ""}`);
  if (u.reprises.articles) parts.push(`${u.reprises.articles} reprise${u.reprises.articles > 1 ? "s" : ""}`);
  return parts.length ? ` · ${parts.join(" · ")}` : "";
}

/** Les faits déjà connus que ce passage confirme ou appuie : une ligne chacun, pas une nouveauté. */
function Confirmations({ items, sources }: { items: FactUpdate[]; sources: Map<string, SourceRef> }) {
  return (
    <ul className="space-y-3">
      {items.map((u, i) => (
        <li key={i} className="flex gap-2.5">
          <Check size={15} className="mt-[3px] shrink-0 text-ok" aria-hidden />
          <div className="min-w-0">
            <p className="text-[14.5px] leading-[1.55] text-ink">{u.text}</p>
            <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[12.5px] text-ink-2">
              {u.kind === "confirmation" ? <span className="font-medium text-ok">Désormais confirmé</span> : <span>Rapporté aussi par</span>}
              {u.kind === "confirmation" && u.refs_new.length > 0 && <span>grâce à</span>}
              {u.refs_new.map((r) => (
                <SourceChip key={r} refId={r} source={sources.get(r)} />
              ))}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}

/** Les articles qui n'ont fait que redire des faits connus : comptés, jamais répétés. */
function Reprises({ reprises }: { reprises: FicheUpdates["reprises"] }) {
  const n = reprises.articles;
  const media = reprises.media.length ? ` (${reprises.media.slice(0, 4).join(", ")}${reprises.media.length > 4 ? "…" : ""})` : "";
  return (
    <p className="mt-6 flex items-center gap-1.5 text-[12.5px] text-ink-3">
      <Repeat size={12} aria-hidden />
      Aussi : {n} article{n > 1 ? "s ont" : " a"} repris des faits déjà connus{media}.
    </p>
  );
}

const NATURE: Record<string, string> = { fait: "Faits", analyse: "Analyse", opinion: "Opinion", reaction: "Réaction", rumeur: "Rumeur", hors_sujet: "Hors sujet" };

function SourcesTab({ topicId }: { topicId: number }) {
  const [kept, setKept] = useState<"true" | "false">("true");
  const q = useQuery({ queryKey: ["articles", topicId, kept], queryFn: () => api<Article[]>(`/topics/${topicId}/articles?kept=${kept}`) });
  return (
    <div className="mt-8">
      <div className="flex items-center justify-between">
        <p className="text-[13px] text-ink-2">{kept === "true" ? "Les articles retenus après tri." : "Les articles écartés, et pourquoi."}</p>
        <Segmented value={kept} onChange={setKept} options={[{ value: "true", label: "Retenus" }, { value: "false", label: "Écartés" }]} />
      </div>
      {q.isLoading && <div className="py-10"><Spinner /></div>}
      {q.data?.length === 0 && <p className="py-10 text-ink-3">Aucun article pour l'instant.</p>}
      <ul className="mt-4 divide-y divide-line">
        {q.data?.map((a) => (
          <li key={a.id} className="py-3.5">
            <button onClick={() => openLink(a.url)} className="text-left text-[14.5px] font-medium leading-snug text-ink hover:text-accent">
              {a.title}
            </button>
            <p className="mt-1 text-[12.5px] text-ink-3">
              {a.source}
              {a.published_at && `, ${shortDate(a.published_at)}`}
              {a.wire && `, reprend une dépêche ${a.wire}`}
              {a.nature && `. ${NATURE[a.nature] ?? a.nature}`}
              {a.sensationalism >= 0.6 && ", ton sensationnaliste"}
            </p>
            {a.reason && <p className="mt-1 text-[13px] text-ink-2">{a.reason}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

function TopicAnnouncements({ topicId }: { topicId: number }) {
  const q = useQuery({ queryKey: ["announcements", topicId], queryFn: () => api<Announcement[]>(`/topics/${topicId}/announcements`) });
  if (!q.data?.length) return null;
  return (
    <>
      <SectionTitle id="annonces" aside={<span className="text-[12px] text-ink-3">revérifié automatiquement à l'échéance</span>}>Annoncé et réalisé</SectionTitle>
      <AnnouncementList items={q.data} />
    </>
  );
}

function TopicCorrections({ topicId, version }: { topicId: number; version: number }) {
  const q = useQuery({ queryKey: ["corrections", topicId], queryFn: () => api<Correction[]>(`/corrections?topic_id=${topicId}`) });
  const items = (q.data ?? []).filter((c) => c.version <= version).slice(0, 6);
  if (!items.length) return null;
  const read = items.some((c) => c.read_by_user);
  return (
    <>
      <SectionTitle id="corrections">{read ? "Corrigé depuis ta lecture" : "Corrections"}</SectionTitle>
      <CorrectionList items={items} />
    </>
  );
}
