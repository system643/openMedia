/** Couleur et libellé d'un média selon qui le possède (Mes lectures, Enregistrements). */
export const OWNER_COLOR: Record<string, string> = { milliardaire: "#c4553d", conglomerat: "#d39a4a", public: "#1e9e73", independant: "#0a6cff", cooperative: "#8944ab", recherche: "#0a9396", inconnu: "#a1a1a6" };
export const OWNER_LABEL: Record<string, string> = { milliardaire: "grande fortune", conglomerat: "groupe industriel ou financier", public: "public", independant: "indépendant", cooperative: "coopérative ou fondation", inconnu: "propriétaire non qualifié" };

export function ownerColor(m: { kind: string; owner_type: string }): string {
  return OWNER_COLOR[m.kind === "recherche" ? "recherche" : m.owner_type] ?? OWNER_COLOR.inconnu;
}

/** L'initiale du média, sur la couleur de son propriétaire. */
export function MediaAvatar({ m }: { m: { media: string; domain: string; kind: string; owner_type: string } }) {
  return (
    <span className="grid size-8 shrink-0 place-items-center rounded-lg text-[13px] font-semibold text-white" style={{ background: ownerColor(m) }} aria-hidden>
      {(m.media || m.domain).replace(/^www\./, "").charAt(0).toUpperCase()}
    </span>
  );
}
