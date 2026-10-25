import { useQuery } from "@tanstack/react-query";
import { invoke } from "@tauri-apps/api/core";
import { emitTo } from "@tauri-apps/api/event";
import { ArrowRight, Cpu, Globe2, Lock } from "lucide-react";
import type { ReactNode } from "react";
import { api, inTauri } from "../lib/api";
import { relative } from "../lib/format";
import { OPTIONS, aiTarget, coreFlows, listNames, stillOnline, type OptionInfo } from "../lib/privacy";
import type { Settings } from "../lib/types";
import { Toggle } from "./ui";

export interface BrowserProfile {
  browser: string;
  browser_name: string;
  profile: string;
  label: string;
  modified: string | null;
}

type Patch = (body: Partial<Settings>) => void;

/** L'état d'un interrupteur écrit en toutes lettres : la couleur seule ne suffit pas. */
function State({ on }: { on: boolean }) {
  return <span className={`w-[68px] text-right text-[12px] ${on ? "font-medium text-ok" : "text-ink-3"}`}>{on ? "Activé" : "Désactivé"}</span>;
}

/** Le bandeau qui dit, en une phrase, où l'IA travaille. */
export function AiBanner({ settings: st }: { settings: Settings | undefined }) {
  const ai = aiTarget(st);
  if (ai.local)
    return (
      <div className="flex gap-3 rounded-2xl bg-[color-mix(in_srgb,var(--ok)_9%,transparent)] p-4">
        <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-ok text-white">
          <Cpu size={18} />
        </span>
        <div className="text-[13.5px] leading-snug text-ink-2">
          <p className="text-[15px] font-semibold text-ink">L'analyse IA se fait sur ton PC.</p>
          <p className="mt-1">Aucun service d'IA ne reçoit tes sujets, tes articles ni tes fiches. openMedia a quand même besoin d'Internet pour aller chercher l'actualité : {listNames(stillOnline(st)).replace(" ou ", " et ")}. Ces services voient les requêtes de tes sujets, comme quand tu navigues.</p>
        </div>
      </div>
    );
  return (
    <div className="flex gap-3 rounded-2xl bg-accent-soft p-4">
      <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent-fill text-white">
        <Globe2 size={18} />
      </span>
      <div className="text-[13.5px] leading-snug text-ink-2">
        <p className="text-[15px] font-semibold text-ink">
          {ai.pc.length
            ? `L'analyse IA se fait en ligne, chez ${listNames(ai.names.filter((n) => !n.startsWith("ton PC")))}, et sur ton PC (${ai.pc.join(", ")}) pour les rôles que tu lui confies.`
            : `L'analyse IA se fait en ligne, chez ${listNames(ai.names)}.`}
        </p>
        <p className="mt-1">
          Ce qui leur est envoyé est listé ci-dessous, rien d'autre. Ce qu'ils en font (conservation, entraînement) dépend de leurs règles et de tes réglages chez eux :{" "}
          {ai.policies.map((p, i) => (
            <span key={p.url}>
              {i > 0 && ", "}
              <a className="text-accent hover:underline" href={p.url} target="_blank" rel="noreferrer">
                {p.label}
              </a>
            </span>
          ))}
          .
        </p>
        {ai.china.length > 0 && (
          <p className="mt-1.5 text-warn">
            {listNames(ai.china).replace(" ou ", " et ")} {ai.china.length > 1 ? "traitent" : "traite"} tes articles en Chine, sous la loi chinoise. Leur filtre de contenu peut aussi refuser des sujets politiques sensibles : openMedia confie alors l'appel à un autre de tes fournisseurs, s'il y en a un.
          </p>
        )}
      </div>
    </div>
  );
}

/** La condition de fonctionnement : ce que le suivi des sujets envoie, et à qui. */
export function CoreFlows({ settings: st, onChange }: { settings: Settings | undefined; onChange: Patch }) {
  const ai = aiTarget(st);
  return (
    <div className="card overflow-hidden">
      <ul className="divide-y divide-line">
        {coreFlows(st).map((f) => (
          <li key={f.what} className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 px-4 py-2.5 text-[13px]">
            <span className="text-ink">{f.what}</span>
            <ArrowRight size={14} className="text-ink-3" />
            <span className="text-ink-2">
              <span className="font-medium text-ink">{f.to}</span>
              <span className="block text-[12px]">{f.when}</span>
            </span>
          </li>
        ))}
      </ul>
      <div className="border-t border-line bg-fill/40 px-4 py-1">
        <SwitchRow label="Chercher dans GDELT" hint="L'index mondial et ouvert des articles de presse (gdeltproject.org), la recherche datée d'openMedia. Sans lui, il ne reste que les unes des médias et tes flux RSS : beaucoup moins de sources, et plus de pouls les jours sans passage." checked={st?.gdelt ?? true} onChange={(v) => onChange({ gdelt: v })} />
        {!ai.local && <SwitchRow label="Recherche web complémentaire" hint="Quand un sujet est peu couvert, le fournisseur d'IA cherche d'autres sources sur le web." checked={st?.claude_search_fallback ?? true} onChange={(v) => onChange({ claude_search_fallback: v })} />}
      </div>
    </div>
  );
}

function SwitchRow({ label, hint, checked, onChange, children }: { label: string; hint?: ReactNode; checked: boolean; onChange: (v: boolean) => void; children?: ReactNode }) {
  return (
    <div className="py-2.5">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <div className="text-[14px] text-ink">{label}</div>
          {hint && <div className="mt-0.5 text-[12px] leading-snug text-ink-2">{hint}</div>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <State on={checked} />
          <Toggle label={label} checked={checked} onChange={onChange} />
        </div>
      </div>
      {children}
    </div>
  );
}

/** Les options, toutes coupées tant que le lecteur ne les a pas activées. */
export function OptionsList({ settings: st, onChange, browsers, previous = true }: { settings: Settings; onChange: Patch; browsers?: ReactNode; previous?: boolean }) {
  const shown = OPTIONS.filter((o) => !o.requires || st[o.requires]);
  return (
    <div className="card overflow-hidden px-4">
      <div className="divide-y divide-line">
        {shown.map((o) => (
          <OptionRow key={o.id} option={o} settings={st} onChange={onChange} previous={previous ? st.previous_options?.[o.id] : undefined}>
            {o.id === "history_auto" && st.history_auto && browsers}
          </OptionRow>
        ))}
      </div>
    </div>
  );
}

function OptionRow({ option: o, settings: st, onChange, previous, children }: { option: OptionInfo; settings: Settings; onChange: Patch; previous?: boolean; children?: ReactNode }) {
  const on = !!st[o.id];
  const nested = !!o.requires;
  return (
    <div className={nested ? "pl-6" : ""}>
      <SwitchRow
        label={o.label}
        checked={on}
        onChange={(v) => onChange({ [o.id]: v, ...(o.id === "history_auto" && !v ? { readings_ai: false } : {}) } as Partial<Settings>)}
        hint={
          <>
            {o.sends(st)} <span className="text-ink-3">Sans cette option : {o.without.charAt(0).toLowerCase() + o.without.slice(1)}</span>
            {previous && !on && <span className="mt-0.5 block text-ink-3">Tu l'utilisais avant cette version : elle a été coupée en attendant ton accord.</span>}
          </>
        }
      >
        {children}
      </SwitchRow>
    </div>
  );
}

/** Les navigateurs dont lire l'historique : rien n'est coché d'avance. */
export function BrowserPicker({ settings: st, onChange }: { settings: Settings; onChange: Patch }) {
  const q = useQuery({ queryKey: ["history-browsers"], queryFn: () => api<BrowserProfile[]>("/history/browsers") });
  const chosen = new Set((st.history_sources ?? []).map((c) => `${c.browser}/${c.profile}`));
  const key = (b: BrowserProfile) => `${b.browser}/${b.profile}`;
  const toggle = (b: BrowserProfile, v: boolean) => {
    const rest = (st.history_sources ?? []).filter((c) => `${c.browser}/${c.profile}` !== key(b));
    onChange({ history_sources: v ? [...rest, { browser: b.browser, profile: b.profile }] : rest });
  };
  const list = q.data ?? [];
  return (
    <div className="mb-1 mt-3 rounded-xl bg-fill/50 p-3">
      <p className="text-[12.5px] font-medium text-ink">Quels navigateurs lire ?</p>
      {q.isLoading && <p className="mt-1 text-[12.5px] text-ink-2">Recherche des navigateurs…</p>}
      {q.data && list.length === 0 && <p className="mt-1 text-[12.5px] text-ink-2">Aucun navigateur trouvé sur ce PC. Tu pourras indiquer un fichier d'historique dans « Mes lectures ».</p>}
      <div className="mt-1.5 space-y-1">
        {list.map((b) => (
          <label key={key(b)} className="flex cursor-pointer items-center gap-2.5 text-[13px]">
            <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={chosen.has(key(b))} onChange={(e) => toggle(b, e.target.checked)} />
            <span className="flex-1 text-ink">
              {b.browser_name} <span className="text-ink-2">· {b.label}</span>
            </span>
            {b.modified && <span className="text-[11.5px] text-ink-3">utilisé {relative(b.modified)}</span>}
          </label>
        ))}
      </div>
      <label className="mt-2.5 flex cursor-pointer items-center gap-2.5 border-t border-line pt-2.5 text-[13px]">
        <input type="checkbox" className="size-4 accent-[var(--accent)]" checked={st.history_skip_phone} onChange={(e) => onChange({ history_skip_phone: e.target.checked })} />
        <span className="text-ink">Ignorer les visites faites sur mon téléphone</span>
      </label>
    </div>
  );
}

/** Ce que la languette regarde : réglé à l'étape qui la présente et dans Réglages. */
export function PageWatchRows({ settings: st, onChange }: { settings: Settings; onChange: (body: Partial<Settings>) => void }) {
  return (
    <div className="card overflow-hidden px-4">
      <div className="divide-y divide-line">
        <SwitchRow label="Repérer l'article ouvert dans mon navigateur" hint="La languette s'allume devant un article de presse. L'adresse est lue sur ce PC et n'est gardée que si tu enregistres." checked={st.detect_page} onChange={(v) => onChange({ detect_page: v, ...(v ? {} : { page_nudge: false }) })} />
        {st.detect_page && <SwitchRow label="Me proposer d'enregistrer l'article" hint="La première fois que tu restes quelques secondes sur un article, la languette s'ouvre seule, sans prendre la main, puis se referme." checked={st.page_nudge} onChange={(v) => onChange({ page_nudge: v })} />}
      </div>
    </div>
  );
}

/** Rappel affiché sous les conditions : ce que l'auteur reçoit (rien). */
export function NoServer() {
  return (
    <p className="flex items-start gap-2 text-[12.5px] leading-snug text-ink-2">
      <Lock size={14} className="mt-0.5 shrink-0 text-ink-3" />
      openMedia n'a pas de serveur : l'auteur ne reçoit rien, ni compte ni mesure d'audience. Tes données restent dans %APPDATA%\openMedia, sur ce PC, en clair.
    </p>
  );
}

/** Prévient la languette d'un changement de ses réglages (elle ne relit pas les réglages seule). */
export function syncLanguette(body: Partial<Settings>) {
  if (!inTauri) return;
  if ("detect_page" in body) void invoke("set_page_watch", { enabled: !!body.detect_page });
  if ("page_nudge" in body) void emitTo("bulle", "page-nudge", !!body.page_nudge);
}
