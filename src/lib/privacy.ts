// Ce qui part où : la seule description des flux de données, lue par le tutoriel et par
// Réglages › Confidentialité. Le suivi des sujets est la condition de fonctionnement ; tout le
// reste est une option, coupée tant que le lecteur ne l'a pas activée.

import type { PrivacyOption, ProviderId, Settings } from "./types";

/** Les règles de chaque fournisseur (conservation, entraînement) : on renvoie vers elles plutôt
 *  que de recopier des durées qui changent. */
export const POLICIES: Record<ProviderId | "claude_code", { label: string; url: string }> = {
  anthropic: { label: "Anthropic (API)", url: "https://www.anthropic.com/legal/commercial-terms" },
  claude_code: { label: "ton compte Claude", url: "https://claude.ai/settings/data-privacy-controls" },
  openai: { label: "OpenAI", url: "https://platform.openai.com/docs/guides/your-data" },
  gemini: { label: "Google Gemini", url: "https://ai.google.dev/gemini-api/terms" },
  openrouter: { label: "OpenRouter", url: "https://openrouter.ai/privacy" },
  mistral: { label: "Mistral", url: "https://mistral.ai/terms" },
  deepseek: { label: "DeepSeek", url: "https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html" },
  moonshot: { label: "Kimi (Moonshot AI)", url: "https://platform.kimi.ai/docs/agreement/userprivacy" },
  zai: { label: "GLM (Z.ai)", url: "https://docs.z.ai/legal-agreement/privacy-policy" },
  qwen: { label: "Qwen (Alibaba Cloud)", url: "https://www.alibabacloud.com/help/en/legal/latest/alibaba-cloud-international-website-privacy-policy" },
  xai: { label: "Grok (xAI)", url: "https://x.ai/legal/privacy-policy" },
  groq: { label: "Groq", url: "https://groq.com/privacy-policy/" },
  compatible: { label: "ton autre fournisseur", url: "" },
};

export interface AiTarget {
  /** L'analyse se fait sur ce PC (Ollama, LM Studio). */
  local: boolean;
  /** Qui reçoit ce qui part à l'IA : « ton PC » en local, sinon chaque service en ligne possible. */
  names: string[];
  policies: { label: string; url: string }[];
  /** Les fournisseurs qui traitent les articles en Chine : dit en clair avant l'accord. */
  china: string[];
  /** Les serveurs de ce PC à qui des rôles sont confiés, à côté des fournisseurs en ligne. */
  pc: string[];
}

/** Où partent les envois à l'IA. En ligne, chaque fournisseur qui a une clé (ou Claude Code)
 *  peut servir : un rôle réglé sur un fournisseur sans clé passe chez un autre. */
export function aiTarget(st: Settings | undefined): AiTarget {
  if (!st) return { local: false, names: [], policies: [], china: [], pc: [] };
  if (st.engine === "local") {
    const label = st.local_provider === "lmstudio" ? "LM Studio" : "Ollama";
    return { local: true, names: [`ton PC (${label})`], policies: [], china: [], pc: [label] };
  }
  const ids: (ProviderId | "claude_code")[] = [];
  if (st.engine_active === "claude_code") ids.push("claude_code");
  if (st.engine_active === "api") ids.push("anthropic");
  for (const [id, p] of Object.entries(st.providers ?? {}) as [ProviderId, Settings["providers"][ProviderId]][]) {
    if (id !== "anthropic" && p.has_key) ids.push(id);
  }
  // Des rôles confiés à l'IA de ce PC, à côté (ou à la place) des fournisseurs en ligne.
  const onPc = [...new Set(Object.values(st.models ?? {}).flatMap((m) => (m.startsWith("ollama:") ? ["Ollama"] : m.startsWith("lmstudio:") ? ["LM Studio"] : [])))];
  if (!ids.length && onPc.length) return { local: true, names: [`ton PC (${onPc.join(", ")})`], policies: [], china: [], pc: onPc };
  const region = (id: ProviderId | "claude_code") => st.providers?.[id === "claude_code" ? "anthropic" : id]?.region ?? "";
  const name = (id: ProviderId | "claude_code") => {
    const base = id === "claude_code" ? "Anthropic (Claude Code)" : id === "compatible" ? st.providers?.compatible?.url.replace(/^https?:\/\//, "").split("/")[0] || "ton autre fournisseur" : POLICIES[id].label.replace(" (API)", "");
    const where = region(id);
    return where ? `${base} ${where}` : base;
  };
  return {
    local: false,
    names: [...ids.map(name), ...(onPc.length ? [`ton PC (${onPc.join(", ")})`] : [])],
    policies: ids.map((id) => POLICIES[id]).filter((p) => p.url),
    china: ids.filter((id) => region(id).includes("Chine")).map((id) => POLICIES[id as ProviderId].label),
    pc: onPc,
  };
}

/** Les fournisseurs disponibles qui ont une recherche web (Mistral n'en a pas). */
export function searchNames(st: Settings | undefined): string[] {
  if (!st || st.engine === "local") return [];
  const out: string[] = [];
  if (st.engine_active === "claude_code") out.push("Anthropic (Claude Code)");
  if (st.engine_active === "api") out.push("Anthropic");
  for (const [id, p] of Object.entries(st.providers ?? {}) as [ProviderId, Settings["providers"][ProviderId]][]) {
    if (id !== "anthropic" && p.has_key && p.search) out.push(POLICIES[id].label);
  }
  return out;
}

export function listNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "ton fournisseur d'IA";
  return `${names.slice(0, -1).join(", ")} ou ${names[names.length - 1]}`;
}

export interface Flow {
  what: string;
  to: string;
  when: string;
}

/** Les envois du suivi des sujets : la condition de fonctionnement. */
export function coreFlows(st: Settings | undefined): Flow[] {
  const ai = aiTarget(st);
  const to = ai.local ? "reste sur ce PC" : listNames(ai.names);
  const search = [st?.gdelt !== false && "GDELT"].filter(Boolean) as string[];
  const flows: Flow[] = [
    { what: "La consigne de chaque sujet que tu suis", to, when: "à la création, puis à chaque passage" },
    { what: "Les articles trouvés : titre, média et extraits du texte", to, when: "à chaque passage" },
    { what: "Tes fiches, pour rédiger le Brief", to, when: "à chaque Brief" },
    { what: "Un lien que tu glisses ou que tu fais vérifier", to, when: "quand tu le fais" },
    ...(search.length ? [{ what: "Les mots-clés de tes sujets", to: search.join(" et "), when: "à chaque passage, pour trouver l'actualité" }] : []),
    { what: "La demande des unes, de chaque article à lire et de tes flux RSS", to: "les sites des médias", when: "à chaque passage, comme ton navigateur" },
  ];
  const searchers = searchNames(st);
  if (!ai.local && st?.claude_search_fallback && searchers.length) {
    flows.push({ what: "Le résumé d'un sujet peu couvert, pour une recherche web", to: `le moteur de recherche de ${listNames(searchers)}`, when: "seulement si la couverture est trop mince" });
  }
  return flows;
}

export interface OptionInfo {
  id: PrivacyOption;
  label: string;
  /** Ce que l'option lit ou envoie, et à qui. */
  sends: (st: Settings | undefined) => string;
  /** Ce qu'on garde sans elle. */
  without: string;
  /** Une option qui n'a de sens qu'avec une autre. */
  requires?: PrivacyOption;
}

export const OPTIONS: OptionInfo[] = [
  {
    id: "history_auto",
    label: "Proposer des sujets à partir de mes lectures",
    sends: () =>
      "openMedia lit sur ce PC l'historique des navigateurs que tu coches, sur 90 jours, et n'en garde que les articles de presse. Si ton navigateur est synchronisé, les visites de ton téléphone viennent avec. Les sujets sont repérés par un calcul sur ton PC : rien n'est envoyé.",
    without: "Tu écris tes sujets toi-même.",
  },
  {
    id: "readings_ai",
    label: "Faire nommer ces sujets par l'IA",
    sends: (st) => {
      const ai = aiTarget(st);
      return ai.local ? "Quelques titres d'articles lus (6 au plus par sujet) sont lus par l'IA de ce PC." : `Quelques titres d'articles lus (6 au plus par sujet) sont envoyés à ${listNames(ai.names)}.`;
    },
    without: "Les sujets sont nommés par leurs mots-clés.",
    requires: "history_auto",
  },
  {
    id: "discover_enabled",
    label: "Découvrir",
    sends: (st) => {
      const ai = aiTarget(st);
      return `Les titres à la une de vingt médias et les noms de tes sujets sont ${ai.local ? "lus par l'IA de ce PC" : `envoyés à ${listNames(ai.names)}`} pour te proposer des histoires à suivre.`;
    },
    without: "La page Découvrir reste vide.",
  },
  {
    id: "brief_audio_auto",
    label: "Préparer le Brief en audio chaque jour",
    sends: () => "Le texte du Brief est envoyé au service de voix de Microsoft (en ligne).",
    without: "Tu peux toujours lancer l'audio à la main.",
  },
];

/** La languette : réglée à l'étape qui la présente, et dans Réglages › Général. */
export const PAGE_WATCH =
  "La languette lit l'adresse de l'onglet au premier plan, environ chaque seconde, et reconnaît un article de presse sur ce PC. Elle ne garde rien et n'envoie rien tant que tu ne cliques pas sur Enregistrer ou Vérifier. Elle s'efface devant les fenêtres de navigation privée qu'elle reconnaît.";

/** Ce qui reste en ligne même avec l'IA sur ce PC. */
export function stillOnline(st: Settings | undefined): string[] {
  const out = [st?.gdelt !== false && "GDELT", "tes flux RSS", "les sites des médias, pour lire leurs unes et leurs articles"].filter(Boolean) as string[];
  if (st?.brief_audio_auto) out.push("la voix du Brief (Microsoft)");
  if (st?.ntfy_topic) out.push("les notifications ntfy");
  return out;
}
