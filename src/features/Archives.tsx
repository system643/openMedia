import { usePageChrome } from "../lib/chrome";
import { useQuery } from "@tanstack/react-query";
import { Button, Empty, Page, PageHeader, SectionTitle, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { relative } from "../lib/format";
import { nav } from "../lib/nav";
import type { Topic } from "../lib/types";

export function Archives() {
  const q = useQuery({ queryKey: ["topics", "all"], queryFn: () => api<Topic[]>("/topics?include_archived=true") });
  usePageChrome("Archives");
  if (q.isLoading) return <div className="grid h-full place-items-center"><Spinner /></div>;
  const sleeping = q.data?.filter((t) => t.status === "sleeping") ?? [];
  const archived = q.data?.filter((t) => t.status === "archived") ?? [];

  return (
    <Page>
      <PageHeader title="Archives" subtitle="Chaque fiche garde toutes ses versions : rien n'est effacé, les anciennes nouvelles restent rangées sous leur sujet." />
        {!sleeping.length && !archived.length && <Empty title="Rien en veille, rien d'archivé." />}
        {sleeping.length > 0 && (
          <>
            <SectionTitle>En veille</SectionTitle>
            <TopicList topics={sleeping} />
          </>
        )}
        {archived.length > 0 && (
          <>
            <SectionTitle>Archivés</SectionTitle>
            <TopicList topics={archived} />
          </>
        )}
    </Page>
  );
}

function TopicList({ topics }: { topics: Topic[] }) {
  return (
    <ul className="divide-y divide-line">
      {topics.map((t) => (
        <li key={t.id} className="flex items-center justify-between gap-4 py-3">
          <div className="min-w-0">
            <p className="truncate text-[15px] text-ink">{t.name}</p>
            <p className="text-[12.5px] text-ink-3">{t.latest ? `${t.latest.version} version${t.latest.version > 1 ? "s" : ""}, dernière ${relative(t.latest.created_at)}` : "Aucune fiche"}</p>
          </div>
          <Button variant="ghost" onClick={() => nav.go({ name: "topic", id: t.id })}>
            Ouvrir
          </Button>
        </li>
      ))}
    </ul>
  );
}
