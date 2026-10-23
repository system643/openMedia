import { useQuery } from "@tanstack/react-query";
import { CalendarClock } from "lucide-react";
import { useState } from "react";
import { Calendar } from "../components/Calendar";
import { AnnouncementList } from "../components/Followups";
import { Card, Empty, Page, PageHeader, SectionTitle, Segmented, Spinner } from "../components/ui";
import { api } from "../lib/api";
import { usePageChrome } from "../lib/chrome";
import { parse } from "../lib/format";
import { nav } from "../lib/nav";
import type { Announcement } from "../lib/types";

type Mode = "liste" | "calendrier";

function storedMode(): Mode {
  try {
    return localStorage.getItem("deadlines-mode") === "calendrier" ? "calendrier" : "liste";
  } catch {
    return "liste";
  }
}

/** Les annonces datées de tous les sujets, de la plus pressante à la plus lointaine, ou au calendrier. */
export function DeadlinesView() {
  const q = useQuery({ queryKey: ["announcements", "all"], queryFn: () => api<Announcement[]>("/announcements/upcoming?days=3650") });
  const [mode, setMode] = useState<Mode>(storedMode);
  const pick = (m: Mode) => {
    setMode(m);
    try {
      localStorage.setItem("deadlines-mode", m);
    } catch {
      // Préférence de confort : sans stockage, la liste revient au prochain lancement.
    }
  };
  usePageChrome("Échéances", <Segmented<Mode> label="Affichage" value={mode} onChange={pick} options={[{ value: "liste", label: "Liste" }, { value: "calendrier", label: "Calendrier" }]} />, [mode]);

  if (q.isLoading) return <div className="grid h-[60vh] place-items-center"><Spinner /></div>;
  const all = q.data ?? [];
  const in7 = Date.now() + 7 * 86_400_000;
  const due = (a: Announcement) => parse(a.due_date)?.getTime() ?? Infinity;
  const groups: [string, Announcement[]][] = [
    ["En retard", all.filter((a) => a.status === "en_retard")],
    ["Cette semaine", all.filter((a) => a.status === "a_venir" && due(a) <= in7)],
    ["Plus tard", all.filter((a) => a.status === "a_venir" && due(a) > in7)],
    ["Tranchées récemment", all.filter((a) => a.status === "realise" || a.status === "reporte" || a.status === "abandonne")],
  ];

  return (
    <Page wide={mode === "calendrier"}>
      <PageHeader title="Échéances" subtitle="Les annonces datées relevées dans tes fiches. À l'échéance, openMedia vérifie de lui-même si elles ont eu lieu." />
      {mode === "calendrier" && <Calendar onOpenTopic={(id) => nav.go({ name: "topic", id, tab: "calendrier" })} />}
      {mode === "liste" && !all.length && (
        <Empty icon={<CalendarClock size={22} />} title="Aucune annonce suivie.">
          Quand une fiche relève une promesse datée (« le vote aura lieu en mars »), elle apparaît ici.
        </Empty>
      )}
      {mode === "liste" &&
        groups
        .filter(([, items]) => items.length)
        .map(([title, items]) => (
          <section key={title}>
            <SectionTitle>
              {title} <span className="font-normal text-ink-3">{items.length}</span>
            </SectionTitle>
            <Card className="px-5 py-4">
              <AnnouncementList items={items} showTopic onOpenTopic={(id) => nav.go({ name: "topic", id })} />
            </Card>
          </section>
        ))}
    </Page>
  );
}
