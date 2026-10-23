// Raccourcis clavier globaux de la fenêtre principale.

import { useEffect } from "react";
import { nav } from "./nav";

export const SHORTCUTS: { keys: string; label: string }[] = [
  { keys: "Ctrl K", label: "Rechercher et aller n'importe où" },
  { keys: "Ctrl N", label: "Suivre un nouveau sujet" },
  { keys: "Ctrl R", label: "Mettre à jour le sujet ouvert" },
  { keys: "Ctrl 1", label: "Aujourd'hui" },
  { keys: "Ctrl 2", label: "Le Brief" },
  { keys: "Ctrl 3", label: "Corrections" },
  { keys: "Ctrl 4", label: "Échéances" },
  { keys: "Ctrl ,", label: "Réglages" },
  { keys: "Ctrl \\", label: "Afficher ou masquer la barre latérale" },
  { keys: "Alt ← / Alt →", label: "Page précédente / suivante" },
  { keys: "?", label: "Cet aide-mémoire" },
];

const typing = (e: KeyboardEvent) => {
  const t = e.target as HTMLElement | null;
  return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
};

/** `onRefresh` : mettre à jour le sujet ouvert (Ctrl+R remplace le rechargement de la page). */
export function useShortcuts(onRefresh: () => void) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const ctrl = e.ctrlKey || e.metaKey;
      if (ctrl && e.key.toLowerCase() === "k") {
        e.preventDefault();
        nav.setPalette(true);
      } else if (ctrl && e.key.toLowerCase() === "n") {
        e.preventDefault();
        nav.openNewTopic();
      } else if (ctrl && e.key.toLowerCase() === "r") {
        e.preventDefault();
        onRefresh();
      } else if (ctrl && e.key === ",") {
        e.preventDefault();
        nav.go({ name: "settings" });
      } else if (ctrl && e.key === "\\") {
        e.preventDefault();
        nav.toggleSidebar();
      } else if (ctrl && ["1", "2", "3", "4"].includes(e.key)) {
        e.preventDefault();
        nav.go([{ name: "today" } as const, { name: "brief" } as const, { name: "corrections" } as const, { name: "deadlines" } as const][Number(e.key) - 1]);
      } else if (e.altKey && e.key === "ArrowLeft") {
        e.preventDefault();
        nav.back();
      } else if (e.altKey && e.key === "ArrowRight") {
        e.preventDefault();
        nav.forward();
      } else if (e.key === "?" && !typing(e)) {
        nav.setShortcuts(true);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onRefresh]);
}
