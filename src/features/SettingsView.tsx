import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { writeText } from "@tauri-apps/plugin-clipboard-manager";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import { disable, enable, isEnabled } from "@tauri-apps/plugin-autostart";
import { useEffect, useMemo, useState } from "react";
import { Cpu, Gauge, Lock, Newspaper, ShieldCheck, SlidersHorizontal, Smartphone, Sparkles } from "lucide-react";
import { CadencePicker } from "../components/CadencePicker";
import { everyLabel } from "../components/RhythmAdvice";
import { ModelSelect, useModelCatalog } from "../components/ModelSelect";
import { LocalEngine } from "../components/EngineChoice";
import { AiBanner, BrowserPicker, CoreFlows, NoServer, OptionsList, PageWatchRows, syncLanguette } from "../components/PrivacyControls";
import { Button, Group, Row, Segmented, Spinner, Toggle, inputClass, useCompactTitle } from "../components/ui";
import { api, inTauri } from "../lib/api";
import { usePageChrome } from "../lib/chrome";
import { nav, type SettingsSection } from "../lib/nav";
import { applyTheme, type ThemeChoice } from "../lib/theme";
import { KIND_LABEL, LOW_QUALITY, QUALITY_ORIGIN, euros, qualityLabel, tokens, upcoming } from "../lib/format";
import type { CostRun, CostsReport, EngineChoice, ProviderId, RecurringTopic, RhythmAdvice, Role, Settings, SourceRow } from "../lib/types";
import { cadenceLabel, dailyBaseline, generalCadence, perMonth, useCosts } from "../lib/usage";

const ROLES: { id: Role; label: string; hint: string }[] = [
  { id: "triage", label: "Tri des articles", hint: "Beaucoup d'articles, une tâche simple." },
  { id: "topic", label: "Agents de sujet", hint: "Recoupement et rédaction des fiches : ce rôle écrit les faits." },
  { id: "director", label: "Directeur de rédaction", hint: "Le brief quotidien, à partir de faits déjà recoupés." },
];

const VOICES = [
  { value: "fr-FR-DeniseNeural", label: "Denise" },
  { value: "fr-FR-HenriNeural", label: "Henri" },
  { value: "fr-FR-VivienneMultilingualNeural", label: "Vivienne" },
  { value: "fr-FR-RemyMultilingualNeural", label: "Rémy" },
];

const SECTIONS: { id: SettingsSection; label: string; icon: React.ReactNode }[] = [
  { id: "general", label: "Général", icon: <SlidersHorizontal size={15} /> },
  { id: "moteur", label: "Moteur IA", icon: <Cpu size={15} /> },
  { id: "confidentialite", label: "Confidentialité", icon: <Lock size={15} /> },
  { id: "rigueur", label: "Rigueur", icon: <ShieldCheck size={15} /> },
  { id: "sources", label: "Sources", icon: <Newspaper size={15} /> },
  { id: "telephone", label: "Téléphone", icon: <Smartphone size={15} /> },
  { id: "claude", label: "Serveur MCP", icon: <Sparkles size={15} /> },
  { id: "couts", label: "Consommation", icon: <Gauge size={15} /> },
];

/** Le titre de la catégorie ouverte : il passe dans la barre d'outils quand on défile. */
function SectionTitle({ children }: { children: React.ReactNode }) {
  const ref = useCompactTitle();
  return (
    <h2 ref={ref} className="title-md mb-5 px-1 text-ink">
      {children}
    </h2>
  );
}

export function SettingsView({ section = "general" }: { section?: SettingsSection }) {
  const qc = useQueryClient();
  const s = useQuery({ queryKey: ["settings"], queryFn: () => api<Settings>("/settings") });
  const patch = useMutation({
    mutationFn: (body: Partial<Settings>) => api<Settings>("/settings", { method: "PATCH", body }),
    onSuccess: (data, body) => {
      qc.setQueryData(["settings"], data);
      // Rythme ou plafond : les estimations et les prochains passages changent.
      if (["run_every_days", "run_weekdays", "run_hours", "monthly_token_cap"].some((k) => k in body)) {
        void qc.invalidateQueries({ queryKey: ["calendar"] });
        void qc.invalidateQueries({ queryKey: ["costs"] });
        void qc.invalidateQueries({ queryKey: ["topics"] });
      }
    },
  });
  const current = SECTIONS.find((x) => x.id === section) ?? SECTIONS[0];
  usePageChrome(`Réglages · ${current.label}`);
  if (!s.data) return <div className="grid h-[60vh] place-items-center"><Spinner /></div>;
  const st = s.data;
  const set = (body: Partial<Settings>) => {
    syncLanguette(body);
    patch.mutate(body);
  };

  return (
    <div className="flex justify-center gap-8 px-10 pb-24 pt-6">
      <nav aria-label="Catégories de réglages" className="sticky top-[76px] w-[190px] shrink-0 self-start">
        <h1 className="title-lg mb-4 px-2 text-ink">Réglages</h1>
        <ul className="space-y-px">
          {SECTIONS.map((x) => (
            <li key={x.id}>
              <button
                onClick={() => nav.go({ name: "settings", section: x.id })}
                aria-current={x.id === current.id ? "page" : undefined}
                className={`flex h-8 w-full items-center gap-2.5 rounded-lg px-2 text-left text-[13.5px] transition-colors ${x.id === current.id ? "bg-accent-fill text-white" : "text-ink hover:bg-fill"}`}
              >
                <span className={x.id === current.id ? "text-white" : "text-ink-2"}>{x.icon}</span>
                {x.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <div className="min-w-0 max-w-[640px] flex-1 pt-1">
        <SectionTitle key={current.id}>{current.label}</SectionTitle>

        {current.id === "general" && (
          <>
            <Group title="Apparence">
              <Row label="Thème" hint="Automatique suit le réglage de Windows.">
                <Segmented<ThemeChoice>
                  label="Thème"
                  value={st.theme ?? "system"}
                  onChange={(theme) => {
                    applyTheme(theme);
                    set({ theme });
                  }}
                  options={[
                    { value: "system", label: "Automatique" },
                    { value: "light", label: "Clair" },
                    { value: "dark", label: "Sombre" },
                  ]}
                />
              </Row>
            </Group>
            <Group title="Passages">
              <div className="px-4 py-3.5">
                <div className="mb-3">
                  <div className="text-[14px] text-ink">Rythme</div>
                  <div className="mt-0.5 text-[12px] leading-snug text-ink-2">
                    À chaque passage, les agents mettent leurs fiches à jour, puis le Directeur rédige le brief. Un passage manqué est rattrapé au démarrage. Chaque sujet peut avoir son propre rythme.
                  </div>
                </div>
                <CadencePicker value={generalCadence(st)} onChange={(c) => set({ run_every_days: c.every, run_weekdays: c.weekdays, run_hours: c.hours })} extra={<NextRunHint />} />
              </div>
              <Row label="Rythme adaptatif pour les nouveaux sujets" hint="Un sujet qui bouge peu s'espace tout seul (jusqu'à un jour sur quatre), et revient chaque jour dès qu'il repart. Tu es prévenu à chaque changement ; chaque sujet se règle aussi dans son onglet Agent.">
                <Toggle label="Rythme adaptatif pour les nouveaux sujets" checked={st.rhythm_auto_default ?? false} onChange={(v) => set({ rhythm_auto_default: v })} />
              </Row>
              <AutostartRow />
              <BulleRow />
              <Row label="Me notifier à partir de l'importance" hint="Une notification seulement quand une nouveauté atteint ce niveau (1 à 5).">
                <select className={`${inputClass} w-20`} value={st.notify_threshold} onChange={(e) => set({ notify_threshold: Number(e.target.value) })}>
                  {[1, 2, 3, 4, 5].map((n) => <option key={n}>{n}</option>)}
                </select>
              </Row>
            </Group>
            <Group title="Écoute">
              <Row label="Voix">
                <select className={`${inputClass} w-36`} value={st.voice} onChange={(e) => set({ voice: e.target.value })}>
                  {VOICES.map((v) => <option key={v.value} value={v.value}>{v.label}</option>)}
                </select>
              </Row>
            </Group>
            <Group title="La languette" footer="Ce que la languette regarde, et quand : voir aussi Réglages › Confidentialité.">
              <PageWatchRows settings={st} onChange={set} />
            </Group>
            <Group footer="Appuie sur ? n'importe où pour voir tous les raccourcis clavier.">
              <Row label="Rechercher et aller n'importe où">
                <kbd className="rounded-md bg-fill px-2 py-0.5 text-[12px] font-medium text-ink-2">Ctrl K</kbd>
              </Row>
              <Row label="Revoir le tutoriel" hint="Le fonctionnement d'openMedia, tes choix de données, la languette.">
                <Button size="sm" onClick={() => set({ onboarding_done: false, onboarding_step: 0 })}>
                  Revoir
                </Button>
              </Row>
            </Group>
          </>
        )}

        {current.id === "moteur" && (
          <>
            <section className="mb-7">
              <h3 className="mb-1.5 px-4 text-[13px] font-semibold text-ink-2">IA sur ce PC</h3>
              <LocalEngine settings={st} />
            </section>
            {st.engine === "local" ? (
              <Group footer="Avec l'IA de ce PC, les trois rôles (tri, agents de sujet, Directeur) utilisent le modèle choisi ci-dessus, et rien ne part chez un fournisseur en ligne. Pour revenir à une IA en ligne, clique sur « Utiliser plutôt une IA en ligne ».">
                <Row label="Modèle utilisé pour tout" hint="La recherche web complémentaire n'existe pas en local.">
                  <span className="text-[13px] text-ink">{st.local_model || "aucun"}</span>
                </Row>
              </Group>
            ) : (
              <ModelsGroup settings={st} onChange={set} />
            )}
            <ApiKeyGroup settings={st} />
            {st.engine !== "local" && <EngineGroup settings={st} onChange={set} />}
          </>
        )}

        {current.id === "confidentialite" && <PrivacyPanel settings={st} onChange={set} />}

        {current.id === "rigueur" && (
          <Group footer="Un fait n'est « confirmé » qu'avec deux sources indépendantes : une dépêche reprise ou un même groupe de presse ne comptent qu'une fois, et les réseaux sociaux jamais.">
            <Row label="Sources indépendantes visées" hint="En dessous, l'agent complète sa collecte par la recherche web de son modèle, chez les fournisseurs qui en ont une (Anthropic, OpenAI, Gemini, OpenRouter).">
              <select className={`${inputClass} w-20`} value={st.min_independent_sources} onChange={(e) => set({ min_independent_sources: Number(e.target.value) })}>
                {[2, 3, 4, 5, 6].map((n) => <option key={n}>{n}</option>)}
              </select>
            </Row>
            <Row label="Recherche complémentaire" hint="Environ 1 centime par recherche, seulement quand la couverture est trop mince.">
              <Toggle label="Recherche complémentaire" checked={st.claude_search_fallback} onChange={(v) => set({ claude_search_fallback: v })} />
            </Row>
          </Group>
        )}

        {current.id === "sources" && <SourcesGroup />}
        {current.id === "telephone" && <PhoneGroup settings={st} onChange={set} />}
        {current.id === "claude" && <ClaudeGroup />}

        {current.id === "couts" && <CostsPanel settings={st} onChange={set} />}
      </div>
    </div>
  );
}

const ENGINE_LABEL = { api: "l'API Claude", claude_code: "Claude Code", local: "l'IA de ce PC" } as const;

function EngineGroup({ settings: st, onChange }: { settings: Settings; onChange: (body: Partial<Settings>) => void }) {
  const cc = st.claude_code ?? { found: false, path: null, version: null };
  return (
    <Group title="Modèles Claude" footer="Avec Claude Code, la consommation relève de ton abonnement : elle est affichée au tarif de l'API, mais pas facturée en plus.">
      <Row
        label="Les modèles Claude passent par"
        hint={st.engine_active ? `En ce moment : ${ENGINE_LABEL[st.engine_active]}.` : "Ni clé Anthropic ni Claude Code : les rôles réglés sur Claude passent par un autre fournisseur, à gamme égale."}
      >
        <Segmented<EngineChoice>
          value={st.engine}
          onChange={(engine) => onChange({ engine })}
          options={[
            { value: "auto", label: "Automatique" },
            { value: "claude_code", label: "Claude Code" },
            { value: "api", label: "Clé API" },
          ]}
        />
      </Row>
      <Row label="Claude Code" hint={cc.found ? `Version ${cc.version ?? "inconnue"}, ${cc.path}. ${cc.lockdown === "partiel" ? `Verrouillage partiel : mets Claude Code à jour (options absentes : ${(cc.lockdown_missing ?? []).join(", ")}).` : "Verrouillé : les agents n'ont aucun outil et ne peuvent rien faire sur le PC."}` : "Introuvable. Installe-le, connecte-toi en lançant « claude » dans un terminal, ou indique son chemin."}>
        <span className={`text-[13px] ${cc.found ? "text-ok" : "text-ink-3"}`}>{cc.found ? "Détecté" : "Absent"}</span>
      </Row>
      <Row label="Appels Claude Code en parallèle" hint="Plus rapide, mais chaque appel est un processus : 3 convient à la plupart des PC.">
        <select className={`${inputClass} w-20`} value={st.claude_code_parallel} onChange={(e) => onChange({ claude_code_parallel: Number(e.target.value) })}>
          {[1, 2, 3, 4, 6, 8].map((n) => <option key={n}>{n}</option>)}
        </select>
      </Row>
      <div className="px-4 py-3">
        <input className={inputClass} placeholder="Chemin de claude.exe (vide : détection automatique)" defaultValue={st.claude_code_path} onBlur={(e) => e.target.value !== st.claude_code_path && onChange({ claude_code_path: e.target.value.trim() })} />
      </div>
    </Group>
  );
}


function AutostartRow() {
  const [on, setOn] = useState<boolean | null>(null);
  useEffect(() => {
    if (inTauri) isEnabled().then(setOn).catch(() => setOn(false));
  }, []);
  if (!inTauri) return null;
  return (
    <Row label="Lancer au démarrage de Windows" hint="openMedia attend discrètement dans la zone de notification pour faire son passage.">
      <Toggle
        checked={!!on}
        onChange={async (v) => {
          await (v ? enable() : disable());
          setOn(v);
        }}
      />
    </Row>
  );
}

function BulleRow() {
  const [on, setOn] = useState(true);
  useEffect(() => {
    if (inTauri) WebviewWindow.getByLabel("bulle").then((w) => w?.isVisible().then(setOn));
  }, []);
  if (!inTauri) return null;
  return (
    <Row label="Languette d'enregistrement" hint="Au bord droit de l'écran. Survole-la pour enregistrer l'article ouvert (ou Ctrl + Alt + S), glisse-y un lien, ou copie un lien puis Ctrl + Alt + N.">
      <Toggle
        checked={on}
        onChange={async (v) => {
          const w = await WebviewWindow.getByLabel("bulle");
          await (v ? w?.show() : w?.hide());
          setOn(v);
        }}
      />
    </Row>
  );
}

function ModelsGroup({ settings: st, onChange }: { settings: Settings; onChange: (body: Partial<Settings>) => void }) {
  const q = useModelCatalog();
  const [chosen, setChosen] = useState<ProviderId | null>(null);
  const catalog = q.data;
  if (!catalog) return null;
  const usable = catalog.providers.filter((p) => p.usable);
  const ofTopic = catalog.models.find((m) => m.id === st.models.topic)?.provider;
  const provider = chosen ?? (usable.some((p) => p.id === ofTopic) ? ofTopic! : usable[0]?.id);
  const presets = Object.entries(catalog.presets);
  const picks = (key: string) => (provider ? catalog.presets[key].by_provider[provider] : null);
  const active = presets.find(([key]) => ROLES.every((r) => picks(key)?.[r.id] === st.models[r.id]))?.[0] ?? "";
  const topicTier = catalog.models.find((m) => m.id === st.models.topic)?.tier;
  return (
    <Group
      title="Modèles"
      footer="Prix par million de tokens, en entrée puis en sortie. Un rôle réglé sur un fournisseur sans clé passe au modèle de même gamme d'un fournisseur disponible."
    >
      {provider && (
        <Row label="Gamme" hint="Remplit les trois rôles avec les modèles du fournisseur choisi.">
          <div className="flex items-center gap-2">
            <select className={`${inputClass} w-36`} value={provider} onChange={(e) => setChosen(e.target.value as ProviderId)} aria-label="Fournisseur">
              {usable.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.id === "anthropic" ? "Claude" : p.label}
                </option>
              ))}
            </select>
            <Segmented<string>
              label="Gamme"
              value={active}
              onChange={(key) => {
                const p = picks(key);
                if (p) onChange({ models: { triage: p.triage ?? st.models.triage, topic: p.topic ?? st.models.topic, director: p.director ?? st.models.director } });
              }}
              options={presets.map(([key, p]) => ({ value: key, label: p.label }))}
            />
          </div>
        </Row>
      )}
      {ROLES.map((r) => (
        <Row key={r.id} label={r.label} hint={r.hint}>
          <div className="flex items-center gap-2">
            <ModelSelect className="w-64" value={st.models[r.id]} onChange={(v) => onChange({ models: { ...st.models, [r.id]: v } })} />
            <CheckModel model={st.models[r.id]} />
          </div>
        </Row>
      ))}
      {catalog.providers.some((p) => p.id === "deepseek" && p.usable) && !ROLES.every((r) => st.models[r.id].startsWith("deepseek:")) && (
        <div className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-[12.5px] leading-snug text-ink-2">
          <span className="min-w-0 flex-1">Petit budget : DeepSeek Flash pour le tri, DeepSeek V4 Pro pour les sujets et le Directeur. Environ 3 à 5 fois moins cher que Claude Sonnet ; les articles sont traités en Chine.</span>
          <Button size="sm" onClick={() => onChange({ models: { triage: "deepseek:deepseek-flash", topic: "deepseek:deepseek-v4-pro", director: "deepseek:deepseek-v4-pro" } })}>
            Appliquer
          </Button>
        </div>
      )}
      {topicTier === "rapide" && (
        <div className="px-4 py-2.5 text-[12.5px] leading-snug text-warn">
          Un modèle rapide écrit et recoupe ici les faits des fiches : il se trompe plus souvent sur les nuances et les attributions. Pour la rigueur, garde au moins la gamme Équilibré pour ce rôle.
        </div>
      )}
    </Group>
  );
}

interface CheckResult {
  ok: boolean;
  faithful?: boolean;
  mode?: string;
  seconds?: number;
  cost_usd?: number;
  error?: string;
}

const MODE_LABEL: Record<string, string> = { schema: "schéma strict", schema_noref: "schéma strict", object: "objet JSON", prompt: "consigne seule" };

/** « Tester ce modèle » : un court appel structuré, pour savoir tout de suite s'il marche avec openMedia. */
function CheckModel({ model }: { model: string }) {
  const check = useMutation({ mutationFn: () => api<CheckResult>("/models/check", { method: "POST", body: { model } }) });
  const r = check.data;
  useEffect(() => check.reset(), [model]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="flex items-center gap-2">
      <Button size="sm" busy={check.isPending} onClick={() => check.mutate()} title="Envoie un court essai à ce modèle (coût : une fraction de centime)">
        Tester
      </Button>
      {r && (
        <span className={`max-w-56 text-[12px] leading-tight ${r.ok && r.faithful ? "text-ok" : "text-warn"}`} title={r.error}>
          {r.ok ? `${r.faithful ? "Marche" : "Répond, mais a mal lu le texte"} · ${MODE_LABEL[r.mode ?? ""] ?? r.mode} · ${r.seconds} s` : r.error}
        </span>
      )}
      {check.error && <span className="text-[12px] text-warn">{check.error.message}</span>}
    </div>
  );
}

function ProviderUrl({ id, settings: st }: { id: ProviderId; settings: Settings }) {
  const qc = useQueryClient();
  const p = st.providers[id];
  const save = useMutation({
    mutationFn: (url: string) => api<Settings>("/settings", { method: "PATCH", body: { provider_urls: { [id]: url } } }),
    onSuccess: (data) => {
      qc.setQueryData(["settings"], data);
      void qc.invalidateQueries({ queryKey: ["models"] });
    },
  });
  const placeholder = id === "qwen" ? "https://dashscope-intl.aliyuncs.com/compatible-mode/v1 (par défaut)" : "https://api.fournisseur.com/v1";
  return (
    <div className="px-4 pb-3">
      <input
        className={inputClass}
        aria-label={`Adresse de l'API ${p.label}`}
        placeholder={placeholder}
        defaultValue={p.url}
        onBlur={(e) => e.target.value.trim() !== p.url && save.mutate(e.target.value.trim())}
      />
      {save.error && <p className="mt-1 text-[12px] text-warn">{save.error.message}</p>}
      {id === "compatible" && <p className="mt-1 text-[12px] text-ink-3">Groq, Together, Fireworks, Cerebras, Perplexity… : colle l'adresse de leur API compatible OpenAI, puis leur clé ci-dessus en choisissant ce fournisseur. Leurs modèles apparaissent ensuite dans la liste des rôles.</p>}
    </div>
  );
}

function ApiKeyGroup({ settings: st }: { settings: Settings }) {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const [forProvider, setForProvider] = useState<ProviderId | "">("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const refresh = (data: Settings) => {
    qc.setQueryData(["settings"], data);
    void qc.invalidateQueries({ queryKey: ["models"] });
  };
  const save = useMutation({
    mutationFn: (k: string) => api<Settings & { detected: ProviderId; verified: boolean }>("/settings/api-key", { method: "PUT", body: { key: k, provider: forProvider || null } }),
    onSuccess: (data) => {
      refresh(data);
      setKey("");
      setMessage({ ok: true, text: `Clé ${data.providers[data.detected].label} reconnue${data.verified ? " et vérifiée" : " (vérification impossible pour le moment : le fournisseur ne répond pas, elle sera utilisée quand même)"}.` });
    },
    onError: (e: Error) => setMessage({ ok: false, text: e.message }),
  });
  const remove = useMutation({
    mutationFn: (provider: ProviderId) => api<Settings>(`/settings/api-key/${provider}`, { method: "DELETE" }),
    onSuccess: refresh,
  });
  const providers = Object.entries(st.providers ?? {}) as [ProviderId, Settings["providers"][ProviderId]][];
  return (
    <Group title="Clés API" footer="Le fournisseur est reconnu d'après la clé, puis vérifié ; si la clé ne suffit pas à le reconnaître, choisis-le dans la liste. Les clés sont rangées dans le Gestionnaire d'identifiants de Windows, jamais sur le disque.">
      <div className="flex gap-2 px-4 py-3">
        <div className="w-44 shrink-0">
          <select className={inputClass} aria-label="Fournisseur de la clé" value={forProvider} onChange={(e) => setForProvider(e.target.value as ProviderId | "")}>
            <option value="">Reconnu tout seul</option>
            {providers.map(([id, p]) => (
              <option key={id} value={id}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
        <input
          className={inputClass}
          type="password"
          placeholder="Colle une clé : Anthropic, OpenAI, DeepSeek, Gemini, Mistral, Kimi, GLM, Qwen, Grok, OpenRouter…"
          value={key}
          onChange={(e) => {
            setKey(e.target.value);
            setMessage(null);
          }}
          onKeyDown={(e) => e.key === "Enter" && key.trim() && save.mutate(key.trim())}
        />
        <Button variant="primary" disabled={!key.trim()} busy={save.isPending} onClick={() => save.mutate(key.trim())}>
          Ajouter
        </Button>
      </div>
      {message && <div className={`px-4 py-2.5 text-[12.5px] ${message.ok ? "text-ok" : "text-warn"}`}>{message.text}</div>}
      {providers.map(([id, p]) => (
        <div key={id}>
          <Row label={p.label} hint={`${p.has_key ? (p.search ? "Clé enregistrée." : "Clé enregistrée. Pas de recherche web complémentaire chez ce fournisseur.") : `Aucune clé (${p.hint}).`}${p.region ? ` Articles traités ${p.region}.` : ""}`}>
            {p.has_key ? (
              <Button variant="danger" busy={remove.isPending && remove.variables === id} onClick={() => remove.mutate(id)}>
                Retirer
              </Button>
            ) : (
              <span className="text-[13px] text-ink-3">Absente</span>
            )}
          </Row>
          {p.url_setting && <ProviderUrl id={id} settings={st} />}
        </div>
      ))}
    </Group>
  );
}

function NextRunHint() {
  const { data: c } = useCosts();
  return <>{c && ` · prochain passage ${upcoming(c.next_run)}`}</>;
}

function CostsPanel({ settings: st, onChange }: { settings: Settings; onChange: (body: Partial<Settings>) => void }) {
  const c = useCosts().data;
  const batchable = st.providers?.openai?.has_key || st.engine_active === "api";
  const capInput = (cap: number) => (cap ? String(cap / 1e6).replace(".", ",") : "");
  return (
    <>
      {c && (
        <Group
          title="Tokens"
          footer="Tokens lus (articles, consignes, fiches précédentes) et écrits (fiches, brief). La lecture depuis le cache coûte environ dix fois moins. Avec Claude Code, ce sont eux qui comptent dans les limites de ton abonnement."
        >
          <Row label="Ce mois-ci" hint={`${tokens(c.month.tokens.in)} lus, dont ${tokens(c.month.tokens.cached)} depuis le cache · ${tokens(c.month.tokens.out)} écrits · ${tokens(c.today.tokens)} aujourd'hui`}>
            <span className="tabular-nums font-medium text-ink">{tokens(c.month.tokens.total)}</span>
          </Row>
          <Row label="Fin de mois, au rythme réglé" hint={`Prochain passage : ${upcoming(c.next_run)}.`}>
            <span className={`tabular-nums ${c.month.cap && c.month.end_estimate > c.month.cap ? "text-warn" : "text-ink-2"}`}>≈ {tokens(c.month.end_estimate)}</span>
          </Row>
          <Row label="Plafond mensuel (millions de tokens)" hint="Au-delà, les passages planifiés s'arrêtent jusqu'au mois suivant ; « Tout mettre à jour » reste possible. Vide : aucun plafond.">
            <input
              key={st.monthly_token_cap}
              inputMode="decimal"
              aria-label="Plafond mensuel en millions de tokens"
              placeholder="aucun"
              className={`${inputClass} w-24 text-right tabular-nums`}
              defaultValue={capInput(st.monthly_token_cap)}
              onBlur={(e) => {
                const raw = e.target.value.trim().replace(",", ".");
                const v = raw ? Number(raw) : 0;
                if (Number.isFinite(v) && v >= 0 && Math.round(v * 1e6) !== st.monthly_token_cap) onChange({ monthly_token_cap: Math.round(v * 1e6) });
              }}
            />
          </Row>
          <DaysChart days={c.days} />
        </Group>
      )}

      {c && <FrequencyGroup report={c} settings={st} />}

      <Group title="En dollars" footer="« Facturé » : dépensé sur tes clés API, borné par le budget. « Abonnement » : ce que Claude Code a consommé, compté au tarif de l'API mais couvert par ton abonnement.">
        <Row label="Facturé ce mois-ci" hint="Les passages s'arrêtent d'eux-mêmes au-delà du budget.">
          <span className="tabular-nums text-ink">
            {euros(st.month_cost_usd)} sur {euros(st.monthly_budget_usd)}
          </span>
        </Row>
        <Row label="Abonnement Claude Code ce mois-ci" hint="Équivalent au tarif de l'API, non facturé en plus.">
          <span className="tabular-nums text-ink-2">{euros(st.month_subscription_usd ?? 0)}</span>
        </Row>
        {c && (
          <Row label="Projection sur 30 jours" hint="D'après les 7 derniers jours.">
            <span className="tabular-nums text-ink-2">
              {euros(c.projection.real)} facturé · {euros(c.projection.subscription)} abonnement
            </span>
          </Row>
        )}
        <Row label="Budget mensuel ($)">
          <input inputMode="decimal" className={`${inputClass} w-24 text-right tabular-nums`} defaultValue={st.monthly_budget_usd} onBlur={(e) => { const v = Number(e.target.value.replace(",", ".")); if (v > 0) onChange({ monthly_budget_usd: v }); }} />
        </Row>
      </Group>
      <Group footer="Le passage quotidien regroupe ses appels en lots : moitié prix, mais il peut prendre de quelques minutes à quelques heures. Les actions que tu lances toi-même restent immédiates.">
        <Row label="Mode Économie (−50 %)" hint={batchable ? "Clé Anthropic ou OpenAI : les appels de ces fournisseurs passent en lot." : "Demande une clé API Anthropic ou OpenAI : Claude Code et les autres fournisseurs ne passent pas par les lots."}>
          <Toggle label="Mode Économie" checked={st.economy_batch} onChange={(v) => onChange({ economy_batch: v })} />
        </Row>
      </Group>
      {c?.last_topic_run && <RunCost title="Dernier passage de sujet" run={c.last_topic_run} />}
      {c?.last_brief && <RunCost title="Dernier brief" run={c.last_brief} />}
    </>
  );
}

const dayFmt = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short" });
const dayOf = (day: string) => dayFmt.format(new Date(`${day}T12:00:00`));

/** Les 30 derniers jours, en barres empilées : sujets, brief, le reste. Les jours sans passage restent visibles. */
function DaysChart({ days }: { days: CostsReport["days"] }) {
  const total = (d: CostsReport["days"][number]) => d.topics + d.brief + d.other;
  const max = Math.max(1, ...days.map(total));
  return (
    <div className="px-4 pb-3 pt-4">
      <div className="mb-2 text-[13px] text-ink-2">30 derniers jours</div>
      <div className="flex h-28 items-end gap-[3px]" role="img" aria-label={`Tokens par jour sur 30 jours, au plus ${tokens(max)} en un jour`}>
        {days.map((d) => {
          const t = total(d);
          return (
            <div key={d.day} className="flex h-full flex-1 flex-col justify-end" title={`${dayOf(d.day)} : ${t ? `${tokens(t)} tokens (sujets ${tokens(d.topics)}, brief ${tokens(d.brief)}, autres ${tokens(d.other)})` : "aucun passage"}`}>
              {t ? (
                <div className="flex flex-col overflow-hidden rounded-t-[3px]" style={{ height: `${Math.max(3, (t / max) * 100)}%` }}>
                  <div className="basis-0 bg-ink-3/50" style={{ flexGrow: d.other }} />
                  <div className="basis-0 bg-[color-mix(in_srgb,var(--accent)_45%,transparent)]" style={{ flexGrow: d.brief }} />
                  <div className="basis-0 bg-accent" style={{ flexGrow: d.topics }} />
                </div>
              ) : (
                <div className="h-[2px] rounded-full bg-fill-strong" />
              )}
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 flex justify-between text-[11.5px] text-ink-3">
        <span>{dayOf(days[0].day)}</span>
        <span className="flex gap-3">
          <Legend className="bg-accent">Sujets</Legend>
          <Legend className="bg-[color-mix(in_srgb,var(--accent)_45%,transparent)]">Brief</Legend>
          <Legend className="bg-ink-3/50">Autres</Legend>
        </span>
        <span>Aujourd'hui</span>
      </div>
    </div>
  );
}

function Legend({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-1">
      <span className={`size-2 rounded-sm ${className}`} />
      {children}
    </span>
  );
}

/** Ce que consomme le rythme de tout le journal et de chaque sujet ; on le règle dans Général
 *  (rythme général) et dans l'onglet Agent de chaque sujet. */
function FrequencyGroup({ report: c, settings: st }: { report: CostsReport; settings: Settings }) {
  const qc = useQueryClient();
  const advice = useQuery({ queryKey: ["rhythm", "all"], queryFn: () => api<{ topic_id: number; name: string; auto: boolean; advice: RhythmAdvice }[]>("/rhythm") });
  const tips = new Map((advice.data ?? []).filter((r) => r.advice.direction && !r.advice.dismissed && r.advice.every).map((r) => [r.topic_id, r.advice]));
  const spacing = [...tips.entries()].filter(([, a]) => a.direction !== "resserrer");
  const apply = useMutation({
    mutationFn: async (items: [number, number][]) => {
      for (const [id, every] of items) await api(`/topics/${id}/rhythm/apply`, { method: "POST", body: { every } });
    },
    onSuccess: () => {
      for (const key of ["topics", "rhythm", "costs", "calendar"]) void qc.invalidateQueries({ queryKey: [key] });
    },
  });
  const spared = spacing.reduce((n, [, a]) => n + (a.simulation?.tokens_saved ?? 0), 0);
  const baseline = dailyBaseline(c);
  const saving = baseline > 0 ? Math.round((1 - c.projection.tokens / baseline) * 100) : 0;
  const runs = c.topics.reduce((n, t) => n + t.runs, 0);
  return (
    <Group
      title="Rythme des passages"
      footer={`Estimations d'après tes ${runs} passage${runs > 1 ? "s" : ""} de sujet et ${c.brief.runs} brief${c.brief.runs > 1 ? "s" : ""} des 30 derniers jours ; un sujet sans historique reprend la moyenne des autres. Les sujets d'un même rythme tournent ensemble, et le brief suit leurs passages. Les passages des jours d'échéance sont comptés. Un sujet en veille n'est contrôlé qu'une fois par semaine.`}
    >
      <Row label="Sur un mois complet, au rythme réglé" hint={saving > 0 ? `Soit ${saving} % de moins qu'un passage de tout chaque jour (≈ ${tokens(baseline)} par mois).` : saving < 0 ? `Soit ${-saving} % de plus qu'un passage de tout chaque jour (≈ ${tokens(baseline)} par mois).` : "Comme un passage de tout chaque jour."}>
        <span className="tabular-nums font-medium text-ink">≈ {tokens(c.projection.tokens)} / mois</span>
      </Row>
      {spacing.length > 0 && (
        <Row label={`${spacing.length} sujet${spacing.length > 1 ? "s bougent" : " bouge"} peu`} hint={`Les espacer selon le conseil de chacun${spared ? ` : ≈ ${tokens(spared)} tokens de moins par mois` : ""}. Les jours d'échéance gardent leur passage, et le pouls avance le passage d'un sujet qui s'emballe.`}>
          <Button size="sm" busy={apply.isPending} onClick={() => apply.mutate(spacing.map(([id, a]) => [id, a.every!]))}>
            Appliquer {spacing.length > 1 ? `les ${spacing.length} conseils` : "le conseil"}
          </Button>
        </Row>
      )}
      <Row label="Rythme général" hint={`${cadenceLabel(generalCadence(st))} · brief : ≈ ${tokens(c.brief.avg_tokens)} par passage, ${String(c.brief.per_month).replace(".", ",")} par mois.`}>
        <Button variant="ghost" size="sm" onClick={() => nav.go({ name: "settings", section: "general" })}>
          Régler
        </Button>
      </Row>
      {c.topics.map((t) => (
        <div key={t.topic_id} className="flex items-center justify-between gap-4 px-4 py-2.5">
          <div className="min-w-0">
            <div className="truncate text-[14px] text-ink">{t.name}</div>
            <div className="mt-0.5 text-[12px] leading-snug text-ink-2">
              {t.status === "sleeping"
                ? "En veille : un contrôle par semaine."
                : `${t.own_schedule ? cadenceLabel(t.schedule) : "Rythme général"}${t.follow_deadlines ? ", jours d'échéance compris" : ""} · ${perMonth(t.runs_per_month)} · ≈ ${tokens(t.avg_tokens)} par passage${t.estimated ? " (estimé)" : ""}${t.avg_cost != null ? ` · ${euros(t.avg_cost)}` : ""} · prochain : ${upcoming(t.next_run)}`}
            </div>
            {tips.get(t.topic_id) && <RhythmTip advice={tips.get(t.topic_id)!} busy={apply.isPending} onApply={(every) => apply.mutate([[t.topic_id, every]])} />}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <span className="text-[13px] tabular-nums text-ink-2">≈ {tokens(t.monthly_tokens)} / mois</span>
            {t.status === "active" && (
              <Button variant="ghost" size="sm" onClick={() => nav.go({ name: "topic", id: t.topic_id, tab: "agent" })}>
                Régler
              </Button>
            )}
          </div>
        </div>
      ))}
    </Group>
  );
}

/** Le conseil de rythme d'un sujet, en une ligne sous sa consommation. */
function RhythmTip({ advice: a, busy, onApply }: { advice: RhythmAdvice; busy: boolean; onApply: (every: number) => void }) {
  const runs = Math.abs(Math.round(a.simulation?.runs_saved ?? 0));
  const sign = a.direction === "resserrer" ? "+" : "−";
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-[12px]">
      <span className="rounded-md bg-accent-soft px-1.5 py-[1px] text-accent">
        Conseil : {everyLabel(a.every!)} · {sign}
        {runs} passage{runs > 1 ? "s" : ""}/mois
      </span>
      <button disabled={busy} onClick={() => onApply(a.every!)} className="font-medium text-accent hover:underline disabled:opacity-50">
        Appliquer
      </button>
    </div>
  );
}

function RunCost({ title, run }: { title: string; run: CostRun }) {
  const k = (n: number) => (n >= 1000 ? `${Math.round(n / 100) / 10} k` : `${n}`).replace(".", ",");
  const label = (id: string) => id.replace(/^[a-z]+:/, "").replace(/^claude-/, "").replace(/-(\d)-(\d)$/, " $1.$2");
  return (
    <Group title={`${title}${run.topic ? ` · ${run.topic}` : ""}`} footer={run.subscription_usd > 0 ? "Passé par Claude Code : couvert par l'abonnement." : undefined}>
      {run.stages.map((s) => (
        <Row key={s.stage} label={s.stage} hint={`${s.models.map(label).join(", ")} · ${s.calls} appel${s.calls > 1 ? "s" : ""} · ${k(s.in)} tokens lus, ${k(s.out)} écrits`}>
          <span className="tabular-nums text-ink-2">{s.unknown_price ? "prix inconnu" : euros(s.cost)}</span>
        </Row>
      ))}
      <Row label="Total" hint={`${tokens(run.stages.reduce((n, s) => n + s.in + s.out, 0))} tokens`}>
        <span className="tabular-nums font-medium text-ink">{euros(run.cost_usd)}</span>
      </Row>
    </Group>
  );
}

function SourcesGroup() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState("");
  const q = useQuery({ queryKey: ["sources"], queryFn: () => api<SourceRow[]>("/sources") });
  const patch = useMutation({
    mutationFn: ({ domain, body }: { domain: string; body: Partial<SourceRow> }) => api<SourceRow>(`/sources/${encodeURIComponent(domain)}`, { method: "PATCH", body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources"] }),
  });
  const rows = useMemo(() => {
    const f = filter.toLowerCase();
    return (q.data ?? []).filter((r) => !f || r.name.toLowerCase().includes(f) || r.domain.includes(f) || r.owner.toLowerCase().includes(f));
  }, [q.data, filter]);

  return (
    <Group title="Registre des sources">
      <div className="border-b border-line px-4 py-3">
        <p className="mb-2 text-[12.5px] text-ink-3">
          Le groupe de presse sert au recoupement : deux titres du même groupe ne comptent que pour une source. Les sites inconnus s'ajoutent ici au fil des passages ; qualifie-les ou bloque-les.
          La fiabilité vient d'une notation ouverte qui agrège six organismes (NewsGuard, Media Bias/Fact Check…), sinon d'une qualification par l'IA ; une source « faible » reste lisible mais ne confirme jamais un fait.
        </p>
        <input className={inputClass} placeholder="Chercher un média, un domaine ou un groupe" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <div className="scroll-area max-h-[420px]">
        <table className="w-full text-[13px]">
          <tbody>
            {rows.map((r) => (
              <tr key={r.domain} className="border-b border-line last:border-b-0">
                <td className="px-4 py-2">
                  <div className={r.blocked ? "text-ink-3 line-through" : "text-ink"}>{r.name}</div>
                  <div className="text-[12px] text-ink-3">{r.domain}</div>
                </td>
                <td className="px-2 py-2 text-ink-2">{KIND_LABEL[r.kind] ?? r.kind}</td>
                <td className="px-2 py-2 text-ink-2">{r.owner}</td>
                <td className="px-2 py-2 text-ink-3">{r.country}</td>
                <td className="px-2 py-2">
                  <select
                    className={`rounded-md bg-transparent text-[12.5px] ${r.quality != null && r.quality < LOW_QUALITY ? "text-warn" : "text-ink-2"}`}
                    value={r.quality_origin === "lecteur" ? String(r.quality) : ""}
                    onChange={(e) => patch.mutate({ domain: r.domain, body: { quality: e.target.value === "" ? null : Number(e.target.value) } })}
                    title={[r.quality != null ? `Fiabilité ${qualityLabel(r.quality, r.quality_origin)}` : "Pas encore notée", QUALITY_ORIGIN[r.quality_origin ?? ""], r.quality_note].filter(Boolean).join(" · ")}
                    aria-label={`Fiabilité de ${r.name}`}
                  >
                    <option value="">{r.quality_origin === "lecteur" ? "Auto" : `Auto : ${qualityLabel(r.quality, r.quality_origin)}`}</option>
                    <option value="0.8">Élevée</option>
                    <option value="0.5">Moyenne</option>
                    <option value="0.2">Faible</option>
                  </select>
                </td>
                <td className="px-4 py-2 text-right">
                  <button
                    onClick={() => patch.mutate({ domain: r.domain, body: { priority: !r.priority } })}
                    aria-pressed={!!r.priority}
                    title={r.priority ? "Source prioritaire : consultée en premier" : "Rendre prioritaire"}
                    className={`mr-3 text-[12.5px] ${r.priority ? "font-medium text-warn" : "text-ink-3 hover:text-ink"}`}
                  >
                    {r.priority ? "★ Prioritaire" : "☆"}
                  </button>
                  <button onClick={() => patch.mutate({ domain: r.domain, body: { blocked: !r.blocked } })} className="text-[12.5px] text-ink-2 hover:text-ink">
                    {r.blocked ? "Débloquer" : "Bloquer"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Group>
  );
}

/** Écouter et être prévenu sur son téléphone, sans compte ni cloud openMedia. */
function PhoneGroup({ settings: st, onChange }: { settings: Settings; onChange: (body: Partial<Settings>) => void }) {
  const phone = useQuery({ queryKey: ["phone", st.phone_listen], queryFn: () => api<{ enabled: boolean; url?: string; qr_svg?: string }>("/phone") });
  return (
    <Group title="Sur ton téléphone">
      <Row label="Écouter en podcast" hint="Un flux privé de tes briefs et fiches audio, servi sur ton réseau Wi-Fi uniquement. Windows peut demander d'autoriser le pare-feu.">
        <Toggle checked={st.phone_listen} onChange={(v) => onChange({ phone_listen: v })} />
      </Row>
      {st.phone_listen && phone.data?.url && (
        <div className="flex items-center gap-5 border-b border-line px-4 py-4">
          <div className="size-[132px] shrink-0 overflow-hidden rounded-lg bg-white p-1" dangerouslySetInnerHTML={{ __html: phone.data.qr_svg ?? "" }} />
          <div className="min-w-0 text-[13px] text-ink-2">
            <p>Scanne ce code avec ton téléphone connecté au même Wi-Fi, puis ajoute l'adresse dans ton application de podcasts (Apple Podcasts, Pocket Casts, AntennaPod…).</p>
            <p className="mt-2 break-all font-mono text-[12px] text-ink">{phone.data.url}</p>
          </div>
        </div>
      )}
      <Row label="Notifications sur le téléphone (ntfy)" hint="Installe l'app ntfy, abonne-toi à un nom de sujet difficile à deviner, et indique-le ici. Corrections, annonces et brief y sont envoyés.">
        <input className={`${inputClass} w-56`} placeholder="ex. : openmedia-7f3k9q" defaultValue={st.ntfy_topic} onBlur={(e) => e.target.value.trim() !== st.ntfy_topic && onChange({ ntfy_topic: e.target.value.trim() })} />
      </Row>
    </Group>
  );
}

/** Interroger son journal depuis Claude (Code ou Desktop) grâce au serveur MCP d'openMedia. */
function ClaudeGroup() {
  const info = useQuery({ queryKey: ["mcp"], queryFn: () => api<{ command: string; claude_code: boolean }>("/mcp") });
  const install = useMutation({ mutationFn: () => api<{ ok: boolean; message: string }>("/mcp/install", { method: "POST" }) });
  const [copied, setCopied] = useState(false);
  if (!info.data) return null;
  return (
    <Group title="Interroger ton journal depuis Claude">
      <div className="px-4 py-3 text-[13px] text-ink-2">
        <p>Claude peut lire tes fiches, avec le statut de vérification de chaque fait, tes corrections et tes annonces suivies. Par exemple : « Que dit mon journal sur le budget ? Qu'est-ce qui a été démenti cette semaine ? »</p>
        <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-paper px-3 py-2 font-mono text-[12px] text-ink">{info.data.command}</pre>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {info.data.claude_code && (
            <Button variant="primary" busy={install.isPending} onClick={() => install.mutate()}>
              Ajouter à Claude Code
            </Button>
          )}
          <Button
            onClick={async () => {
              if (inTauri) await writeText(info.data!.command);
              else await navigator.clipboard.writeText(info.data!.command);
              setCopied(true);
              setTimeout(() => setCopied(false), 2000);
            }}
          >
            {copied ? "Copiée" : "Copier la commande"}
          </Button>
          {install.isSuccess && <span className="text-[12.5px] text-ok">Ajouté. Relance Claude Code pour l'utiliser.</span>}
          {install.error && <span className="text-[12.5px] text-deny">{install.error.message}</span>}
        </div>
      </div>
    </Group>
  );
}

/** Ce qui part où, les options, et de quoi tout effacer ou retirer son accord. */
function PrivacyPanel({ settings: st, onChange }: { settings: Settings; onChange: (body: Partial<Settings>) => void }) {
  const qc = useQueryClient();
  const recurring = useQuery({ queryKey: ["recurring"], queryFn: () => api<{ topics: RecurringTopic[] }>("/readings/recurring"), enabled: st.history_auto });
  const titles = (recurring.data?.topics ?? []).flatMap((t) => t.titles.slice(0, 6)).slice(0, 40);
  const clear = useMutation({
    mutationFn: () => api<{ deleted: number }>("/readings", { method: "DELETE" }),
    onSuccess: () => {
      for (const key of ["readings", "recurring"]) void qc.invalidateQueries({ queryKey: [key] });
    },
  });
  const [confirm, setConfirm] = useState(false);
  return (
    <>
      <div className="mb-4">
        <AiBanner settings={st} />
      </div>
      <section className="mb-7">
        <h3 className="mb-1.5 px-4 text-[13px] font-semibold text-ink-2">Le suivi de tes sujets (nécessaire)</h3>
        <CoreFlows settings={st} onChange={onChange} />
      </section>
      <section className="mb-7">
        <h3 className="mb-1.5 px-4 text-[13px] font-semibold text-ink-2">Options</h3>
        <OptionsList settings={st} onChange={onChange} previous={false} browsers={<BrowserPicker settings={st} onChange={onChange} />} />
        {st.readings_ai && titles.length > 0 && (
          <details className="mt-2 px-4 text-[12.5px]">
            <summary className="cursor-pointer text-accent">Voir les titres de lectures que l'IA peut recevoir</summary>
            <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-ink-2">
              {titles.map((t, i) => (
                <li key={i}>{t}</li>
              ))}
            </ul>
          </details>
        )}
      </section>
      <Group title="La languette">
        <PageWatchRows settings={st} onChange={onChange} />
      </Group>
      <Group title="Effacer ou retirer" footer="Retirer ton accord arrête tout : aucun passage, aucun envoi, jusqu'à ce que tu acceptes à nouveau les conditions de fonctionnement.">
        <Row label="Effacer mes lectures" hint="Les lectures, les articles qu'elles avaient ajoutés (sauf ceux de tes sujets et enregistrements) et les sujets repérés dedans.">
          <Button variant="danger" size="sm" busy={clear.isPending} onClick={() => clear.mutate()}>
            {clear.data ? `${clear.data.deleted} effacée(s)` : "Effacer"}
          </Button>
        </Row>
        <Row label={st.consent_at ? "Retirer mon accord" : "Accepter les conditions de fonctionnement"} hint={st.consent_at ? `Accordé le ${new Date(st.consent_at).toLocaleDateString("fr-FR")}.` : "Les conditions sont décrites en haut de cette page : sans cet accord, openMedia ne fait aucun passage."}>
          {confirm ? (
            <span className="flex gap-1">
              <Button size="sm" onClick={() => setConfirm(false)}>
                Annuler
              </Button>
              <Button
                variant="danger"
                size="sm"
                onClick={() => {
                  setConfirm(false);
                  onChange({ consent_at: null });
                }}
              >
                Confirmer
              </Button>
            </span>
          ) : st.consent_at ? (
            <Button variant="danger" size="sm" onClick={() => setConfirm(true)}>
              Retirer
            </Button>
          ) : (
            <Button variant="primary" size="sm" onClick={() => onChange({ consent_at: true as unknown as string })}>
              J'accepte les conditions
            </Button>
          )}
        </Row>
      </Group>
      <NoServer />
    </>
  );
}
