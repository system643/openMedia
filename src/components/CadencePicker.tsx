// Régler un rythme de passage : des raccourcis, puis les jours (tous les N jours ou certains
// jours de la semaine) et jusqu'à six heures par jour. Le résumé dit ce que ça donne sur un mois.

import { Minus, Plus, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import type { ReactNode } from "react";
import { spring } from "../lib/motion";
import type { Cadence } from "../lib/types";
import { DAY_NAMES, MAX_HOURS, PRESETS, cadenceLabel, daysLabel, hourLabel, perMonth, runsPerMonth, sameCadence } from "../lib/usage";
import { HOURS, Segmented } from "./ui";

const WEEKDAYS = ["L", "M", "M", "J", "V", "S", "D"];
const WORKDAYS = [0, 1, 2, 3, 4];

export function CadencePicker({ value, onChange, extra }: { value: Cadence; onChange: (c: Cadence) => void; extra?: ReactNode }) {
  const mode = value.weekdays.length ? "weekdays" : "every";
  const hours = [...value.hours].sort();
  return (
    <div className="space-y-3.5">
      <div role="group" aria-label="Raccourcis" className="flex flex-wrap gap-1.5">
        {PRESETS.map((p) => {
          const on = sameCadence(p.apply(value), value);
          return (
            <button
              key={p.label}
              type="button"
              aria-pressed={on}
              onClick={() => onChange(p.apply(value))}
              className={`h-7 rounded-full px-3 text-[12.5px] font-medium transition-[background-color,color,scale] duration-150 active:scale-[0.96] ${on ? "bg-accent-fill text-white" : "bg-fill text-ink hover:bg-fill-strong"}`}
            >
              {p.label}
            </button>
          );
        })}
      </div>

      <div className="grid grid-cols-[64px_1fr] items-center gap-x-3 gap-y-3">
        <span className="text-[13px] text-ink-2">Jours</span>
        <div className="flex min-w-0 flex-wrap items-center gap-2.5">
          <Segmented
            label="Choix des jours"
            value={mode}
            onChange={(m) => onChange(m === "every" ? { ...value, weekdays: [] } : { ...value, weekdays: WORKDAYS })}
            options={[
              { value: "every", label: "Intervalle" },
              { value: "weekdays", label: "Jours de la semaine" },
            ]}
          />
          <AnimatePresence mode="popLayout" initial={false}>
            <motion.div key={mode} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0, transition: spring.snappy }} exit={{ opacity: 0, transition: { duration: 0.08 } }}>
              {mode === "every" ? (
                <Stepper value={value.every} onChange={(every) => onChange({ ...value, every })} />
              ) : (
                <Weekdays value={value.weekdays} onChange={(weekdays) => onChange({ ...value, weekdays })} />
              )}
            </motion.div>
          </AnimatePresence>
        </div>

        <span className="text-[13px] text-ink-2">Heures</span>
        <div className="flex flex-wrap items-center gap-1.5">
          {hours.map((h) => (
            <span key={h} className="inline-flex h-7 items-center rounded-full bg-fill pl-3 pr-1">
              <select
                aria-label={`Passage de ${hourLabel(h)}`}
                value={h}
                onChange={(e) => onChange({ ...value, hours: [...new Set(hours.map((x) => (x === h ? e.target.value : x)))] })}
                className="cursor-pointer appearance-none bg-transparent pr-1 text-[13px] font-medium tabular-nums text-ink outline-none"
              >
                {(HOURS.includes(h) ? HOURS : [h, ...HOURS]).filter((x) => x === h || !hours.includes(x)).map((x) => (
                  <option key={x} value={x}>
                    {hourLabel(x)}
                  </option>
                ))}
              </select>
              {hours.length > 1 ? (
                <button type="button" aria-label={`Retirer le passage de ${hourLabel(h)}`} title="Retirer" onClick={() => onChange({ ...value, hours: hours.filter((x) => x !== h) })} className="grid size-5 place-items-center rounded-full text-ink-3 hover:bg-fill-strong hover:text-ink">
                  <X size={12} strokeWidth={2} />
                </button>
              ) : (
                <span className="w-2" />
              )}
            </span>
          ))}
          {hours.length < MAX_HOURS && (
            <button type="button" onClick={() => onChange({ ...value, hours: [...hours, nextHour(hours)] })} className="inline-flex h-7 items-center gap-1 rounded-full px-2.5 text-[12.5px] font-medium text-accent transition-colors hover:bg-accent-soft">
              <Plus size={13} strokeWidth={2} /> Ajouter une heure
            </button>
          )}
        </div>
      </div>

      <p className="text-[12.5px] leading-snug text-ink-2">
        <span className="font-medium text-ink">{cadenceLabel(value)}</span> · {perMonth(runsPerMonth(value))}
        {extra}
      </p>
    </div>
  );
}

/** Une heure libre, six heures après la dernière (« 6 h 30 » appelle « 12 h 30 »). */
function nextHour(hours: string[]): string {
  const start = Math.max(0, HOURS.indexOf(hours[hours.length - 1] ?? "06:30"));
  for (let k = 0; k < HOURS.length; k++) {
    const h = HOURS[(start + 12 + k) % HOURS.length];
    if (!hours.includes(h)) return h;
  }
  return "12:00";
}

function Stepper({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const step = (d: number) => onChange(Math.min(30, Math.max(1, value + d)));
  const button = "grid size-[26px] place-items-center rounded-full text-ink transition-[background-color,scale] duration-150 hover:bg-fill-strong active:scale-[0.9] disabled:text-ink-3 disabled:opacity-50 disabled:hover:bg-transparent";
  return (
    <div role="group" aria-label="Intervalle entre deux jours de passage" className="inline-flex items-center rounded-full bg-fill p-[3px]">
      <button type="button" aria-label="Plus souvent" disabled={value <= 1} onClick={() => step(-1)} className={button}>
        <Minus size={13} strokeWidth={2} />
      </button>
      <span aria-live="polite" className="min-w-[150px] px-1 text-center text-[13px] font-medium tabular-nums text-ink">
        {daysLabel({ every: value, weekdays: [], hours: [] })}
      </span>
      <button type="button" aria-label="Moins souvent" disabled={value >= 30} onClick={() => step(1)} className={button}>
        <Plus size={13} strokeWidth={2} />
      </button>
    </div>
  );
}

function Weekdays({ value, onChange }: { value: number[]; onChange: (v: number[]) => void }) {
  return (
    <div role="group" aria-label="Jours de passage" className="flex gap-1">
      {WEEKDAYS.map((letter, d) => {
        const on = value.includes(d);
        return (
          <button
            key={d}
            type="button"
            aria-pressed={on}
            aria-label={DAY_NAMES[d]}
            title={DAY_NAMES[d]}
            // Au moins un jour reste choisi.
            onClick={() => (on ? value.length > 1 && onChange(value.filter((x) => x !== d)) : onChange([...value, d].sort((a, b) => a - b)))}
            className={`grid size-[30px] place-items-center rounded-full text-[12.5px] font-semibold transition-[background-color,color,scale] duration-150 active:scale-[0.9] ${on ? "bg-accent-fill text-white" : "bg-fill text-ink-2 hover:bg-fill-strong hover:text-ink"}`}
          >
            {letter}
          </button>
        );
      })}
    </div>
  );
}
