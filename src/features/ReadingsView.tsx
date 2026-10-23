import * as Dialog from "@radix-ui/react-dialog";
import * as Tooltip from "@radix-ui/react-tooltip";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, ChevronDown, ChevronRight, Download, EyeOff, ExternalLink, Laptop, Plus, ShieldCheck, Smartphone, Star, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FactPanel, type Factcheck } from "../components/FactPanel";
import { openLink } from "../components/Facts";
import { Popover } from "../components/Popover";
import { RecurringStrip } from "../components/RecurringTopics";
import { MediaAvatar, OWNER_COLOR, OWNER_LABEL } from "../components/MediaAvatar";
import { Button, Empty, PageHeader, Segmented, Spinner, Toggle, inputClass } from "../components/ui";
import { api, backend } from "../lib/api";
import { usePageChrome } from "../lib/chrome";
import { parse, relative, shortDate } from "../lib/format";
import { nav } from "../lib/nav";
import type { RecurringTopic, Settings, Status, Topic } from "../lib/types";

type Device = "ordinateur" | "telephone" | "les_deux" | "compte_google";

interface ReadingRow {
  id: number;
  title: string;
  url: string;
  domain: string;
  media: string;
  owner: string;
  owner_type: string;
  controller: string;
  kind: string;
  priority: boolean;
  browser: string;
  profile: string;
  device: Device;
  first_visit: string | null;
  last_visit: string | null;
  visits: number;
  status: "nouveau" | "suivi" | "ignore";
  topic_id: number | null;
  factcheck: Factcheck | Record<string, never>;
  factcheck_summary: Partial<Record<Status, number>> | null;
}

interface Diet {
  total: number;
  media: { domain: string; name: string; reads: number; share: number; owner: string; owner_type: string; controller: string; kind: string; priority: boolean }[];
  suggestions: Diet["media"];
  unqualified: Diet["media"];
  alerts: string[];
  hidden: string[];
  devices: Partial<Record<Device, number>>;
}

type StatusFilter = "nouveau" | "suivi" | "ignore";
type DeviceFilter = "tous" | "ordinateur" | "telephone";
type Period = "7" | "30" | "90" | "tout";

const DEVICE_LABEL: Record<Device, string> = { ordinateur: "Sur cet ordinateur", telephone: "Sur ton téléphone (synchronisé)", les_deux: "Sur l'ordinateur et le téléphone", compte_google: "Depuis ton compte Google (Takeout)" };
const PAGE = 8;

/** Regroupe les lectures par période, du plus récent au plus ancien. */
function bucket(d: Date | null): string {
  if (!d) return "Date inconnue";
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = (today.getTime() - new Date(d).setHours(0, 0, 0, 0)) / 86_400_000;
  if (diff <= 0) return "Aujourd'hui";
  if (diff === 1) return "Hier";
  if (diff < 7) return "Cette semaine";
  if (diff < 31) return "Ce mois-ci";
  return "Plus ancien";
}

export function ReadingsView() {
  const qc = useQueryClient();
  const [importing, setImporting] = useState(false);
  const [status, setStatus] = useState<StatusFilter>("nouveau");
  const [device, setDevice] = useState<DeviceFilter>("tous");
  const [period, setPeriod] = useState<Period>("tout");
  const [q, setQ] = useState("");
  const [domain, setDomain] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [showDiet, setShowDiet] = useState(false);
  // Un sujet récurrent choisi dans le bandeau : la liste ne montre que ses articles, quel que soit leur statut.
  const [cluster, setCluster] = useState<RecurringTopic | null>(null);

  const params = new URLSearchParams({ ...(cluster ? { ids: cluster.reading_ids.join(",") } : { status }), limit: "400", ...(device !== "tous" ? { device } : {}), ...(period !== "tout" ? { days: period } : {}), ...(domain ? { domain } : {}), ...(q.trim() ? { q: q.trim() } : {}) });
  const list = useQuery({ queryKey: ["readings", params.toString()], queryFn: () => api<{ total: number; items: ReadingRow[]; counts: Record<StatusFilter, number> }>(`/readings?${params}`) });
  const diet = useQuery({ queryKey: ["readings", "diet"], queryFn: () => api<Diet>("/readings/diet") });
  const hide = useMutation({
    mutationFn: (body: { domain: string; hidden: boolean; delete?: boolean }) => api("/readings/hide-media", { method: "POST", body }),
    onSuccess: () => {
      if (domain) setDomain("");
      setSelectedId(null);
      void qc.invalidateQueries({ queryKey: ["readings"] });
    },
  });
  const priority = useMutation({
    mutationFn: ({ domain, value }: { domain: string; value: boolean }) => api(`/sources/${encodeURIComponent(domain)}`, { method: "PATCH", body: { priority: value } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["readings"] }),
  });

  // Mise à jour automatique : à l'ouverture de la vue (si la dernière date de plus de 5 min),
  // et toutes les 15 minutes côté moteur. Une option : coupée tant que le lecteur ne l'a pas activée.
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<Settings>("/settings") });
  const auto = settings.data?.history_auto ?? false;
  const sync = useMutation({
    mutationFn: () => api<{ synced: boolean; articles_kept?: number }>("/history/sync?max_age=5", { method: "POST" }),
    onSuccess: (r) => {
      if (r.synced) void qc.invalidateQueries({ queryKey: ["settings"] });
      if (r.articles_kept) void qc.invalidateQueries({ queryKey: ["readings"] });
    },
  });
  const setAuto = useMutation({
    mutationFn: (history_auto: boolean) => api<Settings>("/settings", { method: "PATCH", body: { history_auto } }),
    onSuccess: (st) => {
      qc.setQueryData(["settings"], st);
      if (st.history_auto) sync.mutate();
    },
  });
  useEffect(() => {
    if (settings.data?.history_auto) sync.mutate();
  }, [settings.data?.history_auto]); // eslint-disable-line react-hooks/exhaustive-deps

  const syncedAt = settings.data?.history_synced_at;
  usePageChrome(
    "Mes lectures",
    <>
      <label className="mr-1 inline-flex items-center gap-2 text-[12.5px] text-ink-2" title="Les nouvelles visites des navigateurs que tu as cochés arrivent seules, toutes les 15 minutes, sans réimporter. L'historique est lu sur ce PC. Seuls des titres peuvent être envoyés à l'IA, si tu l'as accepté (Réglages › Confidentialité).">
        {sync.isPending ? <Spinner size={12} /> : null}
        <span>{auto ? (syncedAt ? `Mise à jour auto · ${relative(syncedAt)}` : "Mise à jour auto") : "Mise à jour auto désactivée"}</span>
        <Toggle label="Mise à jour automatique de l'historique" checked={auto} onChange={(v) => setAuto.mutate(v)} />
      </label>
      <Button size="sm" variant="primary" icon={<Download size={13} />} onClick={() => setImporting(true)}>
        Importer
      </Button>
    </>,
    [auto, syncedAt, sync.isPending],
  );

  const groups = useMemo(() => {
    const map = new Map<string, ReadingRow[]>();
    for (const r of list.data?.items ?? []) {
      const key = bucket(parse(r.last_visit));
      map.set(key, [...(map.get(key) ?? []), r]);
    }
    return [...map.entries()];
  }, [list.data]);
  const selected = list.data?.items.find((r) => r.id === selectedId) ?? null;
  const empty = diet.data && diet.data.total === 0 && diet.data.hidden.length === 0 && status === "nouveau" && !q && !domain;

  if (empty)
    return (
      <div className="px-10 pb-24 pt-6">
        <div className="mx-auto max-w-[720px]">
          <PageHeader title="Mes lectures" />
          <Empty icon={<BookOpen size={22} />} title="Retrouve tout ce que tu as lu." action={<Button variant="primary" icon={<Download size={14} />} onClick={() => setImporting(true)}>Importer mon historique</Button>}>
            openMedia lit l'historique des navigateurs que tu coches, sur ce PC, et n'en garde que les articles de presse. Si Chrome ou Edge est connecté à ton compte Google, l'historique de ton téléphone vient avec. Seuls des titres peuvent être envoyés à l'IA, et seulement si tu l'as accepté.
          </Empty>
          <ImportSheet open={importing} onOpenChange={setImporting} />
        </div>
      </div>
    );

  return (
    <Tooltip.Provider>
      <div className="px-8 pb-24 pt-6">
        <div className="mx-auto max-w-[1320px]">
          <PageHeader title="Mes lectures" subtitle="Les articles d'actualité retrouvés dans tes navigateurs, sur cet ordinateur et sur ton téléphone. Trie-les, suis-les, vérifie-les." />

          {diet.data && diet.data.total > 0 && (
            <div className="-mt-3 mb-6 flex flex-wrap items-center gap-2 text-[13px]">
              <span className="rounded-full bg-fill px-3 py-1 text-ink">{diet.data.total} articles</span>
              {!!(diet.data.devices.telephone || diet.data.devices.les_deux || diet.data.devices.compte_google) && (
                <span className="inline-flex items-center gap-1 rounded-full bg-fill px-3 py-1 text-ink">
                  <Smartphone size={13} /> {(diet.data.devices.telephone ?? 0) + (diet.data.devices.les_deux ?? 0) + (diet.data.devices.compte_google ?? 0)} lus sur le téléphone
                </span>
              )}
              <span className="rounded-full bg-fill px-3 py-1 text-ink">{diet.data.media.length} médias</span>
              {diet.data.alerts[0] && <span className="rounded-full bg-[color-mix(in_srgb,var(--warn)_14%,transparent)] px-3 py-1 text-warn">{diet.data.alerts[0]}</span>}
              <button onClick={() => setShowDiet(!showDiet)} className="ml-auto inline-flex items-center gap-1 text-accent hover:underline">
                {showDiet ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Ton régime d'information
              </button>
            </div>
          )}
          {showDiet && diet.data && <DietPanel diet={diet.data} onPriority={(d, v) => priority.mutate({ domain: d, value: v })} />}
          <RecurringStrip active={cluster?.key ?? null} onPick={setCluster} />

          <div className="flex items-start gap-6">
            {/* Filtres */}
            <aside className="sticky top-[68px] hidden w-[220px] shrink-0 space-y-6 lg:block">
              <FilterGroup title="Statut">
                {(["nouveau", "suivi", "ignore"] as const).map((s) => (
                  <FilterItem key={s} active={status === s} onClick={() => setStatus(s)} count={list.data?.counts[s]}>
                    {{ nouveau: "À trier", suivi: "Suivies", ignore: "Ignorées" }[s]}
                  </FilterItem>
                ))}
              </FilterGroup>
              <FilterGroup title="Appareil">
                {(["tous", "ordinateur", "telephone"] as const).map((d) => (
                  <FilterItem key={d} active={device === d} onClick={() => setDevice(d)} icon={d === "telephone" ? <Smartphone size={13} /> : d === "ordinateur" ? <Laptop size={13} /> : undefined}>
                    {{ tous: "Tous", ordinateur: "Ordinateur", telephone: "Téléphone" }[d]}
                  </FilterItem>
                ))}
              </FilterGroup>
              <FilterGroup title="Période">
                <Segmented<Period> label="Période" value={period} onChange={setPeriod} options={[{ value: "7", label: "7 j" }, { value: "30", label: "30 j" }, { value: "90", label: "3 m" }, { value: "tout", label: "Tout" }]} />
              </FilterGroup>
              {diet.data && <MediaFilter diet={diet.data} active={domain} onPick={(d) => setDomain(d === domain ? "" : d)} onHide={(d) => hide.mutate({ domain: d, hidden: true })} onRestore={(d) => hide.mutate({ domain: d, hidden: false })} onPriority={(d, v) => priority.mutate({ domain: d, value: v })} />}
            </aside>

            {/* Liste */}
            <section className="min-w-0 flex-1">
              <div className="mb-3 flex items-center gap-3">
                <input className={`${inputClass} max-w-[340px]`} placeholder="Chercher dans les titres" value={q} onChange={(e) => setQ(e.target.value)} />
                {cluster && (
                  <button onClick={() => setCluster(null)} className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-3 py-1 text-[12.5px] text-accent">
                    {cluster.name} <X size={12} />
                  </button>
                )}
                {domain && (
                  <button onClick={() => setDomain("")} className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-3 py-1 text-[12.5px] text-accent">
                    {diet.data?.media.find((m) => m.domain === domain)?.name ?? domain} <X size={12} />
                  </button>
                )}
                <span className="ml-auto text-[12.5px] text-ink-2">{list.data ? `${list.data.total} lecture${list.data.total > 1 ? "s" : ""}` : ""}</span>
              </div>
              {checked.size > 0 && <SelectionBar ids={[...checked]} onDone={() => setChecked(new Set())} />}
              {list.isLoading && <div className="py-16"><Spinner /></div>}
              {list.data?.items.length === 0 && <p className="py-16 text-center text-[14px] text-ink-2">{status === "nouveau" ? "Tout est trié. 🎉" : "Rien ici."}</p>}
              {groups.map(([label, rows]) => (
                <PeriodGroup key={label} label={label} rows={rows} selectedId={selectedId} onSelect={setSelectedId} checked={checked} onCheck={(id, v) => {
                  const next = new Set(checked);
                  if (v) next.add(id);
                  else next.delete(id);
                  setChecked(next);
                }} />
              ))}
            </section>

            {/* Inspecteur */}
            {selected && (
              <aside className="sticky top-[68px] hidden w-[380px] shrink-0 xl:block">
                <Inspector r={selected} onClose={() => setSelectedId(null)} onHideMedia={(del) => hide.mutate({ domain: selected.domain, hidden: true, delete: del })} onPriority={(v) => priority.mutate({ domain: selected.domain, value: v })} />
              </aside>
            )}
          </div>
          {/* Sur une fenêtre étroite, l'inspecteur s'ouvre en feuille */}
          <Dialog.Root open={!!selected && typeof window !== "undefined" && window.innerWidth < 1280} onOpenChange={(o) => !o && setSelectedId(null)}>
            <Dialog.Portal>
              <Dialog.Overlay className="scrim anim-scrim z-40 xl:hidden" />
              <Dialog.Content aria-describedby={undefined} className="glass anim-drawer fixed inset-y-[calc(var(--win-gap,0px)+12px)] right-[calc(var(--win-gap,0px)+12px)] z-50 w-[400px] max-w-[calc(100vw-24px)] overflow-y-auto rounded-[var(--r-sheet)] p-1 xl:hidden">
                <Dialog.Title className="sr-only">Lecture</Dialog.Title>
                {selected && <Inspector r={selected} onClose={() => setSelectedId(null)} onHideMedia={(del) => hide.mutate({ domain: selected.domain, hidden: true, delete: del })} onPriority={(v) => priority.mutate({ domain: selected.domain, value: v })} />}
              </Dialog.Content>
            </Dialog.Portal>
          </Dialog.Root>
          <ImportSheet open={importing} onOpenChange={setImporting} />
        </div>
      </div>
    </Tooltip.Provider>
  );
}

function FilterGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-1.5 px-2 text-[12px] font-semibold text-ink-3">{title}</p>
      <div className="space-y-px">{children}</div>
    </div>
  );
}

function FilterItem({ active, onClick, count, icon, children }: { active: boolean; onClick: () => void; count?: number; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <button onClick={onClick} aria-pressed={active} className={`flex h-8 w-full items-center gap-2 rounded-lg px-2 text-left text-[13.5px] transition-colors ${active ? "bg-fill-strong font-medium text-ink" : "text-ink hover:bg-fill"}`}>
      {icon && <span className="text-ink-2">{icon}</span>}
      <span className="flex-1 truncate">{children}</span>
      {count !== undefined && <span className="text-[12px] tabular-nums text-ink-3">{count}</span>}
    </button>
  );
}

/** Les médias lus, du plus au moins lu : filtrer d'un clic, promouvoir, ou masquer ceux qui n'intéressent pas. */
function MediaFilter({ diet, active, onPick, onHide, onRestore, onPriority }: { diet: Diet; active: string; onPick: (d: string) => void; onHide: (d: string) => void; onRestore: (d: string) => void; onPriority: (d: string, v: boolean) => void }) {
  const [all, setAll] = useState(false);
  const [showHidden, setShowHidden] = useState(false);
  const media = all ? diet.media : diet.media.slice(0, 10);
  return (
    <FilterGroup title="Médias">
      {media.map((m) => (
        <div key={m.domain} className="group relative">
          <FilterItem active={active === m.domain} onClick={() => onPick(m.domain)} count={m.reads} icon={<span className="block size-2 rounded-full" style={{ background: OWNER_COLOR[m.kind === "recherche" ? "recherche" : m.owner_type] ?? OWNER_COLOR.inconnu }} />}>
            {m.name}
            {m.priority && <Star size={11} className="ml-1 inline text-warn" fill="currentColor" />}
          </FilterItem>
          <span className="absolute right-1 top-1/2 hidden -translate-y-1/2 gap-0.5 rounded-md bg-[var(--surface)] shadow-card group-hover:flex">
            {m.kind !== "unknown" && (
              <button title={m.priority ? "Retirer des sources prioritaires" : "Source prioritaire"} onClick={() => onPriority(m.domain, !m.priority)} className="grid size-6 place-items-center rounded-md text-ink-2 hover:text-warn">
                <Star size={12} fill={m.priority ? "currentColor" : "none"} />
              </button>
            )}
            <button title="Masquer ce média de mes lectures" onClick={() => onHide(m.domain)} className="grid size-6 place-items-center rounded-md text-ink-2 hover:text-deny">
              <EyeOff size={12} />
            </button>
          </span>
        </div>
      ))}
      {diet.media.length > 10 && (
        <button onClick={() => setAll(!all)} className="px-2 py-1 text-[12.5px] text-accent hover:underline">
          {all ? "Moins de médias" : `Tous les médias (${diet.media.length})`}
        </button>
      )}
      {diet.hidden.length > 0 && (
        <div className="pt-1">
          <button onClick={() => setShowHidden(!showHidden)} className="px-2 py-1 text-[12.5px] text-ink-2 hover:text-ink">
            {diet.hidden.length} média(s) masqué(s)
          </button>
          {showHidden &&
            diet.hidden.map((d) => (
              <div key={d} className="flex items-center justify-between px-2 py-0.5 text-[12.5px] text-ink-3">
                <span className="truncate">{d}</span>
                <button onClick={() => onRestore(d)} className="text-accent hover:underline">
                  Réafficher
                </button>
              </div>
            ))}
        </div>
      )}
    </FilterGroup>
  );
}

function PeriodGroup({ label, rows, selectedId, onSelect, checked, onCheck }: { label: string; rows: ReadingRow[]; selectedId: number | null; onSelect: (id: number) => void; checked: Set<number>; onCheck: (id: number, v: boolean) => void }) {
  const [open, setOpen] = useState(true);
  const [limit, setLimit] = useState(PAGE);
  return (
    <section className="mb-5">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="mb-1.5 flex items-center gap-1.5 px-1 text-[13px] font-semibold text-ink-2 hover:text-ink">
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {label} <span className="font-normal text-ink-3">{rows.length}</span>
      </button>
      {open && (
        <div className="card divide-y divide-line overflow-hidden">
          {rows.slice(0, limit).map((r) => (
            <Row key={r.id} r={r} active={r.id === selectedId} onSelect={() => onSelect(r.id)} checked={checked.has(r.id)} selecting={checked.size > 0} onCheck={(v) => onCheck(r.id, v)} />
          ))}
          {rows.length > limit && (
            <button onClick={() => setLimit(limit + 20)} className="w-full py-2.5 text-center text-[13px] text-accent hover:bg-fill/50">
              Afficher {Math.min(20, rows.length - limit)} de plus ({rows.length - limit} restantes)
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function FactDots({ summary }: { summary: ReadingRow["factcheck_summary"] }) {
  if (!summary) return null;
  const order: Status[] = ["confirme", "non_confirme", "conteste", "dementi"];
  const color = { confirme: "bg-ok", non_confirme: "bg-warn", conteste: "bg-contest", dementi: "bg-deny" };
  return (
    <span className="flex shrink-0 items-center gap-0.5" title="Vérifié : statut des affirmations">
      {order.flatMap((s) => Array.from({ length: summary[s] ?? 0 }, (_, i) => <span key={`${s}${i}`} className={`size-1.5 rounded-full ${color[s]}`} />))}
    </span>
  );
}

/** Une ligne compacte : le titre d'abord, le reste en retrait ; les actions vivent dans l'inspecteur. */
function Row({ r, active, onSelect, checked, selecting, onCheck }: { r: ReadingRow; active: boolean; onSelect: () => void; checked: boolean; selecting: boolean; onCheck: (v: boolean) => void }) {
  return (
    <div onClick={onSelect} className={`group flex cursor-default items-center gap-3 px-3 py-2.5 transition-colors ${active ? "bg-accent-soft" : "hover:bg-fill/50"}`}>
      <input
        type="checkbox"
        checked={checked}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onCheck(e.target.checked)}
        aria-label="Sélectionner"
        className={`size-4 shrink-0 accent-[var(--accent)] ${selecting || checked ? "" : "opacity-0 group-hover:opacity-100"}`}
      />
      <MediaAvatar m={r} />
      <div className="min-w-0 flex-1">
        <p className="line-clamp-1 text-[14px] font-medium text-ink">{r.title}</p>
        <p className="flex items-center gap-1.5 text-[12px] text-ink-2">
          <span className="truncate">{r.media}</span>
          {r.priority && <Star size={10} className="shrink-0 text-warn" fill="currentColor" />}
          <span className="text-ink-3">·</span>
          <span className="shrink-0">{relative(r.last_visit)}</span>
          {(r.device === "telephone" || r.device === "compte_google") && <Smartphone size={11} className="shrink-0 text-ink-3" aria-label="lu sur le téléphone" />}
          {r.status === "suivi" && <span className="shrink-0 text-accent">· suivi</span>}
        </p>
      </div>
      <FactDots summary={r.factcheck_summary} />
    </div>
  );
}

function Inspector({ r, onClose, onHideMedia, onPriority }: { r: ReadingRow; onClose: () => void; onHideMedia: (del: boolean) => void; onPriority: (v: boolean) => void }) {
  const qc = useQueryClient();
  const patch = useMutation({ mutationFn: (body: object) => api(`/readings/${r.id}`, { method: "PATCH", body }), onSuccess: () => qc.invalidateQueries({ queryKey: ["readings"] }) });
  const check = useMutation({ mutationFn: () => api<Factcheck>(`/readings/${r.id}/factcheck`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["readings"] }) });
  const [confirmHide, setConfirmHide] = useState(false);
  const fc = "status" in r.factcheck ? (r.factcheck as Factcheck) : null;
  return (
    <div className="card p-5">
      <div className="flex items-start gap-3">
        <MediaAvatar m={r} />
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium text-ink">{r.media}</p>
          <p className="text-[12px] text-ink-2">
            {r.owner && r.owner !== r.domain ? `${r.owner}${r.controller ? ` (${r.controller})` : ""}, ` : ""}
            {r.kind === "recherche" ? "recherche" : OWNER_LABEL[r.owner_type] ?? r.owner_type}
          </p>
        </div>
        <button onClick={onClose} aria-label="Fermer" className="grid size-7 place-items-center rounded-full text-ink-2 hover:bg-fill">
          <X size={15} />
        </button>
      </div>
      <h2 className="serif mt-4 text-[20px] font-medium leading-snug text-ink">{r.title}</h2>
      <dl className="mt-3 space-y-1 text-[12.5px] text-ink-2">
        <div className="flex gap-2">
          <dt className="w-[86px] shrink-0 text-ink-3">Lu</dt>
          <dd>
            {relative(r.last_visit)}
            {r.visits > 1 ? `, ${r.visits} fois depuis le ${shortDate(r.first_visit)}` : ""}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="w-[86px] shrink-0 text-ink-3">Où</dt>
          <dd>
            {DEVICE_LABEL[r.device]} · {r.browser}
          </dd>
        </div>
      </dl>

      <div className="mt-4 flex flex-wrap gap-2">
        <Button size="sm" icon={<ExternalLink size={13} />} onClick={() => openLink(r.url)}>
          Ouvrir
        </Button>
        <Button size="sm" variant="primary" busy={check.isPending} icon={<ShieldCheck size={13} />} onClick={() => check.mutate()}>
          {check.isPending ? "Vérification…" : fc ? "Revérifier" : "Vérifier"}
        </Button>
        <FollowMenu r={r} />
      </div>
      {check.isPending && <p className="mt-2 text-[12px] text-ink-2">Recherche d'autres médias sur les mêmes faits, puis recoupement : une à trois minutes.</p>}
      {check.error && <p className="mt-2 text-[12.5px] text-deny">{check.error.message}</p>}
      {fc && <FactPanel fc={fc} />}

      <div className="mt-5 space-y-1 border-t border-line pt-3 text-[13px]">
        {r.status !== "ignore" ? (
          <button onClick={() => patch.mutate({ status: "ignore" })} className="block text-ink-2 hover:text-ink">
            Ignorer cet article
          </button>
        ) : (
          <button onClick={() => patch.mutate({ status: "nouveau" })} className="block text-ink-2 hover:text-ink">
            Remettre à trier
          </button>
        )}
        {r.kind !== "unknown" && (
          <button onClick={() => onPriority(!r.priority)} className="block text-ink-2 hover:text-ink">
            {r.priority ? `Retirer ${r.media} des sources prioritaires` : `Faire de ${r.media} une source prioritaire`}
          </button>
        )}
        {!confirmHide ? (
          <button onClick={() => setConfirmHide(true)} className="block text-deny">
            Masquer {r.media} de mes lectures…
          </button>
        ) : (
          <div className="rounded-lg bg-fill/60 p-3">
            <p className="text-[12.5px] text-ink">Ne plus voir ce média ici, y compris aux prochains imports ?</p>
            <div className="mt-2 flex flex-wrap gap-2">
              <Button size="sm" onClick={() => onHideMedia(false)}>
                Masquer
              </Button>
              <Button size="sm" variant="danger" onClick={() => onHideMedia(true)}>
                Masquer et effacer ses lectures
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setConfirmHide(false)}>
                Annuler
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** Le détail de « Tes médias », replié par défaut pour ne pas encombrer la page. */
function DietPanel({ diet, onPriority }: { diet: Diet; onPriority: (d: string, v: boolean) => void }) {
  const top = diet.media.slice(0, 8);
  const max = top[0]?.reads ?? 1;
  return (
    <section className="card mb-6 p-5">
      <ul className="space-y-2">
        {top.map((m) => (
          <li key={m.domain} className="grid grid-cols-[160px_1fr_auto] items-center gap-3 text-[13px]">
            <span className="truncate text-ink">{m.name}</span>
            <div className="h-2 overflow-hidden rounded-full bg-fill">
              <div className="h-full rounded-full" style={{ width: `${(100 * m.reads) / max}%`, background: OWNER_COLOR[m.owner_type] ?? OWNER_COLOR.inconnu }} />
            </div>
            <span className="w-8 text-right tabular-nums text-ink-2">{m.reads}</span>
          </li>
        ))}
      </ul>
      {diet.suggestions.length > 0 && (
        <p className="mt-4 text-[13px] text-ink-2">
          Tu lis souvent {diet.suggestions.map((m) => m.name).join(", ")}.{" "}
          <button className="text-accent hover:underline" onClick={() => diet.suggestions.forEach((m) => onPriority(m.domain, true))}>
            En faire des sources prioritaires
          </button>
        </p>
      )}
      {diet.alerts.map((a) => (
        <p key={a} className="rail mt-3 text-[13px] text-ink" data-status="non_confirme">
          {a}
        </p>
      ))}
    </section>
  );
}

function FollowMenu({ r }: { r: ReadingRow }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLSpanElement>(null);
  const close = useCallback(() => setOpen(false), []);
  const topics = useQuery({ queryKey: ["topics"], queryFn: () => api<Topic[]>("/topics"), enabled: open });
  const assign = useMutation({
    mutationFn: (topic_id: number) => api("/readings/assign", { method: "POST", body: { ids: [r.id], topic_id } }),
    onSuccess: () => {
      setOpen(false);
      void qc.invalidateQueries({ queryKey: ["readings"] });
    },
  });
  return (
    <span ref={anchor} className="inline-flex">
      <Button size="sm" icon={open ? <ChevronDown size={13} /> : <ChevronRight size={13} />} onClick={() => setOpen(!open)}>
        Suivre
      </Button>
      <Popover anchor={anchor} open={open} onClose={close}>
          <button onClick={() => nav.openNewTopic({ prompt: `Suis l'actualité liée à cet article : « ${r.title} » (${r.media}). Les faits nouveaux, les positions des acteurs et ce qui est attendu ensuite.`, name: r.title.slice(0, 60) })} className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-[13.5px] text-ink hover:bg-fill">
            <Plus size={14} /> En faire un nouveau sujet
          </button>
          <p className="px-3 pb-1 pt-2 text-[11.5px] font-semibold text-ink-3">Ajouter à un sujet</p>
          {topics.data?.map((t) => (
            <button key={t.id} onClick={() => assign.mutate(t.id)} className="block w-full truncate rounded-lg px-3 py-1.5 text-left text-[13.5px] text-ink hover:bg-fill">
              {t.name}
            </button>
          ))}
      </Popover>
    </span>
  );
}

/** Plusieurs lectures sélectionnées : les ranger d'un coup dans un sujet. */
function SelectionBar({ ids, onDone }: { ids: number[]; onDone: () => void }) {
  const qc = useQueryClient();
  const topics = useQuery({ queryKey: ["topics"], queryFn: () => api<Topic[]>("/topics") });
  const [topic, setTopic] = useState<number | "">("");
  const assign = useMutation({
    mutationFn: () => api("/readings/assign", { method: "POST", body: { ids, topic_id: topic } }),
    onSuccess: () => {
      onDone();
      void qc.invalidateQueries({ queryKey: ["readings"] });
    },
  });
  return (
    <div className="glass sticky top-[60px] z-10 mt-4 flex flex-wrap items-center gap-3 rounded-[var(--r-panel)] px-4 py-2.5">
      <span className="text-[13.5px] font-medium text-ink">{ids.length} sélectionnée(s)</span>
      <select className={`${inputClass} max-w-[240px]`} value={topic} onChange={(e) => setTopic(e.target.value ? Number(e.target.value) : "")}>
        <option value="">Choisir un sujet…</option>
        {topics.data?.map((t) => (
          <option key={t.id} value={t.id}>
            {t.name}
          </option>
        ))}
      </select>
      <Button size="sm" variant="primary" disabled={!topic} busy={assign.isPending} onClick={() => assign.mutate()}>
        Ranger dans ce sujet
      </Button>
      <Button size="sm" variant="ghost" onClick={onDone}>
        Annuler
      </Button>
    </div>
  );
}

interface BrowserProfile {
  browser: string;
  browser_name: string;
  profile: string;
  label: string;
  modified: string | null;
}

function ImportSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (v: boolean) => void }) {
  const qc = useQueryClient();
  const browsers = useQuery({ queryKey: ["history-browsers"], queryFn: () => api<BrowserProfile[]>("/history/browsers"), enabled: open });
  const key = (b: BrowserProfile) => `${b.browser}/${b.profile}`;
  const [unchecked, setUnchecked] = useState<Set<string> | null>(null);
  const off = unchecked ?? new Set<string>();
  const [days, setDays] = useState("90");
  const [files, setFiles] = useState<string[]>([]);
  const [fileInput, setFileInput] = useState("");
  const [mode, setMode] = useState<"pc" | "telephone">("pc");
  const run = useMutation({
    mutationFn: () => api<{ profiles: number; pages_seen: number; articles_kept: number; readings_total: number; errors: string[] }>("/history/import", { method: "POST", body: { browsers: [...(browsers.data ?? []).filter((b) => !off.has(key(b))).map((b) => ({ browser: b.browser, profile: b.profile })), ...files.map((path) => ({ path }))], days: Number(days) } }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["readings"] });
      void qc.invalidateQueries({ queryKey: ["settings"] }); // les navigateurs choisis servent à la mise à jour auto
    },
  });
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v);
        if (!v) run.reset();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="scrim anim-scrim z-50" />
        <Dialog.Content aria-describedby={undefined} className="scroll-area anim-sheet fixed left-1/2 top-[8vh] z-50 max-h-[84vh] w-[540px] max-w-[calc(100vw-32px)] -translate-x-1/2 glass rounded-[var(--r-sheet)] p-6">
          <Dialog.Title className="title-md text-ink">Importer ton historique</Dialog.Title>
          <div className="mt-3">
            <Segmented label="Source de l'historique" value={mode} onChange={setMode} options={[{ value: "pc", label: "Navigateurs de ce PC" }, { value: "telephone", label: "Mon téléphone" }]} />
          </div>
          {mode === "telephone" ? (
            <PhoneImport />
          ) : (
            <>
          <p className="mt-1.5 text-[13.5px] leading-relaxed text-ink-2">
            openMedia lit l'historique de tes navigateurs <strong className="font-medium text-ink">sur ce PC uniquement</strong> et n'en garde que les articles de presse. Recherches, messageries, achats et réseaux sociaux sont ignorés et jamais enregistrés. Ensuite, les navigateurs cochés se mettent à jour tout seuls (désactivable en haut de « Mes lectures »).
          </p>

          {run.data ? (
            <div className="mt-5 rounded-xl bg-fill/60 p-4 text-[14px] text-ink">
              <p className="font-semibold">{run.data.articles_kept} article(s) ajouté(s)</p>
              <p className="mt-1 text-[13px] text-ink-2">
                {run.data.pages_seen.toLocaleString("fr-FR")} pages parcourues dans {run.data.profiles} profil(s) ; {run.data.readings_total} lectures au total.
              </p>
              {run.data.errors.map((e) => (
                <p key={e} className="mt-1 text-[12.5px] text-deny">
                  {e}
                </p>
              ))}
            </div>
          ) : (
            <>
              <p className="mb-2 mt-5 text-[13px] font-medium text-ink">Navigateurs trouvés</p>
              {browsers.isLoading && <Spinner />}
              {browsers.data?.length === 0 && <p className="text-[13px] text-ink-2">Aucun navigateur trouvé automatiquement : indique son fichier d'historique ci-dessous.</p>}
              {!!browsers.data?.length && (
                  <div className="mb-3">
                    <div className="card divide-y divide-line overflow-hidden">
                      {browsers.data.map((b) => (
                        <label key={key(b)} className="flex cursor-pointer items-center gap-3 px-4 py-2.5">
                          <input
                            type="checkbox"
                            className="size-4 accent-[var(--accent)]"
                            checked={!off.has(key(b))}
                            onChange={(e) => {
                              const next = new Set(off);
                              if (e.target.checked) next.delete(key(b));
                              else next.add(key(b));
                              setUnchecked(next);
                            }}
                          />
                          <span className="flex-1 text-[14px] text-ink">
                            {b.browser_name} <span className="text-ink-2">· {b.label}</span>
                          </span>
                          <span className="text-[12px] text-ink-3">{b.modified ? `utilisé ${relative(b.modified)}` : ""}</span>
                        </label>
                      ))}
                    </div>
                  </div>
              )}
              <details className="mt-2 text-[13px]">
                <summary className="cursor-pointer text-accent">Ton navigateur n'est pas dans la liste ?</summary>
                <p className="mt-2 text-[12.5px] leading-snug text-ink-2">
                  Indique son fichier d'historique : « History » pour les navigateurs Chromium (dossier du profil), « places.sqlite » pour ceux de la famille Firefox. Un dossier de profil suffit aussi.
                </p>
                <div className="mt-2 flex gap-2">
                  <input className={inputClass} placeholder="C:\Users\…\User Data\Default\History" value={fileInput} onChange={(e) => setFileInput(e.target.value)} />
                  <Button
                    disabled={!fileInput.trim()}
                    onClick={() => {
                      setFiles([...files, fileInput.trim()]);
                      setFileInput("");
                    }}
                  >
                    Ajouter
                  </Button>
                </div>
                {files.map((f) => (
                  <p key={f} className="mt-1 truncate text-[12.5px] text-ink">
                    {f}{" "}
                    <button className="text-deny" onClick={() => setFiles(files.filter((x) => x !== f))}>
                      retirer
                    </button>
                  </p>
                ))}
              </details>
              <div className="mt-4 flex items-center justify-between">
                <span className="text-[13px] font-medium text-ink">Période</span>
                <Segmented value={days} onChange={setDays} options={[{ value: "30", label: "30 jours" }, { value: "90", label: "3 mois" }, { value: "365", label: "1 an" }]} />
              </div>
            </>
          )}
          {run.error && <p className="mt-3 text-[13px] text-deny">{run.error.message}</p>}
            </>
          )}
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close asChild>
              <Button variant="ghost">{run.data ? "Fermer" : "Annuler"}</Button>
            </Dialog.Close>
            {!run.data && mode === "pc" && (
              <Button variant="primary" busy={run.isPending} disabled={!files.length && (!browsers.data?.length || browsers.data.every((b) => off.has(key(b))))} onClick={() => run.mutate()}>
                Importer
              </Button>
            )}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** L'historique du téléphone : déjà là si Chrome ou Edge synchronise l'historique avec le compte
 *  Google ; sinon, par un export Google Takeout déposé ici. */
function PhoneImport() {
  const qc = useQueryClient();
  const [over, setOver] = useState(false);
  const diet = useQuery({ queryKey: ["readings", "diet"], queryFn: () => api<Diet>("/readings/diet") });
  const upload = useMutation({
    mutationFn: async (file: File) => {
      const { url, token } = await backend();
      const res = await fetch(`${url}/history/takeout`, { method: "POST", headers: { "X-Token": token, "X-Filename": encodeURIComponent(file.name) }, body: file });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `Erreur ${res.status}`);
      return data as { pages_seen: number; articles_kept: number; readings_total: number };
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["readings"] }),
  });
  const phone = (diet.data?.devices.telephone ?? 0) + (diet.data?.devices.les_deux ?? 0) + (diet.data?.devices.compte_google ?? 0);
  return (
    <div className="mt-5 space-y-5 text-[13.5px] leading-relaxed">
      <section>
        <p className="font-semibold text-ink">1. Le plus simple : la synchronisation Google</p>
        <p className="mt-1 text-ink-2">
          Si Chrome (ou Edge) est connecté à ton compte sur le téléphone <em>et</em> sur ce PC, avec la synchronisation de l'historique activée, les pages lues sur le téléphone arrivent dans l'historique de ce PC. L'import « Navigateurs de ce PC » les récupère et les marque d'une icône de téléphone.
        </p>
        <p className="mt-2 rounded-lg bg-fill/60 px-3 py-2 text-ink">
          {phone > 0 ? `✓ ${phone} article(s) lus sur le téléphone sont déjà dans tes lectures.` : "Aucun article du téléphone pour l'instant."}
        </p>
        <p className="mt-2 text-[12.5px] text-ink-2">Sur le téléphone : Chrome → Paramètres → ton compte → Synchronisation → active « Historique ». Puis relance l'import depuis ce PC.</p>
      </section>
      <section>
        <p className="font-semibold text-ink">2. Sinon : l'export Google Takeout</p>
        <ol className="mt-1 list-decimal space-y-0.5 pl-5 text-ink-2">
          <li>
            Ouvre{" "}
            <button className="text-accent hover:underline" onClick={() => openLink("https://takeout.google.com/")}>
              takeout.google.com
            </button>{" "}
            et clique « Tout désélectionner ».
          </li>
          <li>Coche seulement « Chrome » et « Mon activité » (format JSON), puis exporte.</li>
          <li>Dépose ici l'archive .zip reçue par e-mail.</li>
        </ol>
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setOver(false);
            const f = e.dataTransfer.files[0];
            if (f) upload.mutate(f);
          }}
          className={`mt-3 flex cursor-pointer flex-col items-center gap-1 rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors ${over ? "border-accent bg-accent-soft" : "border-line-strong hover:bg-fill/50"}`}
        >
          <Download size={18} className="text-ink-2" />
          <span className="text-ink">{upload.isPending ? "Analyse de l'export…" : "Dépose l'archive Takeout ou clique pour la choisir"}</span>
          <span className="text-[12px] text-ink-3">Analysée sur ce PC puis effacée ; seuls les articles de presse sont gardés.</span>
          <input type="file" accept=".zip,.json" className="hidden" onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} />
        </label>
        {upload.data && (
          <p className="mt-2 rounded-lg bg-fill/60 px-3 py-2 text-ink">
            {upload.data.articles_kept} article(s) ajouté(s) sur {upload.data.pages_seen.toLocaleString("fr-FR")} pages de l'export.
          </p>
        )}
        {upload.error && <p className="mt-2 text-[12.5px] text-deny">{upload.error.message}</p>}
      </section>
    </div>
  );
}
