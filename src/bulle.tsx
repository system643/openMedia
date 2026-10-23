// La languette : une barre fine collée au bord droit de l'écran, toujours au premier plan. Elle
// prend la couleur d'accent quand le navigateur affiche un article de presse, et s'ouvre seule
// quelques secondes la première fois (sans prendre le focus) pour proposer de l'enregistrer,
// de le suivre ou de le vérifier ; au survol, elle s'ouvre aussi en carte. On peut y glisser
// un lien, enregistrer un lien copié (Ctrl+Alt+N) ou la page ouverte (Ctrl+Alt+S).

import "./styles.css";
import { invoke } from "@tauri-apps/api/core";
import { emitTo, listen } from "@tauri-apps/api/event";
import { PhysicalPosition, PhysicalSize, currentMonitor, getCurrentWindow } from "@tauri-apps/api/window";
import { readText } from "@tauri-apps/plugin-clipboard-manager";
import { register, unregister } from "@tauri-apps/plugin-global-shortcut";
import { Bookmark, Check, ExternalLink, Plus, ShieldCheck, X } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { StrictMode, useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { urlFromDrop } from "./components/DropCard";
import { cost, modelName, Reads } from "./components/FactPanel";
import { openLink } from "./components/Facts";
import { Logo } from "./components/Logo";
import { Spinner } from "./components/ui";
import { api, inTauri, waitForBackend } from "./lib/api";
import { STATUS_LABEL } from "./lib/format";
import { restoreTheme } from "./lib/theme";
import type { Factcheck, PageCheck, Recording, Settings } from "./lib/types";

restoreTheme();

const BAR = { w: 7, h: 60 };
const CARD = { w: 340, h: 146 };
const RESULT = { w: 360, h: 380 };
// Devant un article pas encore enregistré : la carte s'ouvre après 3 s sur la page, pour 6 s.
const NUDGE_AFTER = 3000;
const NUDGE_FOR = 6000;
const DOT = {
  confirme: "bg-ok",
  non_confirme: "bg-warn",
  conteste: "bg-contest",
  dementi: "bg-deny",
} as const;
const SHORTCUT_LINK = "CommandOrControl+Alt+N";
const SHORTCUT_PAGE = "CommandOrControl+Alt+S";

interface Page {
  url: string;
  title: string;
  browser: string;
}

// Hauteur de la languette sur le bord : fraction de la zone de travail (sans la barre des tâches).
let anchor = storedAnchor();

function storedAnchor(): number {
  try {
    const v = Number(localStorage.getItem("languette-y"));
    return v > 0 && v < 1 ? v : 0.62;
  } catch {
    return 0.62;
  }
}

function saveAnchor() {
  try {
    localStorage.setItem("languette-y", String(anchor));
  } catch {
    /* position non mémorisée */
  }
}

// Les pages déjà proposées : la carte ne s'ouvre seule qu'une fois par article.
const nudged = new Set<string>(storedNudged());

function storedNudged(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem("languette-vues") ?? "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function markNudged(url: string) {
  nudged.add(url);
  try {
    localStorage.setItem("languette-vues", JSON.stringify([...nudged].slice(-200)));
  } catch {
    /* non mémorisé : la carte pourra se rouvrir après un redémarrage */
  }
}

/** Colle la fenêtre au bord droit de l'écran, centrée sur la hauteur choisie. */
async function layout(to: { w: number; h: number }) {
  if (!inTauri) return;
  const m = await currentMonitor();
  if (!m) return;
  const win = getCurrentWindow();
  const s = m.scaleFactor;
  const { position: wp, size: ws } = m.workArea;
  const w = Math.round(to.w * s);
  const h = Math.round(to.h * s);
  const y = Math.min(Math.max(Math.round(wp.y + anchor * ws.height - h / 2), wp.y), wp.y + ws.height - h);
  const pos = new PhysicalPosition(wp.x + ws.width - w, y);
  const growing = w > (await win.outerSize()).width;
  // En grandissant, on déplace d'abord (sinon la carte déborde un instant de l'écran).
  if (growing) await win.setPosition(pos);
  await win.setSize(new PhysicalSize(w, h));
  if (!growing) await win.setPosition(pos);
}

function Languette() {
  const [page, setPage] = useState<Page | null>(null);
  const [check, setCheck] = useState<PageCheck | null>(null);
  const [open, setOpen] = useState(false);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState<Recording | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [quick, setQuick] = useState<{ title: string; fc: Factcheck } | null>(null);
  const [checking, setChecking] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const hovering = useRef(false);
  const opened = useRef(false);
  const nudgeOn = useRef(false);
  // La carte reste ouverte pendant la vérification, puis jusqu'à ce que le résultat ait été vu.
  const stay = useRef<"checking" | "result" | "seen" | null>(null);
  const drag = useRef<{
    y: number;
    anchor: number;
    moved: boolean;
    scale: number;
    height: number;
  } | null>(null);

  const show = useCallback(async (v: boolean) => {
    clearTimeout(timer.current);
    if (v) await layout(CARD);
    opened.current = v;
    setOpen(v);
    if (!v) {
      stay.current = null;
      setSaved(null);
      setError(null);
      setQuick(null);
      await layout(BAR);
    }
  }, []);

  /** Referme la carte un peu après que la souris l'a quittée. */
  const closeSoon = useCallback(
    (ms = 550) => {
      clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        if (!hovering.current && !stay.current) void show(false);
      }, ms);
    },
    [show],
  );

  const showRef = useRef(show);
  showRef.current = show;
  const closeRef = useRef(closeSoon);
  closeRef.current = closeSoon;

  // La page ouverte dans le navigateur, envoyée par la coque Rust quand elle change.
  useEffect(() => {
    if (!inTauri) return;
    void layout(BAR);
    void invoke<Page | null>("current_page").then(setPage);
    const off = listen<Page | null>("browser-page", (e) => setPage(e.payload));
    const offNudge = listen<boolean>("page-nudge", (e) => (nudgeOn.current = e.payload));
    // « Montre-moi » du tutoriel : la carte s'ouvre quelques secondes, sans prendre la main.
    const offDemo = listen("bulle-demo", () => void showRef.current(true).then(() => !hovering.current && closeRef.current(5000)));
    void waitForBackend()
      .then(() => api<Settings>("/settings"))
      .then((st) => {
        // Options coupées tant que le lecteur ne les a pas activées.
        nudgeOn.current = st.page_nudge ?? false;
        return invoke("set_page_watch", { enabled: st.detect_page ?? false });
      })
      .catch(() => undefined);
    return () => {
      void off.then((f) => f());
      void offNudge.then((f) => f());
      void offDemo.then((f) => f());
    };
  }, []);

  // Est-ce un article ? Déjà enregistré ? (sans réseau ni modèle, côté moteur)
  useEffect(() => {
    setCheck(null);
    setSaved(null);
    if (!page) return;
    let stale = false;
    void waitForBackend()
      .then(() =>
        api<PageCheck>("/page/check", {
          method: "POST",
          body: { url: page.url, title: page.title },
        }),
      )
      .then((c) => !stale && setCheck(c))
      .catch(() => undefined);
    return () => {
      stale = true;
    };
  }, [page]);

  const save = useCallback(
    async (url: string, title = "") => {
      setBusy(true);
      setError(null);
      try {
        await waitForBackend();
        const rec = await api<Recording>("/recordings", {
          method: "POST",
          body: { url, title },
        });
        setSaved(rec);
        if (page && url === page.url) setCheck((c) => c && { ...c, recording_id: rec.id, status: rec.status });
        void emitTo("main", "recordings-changed");
        if (!hovering.current) closeSoon(1800);
        return rec;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        if (!hovering.current) closeSoon(4000);
        return null;
      } finally {
        setBusy(false);
      }
    },
    [page, closeSoon],
  );

  // Un article pas encore enregistré, regardé 3 s : la carte s'ouvre seule, une fois par page.
  useEffect(() => {
    if (!page || !check?.is_article || check.recording_id || !nudgeOn.current || nudged.has(page.url)) return;
    const t = setTimeout(() => {
      if (opened.current || drag.current) return;
      markNudged(page.url);
      void show(true).then(() => !hovering.current && closeSoon(NUDGE_FOR));
    }, NUDGE_AFTER);
    return () => clearTimeout(t);
  }, [page, check, show, closeSoon]);

  /** « Vérifier » : recoupement rapide par Haiku seul ; une page vérifiée il y a moins de 12 h
   * rend son résultat tout de suite, sans nouvel appel. */
  const verify = useCallback(
    async (p: Page) => {
      clearTimeout(timer.current);
      stay.current = "checking";
      setChecking(true);
      setError(null);
      try {
        await waitForBackend();
        const fc = await api<Factcheck>("/page/quickcheck", {
          method: "POST",
          body: { url: p.url, title: p.title },
        });
        if (!opened.current) return; // carte fermée entre-temps : le résultat reste gardé côté moteur
        await layout(RESULT);
        setQuick({ title: p.title || p.url, fc });
        stay.current = hovering.current ? "seen" : "result";
      } catch (e) {
        stay.current = null;
        setError(e instanceof Error ? e.message : String(e));
        if (!hovering.current) closeSoon(4000);
      } finally {
        setChecking(false);
      }
    },
    [closeSoon],
  );

  const follow = useCallback(
    async (p: Page) => {
      const rec = await save(p.url, p.title);
      if (rec) {
        void invoke("open_main", { route: `follow:${rec.id}` });
        void show(false);
      }
    },
    [save, show],
  );

  // Raccourcis globaux : le lien copié, ou la page ouverte.
  const latest = useRef({ page, save, show });
  latest.current = { page, save, show };
  useEffect(() => {
    if (!inTauri) return;
    void register(SHORTCUT_LINK, async (e) => {
      if (e.state !== "Pressed") return;
      const text = (await readText().catch(() => "")).trim();
      if (!/^https?:\/\//.test(text)) return;
      await latest.current.show(true);
      void latest.current.save(text);
    }).catch(() => undefined);
    void register(SHORTCUT_PAGE, async (e) => {
      if (e.state !== "Pressed") return;
      const p = latest.current.page;
      if (!p) return;
      await latest.current.show(true);
      void latest.current.save(p.url, p.title);
    }).catch(() => undefined);
    return () => {
      void unregister(SHORTCUT_LINK).catch(() => undefined);
      void unregister(SHORTCUT_PAGE).catch(() => undefined);
    };
  }, []);

  const article = !!check?.is_article;
  const recordingId = saved?.id ?? check?.recording_id ?? null;
  const dropHandlers = {
    onDragOver: (e: React.DragEvent) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
      if (!over) setOver(true);
      if (!open) void show(true);
    },
    onDragLeave: () => setOver(false),
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      setOver(false);
      const url = urlFromDrop(e.dataTransfer);
      if (url) void save(url);
    },
  };

  if (!open) {
    const tone = recordingId ? "bg-ok opacity-90" : article ? "bg-accent opacity-100" : "bg-ink-3 opacity-35";
    return (
      <div
        className="flex h-full cursor-pointer items-center justify-end"
        {...dropHandlers}
        onPointerEnter={() => {
          hovering.current = true;
          clearTimeout(timer.current);
          timer.current = setTimeout(() => !drag.current && void show(true), 350);
        }}
        onPointerLeave={() => {
          hovering.current = false;
          clearTimeout(timer.current);
        }}
        onPointerDown={async (e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          clearTimeout(timer.current);
          const m = inTauri ? await currentMonitor() : null;
          drag.current = {
            y: e.screenY,
            anchor,
            moved: false,
            scale: m?.scaleFactor ?? 1,
            height: m?.workArea.size.height ?? window.screen.availHeight,
          };
        }}
        onPointerMove={(e) => {
          // Glisser verticalement : la languette se déplace le long du bord.
          const d = drag.current;
          if (!d || e.buttons !== 1) return;
          const dy = e.screenY - d.y;
          if (!d.moved && Math.abs(dy) < 4) return;
          d.moved = true;
          anchor = Math.min(0.97, Math.max(0.03, d.anchor + (dy * d.scale) / d.height));
          void layout(BAR);
        }}
        onPointerUp={() => {
          const d = drag.current;
          drag.current = null;
          if (d?.moved) saveAnchor();
          else void show(true);
        }}
        title="openMedia : survole pour enregistrer l'article ouvert"
      >
        <motion.span layout className={`block h-[calc(100%-8px)] rounded-l-full transition-[background-color,opacity,width] duration-300 ${tone}`} style={{ width: article || recordingId ? 5 : 4 }} />
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: 16 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ type: "spring", stiffness: 520, damping: 38 }}
      className="h-full py-1.5 pl-1.5"
      onPointerEnter={() => {
        hovering.current = true;
        if (stay.current === "result") stay.current = "seen";
        clearTimeout(timer.current);
      }}
      onPointerLeave={() => {
        hovering.current = false;
        if (stay.current === "seen") stay.current = null;
        if (!busy) closeSoon();
      }}
      {...dropHandlers}
    >
      <div className={`glass flex h-full flex-col rounded-l-[var(--r-sheet)] px-4 py-3 ${over ? "outline-2 -outline-offset-2 outline-dashed outline-accent" : ""}`}>
        <div className="flex items-center gap-2 text-[12px] text-ink-2">
          <Logo size={16} />
          <span className="min-w-0 flex-1 truncate">{over ? "Dépose le lien pour l'enregistrer" : quick ? "Vérification rapide" : page ? (article ? check?.media : `${page.browser} · pas un article`) : "openMedia"}</span>
          <button onClick={() => void invoke("open_main", { route: null })} title="Ouvrir openMedia" aria-label="Ouvrir openMedia" className="grid size-6 place-items-center rounded-md text-ink-3 hover:bg-fill hover:text-ink">
            <ExternalLink size={13} />
          </button>
          <button onClick={() => void show(false)} title="Fermer" aria-label="Fermer" className="-mr-1.5 grid size-6 place-items-center rounded-md text-ink-3 hover:bg-fill hover:text-ink">
            <X size={13} />
          </button>
        </div>

        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={quick ? "quick" : saved ? "saved" : "page"} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-1.5 flex min-h-0 flex-1 flex-col">
            {quick ? (
              <QuickResult title={quick.title} fc={quick.fc} />
            ) : saved ? (
              <p className="line-clamp-2 text-[13.5px] font-medium leading-snug text-ink">{saved.title}</p>
            ) : page && !over ? (
              <p className={`line-clamp-2 text-[13.5px] leading-snug ${article ? "font-medium text-ink" : "text-ink-2"}`}>{page.title || page.url}</p>
            ) : (
              <p className="text-[13px] leading-snug text-ink-2">Glisse ici un lien depuis ton navigateur pour l'enregistrer, sans le suivre.</p>
            )}

            {!quick && (
              <div className="mt-auto flex items-center gap-1.5 pt-2">
                {error ? (
                  <p className="line-clamp-2 text-[12px] text-deny">{error}</p>
                ) : checking ? (
                  <span className="inline-flex items-center gap-2 text-[12.5px] text-ink-2">
                    <Spinner size={13} /> Recoupement avec d'autres médias…
                  </span>
                ) : recordingId ? (
                  <>
                    <span className="inline-flex items-center gap-1 text-[12.5px] font-medium text-ok">
                      <Check size={14} /> Enregistré
                    </span>
                    {page && article && (
                      <button onClick={() => void verify(page)} className={`ml-auto ${CHIP} bg-fill text-ink hover:bg-fill-strong`}>
                        <ShieldCheck size={13} /> Vérifier
                      </button>
                    )}
                    <button
                      onClick={() =>
                        void invoke("open_main", {
                          route: `recordings:${recordingId}`,
                        })
                      }
                      className={`${page && article ? "" : "ml-auto"} ${CHIP} text-accent hover:bg-accent-soft`}
                    >
                      Voir
                    </button>
                  </>
                ) : page && !over ? (
                  article ? (
                    <>
                      <button onClick={() => void save(page.url, page.title)} disabled={busy} title="Enregistrer sans suivre (Ctrl Alt S)" className={`${CHIP} bg-accent-fill text-[var(--on-accent)] hover:brightness-110`}>
                        {busy ? <Spinner size={13} /> : <Bookmark size={13} />} Enregistrer
                      </button>
                      <button onClick={() => void follow(page)} disabled={busy} title="Enregistrer, puis en faire un sujet suivi ou l'ajouter à un sujet" className={`${CHIP} bg-fill text-ink hover:bg-fill-strong`}>
                        <Plus size={13} /> Suivre
                      </button>
                      <button
                        onClick={() => void verify(page)}
                        disabled={busy}
                        title="Recouper les faits avec d'autres médias : Haiku seul, quelques secondes, moins d'un dixième de centime"
                        className={`${CHIP} bg-fill text-ink hover:bg-fill-strong`}
                      >
                        <ShieldCheck size={13} /> Vérifier
                      </button>
                    </>
                  ) : (
                    <button onClick={() => void save(page.url, page.title)} disabled={busy} className={`${CHIP} bg-fill text-ink hover:bg-fill-strong`}>
                      {busy ? <Spinner size={13} /> : <Bookmark size={13} />} Enregistrer quand même
                    </button>
                  )
                ) : busy ? (
                  <Spinner size={14} />
                ) : null}
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

const CHIP = "inline-flex h-7 items-center gap-1.5 rounded-full px-2.5 text-[12.5px] font-medium disabled:opacity-50";

/** Le verdict de la vérification rapide : chaque affirmation, son statut et les médias qui la portent. */
function QuickResult({ title, fc }: { title: string; fc: Factcheck }) {
  const sources = new Map((fc.sources ?? []).map((s) => [s.ref, s]));
  return (
    <>
      <p className="line-clamp-1 text-[12.5px] font-medium text-ink">{title}</p>
      {fc.message && <p className="mt-1.5 rounded-lg bg-fill px-2.5 py-1.5 text-[11.5px] leading-snug text-ink-2">{fc.message}</p>}
      {fc.status === "ok" && (
        <div className="-mr-2 mt-2 min-h-0 flex-1 overflow-y-auto pr-2">
          <ul className="space-y-2.5">
            {fc.claims.map((c, i) => (
              <li key={i} className="flex gap-2">
                <span className={`mt-[5px] size-2 shrink-0 rounded-full ${DOT[c.status]}`} />
                <div className="min-w-0">
                  <p className="line-clamp-3 text-[12.5px] leading-snug text-ink">{c.text}</p>
                  <p className="mt-0.5 text-[11.5px] leading-snug text-ink-2">
                    <span className="font-medium">{STATUS_LABEL[c.status]}</span>
                    {[...c.refs, ...c.contradicted_by].slice(1, 5).map((r) => {
                      const src = sources.get(r);
                      return src ? (
                        <button key={r} onClick={() => openLink(src.url)} className={`ml-1.5 underline-offset-2 hover:underline ${c.contradicted_by.includes(r) ? "text-contest" : "text-accent"}`}>
                          {src.name}
                        </button>
                      ) : null;
                    })}
                    {c.note ? <span className="block text-ink-3">{c.note}</span> : null}
                  </p>
                </div>
              </li>
            ))}
          </ul>
          <Reads fc={fc} compact />
        </div>
      )}
      <p className="mt-auto pt-2 text-[11px] text-ink-3">
        {fc.others ?? 0} autre(s) média(s)
        {fc.model ? ` · ${modelName(fc.model)}` : ""}
        {fc.cost_usd ? ` · ${cost(fc)}` : ""}
      </p>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Languette />
  </StrictMode>,
);
