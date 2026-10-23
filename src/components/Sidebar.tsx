import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, BookOpen, Bookmark, CalendarClock, ChevronDown, Compass, History, Moon, Newspaper, PanelLeft, PencilLine, Plus, Radio, Search, Settings as SettingsIcon, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, type ReactNode } from "react";
import { api } from "../lib/api";
import type { Draft } from "../lib/drafts";
import { parse, tokens, upcoming } from "../lib/format";
import { spring } from "../lib/motion";
import { nav, useNav, type View } from "../lib/nav";
import type { Announcement, Correction, Recording, Topic } from "../lib/types";
import { Logo } from "./Logo";
import { useCosts } from "../lib/usage";
import { usePreviousVisit } from "../lib/visit";

/** Barre latérale : sections titrées et repliables (Lire, Suivre, Vérifier, Explorer). */
export function Sidebar() {
  const { view } = useNav();
  const topics = useQuery({ queryKey: ["topics"], queryFn: () => api<Topic[]>("/topics") });
  const previous = usePreviousVisit();
  const corrections = useQuery({ queryKey: ["corrections", "unseen"], queryFn: () => api<Correction[]>("/corrections?unseen=true"), refetchInterval: 60_000 });
  const deadlines = useQuery({ queryKey: ["announcements", "upcoming"], queryFn: () => api<Announcement[]>("/announcements/upcoming"), refetchInterval: 300_000 });
  const late = deadlines.data?.filter((a) => a.status === "en_retard").length ?? 0;
  const recordings = useQuery({ queryKey: ["recordings"], queryFn: () => api<Recording[]>("/recordings") });
  const pending = recordings.data?.filter((r) => r.status === "enregistre").length ?? 0;

  const is = (v: View) => view.name === v.name && (v.name !== "topic" || (view.name === "topic" && view.id === v.id));

  return (
    <aside className="glass-sidebar flex h-full w-[248px] shrink-0 flex-col overflow-hidden rounded-[var(--r-panel)]">
      <div data-tauri-drag-region className="flex h-[46px] shrink-0 items-center justify-between pl-3.5 pr-1.5">
        <span data-tauri-drag-region className="flex items-center gap-2 serif text-[21px] font-semibold tracking-[-0.02em] text-ink">
          <Logo size={22} />
          openMedia
        </span>
        <button onClick={nav.toggleSidebar} aria-label="Masquer la barre latérale (Ctrl \)" title="Masquer la barre latérale (Ctrl \)" className="grid size-8 place-items-center rounded-[var(--r-item)] text-ink-2 hover:bg-fill hover:text-ink">
          <PanelLeft size={17} strokeWidth={1.75} />
        </button>
      </div>

      <div className="px-1.5 pb-2">
        <button onClick={() => nav.setPalette(true)} className="flex h-8 w-full items-center gap-2 rounded-[var(--r-item)] bg-fill px-2.5 text-[13px] text-ink-3 transition-colors hover:bg-fill-strong">
          <Search size={14} />
          <span className="flex-1 text-left">Rechercher</span>
          <kbd className="text-[11px] font-medium text-ink-3">Ctrl K</kbd>
        </button>
      </div>

      <div className="scroll-area min-h-0 flex-1 px-1.5 pb-3">
        <Section id="lire" title="Lire">
          <NavItem icon={<Newspaper size={16} />} active={is({ name: "today" })} onClick={() => nav.go({ name: "today" })}>
            Aujourd'hui
          </NavItem>
          <NavItem icon={<Radio size={16} />} active={is({ name: "brief" })} onClick={() => nav.go({ name: "brief" })}>
            Le Brief
          </NavItem>
          <NavItem icon={<BookOpen size={16} />} active={is({ name: "readings" })} onClick={() => nav.go({ name: "readings" })}>
            Mes lectures
          </NavItem>
          <NavItem icon={<Bookmark size={16} />} active={is({ name: "recordings" })} onClick={() => nav.go({ name: "recordings" })} badge={pending} badgeTone="quiet">
            Enregistrements
          </NavItem>
        </Section>

        <Section
          id="suivre"
          title="Suivre"
          action={
            <button onClick={() => nav.openNewTopic()} aria-label="Suivre un nouveau sujet (Ctrl N)" title="Suivre un nouveau sujet (Ctrl N)" className="grid size-6 place-items-center rounded-md text-ink-2 hover:bg-fill hover:text-ink">
              <Plus size={15} />
            </button>
          }
        >
          {topics.data?.map((t) => {
            const fresh = t.latest && !t.latest.nothing_new && (!previous || (parse(t.latest.created_at)?.getTime() ?? 0) > previous.getTime());
            return (
              <NavItem key={t.id} active={is({ name: "topic", id: t.id })} onClick={() => nav.go({ name: "topic", id: t.id })} icon={<TopicDot topic={t} fresh={!!fresh} />} muted={t.status === "sleeping"}>
                {t.name}
              </NavItem>
            );
          })}
          {topics.data?.length === 0 && (
            <button onClick={() => nav.openNewTopic()} className="flex w-full items-center gap-2.5 rounded-[var(--r-item)] px-2 py-[7px] text-left text-[13.5px] text-accent hover:bg-fill">
              <Plus size={15} /> Suivre un premier sujet
            </button>
          )}
          <Drafts />
        </Section>

        <Section id="verifier" title="Vérifier">
          <NavItem icon={<History size={16} />} active={is({ name: "corrections" })} onClick={() => nav.go({ name: "corrections" })} badge={corrections.data?.length}>
            Corrections
          </NavItem>
          <NavItem icon={<CalendarClock size={16} />} active={is({ name: "deadlines" })} onClick={() => nav.go({ name: "deadlines" })} badge={late} badgeTone="warn">
            Échéances
          </NavItem>
        </Section>

        <Section id="explorer" title="Explorer">
          <NavItem icon={<Compass size={16} />} active={is({ name: "discover" })} onClick={() => nav.go({ name: "discover" })}>
            Découvrir
          </NavItem>
        </Section>
      </div>

      <nav className="space-y-0.5 border-t border-line px-1.5 py-1.5">
        <UsageGauge active={view.name === "settings" && view.section === "couts"} />
        <NavItem icon={<Archive size={16} />} active={is({ name: "archives" })} onClick={() => nav.go({ name: "archives" })}>
          Archives
        </NavItem>
        <NavItem icon={<SettingsIcon size={16} />} active={is({ name: "settings" })} onClick={() => nav.go({ name: "settings" })}>
          Réglages
        </NavItem>
      </nav>
    </aside>
  );
}

/** Tokens du mois, fin de mois au rythme réglé, prochain passage ; un clic ouvre le détail. */
function UsageGauge({ active }: { active: boolean }) {
  const { data: c } = useCosts();
  if (!c) return null;
  const used = c.month.tokens.total;
  const cap = c.month.cap;
  const ratio = cap ? used / cap : 0;
  const over = cap > 0 && c.month.end_estimate > cap;
  return (
    <button
      onClick={() => nav.go({ name: "settings", section: "couts" })}
      title="Voir le détail de la consommation et régler la fréquence"
      className={`mb-1 block w-full rounded-[var(--r-item)] px-2 py-2 text-left transition-colors ${active ? "bg-fill-strong" : "hover:bg-fill"}`}
    >
      <span className="flex items-baseline justify-between gap-2 text-[12px]">
        <span className="font-medium tabular-nums text-ink">{tokens(used)} tokens</span>
        <span className="tabular-nums text-ink-3">{cap ? `sur ${tokens(cap)}` : "ce mois-ci"}</span>
      </span>
      {cap > 0 && (
        <span className="mt-1.5 block h-1 overflow-hidden rounded-full bg-fill-strong" role="meter" aria-label="Part du plafond mensuel utilisée" aria-valuenow={Math.round(ratio * 100)} aria-valuemin={0} aria-valuemax={100}>
          <span className={`block h-full rounded-full ${ratio >= 1 ? "bg-deny" : ratio >= 0.8 ? "bg-warn" : "bg-accent"}`} style={{ width: `${Math.min(100, ratio * 100)}%` }} />
        </span>
      )}
      <span className={`mt-1 block text-[11.5px] leading-snug ${over ? "text-warn" : "text-ink-3"}`}>
        ≈ {tokens(c.month.end_estimate)} fin de mois{over ? ", au-delà du plafond" : ""}
      </span>
      <span className="block text-[11.5px] leading-snug text-ink-3">Prochain passage : {upcoming(c.next_run)}</span>
    </button>
  );
}

function storedOpen(id: string): boolean {
  try {
    return localStorage.getItem(`section:${id}`) !== "0";
  } catch {
    return true;
  }
}

/** Section repliable, état mémorisé ; le titre se replie au clic comme dans les barres latérales d'Apple. */
function Section({ id, title, action, children }: { id: string; title: string; action?: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(() => storedOpen(id));
  const toggle = () => {
    setOpen(!open);
    try {
      localStorage.setItem(`section:${id}`, open ? "0" : "1");
    } catch {
      /* état non mémorisé */
    }
  };
  return (
    <section className="mt-4 first:mt-1">
      <div className="group flex items-center justify-between px-2 pb-1">
        <button onClick={toggle} aria-expanded={open} className="flex items-center gap-1 text-[12px] font-semibold text-ink-3 hover:text-ink-2">
          {title}
          <ChevronDown size={12} className={`opacity-0 transition-[transform,opacity] group-hover:opacity-100 ${open ? "" : "-rotate-90 opacity-100"}`} />
        </button>
        {action}
      </div>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div className="overflow-hidden" initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={spring.smooth}>
            <div className="space-y-px">{children}</div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

function TopicDot({ topic, fresh }: { topic: Topic; fresh: boolean }) {
  if (topic.status === "sleeping") return <Moon size={13} className="text-ink-3" />;
  const color = topic.running ? "bg-accent animate-pulse" : topic.last_run?.status === "error" ? "bg-deny" : fresh ? "bg-accent" : "bg-fill-strong";
  return <span className={`mx-[3px] block size-[8px] rounded-full ${color}`} aria-label={topic.running ? "Mise à jour en cours" : fresh ? "Nouveautés" : undefined} />;
}

function NavItem({ icon, active, muted, onClick, children, badge, badgeTone = "deny" }: { icon: ReactNode; active: boolean; muted?: boolean; onClick: () => void; children: ReactNode; badge?: number; badgeTone?: "deny" | "warn" | "quiet" }) {
  return (
    <button
      onClick={onClick}
      aria-current={active ? "page" : undefined}
      className={`flex h-[32px] w-full items-center gap-2.5 rounded-[var(--r-item)] px-2 text-left text-[13.5px] transition-colors ${
        active ? "bg-fill-strong font-medium text-ink" : muted ? "text-ink-3 hover:bg-fill" : "text-ink hover:bg-fill"
      }`}
    >
      <span className={`grid w-4 shrink-0 place-items-center ${active ? "text-accent" : "text-ink-2"}`}>{icon}</span>
      <span className="truncate">{children}</span>
      {!!badge && (
        <span className={`ml-auto min-w-[18px] rounded-full px-1.5 text-center text-[11px] font-semibold leading-[18px] ${badgeTone === "quiet" ? "bg-fill-strong text-ink-2" : badgeTone === "warn" ? "bg-warn text-white" : "bg-deny text-white"}`} aria-label={`${badge} à voir`}>
          {badge}
        </span>
      )}
    </button>
  );
}

/** Les sujets commencés et pas encore suivis : un clic les rouvre là où on les a laissés. */
function Drafts() {
  const qc = useQueryClient();
  const drafts = useQuery({ queryKey: ["drafts"], queryFn: () => api<Draft[]>("/drafts") });
  if (!drafts.data?.length) return null;
  return (
    <div className="pt-2">
      <p className="px-2 pb-0.5 text-[11.5px] text-ink-3">Brouillons</p>
      {drafts.data.map((d) => (
        <div key={d.id} className="group relative">
          <NavItem active={false} muted onClick={() => nav.openNewTopic({ draftId: d.id, state: d.data })} icon={<PencilLine size={13} />}>
            {d.title}
          </NavItem>
          <button
            aria-label={`Supprimer le brouillon « ${d.title} »`}
            title="Supprimer le brouillon"
            onClick={async () => {
              await api(`/drafts/${d.id}`, { method: "DELETE" });
              void qc.invalidateQueries({ queryKey: ["drafts"] });
            }}
            className="absolute right-1 top-1/2 grid size-6 -translate-y-1/2 place-items-center rounded-md text-ink-3 opacity-0 hover:bg-fill hover:text-ink focus-visible:opacity-100 group-hover:opacity-100"
          >
            <X size={13} />
          </button>
        </div>
      ))}
    </div>
  );
}
