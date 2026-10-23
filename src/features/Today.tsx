import { useQuery } from "@tanstack/react-query";
import { CalendarClock, ChevronRight, History, Newspaper, Plus } from "lucide-react";
import { AudioButton } from "../components/AudioButton";
import { EngineChoice, engineReady } from "../components/EngineChoice";
import { Button, Card, Empty, Page, PageHeader, SectionTitle, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { usePageChrome } from "../lib/chrome";
import { STATUS_LABEL, longDay, parse, relative, shortDate } from "../lib/format";
import { nav } from "../lib/nav";
import type { Announcement, Brief, Correction, Settings, Topic } from "../lib/types";
import { usePreviousVisit } from "../lib/visit";

interface TodayData {
  day: string;
  brief: Brief | null;
  topics: Topic[];
}

export function Today() {
  const today = useQuery({ queryKey: ["today"], queryFn: () => api<TodayData>("/today") });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<Settings>("/settings") });
  const previous = usePreviousVisit();
  const corrections = useQuery({ queryKey: ["corrections", "unseen"], queryFn: () => api<Correction[]>("/corrections?unseen=true") });
  const upcoming = useQuery({ queryKey: ["announcements", "upcoming"], queryFn: () => api<Announcement[]>("/announcements/upcoming") });
  usePageChrome(
    "Aujourd'hui",
    <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => nav.openNewTopic()}>
      Suivre un sujet
    </Button>,
  );

  if (today.isLoading || settings.isLoading) return <div className="grid h-[60vh] place-items-center"><Spinner /></div>;
  const topics = (today.data?.topics ?? []).filter((t) => t.status !== "archived");
  const brief = today.data?.brief;
  const updated = topics.filter((t) => t.latest && !t.latest.nothing_new);
  const isFresh = (t: Topic) => !previous || (parse(t.latest!.created_at)?.getTime() ?? 0) > previous.getTime();
  const quiet = topics.filter((t) => !t.latest || t.latest.nothing_new);
  const readCorrections = (corrections.data ?? []).filter((c) => c.read_by_user);
  const deadlines = upcoming.data ?? [];

  return (
    <Page wide>
      <PageHeader title="Aujourd'hui" eyebrow={longDay()} />

      {settings.data && !engineReady(settings.data) && <EnginePrompt settings={settings.data} />}

      {settings.data && engineReady(settings.data) && !settings.data.consent_at && (
        <Card as="section" className="mb-8 flex items-center gap-4 p-5">
          <div className="min-w-0 flex-1">
            <p className="text-[15px] font-semibold text-ink">openMedia est à l'arrêt</p>
            <p className="mt-0.5 text-[13.5px] text-ink-2">Aucun passage ni envoi tant que tu n'as pas accepté les conditions de fonctionnement.</p>
          </div>
          <Button variant="primary" onClick={() => nav.go({ name: "settings", section: "confidentialite" })}>
            Voir les conditions
          </Button>
        </Card>
      )}

      {readCorrections.length > 0 && (
        <button onClick={() => nav.go({ name: "corrections" })} className="card mb-6 flex w-full items-center gap-4 p-4 text-left transition-transform active:scale-[0.995]">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-[color-mix(in_srgb,var(--deny)_14%,transparent)] text-deny">
            <History size={19} />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[15px] font-semibold text-ink">
              {readCorrections.length === 1 ? "Un fait que tu avais lu a été corrigé" : `${readCorrections.length} faits que tu avais lus ont été corrigés`}
            </span>
            <span className="block truncate text-[13px] text-ink-2">{readCorrections[0].previous_text}</span>
          </span>
          <ChevronRight size={18} className="shrink-0 text-ink-3" />
        </button>
      )}

      {brief && (
        <Card as="section" className="mb-8 p-7">
          <div className="flex items-center justify-between gap-4">
            <p className="text-[13px] font-semibold text-accent">Le Brief</p>
            <p className="text-[12px] text-ink-3">rédigé par une IA, le Directeur de rédaction</p>
          </div>
          <h2 className="serif mt-2 text-[30px] font-medium leading-[1.15] text-ink">{brief.content.headline}</h2>
          <ol className="mt-6 divide-y divide-line">
            {brief.content.points.slice(0, 4).map((p, i) => (
              <li key={i} className="py-3.5 first:pt-0">
                <button onClick={() => nav.go({ name: "topic", id: p.topic_id })} className="text-[12px] font-semibold text-ink-2 hover:text-accent">
                  {p.topic_name}
                </button>
                <p className="mt-0.5 text-[15.5px] leading-[1.5] text-ink">{p.text}</p>
                <p className="mt-0.5 text-[13.5px] leading-[1.5] text-ink-2">{p.why}</p>
              </li>
            ))}
          </ol>
          <div className="mt-5 flex flex-wrap gap-2">
            <AudioButton file={brief.audio_path} generatePath={`/briefs/${brief.id}/audio`} label="Écouter le brief" />
            <Button variant="ghost" onClick={() => nav.go({ name: "brief", id: brief.id })}>
              Lire le brief en entier
            </Button>
          </div>
        </Card>
      )}

      {topics.length === 0 && settings.data && engineReady(settings.data) && (
        <Empty icon={<Newspaper size={22} />} title="Quel sujet veux-tu suivre ?" action={<Button variant="primary" onClick={() => nav.openNewTopic()}>Suivre un sujet</Button>}>
          Décris un sujet et la façon dont tu veux l'étudier. Un agent le suivra chaque jour, recoupera les sources et tiendra sa fiche à jour.
        </Empty>
      )}

      {updated.length > 0 && (
        <>
          <SectionTitle aside={previous && <span className="text-[12px] text-ink-3">depuis ta dernière visite en premier</span>}>Tes sujets</SectionTitle>
          <div className="grid gap-4 lg:grid-cols-2">
            {[...updated].sort((a, b) => Number(isFresh(b)) - Number(isFresh(a))).map((t) => (
              <TopicCard key={t.id} topic={t} fresh={isFresh(t)} />
            ))}
          </div>
        </>
      )}

      {quiet.length > 0 && (
        <Card className="mt-4 px-5 py-4">
          <p className="text-[13px] font-semibold text-ink-2">Rien de neuf</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {quiet.map((t) => (
              <button key={t.id} onClick={() => nav.go({ name: "topic", id: t.id })} className="rounded-full bg-fill px-3 py-1 text-[13px] text-ink hover:bg-fill-strong">
                {t.name}
                {t.running && <span className="text-ink-3"> · mise à jour…</span>}
              </button>
            ))}
          </div>
        </Card>
      )}

      {deadlines.length > 0 && (
        <>
          <SectionTitle
            aside={
              <button onClick={() => nav.go({ name: "deadlines" })} className="text-[13px] text-accent hover:underline">
                Tout voir
              </button>
            }
          >
            Échéances
          </SectionTitle>
          <Card className="divide-y divide-line">
            {deadlines.slice(0, 4).map((a) => (
              <button key={a.id} onClick={() => nav.go({ name: "topic", id: a.topic_id })} className="flex w-full items-center gap-4 px-5 py-3 text-left hover:bg-fill/50">
                <CalendarClock size={16} className={a.status === "en_retard" ? "shrink-0 text-deny" : a.status === "realise" ? "shrink-0 text-ok" : "shrink-0 text-ink-3"} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px] text-ink">{a.text}</span>
                  <span className="block text-[12px] text-ink-2">{a.topic_name}</span>
                </span>
                <span className={`shrink-0 text-[12.5px] ${a.status === "en_retard" ? "font-medium text-deny" : "text-ink-2"}`}>
                  {a.status === "en_retard" ? "En retard" : a.status === "realise" ? "Réalisé" : shortDate(a.due_date)}
                </span>
              </button>
            ))}
          </Card>
        </>
      )}
    </Page>
  );
}

function TopicCard({ topic: t, fresh }: { topic: Topic; fresh: boolean }) {
  const first = t.latest?.whats_new[0];
  const count = t.latest?.whats_new.length ?? 0;
  return (
    <button onClick={() => nav.go({ name: "topic", id: t.id })} className="card group flex flex-col p-5 text-left transition-[transform,box-shadow] hover:shadow-pop active:scale-[0.995]">
      <div className="flex items-center gap-2">
        {fresh && <span className="size-2 rounded-full bg-accent" aria-label="Nouveau depuis ta dernière visite" />}
        <h3 className="title-md min-w-0 flex-1 truncate text-ink">{t.name}</h3>
        <ChevronRight size={17} className="shrink-0 text-ink-3 transition-transform group-hover:translate-x-0.5" />
      </div>
      <p className="mt-0.5 text-[12.5px] text-ink-2">
        {t.running ? "Mise à jour en cours…" : `${relative(t.latest!.created_at)} · ${count} nouveauté${count > 1 ? "s" : ""}`}
      </p>
      {first && (
        <div className="rail mt-4" data-status={first.status}>
          <p className="line-clamp-3 text-[14.5px] leading-[1.5] text-ink">{first.text}</p>
          <p className={`mt-1 text-[12px] font-medium ${{ confirme: "text-ok", non_confirme: "text-warn", conteste: "text-contest", dementi: "text-deny" }[first.status]}`}>{STATUS_LABEL[first.status]}</p>
        </div>
      )}
      {!first && t.latest?.lede && <p className="mt-4 line-clamp-3 text-[14px] leading-[1.5] text-ink-2">{t.latest.lede}</p>}
    </button>
  );
}

function EnginePrompt({ settings }: { settings: Settings }) {
  return (
    <Card as="section" className="mb-8 p-6">
      <h2 className="title-md text-ink">Choisis l'IA de ton journal</h2>
      <p className="mb-4 mt-1.5 max-w-[62ch] text-[14px] text-ink-2">Les agents d'openMedia lisent et recoupent la presse avec un modèle d'IA, sur ce PC ou en ligne.</p>
      <EngineChoice settings={settings} />
    </Card>
  );
}
