import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import type { ModelCatalog, ModelRow } from "../lib/types";
import { inputClass } from "./ui";

export function useModelCatalog(live = false) {
  return useQuery({ queryKey: ["models", live], queryFn: () => api<ModelCatalog>(`/models${live ? "?live=1" : ""}`), staleTime: 5 * 60_000 });
}

/** « 2 $ / 10 $ » : entrée et sortie, par million de tokens. */
export function priceLabel(m: ModelRow): string {
  if (!m.price) return "prix inconnu";
  if (m.price[0] === 0 && m.price[1] === 0) return "gratuit";
  const n = (v: number) => (v >= 1 ? v.toFixed(v % 1 ? 2 : 0) : v.toFixed(2)).replace(".", ",");
  return `${n(m.price[0])} $ / ${n(m.price[1])} $`;
}

/** Choix d'un modèle, regroupé par fournisseur : seuls les fournisseurs utilisables (clé,
 * Claude Code, ou Ollama et LM Studio quand ils répondent) sont proposés, plus le modèle en
 * place s'il ne l'est plus. */
export function ModelSelect({ value, onChange, defaultLabel, className = "" }: { value: string; onChange: (v: string) => void; defaultLabel?: string; className?: string }) {
  const q = useModelCatalog(true);
  const catalog = q.data;
  if (!catalog) {
    return (
      <select className={`${inputClass} ${className}`} value={value} disabled>
        <option value={value}>{value || defaultLabel}</option>
      </select>
    );
  }
  const current = catalog.models.find((m) => m.id === value);
  return (
    <select className={`${inputClass} ${className}`} value={value} onChange={(e) => onChange(e.target.value)}>
      {defaultLabel !== undefined && <option value="">{defaultLabel}</option>}
      {value && !current && <option value={value}>{value}</option>}
      {catalog.providers
        .filter((p) => p.usable || current?.provider === p.id)
        .map((p) => {
          const rows = catalog.models.filter((m) => m.provider === p.id && (m.usable || m.id === value));
          const featured = rows.filter((m) => m.featured);
          const others = rows.filter((m) => !m.featured).sort((a, b) => a.label.localeCompare(b.label));
          return [
            <optgroup key={p.id} label={`${p.id === "anthropic" ? "Claude (Anthropic)" : p.label}${p.region ? ` · ${p.region}` : ""}${p.usable ? "" : " · indisponible"}`}>
              {featured.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                  {m.tier_label ? ` · ${m.tier_label}` : ""} · {priceLabel(m)}
                </option>
              ))}
            </optgroup>,
            others.length > 0 && (
              <optgroup key={`${p.id}-autres`} label={`${p.label} : autres modèles`}>
                {others.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                    {m.tier_label ? ` · ${m.tier_label}` : ""} · {priceLabel(m)}
                  </option>
                ))}
              </optgroup>
            ),
          ];
        })}
    </select>
  );
}
