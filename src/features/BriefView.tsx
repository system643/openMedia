import { usePageChrome } from "../lib/chrome";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioButton } from "../components/AudioButton";
import { Button, Empty, Page, PageHeader, SectionTitle, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { longDay, parse } from "../lib/format";
import { nav } from "../lib/nav";
import type { Brief } from "../lib/types";

export function BriefView({ id }: { id?: number }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["briefs"], queryFn: () => api<{ id: number; day: string; headline: string }[]>("/briefs") });
  const currentId = id ?? list.data?.[0]?.id;
  const brief = useQuery({ queryKey: ["briefs", currentId], queryFn: () => api<Brief>(`/briefs/${currentId}`), enabled: !!currentId });
  const run = useMutation({
    mutationFn: () => api<Brief>("/briefs/run", { method: "POST" }),
    onSuccess: (b) => {
      void qc.invalidateQueries({ queryKey: ["briefs"] });
      void qc.invalidateQueries({ queryKey: ["today"] });
      nav.go({ name: "brief", id: b.id });
    },
  });

  usePageChrome(
    "Le Brief",
    <Button size="sm" busy={run.isPending} onClick={() => run.mutate()}>
      Rédiger un nouveau brief
    </Button>,
    [run.isPending],
  );

  if (list.isLoading) return <div className="grid h-full place-items-center"><Spinner /></div>;
  const b = brief.data;

  return (
    <Page>
        {!b && <PageHeader title="Le Brief" />}
        {run.error && <p className="mt-2 text-[13px] text-deny">{run.error.message}</p>}

        {!b && !brief.isLoading && (
          <Empty title="Pas encore de brief.">
            Chaque matin, après le passage de tes agents, le Directeur de rédaction relit toutes les fiches et te dit ce qui compte. Tu peux aussi le lancer maintenant.
          </Empty>
        )}

        {b && (
          <article className="reading">
            <PageHeader serif eyebrow={`Le Brief du ${longDay(parse(b.day + "T12:00:00") ?? new Date()).toLowerCase()} · rédigé par une IA`} title={b.content.headline}>
              <div className="mt-5">
                <AudioButton key={b.id} file={b.audio_path} generatePath={`/briefs/${b.id}/audio`} label="Écouter le brief" />
              </div>
            </PageHeader>
            <ol className="mt-8 space-y-7">
              {b.content.points.map((p, i) => (
                <li key={i}>
                  <button onClick={() => nav.go({ name: "topic", id: p.topic_id })} className="text-[13px] font-medium text-accent hover:underline">
                    {p.topic_name}
                  </button>
                  <p className="serif mt-1 text-[20px] leading-[1.45] text-ink">{p.text}</p>
                  <p className="mt-1.5 text-[14.5px] leading-[1.6] text-ink-2">{p.why}</p>
                </li>
              ))}
            </ol>
            {b.content.cross_links.length > 0 && (
              <>
                <SectionTitle>Les liens entre tes sujets</SectionTitle>
                <ul className="list-disc space-y-1.5 pl-5 text-[14.5px] text-ink">{b.content.cross_links.map((x, i) => <li key={i}>{x}</li>)}</ul>
              </>
            )}
            {b.content.quiet_topics.length > 0 && <p className="mt-10 text-[13.5px] text-ink-2">Sans nouveauté notable : {b.content.quiet_topics.join(", ")}.</p>}
          </article>
        )}

        {list.data && list.data.length > 1 && (
          <>
            <SectionTitle>Les brefs précédents</SectionTitle>
            <ul className="divide-y divide-line">
              {list.data.map((x) => (
                <li key={x.id}>
                  <button onClick={() => nav.go({ name: "brief", id: x.id })} className={`flex w-full gap-6 py-2.5 text-left text-[14px] hover:text-accent ${x.id === currentId ? "text-accent" : "text-ink"}`}>
                    <span className="w-24 shrink-0 tabular-nums text-ink-3">{x.day}</span>
                    <span className="truncate">{x.headline}</span>
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
    </Page>
  );
}
