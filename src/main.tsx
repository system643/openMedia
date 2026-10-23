import "./styles.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { AnimatedLogo } from "./components/Logo";
import { waitForBackend } from "./lib/api";
import { nav } from "./lib/nav";
import { restoreTheme } from "./lib/theme";
import { trackWindowFrame } from "./lib/windowFrame";

restoreTheme();
trackWindowFrame();

// Lien direct vers une vue (?route=topic:12, ?route=corrections…).
const params = new URLSearchParams(location.search);
const initialRoute = params.get("route");
const initialTheme = params.get("theme");
if (initialTheme === "light" || initialTheme === "dark") document.documentElement.dataset.theme = initialTheme;
if (initialRoute) nav.fromRoute(initialRoute);

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, refetchOnWindowFocus: true, retry: 1 } },
});

// Le temps de l'animation d'ouverture : l'app ne la coupe pas, même si le moteur est déjà prêt.
const OPENING_MS = 1500;

/** L'ouverture : le logo s'écrit pendant que le moteur Python démarre, puis l'app apparaît. */
function Boot() {
  const [state, setState] = useState<"wait" | "ready" | "error">("wait");
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const opening = new Promise((done) => setTimeout(done, OPENING_MS));
    const slowTimer = setTimeout(() => setSlow(true), OPENING_MS + 600);
    Promise.all([waitForBackend(), opening]).then(
      () => setState("ready"),
      () => setState("error"),
    );
    return () => clearTimeout(slowTimer);
  }, []);
  return (
    <AnimatePresence mode="wait">
      {state === "ready" ? (
        <motion.div key="app" className="h-full" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.3 }}>
          <App />
        </motion.div>
      ) : (
        <motion.div key="boot" data-tauri-drag-region className="grid h-full place-items-center bg-paper" exit={{ opacity: 0, scale: 1.02, transition: { duration: 0.22 } }}>
          <div className="flex flex-col items-center text-center" data-tauri-drag-region>
            <AnimatedLogo size={92} />
            <motion.p className="serif mt-5 text-[30px] font-semibold tracking-[-0.02em] text-ink" initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.35, delay: 0.9 }}>
              openMedia
            </motion.p>
            <p className={`mt-2 h-5 text-[13px] text-ink-2 transition-opacity duration-300 ${state === "error" || slow ? "opacity-100" : "opacity-0"}`}>
              {state === "error" ? "Le moteur ne répond pas. Relance l'application ; si le problème persiste, réinstalle-la." : "Démarrage du moteur…"}
            </p>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      {/* « Réduire les animations » du système coupe les déplacements, garde les fondus. */}
      <MotionConfig reducedMotion="user">
        <Boot />
      </MotionConfig>
    </QueryClientProvider>
  </StrictMode>,
);
