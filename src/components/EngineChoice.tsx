import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Cloud, Cpu, KeyRound, RefreshCw, Terminal } from "lucide-react";
import { useState, type ReactNode } from "react";
import { api } from "../lib/api";
import { POLICIES } from "../lib/privacy";
import type { LocalProvider, LocalServers, ProviderId, Settings } from "../lib/types";
import { Button, Segmented, Spinner, inputClass } from "./ui";

/** Un moteur est prêt : l'IA de ce PC si c'est elle qu'on a choisie (jamais de repli en ligne),
 *  sinon Claude (clé ou Claude Code), la clé d'un autre fournisseur, ou un rôle confié à l'IA
 *  de ce PC (`ollama:…`). */
export function engineReady(st: Settings | undefined): boolean {
  if (!st) return false;
  if (st.engine === "local") return st.engine_active === "local";
  return !!st.engine_active || Object.values(st.providers ?? {}).some((p) => p.has_key) || Object.values(st.models ?? {}).some((m) => /^(ollama|lmstudio):/.test(m));
}

const BUDGETS = ["5", "15", "30"];

/** Choisir comment les agents accèdent à une IA : sur ce PC, par une clé API, ou par Claude Code. */
export function EngineChoice({ settings: st }: { settings: Settings }) {
  const qc = useQueryClient();
  const done = (data: Settings) => {
    qc.setQueryData(["settings"], data);
    void qc.invalidateQueries({ queryKey: ["models"] });
  };
  const patch = useMutation({ mutationFn: (body: Partial<Settings>) => api<Settings>("/settings", { method: "PATCH", body }), onSuccess: done });
  const keyed = Object.entries(st.providers ?? {}).filter(([, p]) => p.has_key) as [ProviderId, Settings["providers"][ProviderId]][];
  const onlineReady = st.engine !== "local" && engineReady(st);
  const cc = st.claude_code ?? { found: false, path: null, version: null };
  return (
    <div className="grid gap-3">
      <LocalCard settings={st} onPatch={(b) => patch.mutate(b)} busy={patch.isPending} />
      <EngineCard
        icon={<KeyRound size={17} />}
        title="Une clé API"
        badge="En ligne · facturé à l'usage"
        active={onlineReady && st.engine_active !== "claude_code" && keyed.length > 0}
      >
        <p>Anthropic, OpenAI, DeepSeek, Gemini, Mistral, Kimi, GLM, Qwen, Grok ou OpenRouter : le fournisseur est reconnu tout seul. La clé reste dans le Gestionnaire d'identifiants de Windows et n'est envoyée qu'à son fournisseur. Petit budget : DeepSeek coûte 3 à 5 fois moins que Claude Sonnet, mais traite tes articles en Chine.</p>
        <KeyForm engine={st.engine} onSaved={done} />
        {keyed.length > 0 && (
          <p className="mt-2 text-ok">
            <Check size={13} className="mr-1 inline" />
            {keyed.map(([, p]) => p.label).join(", ")} : clé enregistrée.
          </p>
        )}
        {st.providers?.gemini?.has_key && <p className="mt-2 text-warn">Avec une clé Gemini gratuite (sans facturation), Google peut utiliser tes envois pour entraîner ses modèles et les faire relire par des personnes.</p>}
        {st.providers?.openrouter?.has_key && <p className="mt-2 text-ink-2">OpenRouter transmet tes envois à d'autres fournisseurs : vérifie dans ton compte OpenRouter qu'ils n'entraînent pas leurs modèles avec.</p>}
        {keyed.some(([, p]) => p.region.includes("Chine")) && (
          <p className="mt-2 text-warn">
            {keyed.filter(([, p]) => p.region.includes("Chine")).map(([, p]) => p.label).join(", ")} : tes articles sont traités en Chine. Leur filtre de contenu peut refuser des sujets politiques sensibles ; openMedia passe alors par un autre de tes fournisseurs, s'il y en a un.
          </p>
        )}
        {keyed.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <span className="text-ink">Plafond mensuel</span>
            <Segmented
              label="Plafond mensuel en dollars"
              value={BUDGETS.includes(String(st.monthly_budget_usd)) ? String(st.monthly_budget_usd) : ""}
              onChange={(v) => patch.mutate({ monthly_budget_usd: Number(v) })}
              options={BUDGETS.map((b) => ({ value: b, label: `${b} $` }))}
            />
            <span className="text-ink-2">Au-delà, les passages automatiques s'arrêtent jusqu'au mois suivant.</span>
          </div>
        )}
      </EngineCard>
      <EngineCard icon={<Terminal size={17} />} title="Claude Code (facultatif, abonnement Claude)" badge="En ligne · Anthropic" active={onlineReady && st.engine_active === "claude_code"}>
        {cc.found ? (
          <>
            <p>Installé sur ce PC (version {cc.version ?? "inconnue"}). Pas de facture en plus, mais les passages comptent dans les limites de ton abonnement : tu pourrais les atteindre plus vite dans tes autres usages de Claude.</p>
            <p className="mt-1.5">
              Pour ton usage personnel : openMedia lance le Claude Code officiel, sans le modifier, avec le compte auquel tu t'y es connecté toi-même ; il ne lit ni ne garde tes identifiants. Ne le partage pas avec d'autres personnes, et pour un usage intensif, préfère une clé API.
            </p>
            <p className="mt-1.5">
              Ce que tu envoies suit les réglages de confidentialité de ton compte Claude :{" "}
              <a className="text-accent hover:underline" href={POLICIES.claude_code.url} target="_blank" rel="noreferrer">
                vérifie l'option d'entraînement
              </a>
              .
            </p>
            {st.engine_active !== "claude_code" && (
              <Button className="mt-3" busy={patch.isPending} onClick={() => patch.mutate({ engine: "claude_code" })}>
                Utiliser Claude Code
              </Button>
            )}
          </>
        ) : (
          <p>Pas trouvé sur ce PC, et ce n'est pas nécessaire : une clé API ou l'IA de ce PC suffisent. Si tu as un abonnement Claude et veux t'en servir : « npm install -g @anthropic-ai/claude-code », puis lance « claude » une fois pour te connecter.</p>
        )}
      </EngineCard>
      {patch.error && <p className="text-[13px] text-deny">{patch.error.message}</p>}
    </div>
  );
}

/** L'IA de ce PC seule, pour Réglages › Moteur IA. */
export function LocalEngine({ settings: st }: { settings: Settings }) {
  const qc = useQueryClient();
  const patch = useMutation({
    mutationFn: (body: Partial<Settings>) => api<Settings>("/settings", { method: "PATCH", body }),
    onSuccess: (data) => {
      qc.setQueryData(["settings"], data);
      void qc.invalidateQueries({ queryKey: ["models"] });
    },
  });
  return <LocalCard settings={st} onPatch={(b) => patch.mutate(b)} busy={patch.isPending} />;
}

function EngineCard({ icon, title, badge, active, children }: { icon: ReactNode; title: string; badge: string; active: boolean; children: ReactNode }) {
  return (
    <section className={`rounded-2xl border p-4 transition-colors ${active ? "border-ok bg-[color-mix(in_srgb,var(--ok)_7%,transparent)]" : "border-line-strong bg-surface"}`}>
      <div className="flex items-center gap-2.5">
        <span className={`grid size-8 shrink-0 place-items-center rounded-lg ${active ? "bg-ok text-white" : "bg-fill text-ink-2"}`}>{active ? <Check size={16} /> : icon}</span>
        <h3 className="flex-1 text-[15px] font-semibold text-ink">{title}</h3>
        <span className="rounded-full bg-fill px-2.5 py-0.5 text-[11.5px] text-ink-2">{badge}</span>
      </div>
      <div className="mt-2 pl-[42px] text-[13px] leading-snug text-ink-2">{children}</div>
    </section>
  );
}

type KeySaved = Settings & { detected: ProviderId; verified: boolean; warning: string };

function KeyForm({ engine, onSaved }: { engine: Settings["engine"]; onSaved: (s: Settings) => void }) {
  const [key, setKey] = useState("");
  const [saved, setSaved] = useState<{ label: string; warning: string; leftLocal: boolean } | null>(null);
  const save = useMutation({
    mutationFn: async () => {
      const st = await api<KeySaved>("/settings/api-key", { method: "PUT", body: { key: key.trim() } });
      // Une clé en ligne choisie ici : on quitte le mode « tout sur ce PC » (l'IA de ce PC reste
      // disponible rôle par rôle, dans Réglages › Moteur IA).
      const next = engine === "local" ? await api<Settings>("/settings", { method: "PATCH", body: { engine: "auto" } }) : st;
      return { st: next, label: st.providers[st.detected]?.label ?? st.detected, warning: st.warning, leftLocal: engine === "local" };
    },
    onSuccess: ({ st, ...info }) => {
      setKey("");
      setSaved(info);
      onSaved(st);
    },
    onError: () => setSaved(null),
  });
  return (
    <form
      className="mt-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (key.trim()) save.mutate();
      }}
    >
      <div className="flex gap-2">
        <input className={`${inputClass} bg-surface`} type="password" aria-label="Clé API" placeholder="Colle ta clé" value={key} onChange={(e) => setKey(e.target.value)} />
        <Button type="submit" busy={save.isPending} disabled={!key.trim()}>
          Enregistrer
        </Button>
      </div>
      {save.error && <p className="mt-1.5 text-deny">{save.error.message}</p>}
      {saved?.warning && <p className="mt-1.5 text-warn">{saved.warning}</p>}
      {saved?.leftLocal && <p className="mt-1.5 text-ink-2">{saved.label} servira désormais tes sujets. L'IA de ce PC reste à ta disposition : dans Réglages › Moteur IA, tu peux lui confier un rôle (le tri, par exemple).</p>}
    </form>
  );
}

function LocalCard({ settings: st, onPatch, busy }: { settings: Settings; onPatch: (b: Partial<Settings>) => void; busy: boolean }) {
  const servers = useQuery({ queryKey: ["local-servers"], queryFn: () => api<LocalServers>("/settings/local"), staleTime: 10_000 });
  const found = servers.data ? (Object.entries(servers.data) as [LocalProvider, LocalServers[LocalProvider]][]).filter(([, s]) => s.found) : [];
  const active = st.engine === "local" && st.engine_active === "local";
  const [provider, setProvider] = useState<LocalProvider | null>(null);
  const current = provider ?? (found.some(([p]) => p === st.local_provider) ? st.local_provider : found[0]?.[0]);
  const models = current ? servers.data?.[current].models ?? [] : [];
  const chosen = st.engine === "local" && st.local_provider === current ? st.local_model : "";
  const ctx = models.find((m) => m.id === chosen)?.context;
  return (
    <EngineCard icon={<Cpu size={17} />} title="L'IA sur ce PC (Ollama ou LM Studio)" badge="Analyse sur ton PC · gratuit" active={active}>
      <p>L'analyse se fait sur ton ordinateur : aucun service d'IA ne reçoit tes sujets. C'est plus lent, et un modèle local se trompe davantage qu'un grand modèle en ligne : vise au moins 14 milliards de paramètres (par exemple Qwen3 14B ou Mistral Small).</p>
      {servers.isLoading ? (
        <p className="mt-3 inline-flex items-center gap-2">
          <Spinner size={13} /> Recherche d'Ollama et de LM Studio…
        </p>
      ) : found.length === 0 ? (
        <div className="mt-3 rounded-xl bg-fill/60 p-3">
          <p className="text-ink">Ni Ollama ni LM Studio ne répond sur ce PC.</p>
          <ol className="mt-1.5 list-decimal space-y-0.5 pl-4">
            <li>
              Installe <a className="text-accent hover:underline" href="https://ollama.com/download" target="_blank" rel="noreferrer">Ollama</a> ou{" "}
              <a className="text-accent hover:underline" href="https://lmstudio.ai" target="_blank" rel="noreferrer">LM Studio</a>.
            </li>
            <li>
              Télécharge un modèle, par exemple <code className="rounded bg-fill px-1">ollama pull qwen3:14b</code>, ou depuis LM Studio (démarre alors son serveur local).
            </li>
            <li>Reviens ici et clique sur « Détecter à nouveau ».</li>
          </ol>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {found.length > 1 && <Segmented label="Serveur local" value={current!} onChange={setProvider} options={found.map(([p, s]) => ({ value: p, label: s.label }))} />}
          {models.length === 0 ? (
            <span className="text-warn">{servers.data![current!].label} répond, mais aucun modèle n'est installé.</span>
          ) : (
            <select
              className={`${inputClass} w-64 bg-surface`}
              aria-label="Modèle local"
              value={chosen}
              disabled={busy}
              onChange={(e) => e.target.value && onPatch({ engine: "local", local_provider: current, local_model: e.target.value })}
            >
              <option value="">Choisis un modèle…</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.id}
                  {m.size ? ` · ${m.size}` : ""}
                </option>
              ))}
            </select>
          )}
        </div>
      )}
      {current === "lmstudio" && ctx != null && ctx < 32768 && <p className="mt-2 text-warn">Ce modèle est chargé avec un contexte de {ctx.toLocaleString("fr-FR")} tokens : règle-le sur 32 768 au moins dans LM Studio, sinon les fiches seront tronquées.</p>}
      {st.engine !== "local" && found.some(([, s]) => s.models.length > 0) && (
        <p className="mt-2 text-ink-2">Choisir un modèle ici fait tout passer par ce PC, sans rien en ligne. Pour mélanger (par exemple le tri sur ce PC et les fiches chez ton fournisseur en ligne), choisis plutôt ses modèles rôle par rôle, dans Réglages › Moteur IA.</p>
      )}
      {st.engine === "local" && !active && !servers.isLoading && <p className="mt-2 text-warn">L'IA de ce PC est choisie, mais {st.local?.found ? "le modèle choisi est introuvable" : "elle ne répond pas"} : aucun passage ne peut tourner, et rien ne part en ligne à sa place.</p>}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button size="sm" icon={<RefreshCw size={12} />} busy={servers.isFetching} onClick={() => void servers.refetch()}>
          Détecter à nouveau
        </Button>
        {st.engine === "local" && (
          <Button size="sm" variant="ghost" icon={<Cloud size={12} />} onClick={() => onPatch({ engine: "auto" })}>
            Utiliser plutôt une IA en ligne
          </Button>
        )}
      </div>
    </EngineCard>
  );
}
