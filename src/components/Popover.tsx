// Un menu ancré à un bouton, rendu au-dessus de tout (portail) et gardé dans la fenêtre : il
// se décale vers la gauche près du bord droit et s'ouvre vers le haut s'il manque de place en
// bas. Un conteneur qui coupe ce qui dépasse (overflow) ne peut donc plus le tronquer.

import { useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

const MARGIN = 8;
const GAP = 6;

export function Popover({ anchor, open, onClose, width = 280, children }: { anchor: RefObject<HTMLElement | null>; open: boolean; onClose: () => void; width?: number; children: ReactNode }) {
  const panel = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number; maxHeight: number; origin: string } | null>(null);

  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const place = () => {
      const a = anchor.current?.getBoundingClientRect();
      if (!a) return;
      const w = Math.min(width, window.innerWidth - 2 * MARGIN);
      const h = panel.current?.offsetHeight ?? 0;
      const left = Math.min(Math.max(a.left, MARGIN), window.innerWidth - w - MARGIN);
      const below = window.innerHeight - a.bottom - GAP - MARGIN;
      const above = a.top - GAP - MARGIN;
      const up = h > below && above > below;
      const maxHeight = up ? above : below;
      setPos({ left, top: up ? a.top - GAP - Math.min(h, maxHeight) : a.bottom + GAP, maxHeight, origin: `${a.left - left + a.width / 2}px ${up ? "100%" : "0%"}` });
    };
    place();
    // Une seconde passe, une fois la hauteur du menu connue.
    const frame = requestAnimationFrame(place);
    const close = (e: Event) => {
      const t = e.target as Node;
      if (!panel.current?.contains(t) && !anchor.current?.contains(t)) onClose();
    };
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", key);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", key);
    };
  }, [open, anchor, width, onClose]);

  if (!open) return null;
  return createPortal(
    <div
      ref={panel}
      role="menu"
      className="glass anim-pop scroll-area fixed z-50 overflow-y-auto rounded-[var(--r-panel)] p-1.5"
      style={{ width: Math.min(width, window.innerWidth - 2 * MARGIN), left: pos?.left ?? -9999, top: pos?.top ?? 0, maxHeight: pos?.maxHeight, transformOrigin: pos?.origin, visibility: pos ? "visible" : "hidden" }}
    >
      {children}
    </div>,
    document.body,
  );
}
