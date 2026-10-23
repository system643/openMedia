import { motion } from "motion/react";

/** L'ouverture de l'app : la page arrive, ses lignes s'écrivent une à une, et la dernière, en
 *  rouge, s'écrit en dernier (la fiche qui vient d'être mise à jour). Environ 1,2 s. */
export function AnimatedLogo({ size = 96 }: { size?: number }) {
  const ease = [0.2, 0.8, 0.2, 1] as const;
  const line = (delay: number) => ({ initial: { pathLength: 0 }, animate: { pathLength: 1 }, transition: { duration: 0.28, delay, ease } });
  return (
    <motion.svg viewBox="64 64 896 896" width={size} height={size} aria-hidden initial={{ scale: 0.86, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ duration: 0.4, ease }}>
      <rect x="64" y="64" width="896" height="896" rx="200" fill="#1C1B1F" />
      <motion.g initial={{ y: 60, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ duration: 0.4, delay: 0.12, ease }}>
        <path d="M300 200H604L754 350V794a30 30 0 0 1-30 30H300a30 30 0 0 1-30-30V230a30 30 0 0 1 30-30Z" fill="#F4EEE2" />
        <motion.path d="M604 200V320a30 30 0 0 0 30 30H754Z" fill="#C9BBA0" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.2, delay: 0.4 }} />
      </motion.g>
      <g stroke="#1C1B1F" strokeLinecap="round" fill="none">
        <motion.path d="M352 450H540" strokeWidth="64" {...line(0.45)} />
        <motion.path d="M352 570H672" strokeWidth="44" {...line(0.62)} />
        <motion.path d="M352 662H672" strokeWidth="44" {...line(0.76)} />
      </g>
      <motion.path d="M352 754H540" stroke="#E5483B" strokeWidth="44" strokeLinecap="round" fill="none" {...line(0.92)} />
      <motion.circle cx="652" cy="754" r="34" fill="#E5483B" initial={{ scale: 0 }} animate={{ scale: 1 }} transition={{ duration: 0.3, delay: 1.12, type: "spring", stiffness: 420, damping: 14 }} />
    </motion.svg>
  );
}

/** Le logo d'openMedia : une page de journal au coin plié, dont la dernière ligne vient d'être
 * ajoutée (la fiche qui se met à jour). Même dessin que `src-tauri/icons/source.svg`. */
export function Logo({ size = 22, className = "" }: { size?: number; className?: string }) {
  return (
    <svg viewBox="64 64 896 896" width={size} height={size} className={className} aria-hidden>
      <rect x="64" y="64" width="896" height="896" rx="200" fill="#1C1B1F" />
      <path d="M300 200H604L754 350V794a30 30 0 0 1-30 30H300a30 30 0 0 1-30-30V230a30 30 0 0 1 30-30Z" fill="#F4EEE2" />
      <path d="M604 200V320a30 30 0 0 0 30 30H754Z" fill="#C9BBA0" />
      <g stroke="#1C1B1F" strokeLinecap="round">
        <path d="M352 450H540" strokeWidth="64" />
        <path d="M352 570H672M352 662H672" strokeWidth="44" />
      </g>
      <path d="M352 754H540" stroke="#E5483B" strokeWidth="44" strokeLinecap="round" />
      <circle cx="652" cy="754" r="34" fill="#E5483B" />
    </svg>
  );
}
