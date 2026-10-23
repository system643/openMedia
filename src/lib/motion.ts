// Le mouvement, à la façon d'Apple : des ressorts plutôt que des durées, une apparition un peu
// plus lente que la disparition, et des éléments qui naissent de l'endroit où on les appelle.
// « Réduire les animations » de Windows coupe les déplacements (MotionConfig dans main.tsx).

import type { Transition, Variants } from "motion/react";

export const spring = {
  /** Contrôles : boutons, segments, interrupteurs. Vif, sans rebond visible. */
  snappy: { type: "spring", stiffness: 520, damping: 38, mass: 0.8 } satisfies Transition,
  /** Panneaux : barre latérale, feuilles, palette. Ample et amorti. */
  smooth: { type: "spring", stiffness: 340, damping: 34, mass: 1 } satisfies Transition,
  /** Morphose d'une sélection qui glisse d'un élément à l'autre (Liquid Glass). */
  morph: { type: "spring", stiffness: 460, damping: 32, mass: 0.9 } satisfies Transition,
};

/** Sortie : courte et sans ressort, pour ne jamais retenir l'utilisateur. */
const leave: Transition = { duration: 0.14, ease: [0.4, 0, 1, 1] };

/** Feuille ou dialogue : surgit en grandissant légèrement depuis le haut. */
export const sheet: Variants = {
  hidden: { opacity: 0, scale: 0.94, y: -10 },
  shown: { opacity: 1, scale: 1, y: 0, transition: spring.smooth },
  gone: { opacity: 0, scale: 0.97, y: -4, transition: leave },
};

/** Menu ou popover : naît de son bouton (origine en haut à gauche). */
export const popover: Variants = {
  hidden: { opacity: 0, scale: 0.92, y: -4 },
  shown: { opacity: 1, scale: 1, y: 0, transition: spring.snappy },
  gone: { opacity: 0, scale: 0.96, transition: { duration: 0.1 } },
};

/** Voile derrière une feuille. */
export const scrim: Variants = {
  hidden: { opacity: 0 },
  shown: { opacity: 1, transition: { duration: 0.22 } },
  gone: { opacity: 0, transition: leave },
};

/** Changement de page : le contenu se pose doucement. */
export const page: Variants = {
  hidden: { opacity: 0, y: 10, scale: 0.995 },
  shown: { opacity: 1, y: 0, scale: 1, transition: spring.smooth },
  gone: { opacity: 0, transition: { duration: 0.1 } },
};

export const motionProps = { initial: "hidden", animate: "shown", exit: "gone" } as const;
