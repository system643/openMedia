import { KIND_LABEL } from "../lib/format";
import type { Coverage } from "../lib/types";

// Une teinte par famille de sources ; les sources primaires et les agences, les plus
// précieuses pour vérifier, sont les plus franches.
const KIND_COLOR: Record<string, string> = {
  agence: "#2f5bea",
  institutionnel: "#1e9e73",
  national: "#7d8bb3",
  international: "#4fa3c7",
  regional: "#a7b3cf",
  specialise: "#b58fd6",
  blog: "#d3a35f",
  reseau_social: "#e0c7a8",
  recherche: "#0a9396",
  unknown: "#c9ccd3",
};

const OWNER_COLOR: Record<string, string> = {
  milliardaire: "#c4553d",
  conglomerat: "#d39a4a",
  public: "#1e9e73",
  independant: "#2f5bea",
  cooperative: "#7c5ce0",
  inconnu: "#c9ccd3",
};

const OWNER_LABEL: Record<string, string> = {
  milliardaire: "Grandes fortunes",
  conglomerat: "Groupes industriels ou financiers",
  public: "Public",
  independant: "Indépendants",
  cooperative: "Coopératives, fondations",
  inconnu: "Non qualifiés",
};

const COUNTRY: Record<string, string> = {
  FR: "France", GB: "Royaume-Uni", US: "États-Unis", DE: "Allemagne", BE: "Belgique", CH: "Suisse", CA: "Canada", ES: "Espagne", IT: "Italie",
  QA: "Qatar", IN: "Inde", JP: "Japon", IL: "Israël", UA: "Ukraine", EU: "Union européenne", INT: "International", "??": "Pays inconnu",
};

/** Le spectre des sources : d'où vient l'information de cette fiche, et ce qui manque. */
export function Spectrum({ coverage }: { coverage: Coverage }) {
  const kinds = Object.entries(coverage.kinds ?? {});
  const total = kinds.reduce((n, [, c]) => n + c, 0) || 1;
  const countries = Object.entries(coverage.countries ?? {});
  return (
    <div>
      <p className="text-[14px] text-ink-2">
        {coverage.articles} article{coverage.articles > 1 ? "s" : ""} cité{coverage.articles > 1 ? "s" : ""}, {coverage.independent} source{coverage.independent > 1 ? "s" : ""} indépendante{coverage.independent > 1 ? "s" : ""}{" "}
        <span className="text-ink-3">(une dépêche reprise ou un même groupe de presse ne comptent qu'une fois)</span>
      </p>
      <div className="mt-3 flex h-3 overflow-hidden rounded-full" role="img" aria-label="Répartition des sources par famille">
        {kinds.map(([k, c]) => (
          <div key={k} style={{ width: `${(100 * c) / total}%`, background: KIND_COLOR[k] ?? KIND_COLOR.unknown }} title={`${KIND_LABEL[k] ?? k} : ${c}`} />
        ))}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-ink-2">
        {kinds.map(([k, c]) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ background: KIND_COLOR[k] ?? KIND_COLOR.unknown }} />
            {KIND_LABEL[k] ?? k} {c}
          </span>
        ))}
      </div>
      <OwnerBar coverage={coverage} />
      {countries.length > 0 && <p className="mt-3 text-[12.5px] text-ink-3">{countries.map(([c, n]) => `${COUNTRY[c] ?? c} ${n}`).join(", ")}</p>}
      {coverage.alerts?.length > 0 && (
        <ul className="mt-4 space-y-1.5">
          {coverage.alerts.map((a) => (
            <li key={a} className="rail text-[13.5px] text-ink" data-status="non_confirme">
              {a}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** Qui possède les médias de cette fiche : le contrôle par de grandes fortunes est nommé. */
function OwnerBar({ coverage }: { coverage: Coverage }) {
  const types = Object.entries(coverage.owner_types ?? {});
  if (!types.length) return null;
  const total = types.reduce((n, [, c]) => n + c, 0) || 1;
  const controllers = Object.keys(coverage.controllers ?? {});
  return (
    <div className="mt-5">
      <p className="text-[13px] font-medium text-ink">Qui possède cette couverture</p>
      <div className="mt-2 flex h-3 overflow-hidden rounded-full" role="img" aria-label="Répartition par type de propriétaire">
        {types.map(([k, c]) => (
          <div key={k} style={{ width: `${(100 * c) / total}%`, background: OWNER_COLOR[k] ?? OWNER_COLOR.inconnu }} title={`${OWNER_LABEL[k] ?? k} : ${c}`} />
        ))}
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-ink-2">
        {types.map(([k, c]) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-full" style={{ background: OWNER_COLOR[k] ?? OWNER_COLOR.inconnu }} />
            {OWNER_LABEL[k] ?? k} {c}
          </span>
        ))}
      </div>
      {controllers.length > 0 && <p className="mt-2 text-[12.5px] text-ink-3">Contrôlés par : {controllers.join(", ")}.</p>}
    </div>
  );
}
