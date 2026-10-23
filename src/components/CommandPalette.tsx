import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Bookmark, CalendarClock, Compass, FileText, Hash, History, Newspaper, Plus, Radio, RefreshCw, Search, Settings, Smartphone, Sparkles } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import { STATUS_LABEL } from "../lib/format";
import { fold } from "../lib/fold";
import { nav, useNav } from "../lib/nav";
import type { Status } from "../lib/types";
import { openLink } from "./Facts";
import { motionProps, scrim, sheet } from "../lib/motion";

interface Result {
  key: string;
  group: string;
  icon: ReactNode;
  label: string;
  detail?: string;
  status?: Status;
  run: () => void;
}

interface SearchResults {
  topics: { id: number; name: string; status: string }[];
  facts: { topic_id: number; topic: string; text: string; status: Status | ""; sources: string[] }[];
  articles: { id: number; title: string; url: string; domain: string }[];
}

/** Les actions, toujours proposées ; filtrées par le texte tapé. */
function actions(onRefresh: () => void, topicOpen: boolean): Result[] {
  const a: Omit<Result, "group">[] = [
    { key: "new", icon: <Plus size={15} />, label: "Suivre un nouveau sujet", detail: "Ctrl N", run: () => nav.openNewTopic() },
    { key: "today", icon: <Newspaper size={15} />, label: "Aller à Aujourd'hui", detail: "Ctrl 1", run: () => nav.go({ name: "today" }) },
    { key: "brief", icon: <Radio size={15} />, label: "Ouvrir Le Brief", detail: "Ctrl 2", run: () => nav.go({ name: "brief" }) },
    { key: "corrections", icon: <History size={15} />, label: "Voir le journal des corrections", detail: "Ctrl 3", run: () => nav.go({ name: "corrections" }) },
    { key: "deadlines", icon: <CalendarClock size={15} />, label: "Voir les échéances", detail: "Ctrl 4", run: () => nav.go({ name: "deadlines" }) },
    { key: "readings", icon: <BookOpen size={15} />, label: "Mes lectures : importer mon historique, vérifier un article", run: () => nav.go({ name: "readings" }) },
    { key: "recordings", icon: <Bookmark size={15} />, label: "Enregistrements : les articles mis de côté depuis le navigateur", run: () => nav.go({ name: "recordings" }) },
    { key: "discover", icon: <Compass size={15} />, label: "Découvrir des sujets", run: () => nav.go({ name: "discover" }) },
    { key: "settings", icon: <Settings size={15} />, label: "Ouvrir les Réglages", detail: "Ctrl ,", run: () => nav.go({ name: "settings" }) },
    { key: "phone", icon: <Smartphone size={15} />, label: "Réglages : écouter sur mon téléphone", run: () => nav.go({ name: "settings", section: "telephone" }) },
    { key: "claude", icon: <Sparkles size={15} />, label: "Réglages : interroger mon journal depuis Claude", run: () => nav.go({ name: "settings", section: "claude" }) },
    { key: "engine", icon: <Settings size={15} />, label: "Réglages : moteur IA et clé API", run: () => nav.go({ name: "settings", section: "moteur" }) },
  ];
  if (topicOpen) a.splice(1, 0, { key: "refresh", icon: <RefreshCw size={15} />, label: "Mettre à jour ce sujet", detail: "Ctrl R", run: onRefresh });
  return a.map((x) => ({ ...x, group: "Actions" }));
}

export function CommandPalette({ onRefresh }: { onRefresh: () => void }) {
  const { palette, view } = useNav();
  return (
    <Dialog.Root open={palette} onOpenChange={nav.setPalette}>
      <AnimatePresence>
        {palette && (
          <Dialog.Portal forceMount>
            <Dialog.Overlay asChild>
              <motion.div className="scrim z-50" variants={scrim} {...motionProps} />
            </Dialog.Overlay>
            <Dialog.Content asChild aria-describedby={undefined}>
              <motion.div
                className="glass fixed left-1/2 top-[14vh] z-50 w-[640px] max-w-[calc(100vw-32px)] -translate-x-1/2 overflow-hidden rounded-[var(--r-sheet)]"
                style={{ transformOrigin: "50% 0%" }}
                variants={sheet}
                {...motionProps}
              >
                <Dialog.Title className="sr-only">Rechercher dans openMedia</Dialog.Title>
                <Palette onRefresh={onRefresh} topicOpen={view.name === "topic"} />
              </motion.div>
            </Dialog.Content>
          </Dialog.Portal>
        )}
      </AnimatePresence>
    </Dialog.Root>
  );
}

function Palette({ onRefresh, topicOpen }: { onRefresh: () => void; topicOpen: boolean }) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [index, setIndex] = useState(0);
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 140);
    return () => clearTimeout(t);
  }, [query]);
  const search = useQuery({ queryKey: ["search", debounced], queryFn: () => api<SearchResults>(`/search?q=${encodeURIComponent(debounced)}`), enabled: debounced.length > 1 });

  const results = useMemo<Result[]>(() => {
    const q = fold(query.trim());
    const acts = actions(onRefresh, topicOpen).filter((a) => !q || fold(a.label).includes(q));
    const found = search.data && debounced.length > 1 ? search.data : null;
    const topics: Result[] = (found?.topics ?? []).map((t) => ({ key: `t${t.id}`, group: "Sujets", icon: <Hash size={15} />, label: t.name, run: () => nav.go({ name: "topic", id: t.id }) }));
    const facts: Result[] = (found?.facts ?? []).slice(0, 8).map((f, i) => ({
      key: `f${i}`,
      group: "Faits",
      icon: <FileText size={15} />,
      label: f.text,
      detail: [f.topic, ...f.sources.slice(0, 2)].join(" · "),
      status: f.status || undefined,
      run: () => nav.go({ name: "topic", id: f.topic_id }),
    }));
    const articles: Result[] = (found?.articles ?? []).slice(0, 6).map((a) => ({ key: `a${a.id}`, group: "Articles", icon: <Newspaper size={15} />, label: a.title, detail: a.domain, run: () => openLink(a.url) }));
    return q ? [...topics, ...facts, ...acts, ...articles] : acts;
  }, [query, debounced, search.data, onRefresh, topicOpen]);

  useEffect(() => setIndex(0), [results.length, debounced]);
  useEffect(() => {
    list.current?.querySelector<HTMLElement>(`[data-index="${index}"]`)?.scrollIntoView({ block: "nearest" });
  }, [index]);

  const run = (r?: Result) => {
    if (!r) return;
    nav.setPalette(false);
    r.run();
  };

  let lastGroup = "";
  return (
    <div
      onKeyDown={(e) => {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setIndex((i) => Math.min(i + 1, results.length - 1));
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          setIndex((i) => Math.max(i - 1, 0));
        } else if (e.key === "Enter") {
          e.preventDefault();
          run(results[index]);
        }
      }}
    >
      <div className="flex items-center gap-3 border-b border-line px-4">
        <Search size={18} className="shrink-0 text-ink-3" />
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Rechercher un sujet, un fait, un article, une action…"
          className="h-14 w-full bg-transparent text-[17px] text-ink outline-none placeholder:text-ink-3"
          aria-label="Rechercher"
        />
      </div>
      <div ref={list} className="scroll-area max-h-[min(60vh,460px)] p-2" role="listbox">
        {results.length === 0 && <p className="px-3 py-8 text-center text-[13px] text-ink-2">{search.isFetching ? "Recherche…" : "Aucun résultat."}</p>}
        {results.map((r, i) => {
          const header = r.group !== lastGroup ? r.group : null;
          lastGroup = r.group;
          return (
            <div key={r.key}>
              {header && <p className="px-3 pb-1 pt-2.5 text-[11.5px] font-semibold text-ink-3">{header}</p>}
              <button
                data-index={i}
                role="option"
                aria-selected={i === index}
                onMouseMove={() => setIndex(i)}
                onClick={() => run(r)}
                className={`flex w-full items-center gap-3 rounded-[12px] px-3 py-2 text-left ${i === index ? "bg-accent-fill text-white" : "text-ink"}`}
              >
                <span className={i === index ? "text-white" : "text-ink-2"}>{r.icon}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[14px]">{r.label}</span>
                  {(r.detail || r.status) && (
                    <span className={`block truncate text-[12px] ${i === index ? "text-white/80" : "text-ink-2"}`}>
                      {r.status ? `${STATUS_LABEL[r.status]}${r.detail ? " · " : ""}` : ""}
                      {r.group === "Actions" ? "" : r.detail}
                    </span>
                  )}
                </span>
                {r.group === "Actions" && r.detail && <kbd className={`text-[11.5px] ${i === index ? "text-white/80" : "text-ink-3"}`}>{r.detail}</kbd>}
              </button>
            </div>
          );
        })}
      </div>
      <div className="flex gap-4 border-t border-line px-4 py-2 text-[11.5px] text-ink-3">
        <span>↑ ↓ pour choisir</span>
        <span>Entrée pour ouvrir</span>
        <span>Échap pour fermer</span>
      </div>
    </div>
  );
}
