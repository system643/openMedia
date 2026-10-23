// Le tutoriel du premier lancement : il explique openMedia, fait choisir l'IA, montre ce qui
// part et où, recueille l'accord sur les conditions de fonctionnement (le suivi par une IA),
// propose les options (toutes coupées), fait créer un premier sujet et présente la languette.
// Il reprend là où on l'a laissé, et se relance depuis Réglages › Général.

import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import { ArrowLeft } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { engineReady } from "../../components/EngineChoice";
import { Logo } from "../../components/Logo";
import { syncLanguette } from "../../components/PrivacyControls";
import { Button } from "../../components/ui";
import { api, inTauri } from "../../lib/api";
import { nav } from "../../lib/nav";
import type { Settings, Topic } from "../../lib/types";
import { ConditionsStep, DoneStep, EngineStep, HowItWorks, OptionsStep, ScanStep, TopicStep, Welcome, WidgetStep, type ScanResult } from "./steps";

const STEPS = ["bienvenue", "fonctionnement", "moteur", "conditions", "options", "lectures", "sujet", "languette", "pret"] as const;
type StepId = (typeof STEPS)[number];

/** Affiché tant que le tutoriel n'est pas fini, ou que l'accord a été retiré. */
export function Onboarding() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<Settings>("/settings") });
  const [later, setLater] = useState(false);
  const st = settings.data;
  // « Revoir le tutoriel », ou l'accord retiré : le tutoriel revient, même après « Plus tard ».
  useEffect(() => setLater(false), [st?.onboarding_done, st?.consent_at]);
  if (!st || later || (st.onboarding_done && st.consent_at)) return null;
  return <Flow settings={st} onLater={() => setLater(true)} />;
}

function Flow({ settings: st, onLater }: { settings: Settings; onLater: () => void }) {
  const qc = useQueryClient();
  // L'accord retiré après le tutoriel : on reprend aux conditions.
  const resumeAt = st.onboarding_done ? STEPS.indexOf("conditions") : Math.min(Math.max(0, st.onboarding_step || 0), STEPS.length - 1);
  const [index, setIndex] = useState(resumeAt);
  const [direction, setDirection] = useState(1);
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [created, setCreated] = useState<Topic | null>(null);
  const [accepting, setAccepting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const body = useRef<HTMLDivElement>(null);
  const topics = useQuery({
    queryKey: ["topics"],
    queryFn: () => api<Topic[]>("/topics"),
    // Pendant le premier passage, l'avancement se suit en direct.
    refetchInterval: (q) => ((q.state.data ?? []).some((t) => t.running) ? 3000 : false),
  });
  const active = (topics.data ?? []).filter((t) => t.status !== "archived");

  /** Enregistre un réglage : l'écran change tout de suite, le moteur confirme ensuite. */
  const patch = useCallback(
    async (change: Partial<Settings>) => {
      setError(null);
      qc.setQueryData<Settings>(["settings"], (old) => (old ? { ...old, ...change } : old));
      syncLanguette(change);
      try {
        qc.setQueryData(["settings"], await api<Settings>("/settings", { method: "PATCH", body: change }));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        void qc.invalidateQueries({ queryKey: ["settings"] });
      }
    },
    [qc],
  );

  const id: StepId = STEPS[index];
  const applies = (s: StepId) => s !== "lectures" || (st.history_auto && (st.history_sources ?? []).length > 0);
  const go = (to: number) => {
    setDirection(to > index ? 1 : -1);
    setIndex(to);
    void patch({ onboarding_step: to });
  };
  const next = () => {
    let to = index + 1;
    while (to < STEPS.length - 1 && !applies(STEPS[to])) to++;
    go(to);
  };
  const back = () => {
    let to = index - 1;
    while (to > 0 && !applies(STEPS[to])) to--;
    go(to);
  };

  // Le focus suit l'étape : un lecteur d'écran annonce son titre.
  useEffect(() => {
    body.current?.scrollTo({ top: 0 });
    // Sans anneau de focus : ce n'est pas une navigation au clavier.
    const t = setTimeout(() => body.current?.querySelector<HTMLElement>("[data-step-title]")?.focus({ preventScroll: true, focusVisible: false } as FocusOptions), 260);
    return () => clearTimeout(t);
  }, [index]);

  async function accept() {
    setAccepting(true);
    setError(null);
    try {
      // L'heure de l'accord est celle du moteur.
      qc.setQueryData(["settings"], await api<Settings>("/settings", { method: "PATCH", body: { consent_at: true } }));
      next();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAccepting(false);
    }
  }

  async function finish(open?: number) {
    await patch({ onboarding_done: true, onboarding_step: 0 });
    void qc.invalidateQueries();
    nav.go(open ? { name: "topic", id: open } : { name: "today" });
  }

  const visible = STEPS.filter(applies);
  const position = visible.indexOf(id);
  const historyNeedsBrowser = id === "options" && st.history_auto && !(st.history_sources ?? []).length;
  const blocked =
    (id === "moteur" && !engineReady(st)) ||
    (id === "conditions" && !st.consent_at) ||
    historyNeedsBrowser ||
    (id === "lectures" && !scan) ||
    (id === "sujet" && active.length === 0);
  const hint =
    id === "moteur" && !engineReady(st)
      ? "Choisis une IA pour continuer."
      : historyNeedsBrowser
        ? "Coche au moins un navigateur, ou coupe l'option."
        : id === "sujet" && active.length === 0
          ? "Suis au moins un sujet pour terminer."
          : null;
  const firstTopic = created ?? active[0];

  return (
    <Dialog.Root open onOpenChange={(o) => !o && onLater()}>
      <Dialog.Portal>
        <Dialog.Content aria-describedby={undefined} className="fixed inset-0 z-[60] flex flex-col bg-paper outline-none" onEscapeKeyDown={(e) => e.preventDefault()}>
          {/* Une lueur discrète derrière le contenu, comme un écran d'accueil. */}
          <div aria-hidden className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_70%_45%_at_50%_-5%,var(--accent-soft),transparent)]" />
          <header className="relative z-10 flex items-center gap-3 px-6 pb-3 pt-5">
            <Logo size={22} />
            <Dialog.Title className="text-[13px] font-semibold text-ink">Bienvenue dans openMedia</Dialog.Title>
            <ol className="mx-auto flex items-center gap-1.5" aria-label={`Étape ${position + 1} sur ${visible.length}`}>
              {visible.map((s, i) => (
                <li key={s} className="relative h-1.5 w-7 overflow-hidden rounded-full bg-fill-strong">
                  <motion.span className="absolute inset-y-0 left-0 rounded-full bg-accent" initial={false} animate={{ width: i < position ? "100%" : i === position ? "50%" : "0%" }} transition={{ type: "spring", stiffness: 300, damping: 34 }} />
                </li>
              ))}
            </ol>
            <span className="text-[12px] text-ink-3">≈ 3 min</span>
            {id !== "pret" && (
              <Button variant="ghost" size="sm" onClick={onLater}>
                Plus tard
              </Button>
            )}
          </header>

          <div ref={body} className="scroll-area relative z-10 min-h-0 flex-1">
            <div className="mx-auto w-full max-w-[780px] px-6 pb-10 pt-6">
              <AnimatePresence mode="wait" initial={false} custom={direction}>
                <motion.section
                  key={id}
                  custom={direction}
                  initial={{ opacity: 0, x: 28 * direction }}
                  animate={{ opacity: 1, x: 0, transition: { type: "spring", stiffness: 340, damping: 34 } }}
                  exit={{ opacity: 0, x: -20 * direction, transition: { duration: 0.12 } }}
                >
                  {id === "bienvenue" && <Welcome />}
                  {id === "fonctionnement" && <HowItWorks />}
                  {id === "moteur" && <EngineStep settings={st} />}
                  {id === "conditions" && <ConditionsStep settings={st} onChange={patch} accepting={accepting} onAccept={accept} onLocal={() => go(STEPS.indexOf("moteur"))} onLater={onLater} />}
                  {id === "options" && <OptionsStep settings={st} onChange={patch} />}
                  {id === "lectures" && <ScanStep settings={st} result={scan} onDone={setScan} />}
                  {id === "sujet" && <TopicStep settings={st} suggestions={scan?.topics ?? []} topics={active} created={created} onCreated={setCreated} />}
                  {id === "languette" && <WidgetStepWithPatch settings={st} onChange={patch} />}
                  {id === "pret" && <DoneStep settings={st} topics={active.length ? active : created ? [created] : []} />}
                </motion.section>
              </AnimatePresence>
              {error && <p className="mt-4 text-[13px] text-deny">{error}</p>}
            </div>
          </div>

          <footer className="relative z-10 border-t border-line bg-[color-mix(in_srgb,var(--paper)_82%,transparent)] backdrop-blur-xl">
            <div className="mx-auto flex w-full max-w-[780px] items-center gap-3 px-6 py-3.5">
              {index > 0 && id !== "pret" ? (
                <Button variant="ghost" icon={<ArrowLeft size={14} />} onClick={back}>
                  Retour
                </Button>
              ) : (
                <span />
              )}
              <span className="ml-auto text-[12.5px] text-ink-2">{hint}</span>
              {id === "pret" ? (
                <>
                  <Button onClick={() => void finish()}>Aller à Aujourd'hui</Button>
                  {firstTopic && (
                    <Button variant="primary" onClick={() => void finish(firstTopic.id)}>
                      Ouvrir mon sujet
                    </Button>
                  )}
                </>
              ) : (id === "conditions" && !st.consent_at) || (id === "sujet" && active.length === 0) ? null : (
                <Button variant="primary" disabled={blocked} onClick={next}>
                  {id === "bienvenue" ? "Commencer" : "Continuer"}
                </Button>
              )}
            </div>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** La languette se règle depuis le tutoriel : elle s'affiche dès qu'on l'active. */
function WidgetStepWithPatch({ settings, onChange }: { settings: Settings; onChange: (b: Partial<Settings>) => void }) {
  return (
    <WidgetStep
      settings={settings}
      onChange={(b) => {
        onChange(b);
        if (b.detect_page && inTauri) void WebviewWindow.getByLabel("bulle").then((w) => w?.show());
      }}
    />
  );
}
