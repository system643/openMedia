// Ce que chaque page affiche dans la barre d'outils commune : un titre compact (visible quand
// le grand titre est sorti de l'écran) et ses actions.

import { useEffect, useSyncExternalStore, type ReactNode } from "react";

interface Chrome {
  title: string;
  actions: ReactNode;
  compact: boolean; // le grand titre a défilé hors de vue
  scrolled: boolean; // du contenu passe sous la barre d'outils
}

let state: Chrome = { title: "", actions: null, compact: false, scrolled: false };
const listeners = new Set<() => void>();
const set = (next: Partial<Chrome>) => {
  state = { ...state, ...next };
  listeners.forEach((l) => l());
};

export const chrome = {
  set,
  setCompact: (compact: boolean) => state.compact !== compact && set({ compact }),
  setScrolled: (scrolled: boolean) => state.scrolled !== scrolled && set({ scrolled }),
};

export function useChrome(): Chrome {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => state,
  );
}

/** À appeler dans chaque page : déclare son titre et ses actions de barre d'outils. */
export function usePageChrome(title: string, actions: ReactNode = null, deps: unknown[] = []) {
  useEffect(() => {
    set({ title, actions });
  }, [title, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps
}
