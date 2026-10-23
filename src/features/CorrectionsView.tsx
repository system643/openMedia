import { usePageChrome } from "../lib/chrome";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { CorrectionList } from "../components/Followups";
import { Empty, Page, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { nav } from "../lib/nav";
import type { Correction } from "../lib/types";

/** Le journal des corrections : ce que tu as lu et qui s'est révélé faux, contesté ou inexact. */
export function CorrectionsView() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["corrections"], queryFn: () => api<Correction[]>("/corrections") });
  usePageChrome("Journal des corrections");
  const seen = useMutation({
    mutationFn: (ids?: number[]) => api("/corrections/seen", { method: "POST", body: { ids: ids ?? null } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["corrections"] }),
  });

  // Ouvrir le journal vaut lecture, après un court délai pour laisser voir ce qui est nouveau.
  useEffect(() => {
    if (!q.data?.some((c) => !c.seen_at)) return;
    const t = setTimeout(() => seen.mutate(undefined), 4000);
    return () => clearTimeout(t);
  }, [q.data]); // eslint-disable-line react-hooks/exhaustive-deps

  if (q.isLoading) return <div className="grid h-full place-items-center"><Spinner /></div>;
  const read = q.data?.filter((c) => c.read_by_user) ?? [];
  const other = q.data?.filter((c) => !c.read_by_user) ?? [];

  return (
    <Page>
      <PageHeader title="Journal des corrections" subtitle="Quand un fait déjà publié dans une de tes fiches est démenti, contesté ou corrigé par de nouvelles sources, il est consigné ici. Ceux que tu avais lus te sont signalés en priorité." />
        {!q.data?.length && <Empty title="Aucune correction pour l'instant.">Les faits de tes fiches tiennent toujours.</Empty>}
        {read.length > 0 && (
          <>
            <h2 className="mb-4 mt-10 text-[15px] font-semibold text-ink">Ce que tu avais lu</h2>
            <CorrectionList items={read} showTopic onOpenTopic={(id) => nav.go({ name: "topic", id })} />
          </>
        )}
        {other.length > 0 && (
          <>
            <h2 className="mb-4 mt-10 text-[15px] font-semibold text-ink">Corrigé avant ta lecture</h2>
            <CorrectionList items={other} showTopic onOpenTopic={(id) => nav.go({ name: "topic", id })} />
          </>
        )}
    </Page>
  );
}
