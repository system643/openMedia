import { AnimatePresence, motion } from "motion/react";
import { dismissToast, useToasts } from "../lib/events";
import { nav } from "../lib/nav";
import { Spinner } from "./ui";

/** Messages discrets, centrés en bas de la fenêtre : progression des agents, confirmations. */
export function Toasts() {
  const toasts = useToasts();
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-[calc(var(--win-gap,0px)+20px)] z-50 flex flex-col items-center gap-2" aria-live="polite">
      <AnimatePresence initial={false}>
        {toasts.map((t) => (
          <motion.button
            key={t.id}
            layout
            initial={{ opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, scale: 0.98 }}
            transition={{ type: "spring", stiffness: 500, damping: 34 }}
            onClick={() => {
              if (t.topicId) nav.go({ name: "topic", id: t.topicId });
              dismissToast(t.id);
            }}
            className="glass pointer-events-auto flex max-w-[460px] items-center gap-2.5 rounded-full px-4 py-2 text-left text-[13px] text-ink"
          >
            {t.tone === "info" ? <Spinner size={14} /> : <span className={`size-2 shrink-0 rounded-full ${t.tone === "error" ? "bg-deny" : "bg-ok"}`} />}
            <span className={`truncate ${t.tone === "error" ? "text-deny" : ""}`}>{t.text}</span>
          </motion.button>
        ))}
      </AnimatePresence>
    </div>
  );
}
