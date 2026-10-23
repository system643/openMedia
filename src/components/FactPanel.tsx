import { euros, relative } from "../lib/format";
import type { Factcheck } from "../lib/types";
import { openLink, SourceChip, StatusLabel } from "./Facts";

export type { Factcheck };

/** « claude-haiku-5-5 » → « Haiku ». */
export function modelName(model: string): string {
  const m = /claude-(\w+)/.exec(model);
  return m ? m[1][0].toUpperCase() + m[1].slice(1) : model;
}

/** Le coût d'une vérification : un équivalent quand l'abonnement Claude Code l'a couverte. */
export function cost(fc: Factcheck): string {
  const v = fc.cost_usd ?? 0;
  const text = v < 0.001 ? "moins de 0,001 $" : euros(v);
  return fc.subscription ? `${text} (abonnement)` : text;
}

/** Les autres médias à lire, pour s'informer sans abonnement : ceux dont le texte a été lu
 * sont marqués « accès libre » ; des autres, seul le titre est connu. Affiché quand l'article
 * est réservé aux abonnés, ou quand au moins un média est en accès libre. */
export function Reads({ fc, compact = false }: { fc: Factcheck; compact?: boolean }) {
  const reads = fc.reads ?? [];
  if (!reads.length || !(fc.paywalled || reads.some((r) => r.open))) return null;
  return (
    <div className={compact ? "mt-3" : "mt-4"}>
      <p className={`font-semibold ${compact ? "text-[11.5px] text-ink-2" : "text-[12.5px] text-ink"}`}>À lire ailleurs</p>
      <ul className="mt-1 space-y-1">
        {reads.map((r) => (
          <li key={r.url}>
            <button onClick={() => openLink(r.url)} title={r.title} className={`block w-full text-left text-ink hover:text-accent ${compact ? "truncate text-[12px]" : "text-[13px]"}`}>
              <span className="font-medium text-accent">{r.name}</span>
              {r.open && <span className="ml-1.5 rounded-full bg-ok/15 px-1.5 py-px text-[10.5px] font-medium text-ok">accès libre</span>} · {r.title}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Les affirmations d'un article, recoupées avec d'autres médias. */
export function FactPanel({ fc }: { fc: Factcheck }) {
  const sources = new Map((fc.sources ?? []).map((s) => [s.ref, s]));
  if (fc.status !== "ok") return <p className="mt-3 rounded-lg bg-fill px-3 py-2 text-[13px] text-ink-2">{fc.message}</p>;
  return (
    <div className="mt-4">
      <p className="text-[12px] text-ink-2">
        {fc.claims.length} affirmation(s) recoupée(s) avec {fc.others ?? 0} autre(s) article(s) · vérifié {relative(fc.checked_at)}
        {fc.model ? ` · ${modelName(fc.model)}` : ""}
        {fc.cost_usd ? ` · ${cost(fc)}` : ""}
      </p>
      {fc.message && <p className="mt-2 text-[12.5px] text-ink-2">{fc.message}</p>}
      <ul className="mt-3 space-y-4">
        {fc.claims.map((c, i) => (
          <li key={i} className="rail" data-status={c.status}>
            <p className="text-[13.5px] leading-[1.5] text-ink">{c.text}</p>
            <div className="mt-1 flex flex-wrap items-center gap-1.5">
              <StatusLabel status={c.status} />
              {c.refs.slice(0, 4).map((x) => (
                <SourceChip key={x} refId={x} source={sources.get(x)} />
              ))}
            </div>
            <p className="mt-1 text-[12px] text-ink-2">
              {c.explanation}
              {c.note ? ` — ${c.note}` : ""}
            </p>
          </li>
        ))}
      </ul>
      <Reads fc={fc} />
    </div>
  );
}
