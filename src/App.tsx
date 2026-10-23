import * as Dialog from "@radix-ui/react-dialog";
import * as Tooltip from "@radix-ui/react-tooltip";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { listen } from "@tauri-apps/api/event";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useState } from "react";
import { DropCard, urlFromDrop } from "./components/DropCard";
import { Sidebar } from "./components/Sidebar";
import { CommandPalette } from "./components/CommandPalette";
import { ShortcutsSheet } from "./components/ShortcutsSheet";
import { Toolbar } from "./components/Toolbar";
import { Toasts } from "./components/Toasts";
import { Archives } from "./features/Archives";
import { BriefView } from "./features/BriefView";
import { CorrectionsView } from "./features/CorrectionsView";
import { DeadlinesView } from "./features/DeadlinesView";
import { ReadingsView } from "./features/ReadingsView";
import { RecordingsView } from "./features/RecordingsView";
import { Discover } from "./features/Discover";
import { NewTopicSheet } from "./features/NewTopicSheet";
import { Onboarding } from "./features/onboarding/Onboarding";
import { SettingsView } from "./features/SettingsView";
import { Today } from "./features/Today";
import { TopicView } from "./features/TopicView";
import { api, inTauri } from "./lib/api";
import { chrome } from "./lib/chrome";
import { pushToast, useServerEvents } from "./lib/events";
import { motionProps, page, spring } from "./lib/motion";
import { nav, useNav } from "./lib/nav";
import { useShortcuts } from "./lib/shortcuts";
import { applyTheme } from "./lib/theme";
import type { Drop, Settings } from "./lib/types";

export function App() {
  const { view, sidebar } = useNav();
  const qc = useQueryClient();
  const [drop, setDrop] = useState<Drop | null>(null);
  const [dragging, setDragging] = useState(false);
  useServerEvents();

  // Ctrl+R : mettre à jour le sujet ouvert.
  const refresh = useCallback(() => {
    const v = nav.current();
    if (v.name !== "topic") return;
    api(`/topics/${v.id}/run`, { method: "POST" })
      .then(() => {
        void qc.invalidateQueries({ queryKey: ["topics"] });
        pushToast("Mise à jour du sujet lancée", "info", v.id);
      })
      .catch((e: Error) => pushToast(e.message, "error"));
  }, [qc]);
  useShortcuts(refresh);

  // Le thème choisi dans les Réglages (mémorisé aussi côté moteur, pour la bulle et les relances).
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<Settings>("/settings") });
  useEffect(() => {
    if (settings.data?.theme) applyTheme(settings.data.theme);
  }, [settings.data?.theme]);

  useEffect(() => {
    if (!inTauri) return;
    const offs = [
      listen<string>("navigate", (e) => nav.fromRoute(e.payload)),
      listen("tray-run-all", () => {
        api("/run-all", { method: "POST" })
          .then(() => pushToast("Mise à jour de tous les sujets lancée"))
          .catch((e: Error) => pushToast(e.message, "error"));
      }),
      listen("topics-changed", () => qc.invalidateQueries()),
      listen("recordings-changed", () => qc.invalidateQueries({ queryKey: ["recordings"] })),
    ];
    return () => offs.forEach((p) => p.then((off) => off()));
  }, [qc]);

  // On peut aussi déposer un lien directement sur la fenêtre principale.
  async function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const url = urlFromDrop(e.dataTransfer);
    if (!url) return;
    pushToast("Lecture de l'article déposé…");
    try {
      setDrop(await api<Drop>("/drop", { method: "POST", body: { url } }));
    } catch (err) {
      pushToast(err instanceof Error ? err.message : String(err), "error");
    }
  }

  return (
    <Tooltip.Provider>
      <div
        className="relative flex h-full bg-paper"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={(e) => e.currentTarget === e.target && setDragging(false)}
        onDrop={onDrop}
      >
        <AnimatePresence initial={false}>
          {sidebar && (
            // La barre latérale flotte au-dessus du contenu, en verre, avec une marge de 8 px.
            // Elle glisse vers le bord en se repliant, comme sous macOS.
            <motion.div key="sidebar" className="relative z-30 flex shrink-0 overflow-hidden py-2 pl-2" initial={{ width: 0 }} animate={{ width: 256 }} exit={{ width: 0 }} transition={spring.smooth}>
              <motion.div className="h-full" initial={{ x: -24, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: -24, opacity: 0 }} transition={spring.smooth}>
                <Sidebar />
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
        <div className="relative flex min-w-0 flex-1 flex-col">
          {/* La barre d'outils flotte au-dessus du contenu, qui défile dessous. */}
          <Toolbar />
          <main className="scroll-area relative min-h-0 flex-1" onScroll={(e) => chrome.setScrolled(e.currentTarget.scrollTop > 2)}>
            <div aria-hidden className="h-[52px]" />
            <AnimatePresence mode="wait" initial={false}>
              <motion.div key={JSON.stringify(view)} variants={page} {...motionProps}>
                {view.name === "today" && <Today />}
                {view.name === "brief" && <BriefView id={view.id} />}
                {view.name === "topic" && <TopicView id={view.id} tab={view.tab} />}
                {view.name === "discover" && <Discover />}
                {view.name === "archives" && <Archives />}
                {view.name === "corrections" && <CorrectionsView />}
                {view.name === "deadlines" && <DeadlinesView />}
                {view.name === "readings" && <ReadingsView />}
                {view.name === "recordings" && <RecordingsView id={view.id} follow={view.follow} />}
                {view.name === "settings" && <SettingsView section={view.section} />}
              </motion.div>
            </AnimatePresence>
          </main>
        </div>
        {dragging && (
          <div className="pointer-events-none absolute inset-3 z-40 grid place-items-center rounded-2xl border-2 border-dashed border-accent bg-accent-soft">
            <p className="serif text-[24px] text-accent">Dépose le lien pour le suivre</p>
          </div>
        )}
      </div>
      <NewTopicSheet />
      <Onboarding />
      <CommandPalette onRefresh={refresh} />
      <ShortcutsSheet />
      <Dialog.Root open={!!drop} onOpenChange={(o) => !o && setDrop(null)}>
        <Dialog.Portal>
          <Dialog.Overlay className="scrim anim-scrim z-40" />
          <Dialog.Content aria-describedby={undefined} className="glass anim-sheet fixed left-1/2 top-24 z-50 h-[300px] w-[420px] -translate-x-1/2 rounded-[var(--r-sheet)] p-5">
            <Dialog.Title className="sr-only">Lien déposé</Dialog.Title>
            {drop && <DropCard drop={drop} onDone={() => setDrop(null)} onOpenTopic={(id) => { void qc.invalidateQueries(); nav.go({ name: "topic", id }); }} />}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
      <Toasts />
    </Tooltip.Provider>
  );
}
