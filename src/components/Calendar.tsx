// Le calendrier d'un sujet (ou de tous) : il se remplit au fil des passages avec les échéances
// relevées dans les sources, les dates de la chronologie, et les passages faits ou prévus.
// Vue mois à la façon de Calendrier sur macOS ; le jour choisi se détaille dessous.

import * as Tooltip from "@radix-ui/react-tooltip";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { api } from "../lib/api";
import { longDay } from "../lib/format";
import { spring } from "../lib/motion";
import type { AnnouncementStatus, CalendarData } from "../lib/types";
import { hourLabel } from "../lib/usage";
import { SourceChip } from "./Facts";
import { AnnouncementList } from "./Followups";
import { Button, IconButton } from "./ui";

const pad = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const fromIso = (s: string) => new Date(`${s}T12:00:00`);
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n, 12);

const monthFmt = new Intl.DateTimeFormat("fr-FR", { month: "long" });
const weekdayFmt = new Intl.DateTimeFormat("fr-FR", { weekday: "short" });
const firstFmt = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "short" });
const WEEK = Array.from({ length: 7 }, (_, i) => weekdayFmt.format(new Date(2026, 9, 19 + i))); // du lundi 19 octobre 2026

/** Les 42 jours affichés : six semaines à partir du lundi qui précède le 1er du mois. */
function gridOf(month: Date): Date[] {
  const first = new Date(month.getFullYear(), month.getMonth(), 1, 12);
  const start = addDays(first, -((first.getDay() + 6) % 7));
  return Array.from({ length: 42 }, (_, i) => addDays(start, i));
}

const PILL: Record<AnnouncementStatus, string> = {
  a_venir: "bg-accent-soft text-accent",
  en_retard: "bg-[color-mix(in_srgb,var(--warn)_14%,transparent)] text-warn",
  realise: "bg-[color-mix(in_srgb,var(--ok)_14%,transparent)] text-ok",
  reporte: "bg-[color-mix(in_srgb,var(--contest)_14%,transparent)] text-contest",
  abandonne: "bg-fill text-ink-3 line-through",
};

type Day = { deadlines: CalendarData["deadlines"]; events: CalendarData["events"]; runs: CalendarData["runs"]; planned: CalendarData["planned"] };
const emptyDay = (): Day => ({ deadlines: [], events: [], runs: [], planned: [] });

export function Calendar({ topicId, onOpenVersion, onOpenTopic, header }: { topicId?: number; onOpenVersion?: (version: number) => void; onOpenTopic?: (id: number) => void; header?: ReactNode }) {
  const today = iso(new Date());
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1, 12));
  const [dir, setDir] = useState(0);
  const [selected, setSelected] = useState<string>(today);
  const cells = useRef(new Map<string, HTMLButtonElement>());
  const focusNext = useRef(false);

  const grid = useMemo(() => gridOf(month), [month]);
  const start = iso(grid[0]);
  const end = iso(grid[41]);
  const q = useQuery({
    queryKey: ["calendar", topicId ?? "all", start],
    queryFn: () => api<CalendarData>(`/calendar?start=${start}&end=${end}${topicId ? `&topic_id=${topicId}` : ""}`),
    placeholderData: keepPreviousData,
  });
  const days = useMemo(() => {
    const map = new Map<string, Day>();
    const at = (d: string) => map.get(d) ?? (map.set(d, emptyDay()), map.get(d)!);
    q.data?.deadlines.forEach((x) => at(x.date).deadlines.push(x));
    q.data?.events.forEach((x) => at(x.date).events.push(x));
    q.data?.runs.forEach((x) => at(x.date).runs.push(x));
    q.data?.planned.forEach((x) => at(x.date).planned.push(x));
    return map;
  }, [q.data]);
  const monthKey = `${month.getFullYear()}-${pad(month.getMonth() + 1)}`;
  const undated = q.data?.undated.filter((u) => u.month === monthKey) ?? [];

  const go = (delta: number, pick?: string) => {
    setDir(delta);
    setMonth((m) => new Date(m.getFullYear(), m.getMonth() + delta, 1, 12));
    if (pick) setSelected(pick);
  };
  const goToday = () => {
    const now = new Date();
    const target = new Date(now.getFullYear(), now.getMonth(), 1, 12);
    setDir(Math.sign(target.getTime() - month.getTime()));
    setMonth(target);
    setSelected(today);
  };

  // Flèches : un jour, Haut et Bas : une semaine ; on change de mois en sortant de la grille.
  const onKey = (e: KeyboardEvent) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    if (!step || selected === "month") return;
    e.preventDefault();
    const next = addDays(fromIso(selected), step);
    focusNext.current = true;
    if (next.getMonth() !== month.getMonth()) go(next > month ? 1 : -1, iso(next));
    else setSelected(iso(next));
  };
  useEffect(() => {
    if (focusNext.current) {
      cells.current.get(selected)?.focus();
      focusNext.current = false;
    }
  }, [selected, month]);

  const day = selected === "month" ? null : (days.get(selected) ?? emptyDay());

  return (
    <div className="mt-8">
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <h2 className="text-[24px] font-semibold tracking-[-0.01em] text-ink">
          <span className="capitalize">{monthFmt.format(month)}</span> <span className="font-normal text-ink-2">{month.getFullYear()}</span>
        </h2>
        <div className="flex items-center gap-1">
          <IconButton label="Mois précédent" onClick={() => go(-1)}>
            <ChevronLeft size={17} strokeWidth={1.75} />
          </IconButton>
          <Button size="sm" onClick={goToday}>
            Aujourd'hui
          </Button>
          <IconButton label="Mois suivant" onClick={() => go(1)}>
            <ChevronRight size={17} strokeWidth={1.75} />
          </IconButton>
        </div>
      </div>
      {header}

      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[12px] text-ink-2">
        <Legend swatch={<span className="h-2.5 w-4 rounded-[3px] bg-accent-soft ring-1 ring-inset ring-[color-mix(in_srgb,var(--accent)_30%,transparent)]" />}>Échéance</Legend>
        <Legend swatch={<span className="size-1.5 rounded-full bg-ink-3" />}>Dans la chronologie</Legend>
        {topicId !== undefined && (
          <>
            <Legend swatch={<span className="size-[7px] rounded-full bg-accent" />}>Passage fait</Legend>
            <Legend swatch={<span className="size-[7px] rounded-full border-[1.5px] border-accent" />}>Passage prévu</Legend>
            <Legend swatch={<span className="size-[7px] rounded-full border-[1.5px] border-warn" />}>Passage d'échéance</Legend>
          </>
        )}
      </div>

      {undated.length > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-1.5 text-[12.5px]">
          <span className="mr-1 text-ink-2">Ce mois-ci, sans jour précis :</span>
          {undated.map((u) => (
            <button key={u.id} onClick={() => setSelected("month")} title={topicId ? u.text : `${u.topic_name} : ${u.text}`} className={`max-w-[260px] truncate rounded-[5px] px-1.5 py-0.5 font-medium ${PILL[u.status]} ${selected === "month" ? "ring-1 ring-current" : ""}`}>
              {u.text}
            </button>
          ))}
        </div>
      )}

      <div className="card overflow-hidden">
        <div className="grid grid-cols-7 border-b border-line">
          {WEEK.map((w) => (
            <div key={w} className="px-2 py-1.5 text-right text-[11.5px] font-medium text-ink-2">
              {w}
            </div>
          ))}
        </div>
        <div className="relative overflow-hidden">
          <AnimatePresence mode="popLayout" initial={false} custom={dir}>
            <motion.div
              key={monthKey}
              custom={dir}
              variants={{
                enter: (d: number) => ({ opacity: 0, x: d * 40 }),
                shown: { opacity: 1, x: 0, transition: spring.smooth },
                leave: (d: number) => ({ opacity: 0, x: d * -40, transition: { duration: 0.14 } }),
              }}
              initial="enter"
              animate="shown"
              exit="leave"
              role="group"
              aria-label={`${monthFmt.format(month)} ${month.getFullYear()}`}
              onKeyDown={onKey}
              className="grid grid-cols-7 gap-px bg-line"
            >
              {grid.map((d) => {
                const key = iso(d);
                const items = days.get(key);
                const inMonth = d.getMonth() === month.getMonth();
                return (
                  <DayCell
                    key={key}
                    date={d}
                    items={items}
                    inMonth={inMonth}
                    today={key === today}
                    selected={key === selected}
                    global={topicId === undefined}
                    cellRef={(el) => (el ? cells.current.set(key, el) : cells.current.delete(key))}
                    onPick={() => (inMonth ? setSelected(key) : go(d > month ? 1 : -1, key))}
                  />
                );
              })}
            </motion.div>
          </AnimatePresence>
        </div>
      </div>

      <AnimatePresence mode="wait" initial={false}>
        <motion.section key={selected} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0, transition: spring.smooth }} exit={{ opacity: 0, transition: { duration: 0.08 } }} className="mt-7" aria-live="polite">
          {selected === "month" ? (
            <>
              <h3 className="text-[16px] font-semibold text-ink">
                <span className="capitalize">{monthFmt.format(month)}</span>, sans jour précis
              </h3>
              <div className="mt-3">
                <AnnouncementList items={undated} showTopic={topicId === undefined} onOpenTopic={onOpenTopic} />
              </div>
            </>
          ) : (
            day && <DayDetail date={selected} day={day} global={topicId === undefined} onOpenVersion={onOpenVersion} onOpenTopic={onOpenTopic} />
          )}
        </motion.section>
      </AnimatePresence>
    </div>
  );
}

function Legend({ swatch, children }: { swatch: ReactNode; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {swatch}
      {children}
    </span>
  );
}

function DayCell({ date, items, inMonth, today, selected, global, cellRef, onPick }: { date: Date; items?: Day; inMonth: boolean; today: boolean; selected: boolean; global: boolean; cellRef: (el: HTMLButtonElement | null) => void; onPick: () => void }) {
  const lines = [...(items?.deadlines ?? []).map((a) => ({ kind: "deadline" as const, a })), ...(items?.events ?? []).map((e) => ({ kind: "event" as const, e }))];
  const shown = lines.slice(0, 3);
  const dots = [...(items?.runs ?? []).map((r) => ({ done: true as const, r })), ...(items?.planned ?? []).map((p) => ({ done: false as const, p }))];
  const label = [
    longDay(date),
    items?.deadlines.length && `${items.deadlines.length} échéance${items.deadlines.length > 1 ? "s" : ""}`,
    items?.events.length && `${items.events.length} date${items.events.length > 1 ? "s" : ""} de la chronologie`,
    items?.runs.length && `${items.runs.length} passage${items.runs.length > 1 ? "s" : ""}`,
    items?.planned.length && `${items.planned.length} passage${items.planned.length > 1 ? "s" : ""} prévu${items.planned.length > 1 ? "s" : ""}`,
  ]
    .filter(Boolean)
    .join(", ");
  return (
    <button
      ref={cellRef}
      aria-pressed={selected}
      aria-current={today ? "date" : undefined}
      aria-label={label}
      tabIndex={selected ? 0 : -1}
      onClick={onPick}
      className={`relative flex min-h-[96px] min-w-0 flex-col gap-[3px] p-1.5 text-left outline-none transition-colors duration-150 focus-visible:z-10 focus-visible:shadow-[inset_0_0_0_2px_var(--accent)] ${
        selected ? "bg-[color-mix(in_srgb,var(--accent)_7%,var(--surface))]" : inMonth ? "bg-surface hover:bg-[color-mix(in_srgb,var(--fill)_50%,var(--surface))]" : "bg-paper hover:bg-[color-mix(in_srgb,var(--fill)_50%,var(--paper))]"
      }`}
    >
      <span
        className={`ml-auto grid h-6 min-w-6 place-items-center rounded-full px-1.5 text-[12.5px] tabular-nums ${
          today ? "bg-accent-fill font-semibold text-white" : inMonth ? "font-medium text-ink" : "text-ink-3"
        }`}
      >
        {date.getDate() === 1 ? firstFmt.format(date) : date.getDate()}
      </span>
      {shown.map((l, i) =>
        l.kind === "deadline" ? (
          <span key={i} title={global ? `${l.a.topic_name} : ${l.a.text}` : l.a.text} className={`truncate rounded-[4px] px-1.5 text-[11.5px] font-medium leading-[17px] ${PILL[l.a.status]}`}>
            {l.a.text}
          </span>
        ) : (
          <span key={i} title={global ? `${l.e.topic_name} : ${l.e.text}` : l.e.text} className="flex min-w-0 items-center gap-1 text-[11.5px] leading-[17px] text-ink-2">
            <span className="size-1.5 shrink-0 rounded-full bg-ink-3" />
            <span className="truncate">{l.e.text}</span>
          </span>
        ),
      )}
      {lines.length > 3 && <span className="px-1 text-[11px] text-ink-3">+ {lines.length - 3} autre{lines.length - 3 > 1 ? "s" : ""}</span>}
      {dots.length > 0 && (
        <span className="mt-auto flex flex-wrap gap-[3px] px-0.5 pt-0.5">
          {dots.map((d, i) =>
            d.done ? (
              <span key={i} className={`size-[7px] rounded-full ${runDot(d.r)}`} />
            ) : (
              <span key={i} className={`size-[7px] rounded-full border-[1.5px] ${d.p.deadline ? "border-warn" : "border-accent"}`} />
            ),
          )}
        </span>
      )}
    </button>
  );
}

/** Point d'un passage : plein s'il a apporté du neuf, atténué s'il n'a fait que confirmer. */
function runDot(r: CalendarData["runs"][number]): string {
  if (!r.nothing_new && r.news) return "bg-accent";
  return r.confirmations ? "bg-accent/40" : "bg-ink-3/45";
}

function DayDetail({ date, day, global, onOpenVersion, onOpenTopic }: { date: string; day: Day; global: boolean; onOpenVersion?: (version: number) => void; onOpenTopic?: (id: number) => void }) {
  const empty = !day.deadlines.length && !day.events.length && !day.runs.length && !day.planned.length;
  return (
    <>
      <h3 className="text-[16px] font-semibold text-ink">{longDay(fromIso(date))}</h3>
      {empty && <p className="mt-2 text-[14px] text-ink-3">Rien ce jour-là.</p>}

      {day.deadlines.length > 0 && (
        <>
          <Sub>Échéances</Sub>
          <AnnouncementList items={day.deadlines} showTopic={global} onOpenTopic={onOpenTopic} />
        </>
      )}

      {day.events.length > 0 && (
        <>
          <Sub>Dans la chronologie</Sub>
          <Tooltip.Provider>
            <ul className="space-y-3">
              {day.events.map((e, i) => (
                <li key={i} className="rail" data-status="non_confirme">
                  {global && (
                    <button onClick={() => onOpenTopic?.(e.topic_id)} className="text-[12px] font-medium text-accent hover:underline">
                      {e.topic_name}
                    </button>
                  )}
                  <p className="text-[14.5px] leading-[1.55] text-ink">
                    {e.text}
                    <span className="ml-2 inline-flex flex-wrap gap-1 align-middle">
                      {e.sources.map((s) => (
                        <SourceChip key={s.ref} refId={s.ref} source={s} />
                      ))}
                    </span>
                  </p>
                </li>
              ))}
            </ul>
          </Tooltip.Provider>
        </>
      )}

      {(day.runs.length > 0 || day.planned.length > 0) && (
        <>
          <Sub>Passages</Sub>
          <ul className="divide-y divide-line text-[13.5px]">
            {day.runs.map((r) => (
              <li key={`r${r.version}`} className="flex items-center justify-between gap-4 py-2">
                <span className="flex items-center gap-2.5 text-ink">
                  <span className={`size-[7px] rounded-full ${runDot(r)}`} />
                  <span className="w-12 tabular-nums text-ink-2">{hourLabel(r.time)}</span>
                  Version {r.version} · {r.nothing_new || !r.news ? "rien de neuf" : `${r.news} nouveauté${r.news > 1 ? "s" : ""}`}
                  {!!r.confirmations && `, ${r.confirmations} confirmation${r.confirmations > 1 ? "s" : ""}`}
                </span>
                {onOpenVersion && (
                  <Button variant="ghost" size="sm" onClick={() => onOpenVersion(r.version)}>
                    Lire cette version
                  </Button>
                )}
              </li>
            ))}
            {day.planned.map((p) => (
              <li key={`p${p.time}`} className="flex items-center gap-2.5 py-2 text-ink-2">
                <span className={`size-[7px] rounded-full border-[1.5px] ${p.deadline ? "border-warn" : "border-accent"}`} />
                <span className="w-12 tabular-nums">{hourLabel(p.time)}</span>
                {p.deadline ? "Passage ajouté pour l'échéance" : "Passage prévu"}
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function Sub({ children }: { children: ReactNode }) {
  return <h4 className="mb-3 mt-6 text-[13px] font-semibold text-ink-2">{children}</h4>;
}
