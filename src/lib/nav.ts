// Navigation de l'application : une vue courante, un historique (précédent / suivant), la
// feuille « Suivre un sujet », la palette de recherche et la barre latérale repliable.

import { useSyncExternalStore } from "react";
import type { WizardState } from "./drafts";

export type TopicTab = "fiche" | "calendrier" | "sources" | "agent";

export type SettingsSection = "general" | "moteur" | "confidentialite" | "rigueur" | "sources" | "telephone" | "claude" | "couts";

export type View =
  | { name: "today" }
  | { name: "brief"; id?: number }
  | { name: "topic"; id: number; tab?: TopicTab }
  | { name: "discover" }
  | { name: "archives" }
  | { name: "corrections" }
  | { name: "deadlines" }
  | { name: "readings" }
  | { name: "recordings"; id?: number; follow?: boolean }
  | { name: "settings"; section?: SettingsSection };

export interface NewTopicDraft {
  prompt?: string;
  name?: string;
  /** L'enregistrement d'où vient le sujet : il passe en « suivi » une fois le sujet créé. */
  recordingId?: number;
  /** Reprise d'un brouillon enregistré. */
  draftId?: number;
  state?: WizardState;
}

interface NavState {
  view: View;
  back: View[];
  forward: View[];
  sheet: NewTopicDraft | null;
  palette: boolean;
  shortcuts: boolean;
  sidebar: boolean;
}

function storedSidebar(): boolean {
  try {
    return localStorage.getItem("sidebar") !== "0";
  } catch {
    return true;
  }
}

let state: NavState = { view: { name: "today" }, back: [], forward: [], sheet: null, palette: false, shortcuts: false, sidebar: storedSidebar() };
const listeners = new Set<() => void>();

function set(next: Partial<NavState>) {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
}

const same = (a: View, b: View) => JSON.stringify(a) === JSON.stringify(b);

export const nav = {
  go(view: View) {
    if (same(view, state.view)) return;
    set({ view, back: [...state.back, state.view].slice(-50), forward: [], palette: false });
  },
  back() {
    const prev = state.back.at(-1);
    if (prev) set({ view: prev, back: state.back.slice(0, -1), forward: [state.view, ...state.forward] });
  },
  forward() {
    const next = state.forward[0];
    if (next) set({ view: next, back: [...state.back, state.view], forward: state.forward.slice(1) });
  },
  openNewTopic: (draft: NewTopicDraft = {}) => set({ sheet: draft, palette: false }),
  closeSheet: () => set({ sheet: null }),
  setPalette: (palette: boolean) => set({ palette }),
  setShortcuts: (shortcuts: boolean) => set({ shortcuts }),
  toggleSidebar() {
    const sidebar = !state.sidebar;
    try {
      localStorage.setItem("sidebar", sidebar ? "1" : "0");
    } catch {
      /* préférence non mémorisée */
    }
    set({ sidebar });
  },
  current: () => state.view,
  /** Routes reçues de la coque Rust, de la languette ou de l'URL : « topic:12 », « recordings:3 »,
   * « follow:3 » (l'enregistrement, menu « Suivre » ouvert)… */
  fromRoute(route: string) {
    const [name, arg] = route.split(":");
    if (name === "topic" && arg) nav.go({ name: "topic", id: Number(arg) });
    else if (name === "new") nav.openNewTopic(arg ? { prompt: decodeURIComponent(arg) } : {});
    else if (name === "brief") nav.go({ name: "brief" });
    else if (name === "recordings") nav.go({ name: "recordings", id: arg ? Number(arg) : undefined });
    else if (name === "follow" && arg) nav.go({ name: "recordings", id: Number(arg), follow: true });
    else if (name === "settings") nav.go({ name: "settings", section: (arg as SettingsSection) || undefined });
    else if (name === "corrections" || name === "deadlines" || name === "readings" || name === "discover" || name === "archives" || name === "today") nav.go({ name });
  },
};

export function useNav(): NavState {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
  );
}
