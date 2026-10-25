// Les formes renvoyées par l'API locale (backend/openmedia/api/routes.py).

export type Status = "confirme" | "non_confirme" | "conteste" | "dementi";

export interface Item {
  text: string;
  refs: string[];
  status: Status;
  check?: "chiffre_non_retrouve" | "contenu_suspect";
  contradicted_by?: string[];
  /** AAAA-MM-JJ : la nouvelle était déjà parue avant ce passage. */
  first_reported?: string;
}

export interface FicheContent {
  title: string;
  lede: string;
  state: "emergent" | "en_cours" | "stable" | "clos";
  nothing_new: boolean;
  whats_new: Item[];
  changes: string[];
  key_facts: Item[];
  timeline: { date: string; event: string; refs: string[]; check?: string }[];
  perspectives: { actor: string; position: string; refs: string[] }[];
  uncertainties: string[];
  watch: string[];
  announcements: { text: string; due: string; refs: string[]; status: "a_venir" | "realise" | "reporte" | "abandonne" }[];
  custom_sections: { title: string; body: string; refs: string[] }[];
  importance: number;
  confidence: "elevee" | "moyenne" | "faible";
  /** Écrit par le programme : ce que ce passage confirme sans le refaire passer pour neuf. */
  updates?: FicheUpdates;
}

/** Un fait déjà connu que ce passage confirme (« confirmation ») ou appuie d'un nouveau média (« appui »). */
export interface FactUpdate {
  text: string;
  before: Status | null;
  status: Status;
  kind: "confirmation" | "appui";
  refs_new: string[];
  media_new: string[];
}

export interface FicheUpdates {
  confirmations: FactUpdate[];
  /** Articles qui n'ont fait que redire des faits connus. */
  reprises: { articles: number; media: string[] };
  late: number;
}

/** Ce qu'un passage a apporté, compté par le programme. */
export interface Novelty {
  new?: number;
  late?: number;
  confirmations?: number;
  rectifications?: number;
  reprises?: number;
  synth_skipped?: boolean;
}

export interface SourceRef {
  ref: string;
  preprint?: boolean;
  research?: boolean;
  id: number;
  title: string;
  domain: string;
  name: string;
  url: string;
  published_at: string | null;
  country: string;
  kind: string;
  quality?: number | null;
  quality_note?: string;
  quality_origin?: string;
}

export interface Coverage {
  articles: number;
  independent: number;
  countries: Record<string, number>;
  kinds: Record<string, number>;
  owners: Record<string, number>;
  langs: Record<string, number>;
  owner_types?: Record<string, number>;
  controllers?: Record<string, number>;
  unreliable?: number;
  alerts: string[];
}

export interface Fiche {
  id: number;
  topic_id: number;
  version: number;
  content: Partial<FicheContent>;
  sources: SourceRef[];
  coverage: Coverage;
  nothing_new: boolean;
  novelty?: Novelty;
  audio_path: string | null;
  created_at: string;
}

export interface TopicSpec {
  name: string;
  summary: string;
  angle: string;
  queries_fr: string[];
  queries_en: string[];
  keywords: string[];
  exclusions: string[];
  sections: { title: string; instruction: string }[];
  keep_opinions: boolean;
  start_date: string | null;
}

export interface Topic {
  id: number;
  name: string;
  prompt: string;
  spec: Partial<TopicSpec>;
  model: string | null;
  languages: string[];
  feeds: string[];
  social: { reddit?: boolean; hn?: boolean; telegram?: string[] } | null;
  kind: "actualite" | "recherche";
  research_fields: string[] | null;
  last_seen_at: string | null;
  /** Rythme propre : jours (`run_every_days` ou `run_weekdays`, lundi = 0) et heures ; vides, ceux des réglages. */
  run_hour: string | null;
  run_hours: string[] | null;
  run_every_days: number | null;
  run_weekdays: number[] | null;
  follow_deadlines: boolean;
  /** Rythme conseillé : pilote automatique et journal (voir `RhythmOverview`). */
  rhythm?: { auto?: boolean; min_every?: number; max_every?: number } | null;
  /** Le rythme effectif, réglages compris. */
  schedule: Cadence & { own: boolean };
  next_run: string | null;
  importance: number;
  status: "active" | "sleeping" | "archived";
  last_run_at: string | null;
  created_at: string;
  running: boolean;
  latest: {
    id: number;
    version: number;
    created_at: string;
    nothing_new: boolean;
    novelty?: Novelty;
    title?: string;
    lede?: string;
    state?: FicheContent["state"];
    importance?: number;
    whats_new: Item[];
  } | null;
  last_run: { status: string; error: string; cost_usd: number } | null;
}

export interface Brief {
  id: number;
  day: string;
  audio_path: string | null;
  created_at: string;
  content: {
    headline: string;
    points: { topic_id: number; topic_name: string; text: string; why: string }[];
    cross_links: string[];
    quiet_topics: string[];
    audio_script: string;
  };
}

export type EngineChoice = "auto" | "api" | "claude_code" | "local";
export type LocalProvider = "ollama" | "lmstudio";

/** Ollama et LM Studio détectés sur ce PC (`GET /settings/local`). */
export type LocalServers = Record<LocalProvider, { label: string; found: boolean; url: string; models: { id: string; size: string; context: number | null }[] }>;

/** Les options : coupées tant que le lecteur ne les a pas activées. */
export type PrivacyOption = "history_auto" | "readings_ai" | "discover_enabled" | "detect_page" | "page_nudge" | "brief_audio_auto";

export interface Settings {
  engine: EngineChoice;
  engine_active: "api" | "claude_code" | "local" | null;
  local_provider: LocalProvider;
  local_model: string;
  local_urls: Partial<Record<LocalProvider, string>>;
  /** L'IA de ce PC, quand elle est le moteur choisi : répond-elle, le modèle est-il là ? */
  local: { provider: LocalProvider; model: string; found: boolean; ready: boolean; url: string } | null;
  claude_code: { found: boolean; path: string | null; version: string | null; lockdown?: "complet" | "partiel"; lockdown_missing?: string[] };
  claude_code_path: string;
  models: { triage: string; topic: string; director: string };
  run_hours: string[];
  run_every_days: number;
  run_weekdays: number[];
  schedule_anchor: string;
  languages: string[];
  monthly_budget_usd: number;
  monthly_token_cap: number;
  max_parallel_topics: number;
  claude_search_fallback: boolean;
  min_independent_sources: number;
  notify_threshold: number;
  voice: string;
  last_visit_at: string | null;
  theme: "system" | "light" | "dark";
  detect_page: boolean;
  page_nudge: boolean;
  /** « Mes lectures » se met à jour seule (toutes les 15 minutes et à l'ouverture de la vue). */
  history_auto: boolean;
  history_synced_at: string | null;
  history_sources: { browser?: string; profile?: string; path?: string }[];
  history_skip_phone: boolean;
  readings_ai: boolean;
  discover_enabled: boolean;
  brief_audio_auto: boolean;
  gdelt: boolean;
  onboarding_done: boolean;
  onboarding_step: number;
  consent_at: string | null;
  previous_options: Partial<Record<PrivacyOption, boolean>>;
  claude_code_parallel: number;
  phone_listen: boolean;
  ntfy_topic: string;
  has_api_key: boolean;
  month_cost_usd: number;
  month_subscription_usd: number;
  economy_batch: boolean;
  rhythm_auto_default: boolean;
  providers: Record<ProviderId, ProviderInfo>;
  /** Adresse d'API réglée par le lecteur (espace Qwen, autre fournisseur compatible OpenAI). */
  provider_urls: Record<string, string>;
}

export type ProviderId = "anthropic" | "openai" | "gemini" | "openrouter" | "mistral" | "deepseek" | "moonshot" | "zai" | "qwen" | "xai" | "compatible";

export interface ProviderInfo {
  label: string;
  has_key: boolean;
  search: boolean;
  batch: boolean;
  hint: string;
  /** Où partent les articles (« en Chine », « aux États-Unis »…), dit avant l'accord. */
  region: string;
  policy_url: string;
  /** L'adresse de l'API se règle dans Réglages. */
  url_setting: boolean;
  url: string;
}
export type Tier = "maximum" | "premium" | "equilibre" | "rapide";
export type Role = "triage" | "topic" | "director";

/** Les serveurs de l'IA de ce PC, à qui l'on peut aussi confier un rôle (`ollama:qwen3:14b`). */
export type LocalProviderId = "ollama" | "lmstudio";

export interface ModelRow {
  id: string;
  label: string;
  provider: ProviderId | LocalProviderId;
  tier: Tier | null;
  tier_label: string;
  price: [number, number, number] | null;
  featured: boolean;
  usable: boolean;
  note: string;
  region: string;
}

export interface ModelCatalog {
  providers: { id: ProviderId | LocalProviderId; label: string; usable: boolean; has_key: boolean; search: boolean; batch: boolean; hint: string; region: string; local: boolean }[];
  models: ModelRow[];
  presets: Record<string, { label: string; by_provider: Record<ProviderId, Record<Role, string | null>> }>;
  tiers: Record<Tier, string>;
  /** Le modèle qui sert vraiment chaque rôle (null : aucun moteur) ; vide avec « tout sur ce PC ». */
  effective: Partial<Record<Role, string | null>>;
}

export interface CostStage {
  stage: string;
  models: string[];
  calls: number;
  in: number;
  out: number;
  cost: number;
  unknown_price: boolean;
}

export interface CostRun {
  id: number;
  kind: string;
  topic: string | null;
  started_at: string;
  cost_usd: number;
  subscription_usd: number;
  real_usd: number;
  stages: CostStage[];
}

export interface CostsTopic {
  topic_id: number;
  name: string;
  status: Topic["status"];
  runs_per_month: number;
  own_schedule: boolean;
  follow_deadlines: boolean;
  schedule: Cadence;
  runs: number;
  avg_tokens: number;
  avg_cost: number | null;
  monthly_tokens: number;
  estimated: boolean;
  next_run: string | null;
}

/** Tokens : lus (cache compris) + écrits. */
export interface CostsReport {
  month: {
    real: number;
    subscription: number;
    budget: number;
    tokens: { in: number; cached: number; out: number; total: number };
    cap: number;
    end_estimate: number;
  };
  today: { tokens: number };
  days: { day: string; topics: number; brief: number; other: number }[];
  projection: { real: number; subscription: number; tokens: number };
  general_runs_per_month: number;
  topics: CostsTopic[];
  brief: { runs: number; avg_tokens: number; per_month: number };
  other: { tokens: number };
  next_run: string | null;
  last_topic_run: CostRun | null;
  last_brief: CostRun | null;
}

export interface Article {
  ref: string;
  id: number;
  title: string;
  url: string;
  source: string;
  country: string;
  kind: string;
  published_at: string | null;
  wire: string;
  origin: string;
  kept: boolean;
  nature: string;
  relevance: number;
  sensationalism: number;
  reason: string;
}

export interface Story {
  title: string;
  summary: string;
  section: string;
  size: number;
  sources: string[];
  suggested_prompt: string;
  related_topic_id: number | null;
}

export interface Drop {
  id: number;
  url: string;
  title: string;
  domain: string;
  suggestion: { action: "add_to_topic" | "new_topic"; topic_id: number | null; topic_name: string; prompt_draft: string; reason: string };
}

/** Une vérification d'article (Mes lectures, Enregistrements) : ses affirmations recoupées. */
export interface Factcheck {
  status: "ok" | "illisible" | "rien" | "erreur";
  message?: string | null;
  claims: { text: string; status: Status; refs: string[]; contradicted_by: string[]; explanation: string; independent: number; note?: string; check?: "chiffre_non_retrouve" }[];
  sources?: (SourceRef & { owner_type?: string })[];
  others?: number;
  cost_usd?: number;
  /** Vérification rapide : le modèle (toujours Haiku), les tokens et si l'abonnement Claude Code l'a couverte. */
  model?: string;
  tokens?: number;
  subscription?: boolean;
  /** L'article est réservé aux abonnés : vérifié d'après son titre et son chapô. */
  paywalled?: boolean;
  /** Les autres médias à lire ; `open` : texte lu sans abonnement (sinon, seul le titre est connu). */
  reads?: { name: string; title: string; url: string; open: boolean }[];
  checked_at: string;
}

/** Un sujet qui revient dans « Mes lectures » : trouvé par l'algorithme, nommé par Haiku. */
export interface RecurringTopic {
  key: string;
  name: string;
  prompt: string;
  named_by: "haiku" | "algorithme";
  label: string;
  keywords: string[];
  reading_ids: number[];
  count: number;
  days: number;
  media: string[];
  first: string;
  last: string;
  reason: string;
  titles: string[];
  related_topic_id: number | null;
}

/** Ce que la languette sait de la page ouverte dans le navigateur. */
export interface PageCheck {
  is_article: boolean;
  media: string;
  domain: string;
  recording_id: number | null;
  status: Recording["status"] | null;
  topic_id: number | null;
  /** La dernière vérification rapide de cette page, s'il y en a une. */
  quickcheck: Factcheck | null;
}

export interface DossierPoint {
  text: string;
  refs: string[];
  check?: "chiffre_non_retrouve" | "contenu_suspect";
}

/** Les sources rassemblées autour d'un article enregistré. */
export interface RecordingDossier {
  status?: "en_cours" | "ok" | "erreur";
  message?: string;
  started_at?: string;
  gathered_at?: string;
  cost_usd?: number;
  check?: Factcheck;
  synthesis?: { summary: string; points: DossierPoint[]; context: DossierPoint[]; open_questions: string[]; next_steps: string } | null;
}

export interface Recording {
  id: number;
  article_id: number;
  status: "enregistre" | "suivi";
  topic_id: number | null;
  dossier: RecordingDossier;
  created_at: string;
  title: string;
  url: string;
  domain: string;
  published_at: string | null;
  readable: boolean;
  media: string;
  owner: string;
  owner_type: string;
  controller: string;
  kind: string;
  quickcheck: Factcheck | null;
}

export interface Run {
  id: number;
  topic_id: number | null;
  kind: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  cost_usd: number;
  subscription_usd: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  web_searches: number;
  error: string;
}

export interface SourceRow {
  domain: string;
  name: string;
  kind: string;
  country: string;
  owner: string;
  lang: string;
  weight: number;
  blocked: boolean;
  priority?: boolean;
  quality?: number | null;
  quality_origin?: string;
  quality_note?: string;
}

export interface Correction {
  id: number;
  topic_id: number;
  topic_name: string;
  version: number;
  previous_text: string;
  previous_status: Status | "";
  new_status: "dementi" | "conteste" | "corrige";
  explanation: string;
  refs: string[];
  read_by_user: boolean;
  seen_at: string | null;
  created_at: string;
  sources: SourceRef[];
}

export type AnnouncementStatus = "a_venir" | "realise" | "reporte" | "abandonne" | "en_retard";

export interface Announcement {
  id: number;
  topic_id: number;
  topic_name: string;
  text: string;
  due: string;
  due_date: string | null;
  status: AnnouncementStatus;
  resolution: string;
  last_checked_at: string | null;
  resolved_at: string | null;
  sources: SourceRef[];
  resolution_sources: SourceRef[];
}

/** Un rythme de passage : tous les `every` jours, ou certains jours (`weekdays`, lundi = 0), aux heures `hours`. */
export interface Cadence {
  every: number;
  weekdays: number[];
  hours: string[];
}

/** Le calendrier d'une période, pour un sujet ou pour tous. */
export interface CalendarData {
  deadlines: (Announcement & { date: string })[];
  /** Les échéances situées seulement au mois (ou à l'année). */
  undated: (Announcement & { month: string })[];
  events: { date: string; text: string; topic_id: number; topic_name: string; sources: SourceRef[] }[];
  runs: { date: string; time: string; version: number; nothing_new: boolean; news: number; confirmations?: number }[];
  planned: { date: string; time: string; deadline: boolean }[];
}

export interface ProofArticle {
  ref: string;
  title: string;
  url: string;
  media: string;
  kind: string;
  country: string;
  owner: string;
  owner_type: string;
  owner_type_label: string;
  controller: string;
  wire: string;
  published_at: string | null;
  nature: string;
  reason: string;
  claims: string[];
  counts: boolean;
  quality: number | null;
  quality_label: string;
  quality_origin: string;
  quality_note: string;
}

export interface Proof {
  independent: number;
  articles: number;
  groups: { label: string; counts: boolean; media: string[] }[];
  supporting: ProofArticle[];
  contradicting: ProofArticle[];
  explanation: string;
}

export interface ServerEvent {
  type: "run" | "notify" | "brief" | "topic" | "warning" | "correction" | "announcement" | "recording" | "readings" | "recurring" | "rhythm";
  at: string;
  topic_id?: number;
  run_id?: number;
  stage?: string;
  message?: string;
  title?: string;
  body?: string;
  importance?: number;
  headline?: string;
}

/** Le conseil de rythme d'un sujet (sans IA), d'après ce que ses passages ont apporté. */
export interface RhythmAdvice {
  current: number;
  observed: number;
  needed: number;
  direction: "espacer" | "resserrer" | "veille" | null;
  every: number | null;
  reason: string;
  confidence: "elevee" | "moyenne" | "faible" | null;
  dismissed: boolean;
  simulation: { runs_saved: number; tokens_saved: number; cost_saved: number; mean_delay: number; max_delay: number; news_runs: number; runs: number } | null;
}

export interface RhythmDay {
  day: string;
  runs: { new: number; confirmations: number; rectifications: number; reprises: number; skipped: boolean }[];
  pulse: number | null;
  pulse_media: number | null;
  advanced: boolean;
}

export interface RhythmLogEntry {
  at: string;
  from: number | null;
  to: number | null;
  reason: string;
  by: "auto" | "user" | "pulse";
}

export interface RhythmOverview {
  advice: RhythmAdvice;
  strip: RhythmDay[];
  auto: boolean;
  min_every: number;
  max_every: number;
  log: RhythmLogEntry[];
}
