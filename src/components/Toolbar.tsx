import { getCurrentWindow } from "@tauri-apps/api/window";
import { ChevronLeft, ChevronRight, Minus, PanelLeft, Square, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import type { ReactNode } from "react";
import { inTauri } from "../lib/api";
import { useChrome } from "../lib/chrome";
import { spring } from "../lib/motion";
import { nav, useNav } from "../lib/nav";

/** La barre d'outils de la fenêtre, à la façon de macOS 26 : elle flotte au-dessus du contenu,
 *  qui défile dessous et s'efface à son bord (pas de fond peint sous les contrôles). Trois
 *  groupes : navigation (capsule de verre), titre compact, actions de la page. Puis les
 *  commandes de fenêtre de Windows, à leur place habituelle mais dessinées en pastilles. */
export function Toolbar() {
  const { back, forward, sidebar } = useNav();
  const { title, actions, compact, scrolled } = useChrome();
  const win = inTauri ? getCurrentWindow() : null;
  return (
    <div data-tauri-drag-region className="absolute inset-x-0 top-0 z-20 flex h-[52px] items-center gap-2 pl-3">
      <AnimatePresence>{(compact || scrolled) && <motion.div key="edge" aria-hidden className="scroll-edge pointer-events-none absolute inset-x-0 top-0 -z-10 h-[72px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }} />}</AnimatePresence>
      <div className="glass-capsule flex h-8 items-center px-0.5">
        {!sidebar && (
          <CapsuleButton label="Afficher la barre latérale (Ctrl \)" onClick={nav.toggleSidebar}>
            <PanelLeft size={16} strokeWidth={1.75} />
          </CapsuleButton>
        )}
        <CapsuleButton label="Page précédente (Alt ←)" onClick={nav.back} disabled={!back.length}>
          <ChevronLeft size={18} strokeWidth={1.75} />
        </CapsuleButton>
        <CapsuleButton label="Page suivante (Alt →)" onClick={nav.forward} disabled={!forward.length}>
          <ChevronRight size={18} strokeWidth={1.75} />
        </CapsuleButton>
      </div>
      <div data-tauri-drag-region className="min-w-0 flex-1 px-1">
        <AnimatePresence>
          {compact && (
            <motion.p data-tauri-drag-region initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 6, transition: { duration: 0.1 } }} transition={spring.snappy} className="truncate text-[14px] font-semibold text-ink">
              {title}
            </motion.p>
          )}
        </AnimatePresence>
      </div>
      <div className="toolbar-actions flex items-center gap-2 pr-2">{actions}</div>
      {win && (
        <div className="flex items-center gap-0.5 pr-2">
          <WinButton label="Réduire" onClick={() => win.minimize()}>
            <Minus size={14} strokeWidth={1.5} />
          </WinButton>
          <WinButton label="Agrandir" onClick={() => win.toggleMaximize()}>
            <Square size={11} strokeWidth={1.5} />
          </WinButton>
          <WinButton label="Fermer (openMedia reste dans la zone de notification)" onClick={() => win.close()} danger>
            <X size={15} strokeWidth={1.5} />
          </WinButton>
        </div>
      )}
    </div>
  );
}

function CapsuleButton({ label, onClick, disabled, children }: { label: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return (
    <button aria-label={label} title={label} onClick={onClick} disabled={disabled} className="grid h-7 w-8 place-items-center rounded-full text-ink transition-[background-color,scale] duration-150 hover:bg-fill active:scale-[0.92] active:bg-fill-strong disabled:text-ink-3 disabled:opacity-60 disabled:hover:bg-transparent">
      {children}
    </button>
  );
}

function WinButton({ label, onClick, danger, children }: { label: string; onClick: () => void; danger?: boolean; children: ReactNode }) {
  return (
    <button aria-label={label} title={label} onClick={onClick} className={`grid h-8 w-10 place-items-center rounded-[var(--r-item)] text-ink-2 transition-[background-color,color,scale] duration-150 active:scale-[0.94] ${danger ? "hover:bg-[#c42b1c] hover:text-white" : "hover:bg-fill hover:text-ink"}`}>
      {children}
    </button>
  );
}
