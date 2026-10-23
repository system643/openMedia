import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Cadence, CostsReport } from "./types";

export const DAY_NAMES = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
export const MAX_HOURS = 6;

/** « 6 h 30 », « 18 h ». */
export function hourLabel(h: string): string {
  const [hh, mm] = h.split(":");
  return `${Number(hh)} h${mm === "00" ? "" : ` ${mm}`}`;
}

/** « lundi, mercredi et vendredi ». */
function list(items: string[]): string {
  return items.length < 2 ? items.join("") : `${items.slice(0, -1).join(", ")} et ${items[items.length - 1]}`;
}

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export function daysLabel(c: Cadence): string {
  const w = [...c.weekdays].sort((a, b) => a - b);
  if (w.length) {
    if (w.length === 7) return "Chaque jour";
    if (w.join() === "0,1,2,3,4") return "Du lundi au vendredi";
    if (w.join() === "5,6") return "Le week-end";
    if (w.length === 1) return `Chaque ${DAY_NAMES[w[0]]}`;
    return capital(list(w.map((d) => DAY_NAMES[d])));
  }
  if (c.every === 1) return "Chaque jour";
  if (c.every === 2) return "Un jour sur deux";
  if (c.every === 7) return "Chaque semaine";
  if (c.every === 14) return "Toutes les deux semaines";
  return `Tous les ${c.every} jours`;
}

/** « Du lundi au vendredi à 7 h et 18 h ». */
export function cadenceLabel(c: Cadence): string {
  return `${daysLabel(c)} à ${list([...c.hours].sort().map(hourLabel))}`;
}

/** Passages sur 30 jours, hors échéances. */
export function runsPerMonth(c: Cadence): number {
  return (c.weekdays.length ? (c.weekdays.length * 30) / 7 : 30 / c.every) * c.hours.length;
}

export function perMonth(n: number): string {
  const v = n < 10 ? String(Math.round(n * 10) / 10).replace(".", ",") : String(Math.round(n));
  return `≈ ${v} passage${n >= 2 ? "s" : ""} par mois`;
}

export const sameCadence = (a: Cadence, b: Cadence) =>
  [...a.hours].sort().join() === [...b.hours].sort().join() && [...a.weekdays].sort().join() === [...b.weekdays].sort().join() && (a.weekdays.length > 0 || a.every === b.every);

/** Raccourcis : ils changent les jours et gardent les heures, sauf « Matin et soir ». */
export const PRESETS: { label: string; apply: (c: Cadence) => Cadence }[] = [
  { label: "Chaque jour", apply: (c) => ({ every: 1, weekdays: [], hours: c.hours }) },
  { label: "Matin et soir", apply: () => ({ every: 1, weekdays: [], hours: ["07:00", "18:00"] }) },
  { label: "En semaine", apply: (c) => ({ every: 1, weekdays: [0, 1, 2, 3, 4], hours: c.hours }) },
  { label: "Un jour sur deux", apply: (c) => ({ every: 2, weekdays: [], hours: c.hours }) },
  { label: "Chaque semaine", apply: (c) => ({ every: 7, weekdays: [], hours: c.hours }) },
];

/** Le rythme général, lu dans les réglages. */
export function generalCadence(s: { run_every_days: number; run_weekdays: number[]; run_hours: string[] } | undefined): Cadence {
  return { every: s?.run_every_days ?? 1, weekdays: s?.run_weekdays ?? [], hours: s?.run_hours?.length ? s.run_hours : ["06:30"] };
}

/** Le rapport de consommation, partagé par la jauge, les réglages et la page sujet. */
export function useCosts() {
  return useQuery({ queryKey: ["costs"], queryFn: () => api<CostsReport>("/costs"), refetchInterval: 300_000 });
}

/** Les tokens d'un mois si tout tournait une fois par jour : la référence des économies affichées. */
export function dailyBaseline(c: CostsReport): number {
  const topics = c.topics.reduce((n, t) => n + t.avg_tokens * (t.status === "sleeping" ? 30 / 7 : 30), 0);
  return topics + c.brief.avg_tokens * 30 + c.other.tokens;
}
