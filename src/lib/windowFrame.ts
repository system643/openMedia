// L'état de la fenêtre, reporté sur <html> pour le cadre dessiné en CSS (styles.css) :
// `data-max` quand elle est agrandie (ni coins ni ombre), `data-inactive` quand elle n'a pas
// le focus (ombre plus légère), `data-web` hors de Tauri (aperçu dans un navigateur).

import { getCurrentWindow } from "@tauri-apps/api/window";
import { inTauri } from "./api";

export function trackWindowFrame() {
  const root = document.documentElement;
  if (!inTauri) {
    root.dataset.web = "";
    return;
  }
  const win = getCurrentWindow();
  const sync = async () => {
    const max = (await win.isMaximized().catch(() => false)) || (await win.isFullscreen().catch(() => false));
    if (max) root.dataset.max = "";
    else delete root.dataset.max;
  };
  void sync();
  void win.onResized(() => void sync());
  void win.onFocusChanged(({ payload: focused }) => {
    if (focused) delete root.dataset.inactive;
    else root.dataset.inactive = "";
  });
}
