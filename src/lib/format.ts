const dayFmt = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long" });
const shortFmt = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });
const timeFmt = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });

/** Les dates du backend sont en UTC ; SQLite peut les rendre sans fuseau. */
export function parse(d: string | null | undefined): Date | null {
  if (!d) return null;
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(d) ? d : d + "Z");
}

export function longDay(d = new Date()): string {
  const s = dayFmt.format(d);
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function relative(value: string | null | undefined): string {
  const d = parse(value);
  if (!d) return "jamais";
  const minutes = Math.round((Date.now() - d.getTime()) / 60000);
  if (minutes < 1) return "à l'instant";
  if (minutes < 60) return `il y a ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `il y a ${hours} h`;
  const days = Math.round(hours / 24);
  if (days === 1) return "hier";
  if (days < 7) return `il y a ${days} jours`;
  return `le ${shortFmt.format(d)}`;
}

export function shortDate(value: string | null | undefined): string {
  const d = parse(value);
  return d ? shortFmt.format(d) : "";
}

export function time(value: string | null | undefined): string {
  const d = parse(value);
  return d ? timeFmt.format(d) : "";
}

export function euros(usd: number): string {
  return `${usd.toFixed(usd < 1 ? 3 : 2).replace(".", ",")} $`;
}

/** 850, 12 k, 1,2 M. */
export function tokens(n: number): string {
  if (n < 1000) return `${Math.round(n)}`;
  if (n < 1_000_000) return `${Math.round(n / 1000)} k`;
  return `${(n / 1_000_000).toFixed(n < 10_000_000 ? 1 : 0).replace(".", ",")} M`;
}

const upcomingFmt = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "short" });

/** Un passage à venir : « aujourd'hui à 06:30 », « demain à 06:30 », « jeudi 23 oct. à 06:30 ». */
export function upcoming(value: string | null | undefined): string {
  const d = parse(value);
  if (!d) return "aucun";
  if (d.getTime() <= Date.now() + 60_000) return "en attente, dans quelques minutes";
  const days = Math.round((new Date(d).setHours(0, 0, 0, 0) - new Date().setHours(0, 0, 0, 0)) / 86_400_000);
  const day = days === 0 ? "aujourd'hui" : days === 1 ? "demain" : upcomingFmt.format(d);
  return `${day} à ${timeFmt.format(d)}`;
}

export const STATUS_LABEL = {
  confirme: "Confirmé",
  non_confirme: "Une seule source",
  conteste: "Contesté",
  dementi: "Démenti",
} as const;

export const STATE_LABEL = {
  emergent: "Émergent",
  en_cours: "En cours",
  stable: "Stable",
  clos: "Clos",
} as const;

export const KIND_LABEL: Record<string, string> = {
  agence: "Agences",
  national: "Presse nationale",
  regional: "Presse régionale",
  international: "International",
  institutionnel: "Sources primaires",
  specialise: "Spécialisés",
  blog: "Blogs",
  reseau_social: "Réseaux sociaux (signal)",
  recherche: "Recherche scientifique",
  unknown: "Non qualifiés",
};

/** Sous ce seuil (de 0 à 1), une source reste lisible mais ne confirme jamais un fait. */
export const LOW_QUALITY = 0.4;

/** Ce que permet la note, sans chiffre : « établie » (jeu ouvert ou ta note), « estimée par
 *  l'IA » (ne confirme jamais seule), « faible » (ne confirme rien). */
export function qualityLabel(q: number | null | undefined, origin?: string | null): string {
  if (q === null || q === undefined) return "non notée";
  if (q < LOW_QUALITY) return "faible";
  return origin === "ia" ? "estimée par l'IA" : "établie";
}

export const QUALITY_ORIGIN: Record<string, string> = {
  lin2023: "notation ouverte de six organismes (Lin et al., 2023)",
  ia: "qualifiée par l'IA",
  lecteur: "ta note",
};
