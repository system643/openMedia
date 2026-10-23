// Thème : suit Windows par défaut, ou clair / sombre au choix (Réglages > Général).

export type ThemeChoice = "system" | "light" | "dark";

export function applyTheme(choice: ThemeChoice) {
  document.documentElement.dataset.theme = choice;
  try {
    localStorage.setItem("theme", choice);
  } catch {
    /* sans stockage, le thème vient des réglages au prochain chargement */
  }
}

/** Au démarrage, avant le premier rendu, pour éviter un flash du mauvais thème. */
export function restoreTheme() {
  try {
    const saved = localStorage.getItem("theme") as ThemeChoice | null;
    if (saved) document.documentElement.dataset.theme = saved;
  } catch {
    /* thème du système */
  }
}
