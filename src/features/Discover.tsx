import { usePageChrome } from "../lib/chrome";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { RecurringList } from "../components/RecurringTopics";
import { Compass } from "lucide-react";
import { Button, Empty, Page, PageHeader, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { nav } from "../lib/nav";
import type { Settings, Story } from "../lib/types";

const SECTION: Record<string, string> = {
  TOP: "À la une",
  WORLD: "Monde",
  NATION: "France",
  BUSINESS: "Économie",
  TECHNOLOGY: "Technologie",
  SCIENCE: "Sciences",
  HEALTH: "Santé",
  ENTERTAINMENT: "Culture",
  SPORTS: "Sport",
};

/** Les histoires à la une des médias en ce moment, regroupées et proposées au suivi. */
export function Discover() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<Settings>("/settings") });
  const enabled = !!settings.data?.discover_enabled;
  const q = useQuery({ queryKey: ["discover"], queryFn: () => api<{ stories: Story[] }>("/discover"), staleTime: 30 * 60_000, enabled });
  usePageChrome(
    "Découvrir",
    enabled ? (
      <Button size="sm" busy={q.isFetching} onClick={() => qc.fetchQuery({ queryKey: ["discover"], queryFn: () => api<{ stories: Story[] }>("/discover?force=true") })}>
        Actualiser
      </Button>
    ) : null,
    [q.isFetching, enabled],
  );
  const activate = async () => {
    qc.setQueryData(["settings"], await api<Settings>("/settings", { method: "PATCH", body: { discover_enabled: true } }));
  };

  return (
    <Page>
        <PageHeader title="Découvrir" subtitle="Les histoires qui durent, d'après les unes de vingt médias de tous bords, en France et à l'étranger. Un clic pour en faire un sujet suivi." />
        {settings.data?.history_auto && <RecurringList />}
        {settings.data && !enabled && (
          <Empty
            icon={<Compass size={22} />}
            title="Découvrir est désactivé."
            action={<Button variant="primary" onClick={() => void activate()}>Activer Découvrir</Button>}
          >
            {settings.data.engine === "local"
              ? "Les titres à la une de vingt médias et les noms de tes sujets sont lus par l'IA de ce PC pour te proposer des histoires à suivre."
              : "Les titres à la une de vingt médias et les noms de tes sujets sont envoyés à ton fournisseur d'IA pour te proposer des histoires à suivre."}{" "}
            Tu peux le couper à nouveau dans Réglages › Confidentialité.
          </Empty>
        )}

        {q.isLoading && (
          <div className="flex items-center gap-3 py-16 text-ink-2">
            <Spinner /> Lecture des unes et regroupement des histoires…
          </div>
        )}
        {q.error && <Empty title="Impossible de lire les unes.">{q.error.message}</Empty>}
        {enabled && q.data && q.data.stories.length === 0 && <Empty title="Aucune histoire à proposer pour l'instant.">Les unes des médias n'ont rien donné de suivable : réessaie plus tard avec « Actualiser ».</Empty>}

        <ul className="mt-8 divide-y divide-line">
          {q.data?.stories.map((s, i) => (
            <li key={i} className="flex gap-6 py-5">
              <div className="min-w-0 flex-1">
                <p className="text-[12px] text-ink-3">
                  {SECTION[s.section] ?? s.section}, {s.size} média{s.size > 1 ? "s" : ""}
                </p>
                <h3 className="serif mt-0.5 text-[20px] leading-snug text-ink">{s.title}</h3>
                <p className="mt-1 text-[14px] leading-[1.55] text-ink-2">{s.summary}</p>
                {s.sources.length > 0 && <p className="mt-1.5 text-[12px] text-ink-3">{s.sources.join(", ")}</p>}
              </div>
              <div className="shrink-0 pt-4">
                {s.related_topic_id ? (
                  <Button variant="ghost" onClick={() => nav.go({ name: "topic", id: s.related_topic_id! })}>
                    Déjà suivi
                  </Button>
                ) : (
                  <Button onClick={() => nav.openNewTopic({ prompt: s.suggested_prompt, name: s.title })}>Suivre</Button>
                )}
              </div>
            </li>
          ))}
        </ul>
    </Page>
  );
}
