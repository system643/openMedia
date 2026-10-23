// Le contenu de chaque étape du tutoriel. La coque (Onboarding.tsx) gère la navigation, la
// reprise et l'enregistrement ; ici, seulement ce que voit le lecteur.

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { emitTo, listen } from "@tauri-apps/api/event";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import { Bookmark, Bot, Check, CircleCheck, FileText, Funnel, GitCompare, Newspaper, PenLine, Plus, Search, ShieldCheck, Sunrise } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { EngineChoice } from "../../components/EngineChoice";
import { Logo } from "../../components/Logo";
import { AiBanner, BrowserPicker, CoreFlows, NoServer, OptionsList, PageWatchRows } from "../../components/PrivacyControls";
import { Button, Spinner } from "../../components/ui";
import { api, inTauri } from "../../lib/api";
import { spring } from "../../lib/motion";
import { PAGE_WATCH, aiTarget } from "../../lib/privacy";
import type { PageCheck, RecurringTopic, Settings, Topic } from "../../lib/types";
import { TopicWizard } from "../NewTopicSheet";

type Patch = (body: Partial<Settings>) => void;

export function StepTitle({ eyebrow, children, sub }: { eyebrow?: string; children: ReactNode; sub?: ReactNode }) {
  return (
    <header className="mb-7">
      {eyebrow && <p className="mb-1.5 text-[13px] font-semibold text-accent">{eyebrow}</p>}
      <h2 tabIndex={-1} data-step-title className="serif text-[34px] font-medium leading-[1.12] tracking-[-0.01em] text-ink outline-none">
        {children}
      </h2>
      {sub && <p className="mt-2.5 max-w-[62ch] text-[15px] leading-relaxed text-ink-2">{sub}</p>}
    </header>
  );
}

// ── 1. Bienvenue ─────────────────────────────────────────────────────────────

const PROMISES = [
  { icon: <Bot size={19} />, title: "Un agent par sujet", text: "Tu décris ce que tu veux suivre. Chaque jour, un agent lit la presse pour toi et met sa fiche à jour." },
  { icon: <ShieldCheck size={19} />, title: "Deux sources pour confirmer", text: "La rumeur et l'opinion sont écartées. Un fait n'est « confirmé » que par deux médias indépendants." },
  { icon: <Sunrise size={19} />, title: "Le Brief du matin", text: "Le Directeur de rédaction relit toutes les fiches et résume ce qui a changé, à lire ou à écouter." },
];

export function Welcome() {
  return (
    <div>
      <motion.div initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={spring.smooth} className="mb-6 inline-block rounded-[22px] shadow-pop">
        <Logo size={64} />
      </motion.div>
      <StepTitle eyebrow="Bienvenue dans openMedia" sub="Tu choisis les sujets ; des agents IA lisent l'actualité, trient, recoupent et te disent ce qui a vraiment changé. Ce tutoriel te fait tout essayer et te laisse décider de ce qui est partagé.">
        Ton journal, tenu par des agents.
      </StepTitle>
      <div className="grid gap-3 sm:grid-cols-3">
        {PROMISES.map((p, i) => (
          <motion.div key={p.title} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring.smooth, delay: 0.12 + i * 0.08 }} className="card p-4">
            <span className="grid size-9 place-items-center rounded-xl bg-accent-soft text-accent">{p.icon}</span>
            <p className="mt-3 text-[15px] font-semibold text-ink">{p.title}</p>
            <p className="mt-1 text-[13px] leading-snug text-ink-2">{p.text}</p>
          </motion.div>
        ))}
      </div>
      <div className="mt-7">
        <NoServer />
      </div>
    </div>
  );
}

// ── 2. Comment ça marche ────────────────────────────────────────────────────

const PIPELINE = [
  { icon: <PenLine size={17} />, label: "Ta consigne", text: "Tu décris le sujet et ce que tu veux savoir, comme à un journaliste. L'agent en tire ses mots-clés de recherche." },
  { icon: <Search size={17} />, label: "Collecte", text: "GDELT, l'index mondial de la presse, les unes de vingt médias de tous bords et tes flux RSS : les articles parus depuis le dernier passage, trois au plus par média." },
  { icon: <Funnel size={17} />, label: "Tri", text: "Chaque article est classé : fait, analyse, opinion, réaction ou rumeur. La réaction à chaud et la rumeur sont écartées." },
  { icon: <GitCompare size={17} />, label: "Recoupement", text: "Un fait n'est « confirmé » qu'avec deux sources indépendantes, dont une au moins de fiabilité établie : une dépêche reprise par dix journaux ne compte qu'une fois, et deux sites inconnus ne suffisent pas." },
  { icon: <FileText size={17} />, label: "Fiche", text: "La fiche du sujet n'est réécrite que s'il y a du neuf, chaque fait avec ses sources. Chaque version est gardée." },
  { icon: <Newspaper size={17} />, label: "Brief", text: "Le Directeur de rédaction relit toutes les fiches et rédige le Brief, à l'heure que tu choisis." },
];

const CAVEATS = [
  { title: "La fiabilité d'un média ne mesure pas son bord politique", text: "Elle vient d'une notation publique qui agrège six organismes, ou d'une estimation de l'IA pour les sites inconnus. Elle ne sert qu'à une chose : un média noté faible ne peut pas confirmer un fait à lui seul, mais il reste lisible. Tu peux changer n'importe quelle note." },
  { title: "« Non confirmé » ne veut pas dire faux", text: "Une exclusivité n'a souvent qu'une source au début. Le fait reste affiché, attribué à son média, jusqu'à ce qu'un autre le confirme ou le contredise." },
  { title: "L'IA peut se tromper", text: "Les classements sont automatiques. Chaque fait renvoie à ses articles : vérifie ceux qui comptent pour toi." },
  { title: "Des agents sans pouvoir", text: "Ils lisent et rendent du texte, sans aucun outil pour agir sur ton PC. Une page piégée peut tromper une IA sur le contenu : c'est pour cela que chaque fait renvoie à ses sources." },
];

export function HowItWorks() {
  const [active, setActive] = useState(0);
  const [auto, setAuto] = useState(true);
  useEffect(() => {
    if (!auto) return;
    const t = setInterval(() => setActive((i) => (i + 1) % PIPELINE.length), 2600);
    return () => clearInterval(t);
  }, [auto]);
  return (
    <div>
      <StepTitle eyebrow="Comment ça marche" sub="À chaque passage, au rythme que tu choisis, l'agent de chaque sujet fait ce travail. Clique sur une étape pour la détailler.">
        De l'actualité brute à ta fiche.
      </StepTitle>
      <div className="relative">
        <div className="absolute left-[8%] right-[8%] top-[22px] h-[2px] rounded-full bg-line" aria-hidden />
        <motion.div className="absolute left-[8%] top-[22px] h-[2px] rounded-full bg-accent" aria-hidden animate={{ width: `${(active / (PIPELINE.length - 1)) * 84}%` }} transition={spring.smooth} />
        <ol className="relative grid grid-cols-6 gap-1">
          {PIPELINE.map((p, i) => (
            <li key={p.label} className="flex flex-col items-center">
              <button
                onClick={() => {
                  setAuto(false);
                  setActive(i);
                }}
                aria-current={i === active ? "step" : undefined}
                className="group flex flex-col items-center gap-2 rounded-xl px-1 py-0.5 outline-none focus-visible:shadow-[var(--focus)]"
              >
                <motion.span animate={{ scale: i === active ? 1.12 : 1 }} transition={spring.snappy} className={`grid size-11 place-items-center rounded-full border-2 transition-colors ${i <= active ? "border-accent bg-accent-fill text-white" : "border-line-strong bg-surface text-ink-2"}`}>
                  {p.icon}
                </motion.span>
                <span className={`text-center text-[12.5px] ${i === active ? "font-semibold text-ink" : "text-ink-2"}`}>{p.label}</span>
              </button>
            </li>
          ))}
        </ol>
      </div>
      <div className="mt-5 min-h-[84px] rounded-2xl bg-fill/50 p-4" aria-live="polite">
        <AnimatePresence mode="wait" initial={false}>
          <motion.p key={active} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.18 }} className="text-[15px] leading-relaxed text-ink">
            <span className="font-semibold">{PIPELINE[active].label}. </span>
            {PIPELINE[active].text}
          </motion.p>
        </AnimatePresence>
      </div>
      <div className="mt-6 grid gap-2 sm:grid-cols-2">
        {CAVEATS.map((c) => (
          <details key={c.title} className="group card px-4 py-3 text-[13px]">
            <summary className="cursor-pointer list-none text-[14px] font-medium text-ink marker:hidden">
              <span className="mr-1.5 inline-block text-accent transition-transform group-open:rotate-90">›</span>
              {c.title}
            </summary>
            <p className="mt-1.5 leading-snug text-ink-2">{c.text}</p>
          </details>
        ))}
      </div>
    </div>
  );
}

// ── 3. Le moteur IA ─────────────────────────────────────────────────────────

export function EngineStep({ settings }: { settings: Settings }) {
  return (
    <div>
      <StepTitle eyebrow="Ton moteur IA" sub="Le suivi des sujets repose sur une IA : c'est la seule chose obligatoire. Elle peut tourner sur ton PC, ou en ligne chez un fournisseur. Tu pourras changer plus tard dans Réglages › Moteur IA.">
        Quelle IA lira la presse pour toi ?
      </StepTitle>
      <EngineChoice settings={settings} />
    </div>
  );
}

// ── 4. Conditions de fonctionnement ─────────────────────────────────────────

export function ConditionsStep({ settings: st, onChange, onAccept, onLocal, onLater, accepting }: { settings: Settings; onChange: Patch; onAccept: () => void; onLocal: () => void; onLater: () => void; accepting: boolean }) {
  const ai = aiTarget(st);
  return (
    <div>
      <StepTitle eyebrow="Ce qui est nécessaire" sub="Pour suivre tes sujets, openMedia doit aller chercher l'actualité sur Internet, puis la faire lire par l'IA que tu viens de choisir. Voici exactement ce qui part, et où.">
        Comment openMedia fonctionne.
      </StepTitle>
      <AiBanner settings={st} />
      <div className="mt-4">
        <CoreFlows settings={st} onChange={onChange} />
      </div>
      {!ai.local && <p className="mt-4 text-[13.5px] leading-snug text-ink-2">Tes sujets peuvent en dire long sur toi : opinions, santé, convictions. Si tu préfères qu'aucun service d'IA ne les voie, choisis l'IA sur ton PC. N'écris pas dans une consigne ce que tu ne confierais pas à {ai.names.length > 1 ? "ces services" : ai.names[0]}.</p>}
      <div className="mt-4">
        <NoServer />
      </div>
      {st.consent_at ? (
        <p className="mt-6 inline-flex items-center gap-2 text-[14px] font-medium text-ok">
          <CircleCheck size={17} /> Accepté. Tu peux retirer ton accord à tout moment dans Réglages › Confidentialité.
        </p>
      ) : (
        <div className="mt-6 flex flex-wrap gap-2">
          <Button busy={accepting} onClick={onAccept}>
            D'accord, continuer
          </Button>
          {!ai.local && <Button onClick={onLocal}>Utiliser l'IA sur mon PC</Button>}
          <Button onClick={onLater}>Plus tard</Button>
        </div>
      )}
    </div>
  );
}

// ── 5. Les options ──────────────────────────────────────────────────────────

export function OptionsStep({ settings: st, onChange }: { settings: Settings; onChange: Patch }) {
  return (
    <div>
      <StepTitle eyebrow="Tes données" sub="Des fonctions en plus pour t'aider. Tout est coupé tant que tu ne l'actives pas, et tout se change ensuite dans Réglages › Confidentialité.">
        Des options, si tu veux.
      </StepTitle>
      <OptionsList settings={st} onChange={onChange} browsers={<BrowserPicker settings={st} onChange={onChange} />} />
      <p className="mt-3 text-[12.5px] text-ink-2">La languette, qui repère l'article ouvert dans ton navigateur, te sera présentée plus loin.</p>
    </div>
  );
}

// ── 6. La lecture de l'historique ───────────────────────────────────────────

interface ScanRow {
  key: string;
  label: string;
  state: "attente" | "lecture" | "fait" | "erreur";
  pages?: number;
  kept?: number;
  error?: string;
}

export interface ScanResult {
  topics: RecurringTopic[];
  kept: number;
}

export function ScanStep({ settings: st, result, onDone }: { settings: Settings; result: ScanResult | null; onDone: (r: ScanResult) => void }) {
  const qc = useQueryClient();
  const browsers = useQuery({ queryKey: ["history-browsers"], queryFn: () => api<{ browser: string; browser_name: string; profile: string; label: string }[]>("/history/browsers") });
  const [rows, setRows] = useState<ScanRow[]>([]);
  const [phase, setPhase] = useState<"lecture" | "regroupement" | "fini">(result ? "fini" : "lecture");
  const started = useRef(false);

  useEffect(() => {
    if (result || started.current || !browsers.data) return;
    started.current = true;
    const sources = st.history_sources ?? [];
    const name = (c: (typeof sources)[number]) => {
      const b = browsers.data!.find((x) => x.browser === c.browser && x.profile === c.profile);
      return b ? `${b.browser_name} · ${b.label}` : c.path ?? `${c.browser}`;
    };
    const initial: ScanRow[] = sources.map((c) => ({ key: `${c.browser}/${c.profile}/${c.path ?? ""}`, label: name(c), state: "attente" }));
    setRows(initial);
    void (async () => {
      let kept = 0;
      for (let i = 0; i < sources.length; i++) {
        setRows((r) => r.map((x, j) => (j === i ? { ...x, state: "lecture" } : x)));
        try {
          // Un historique court se lit en un éclair : chaque ligne reste au moins un instant à
          // l'écran, pour qu'on voie ce qui est lu.
          const [out] = await Promise.all([api<{ pages_seen: number; articles_kept: number; errors: string[] }>("/history/import", { method: "POST", body: { browsers: [sources[i]], days: 90, remember: false } }), pause(1200)]);
          kept += out.articles_kept;
          setRows((r) => r.map((x, j) => (j === i ? { ...x, state: out.errors.length ? "erreur" : "fait", pages: out.pages_seen, kept: out.articles_kept, error: out.errors[0] } : x)));
        } catch (e) {
          setRows((r) => r.map((x, j) => (j === i ? { ...x, state: "erreur", error: e instanceof Error ? e.message : String(e) } : x)));
        }
      }
      setPhase("regroupement");
      try {
        const [rec] = await Promise.all([api<{ topics: RecurringTopic[]; generated_at: string }>("/readings/recurring?force=true"), pause(1400)]);
        qc.setQueryData(["recurring"], rec);
        onDone({ topics: rec.topics, kept });
      } catch {
        onDone({ topics: [], kept });
      }
      setPhase("fini");
      void qc.invalidateQueries({ queryKey: ["readings"] });
    })();
  }, [browsers.data, result, st.history_sources, qc, onDone]);

  const done = rows.filter((r) => r.state === "fait" || r.state === "erreur").length;
  // Le regroupement compte pour un peu plus d'une demi-ligne ; il n'est fini qu'à la fin.
  const progress = result || phase === "fini" ? 1 : rows.length ? (done + (phase === "regroupement" ? 0.3 : 0)) / (rows.length + 0.6) : 0;
  const phrases = [
    st.readings_ai && !aiTarget(st).local ? "Lecture sur ce PC. Seuls quelques titres partiront à l'IA, pour nommer les sujets." : "Lecture sur ce PC : rien n'est envoyé pendant cette étape.",
    "On ne garde que les articles de presse : recherches, messageries, achats et réseaux sociaux sont ignorés.",
    "La navigation privée ne laisse pas d'historique : elle n'est jamais lue.",
    "Ensuite, les articles qui parlent de la même histoire sont regroupés.",
  ];
  return (
    <div>
      <StepTitle eyebrow="Tes lectures" sub="openMedia parcourt l'historique des navigateurs que tu as cochés pour repérer les histoires que tu suis déjà sans le savoir.">
        {phase === "fini" ? "Tes lectures sont prêtes." : "Lecture de ton historique…"}
      </StepTitle>
      <div className="flex flex-col items-center gap-8 sm:flex-row sm:items-start">
        <Ring value={progress} done={phase === "fini"} />
        <div className="w-full min-w-0 flex-1">
          <ul className="card divide-y divide-line overflow-hidden">
            {rows.map((r) => (
              <li key={r.key} className="flex items-center gap-3 px-4 py-3 text-[13.5px]">
                <span className="grid size-5 shrink-0 place-items-center">
                  {r.state === "lecture" ? <Spinner size={15} /> : r.state === "fait" ? <Check size={16} className="text-ok" /> : r.state === "erreur" ? <span className="text-deny">!</span> : <span className="size-2 rounded-full bg-fill-strong" />}
                </span>
                <span className="min-w-0 flex-1 truncate text-ink">{r.label}</span>
                <span className="shrink-0 tabular-nums text-ink-2">
                  {r.state === "fait" && (
                    <Counter value={r.kept ?? 0} suffix={` article${(r.kept ?? 0) > 1 ? "s" : ""} de presse`} />
                  )}
                  {r.state === "erreur" && <span className="text-deny" title={r.error}>illisible</span>}
                </span>
              </li>
            ))}
            {phase !== "lecture" && (
              <li className="flex items-center gap-3 px-4 py-3 text-[13.5px]">
                <span className="grid size-5 shrink-0 place-items-center">{phase === "regroupement" ? <Spinner size={15} /> : <Check size={16} className="text-ok" />}</span>
                <span className="flex-1 text-ink">Regroupement par histoire</span>
                {result && <span className="text-ink-2">{result.topics.length} sujet{result.topics.length > 1 ? "s" : ""} repéré{result.topics.length > 1 ? "s" : ""}</span>}
              </li>
            )}
          </ul>
          {phase !== "fini" ? <Rotating phrases={phrases} /> : <p className="mt-4 text-[14px] text-ink-2">{result && result.kept === 0 ? "Aucun article de presse trouvé dans ces navigateurs sur 90 jours. Tu écriras ton sujet toi-même." : "Passe à l'étape suivante pour choisir ton premier sujet."}</p>}
        </div>
      </div>
    </div>
  );
}

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

function Ring({ value, done }: { value: number; done: boolean }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  return (
    <div className="relative grid size-[132px] shrink-0 place-items-center">
      <svg width="132" height="132" viewBox="0 0 132 132" className="-rotate-90" aria-hidden>
        <circle cx="66" cy="66" r={r} fill="none" strokeWidth="9" className="stroke-fill-strong" />
        <motion.circle cx="66" cy="66" r={r} fill="none" strokeWidth="9" strokeLinecap="round" className={done ? "stroke-ok" : "stroke-accent"} strokeDasharray={c} animate={{ strokeDashoffset: c * (1 - Math.min(1, value)) }} transition={spring.smooth} />
      </svg>
      <span className="absolute text-[22px] font-semibold tabular-nums text-ink" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)}>
        {done ? <Check size={30} className="text-ok" /> : `${Math.round(value * 100)} %`}
      </span>
    </div>
  );
}

function Counter({ value, suffix }: { value: number; suffix: string }) {
  const [shown, setShown] = useState(0);
  useEffect(() => {
    let frame = 0;
    const start = performance.now();
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / 700);
      setShown(Math.round(value * (1 - Math.pow(1 - k, 3))));
      if (k < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return (
    <>
      {shown.toLocaleString("fr-FR")}
      {suffix}
    </>
  );
}

function Rotating({ phrases }: { phrases: string[] }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setI((x) => (x + 1) % phrases.length), 3200);
    return () => clearInterval(t);
  }, [phrases.length]);
  return (
    <div className="mt-4 min-h-[44px]" aria-live="polite">
      <AnimatePresence mode="wait" initial={false}>
        <motion.p key={i} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.25 }} className="text-[14px] leading-snug text-ink-2">
          {phrases[i]}
        </motion.p>
      </AnimatePresence>
    </div>
  );
}

// ── 7. Le premier sujet ─────────────────────────────────────────────────────

export function TopicStep({ settings: st, suggestions, topics, created, onCreated }: { settings: Settings; suggestions: RecurringTopic[]; topics: Topic[]; created: Topic | null; onCreated: (t: Topic) => void }) {
  const [picked, setPicked] = useState<RecurringTopic | null>(null);
  const [writing, setWriting] = useState(false);
  const fromReadings = st.history_auto && suggestions.length > 0;
  const shown = suggestions.filter((t) => !t.related_topic_id).slice(0, 6);
  return (
    <div>
      <StepTitle
        eyebrow="Ton premier sujet"
        sub={fromReadings ? "Voici les histoires qui reviennent dans tes lectures. Choisis-en une, relis la consigne et ajuste-la, ou écris ton propre sujet." : "Décris un sujet que tu veux suivre : un événement, une négociation, une technologie, un procès, une entreprise… Tu pourras en ajouter d'autres ensuite."}
      >
        {created ? "Ton agent est au travail." : "Que veux-tu suivre ?"}
      </StepTitle>
      {created ? (
        <div className="card flex items-start gap-3 p-5">
          <CircleCheck size={22} className="mt-0.5 shrink-0 text-ok" />
          <div className="min-w-0 flex-1">
            <p className="text-[16px] font-semibold text-ink">{created.name}</p>
            <p className="mt-1 text-[13.5px] leading-snug text-ink-2">Son premier passage a commencé : collecte, tri et recoupement des sept derniers jours. Compte quelques minutes ; tu peux continuer pendant ce temps.</p>
          </div>
        </div>
      ) : (
        <>
          {topics.length > 0 && !picked && !writing && <p className="mb-4 rounded-xl bg-fill/60 px-4 py-3 text-[13.5px] text-ink">Tu suis déjà {topics.length} sujet{topics.length > 1 ? "s" : ""}. Tu peux continuer, ou en ajouter un.</p>}
          {fromReadings && !picked && !writing && (
            <div className="grid gap-2.5 sm:grid-cols-2">
              {shown.map((t, i) => (
                <motion.button key={t.key} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring.smooth, delay: i * 0.05 }} onClick={() => setPicked(t)} className="card group p-4 text-left transition-[box-shadow,transform] hover:shadow-pop active:scale-[0.99]">
                  <p className="text-[15px] font-semibold text-ink">{t.name}</p>
                  <p className="mt-1 text-[12.5px] text-ink-2">
                    {t.count} article{t.count > 1 ? "s" : ""} en {t.days} jour{t.days > 1 ? "s" : ""}
                    {t.media.length ? ` · ${t.media.slice(0, 3).join(", ")}` : ""}
                  </p>
                  <p className="mt-2 line-clamp-2 text-[12.5px] italic leading-snug text-ink-3">« {t.titles[0]} »</p>
                </motion.button>
              ))}
              <button onClick={() => setWriting(true)} className="flex items-center justify-center gap-2 rounded-[var(--r-card)] border-2 border-dashed border-line-strong p-4 text-[14px] font-medium text-accent hover:bg-accent-soft">
                <Plus size={16} /> Écrire mon propre sujet
              </button>
            </div>
          )}
          {st.history_auto && suggestions.length === 0 && !writing && <p className="mb-4 text-[13.5px] text-ink-2">Aucune histoire ne revient assez souvent dans tes lectures pour être proposée. Écris ton sujet toi-même.</p>}
          {(picked || writing || !fromReadings) && (
            <div className="card p-5">
              {picked && (
                <button onClick={() => setPicked(null)} className="mb-3 text-[13px] text-accent hover:underline">
                  ‹ Revenir aux suggestions
                </button>
              )}
              <TopicWizard key={picked?.key ?? "libre"} embedded initial={picked ? { prompt: picked.prompt, name: picked.name } : {}} onCreated={onCreated} />
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── 8. La languette ─────────────────────────────────────────────────────────

const LANGUETTE = [
  { tone: "bg-ink-3 opacity-40", caption: "Au repos : une fine barre au bord droit de l'écran. Glisse-la pour la déplacer." },
  { tone: "bg-accent", caption: "Devant un article de presse, elle prend la couleur d'accent." },
  { tone: "bg-accent", caption: "Survole-la : Enregistrer, Suivre, ou Vérifier l'article avec d'autres médias.", card: true },
  { tone: "bg-ok", caption: "Enregistré : l'article attend ta décision dans « Enregistrements »." },
];

export function WidgetStep({ settings: st, onChange }: { settings: Settings; onChange: Patch }) {
  const [phase, setPhase] = useState(0);
  const [seen, setSeen] = useState<{ title: string; article: boolean } | null>(null);
  useEffect(() => {
    const t = setInterval(() => setPhase((p) => (p + 1) % LANGUETTE.length), 2800);
    return () => clearInterval(t);
  }, []);
  // Essai : la languette repère-t-elle l'article ouvert ? (seulement si l'option est active)
  useEffect(() => {
    if (!inTauri || !st.detect_page) return;
    const off = listen<{ url: string; title: string } | null>("browser-page", async (e) => {
      if (!e.payload) return;
      try {
        const c = await api<PageCheck>("/page/check", { method: "POST", body: { url: e.payload.url, title: e.payload.title } });
        setSeen({ title: e.payload.title || e.payload.url, article: c.is_article });
      } catch {
        /* moteur occupé : l'essai reste facultatif */
      }
    });
    return () => void off.then((f) => f());
  }, [st.detect_page]);
  const s = LANGUETTE[phase];
  return (
    <div>
      <StepTitle eyebrow="La languette" sub="Un raccourci vers openMedia depuis ton navigateur, sans extension : enregistre un article, fais-en un sujet, ou vérifie-le en quelques secondes.">
        Garde un article sous la main.
      </StepTitle>
      <div className="grid gap-6 sm:grid-cols-[1fr_1fr]">
        <div>
          <div className="relative h-[200px] overflow-hidden rounded-2xl border border-line-strong bg-surface" aria-hidden>
            <div className="flex h-7 items-center gap-1.5 border-b border-line px-3">
              <span className="size-2 rounded-full bg-fill-strong" />
              <span className="size-2 rounded-full bg-fill-strong" />
              <span className="ml-2 h-3 w-40 rounded bg-fill" />
            </div>
            <div className="space-y-2 p-4 pr-10">
              <div className={`h-4 rounded transition-colors duration-500 ${phase > 0 ? "w-4/5 bg-ink/70" : "w-3/5 bg-fill-strong"}`} />
              <div className="h-2.5 w-full rounded bg-fill" />
              <div className="h-2.5 w-11/12 rounded bg-fill" />
              <div className="h-2.5 w-4/6 rounded bg-fill" />
            </div>
            <motion.span layout className={`absolute right-0 top-[70px] h-[54px] w-[5px] rounded-l-full transition-colors duration-500 ${s.tone}`} />
            <AnimatePresence>
              {s.card && (
                <motion.div initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }} transition={spring.smooth} className="glass absolute right-0 top-[52px] w-[200px] rounded-l-2xl p-3">
                  <p className="text-[11px] text-ink-2">Ton média</p>
                  <div className="mt-1 h-2.5 w-full rounded bg-ink/60" />
                  <div className="mt-2.5 flex gap-1">
                    <span className="inline-flex items-center gap-0.5 rounded-full bg-accent-fill px-1.5 py-0.5 text-[10px] text-white">
                      <Bookmark size={9} /> Enregistrer
                    </span>
                    <span className="rounded-full bg-fill px-1.5 py-0.5 text-[10px] text-ink">Suivre</span>
                    <span className="rounded-full bg-fill px-1.5 py-0.5 text-[10px] text-ink">Vérifier</span>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
          <p className="mt-2.5 min-h-[40px] text-[13.5px] leading-snug text-ink-2" aria-live="polite">
            {s.caption}
          </p>
          <ul className="mt-2 space-y-1 text-[13px] text-ink-2">
            <li>
              <kbd className="rounded-md bg-fill px-1.5 py-0.5 text-[12px] font-medium text-ink">Ctrl Alt S</kbd> enregistre l'article ouvert.
            </li>
            <li>
              <kbd className="rounded-md bg-fill px-1.5 py-0.5 text-[12px] font-medium text-ink">Ctrl Alt N</kbd> enregistre le lien copié.
            </li>
            <li>Tu peux aussi y glisser un lien depuis ton navigateur.</li>
          </ul>
        </div>
        <div>
          <p className="mb-3 text-[13.5px] leading-snug text-ink-2">{PAGE_WATCH}</p>
          <PageWatchRows settings={st} onChange={onChange} />
          {inTauri && (
            <Button
              className="mt-4"
              onClick={async () => {
                const w = await WebviewWindow.getByLabel("bulle");
                await w?.show();
                void emitTo("bulle", "bulle-demo");
              }}
            >
              Montre-moi la languette
            </Button>
          )}
          {st.detect_page && (
            <div className="mt-4 rounded-xl bg-fill/60 p-3 text-[13px]">
              {seen ? (
                <p className={seen.article ? "text-ok" : "text-ink-2"}>
                  {seen.article ? <CircleCheck size={14} className="mr-1 inline" /> : null}
                  {seen.article ? `Article repéré : « ${seen.title} ». La languette est prête.` : `Page vue : « ${seen.title} », ce n'est pas un article de presse.`}
                </p>
              ) : (
                <p className="text-ink-2">Essai facultatif : ouvre un article de presse dans ton navigateur, la languette devrait s'allumer.</p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── 9. C'est prêt ───────────────────────────────────────────────────────────

export function DoneStep({ settings: st, topics }: { settings: Settings; topics: Topic[] }) {
  const hours = (st.run_hours ?? []).map((h) => h.replace(":", " h ")).join(" et ");
  return (
    <div>
      <StepTitle eyebrow="C'est prêt" sub="Voici où retrouver chaque chose. Tu peux revoir ce tutoriel quand tu veux, dans Réglages › Général.">
        Bonne lecture.
      </StepTitle>
      <ul className="card divide-y divide-line overflow-hidden">
        {topics.slice(0, 4).map((t) => (
          <li key={t.id} className="flex items-center gap-3 px-4 py-3">
            <span className="grid size-6 shrink-0 place-items-center">{t.running ? <Spinner size={16} /> : t.latest ? <CircleCheck size={18} className="text-ok" /> : failed(t) ? <span className="text-[15px] font-bold text-deny">!</span> : <span className="size-2 rounded-full bg-fill-strong" />}</span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[14.5px] font-medium text-ink">{t.name}</span>
              {failed(t) && !t.running ? (
                <span className="block text-[12.5px] leading-snug text-deny">Le premier passage a échoué : {t.last_run!.error}</span>
              ) : (
                <span className="block text-[12.5px] text-ink-2">{t.running ? "Premier passage en cours : collecte, tri, recoupement…" : t.latest ? "Première fiche prête." : "En attente de son passage."}</span>
              )}
            </span>
            {failed(t) && !t.running && <RetryButton topicId={t.id} />}
          </li>
        ))}
      </ul>
      <div className="mt-5 grid gap-3 sm:grid-cols-3">
        <Tip title="Aujourd'hui">Les sujets qui ont bougé depuis ta dernière visite, et le Brief.</Tip>
        <Tip title="Le Brief">{hours ? `Après chaque passage, à ${hours}. ` : ""}Le rythme se règle dans Réglages › Général.</Tip>
        <Tip title="Confidentialité">Tes choix de ce tutoriel se changent dans Réglages › Confidentialité.</Tip>
      </div>
    </div>
  );
}

const failed = (t: Topic) => !t.latest && t.last_run?.status === "error";

/** Réessayer un passage depuis le tutoriel ; si le moteur est en cause, « Retour » mène à son choix. */
function RetryButton({ topicId }: { topicId: number }) {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <span className="flex shrink-0 flex-col items-end gap-1">
      <Button
        size="sm"
        busy={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await api(`/topics/${topicId}/run`, { method: "POST" });
            await qc.invalidateQueries({ queryKey: ["topics"] });
          } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        Réessayer
      </Button>
      {error && <span className="max-w-[240px] text-right text-[11.5px] text-deny">{error}</span>}
    </span>
  );
}

function Tip({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-2xl bg-fill/60 p-4">
      <p className="text-[14px] font-semibold text-ink">{title}</p>
      <p className="mt-1 text-[13px] leading-snug text-ink-2">{children}</p>
    </div>
  );
}
