// Les événements du moteur (SSE) : progression des passages, notifications, brief.

import { useQueryClient } from "@tanstack/react-query";
import { isPermissionGranted, requestPermission, sendNotification } from "@tauri-apps/plugin-notification";
import { useEffect, useSyncExternalStore } from "react";
import { inTauri, withToken } from "./api";
import type { ServerEvent } from "./types";

export interface Toast {
  id: number;
  text: string;
  tone: "info" | "error" | "done";
  topicId?: number;
}

let toasts: Toast[] = [];
let seq = 0;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export function pushToast(text: string, tone: Toast["tone"] = "info", topicId?: number) {
  const id = ++seq;
  // Un seul message de progression par sujet : le nouveau remplace l'ancien.
  toasts = [...toasts.filter((t) => topicId === undefined || t.topicId !== topicId), { id, text, tone, topicId }].slice(-4);
  emit();
  setTimeout(() => dismissToast(id), tone === "error" ? 9000 : 5000);
}

export function dismissToast(id: number) {
  toasts = toasts.filter((t) => t.id !== id);
  emit();
}

export function useToasts(): Toast[] {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => toasts,
  );
}

async function notify(title: string, body: string) {
  if (!inTauri) return;
  let ok = await isPermissionGranted();
  if (!ok) ok = (await requestPermission()) === "granted";
  if (ok) sendNotification({ title, body });
}

export function useServerEvents() {
  const qc = useQueryClient();
  useEffect(() => {
    let source: EventSource | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;

    async function connect() {
      const url = await withToken("/events");
      // Le composant a pu être démonté pendant l'attente (mode strict de React, changement de
      // vue) : sans ce garde, une connexion SSE resterait ouverte pour rien. Or le navigateur
      // n'ouvre que 6 connexions par hôte : quelques SSE orphelines suffisent à bloquer l'API.
      if (closed) return;
      source?.close();
      source = new EventSource(url);
      source.onmessage = (msg) => {
        const e = JSON.parse(msg.data) as ServerEvent;
        if (e.type === "run") {
          void qc.invalidateQueries({ queryKey: ["topics"] });
          if (e.stage === "done" || e.stage === "error") {
            void qc.invalidateQueries({ queryKey: ["fiche"] });
            void qc.invalidateQueries({ queryKey: ["fiches"] });
            void qc.invalidateQueries({ queryKey: ["today"] });
            void qc.invalidateQueries({ queryKey: ["calendar"] });
          }
          if (e.message) pushToast(e.message, e.stage === "error" ? "error" : e.stage === "done" ? "done" : "info", e.topic_id);
        } else if (e.type === "notify") {
          void notify(e.title ?? "openMedia", e.body ?? "");
        } else if (e.type === "brief") {
          void qc.invalidateQueries({ queryKey: ["today"] });
          void qc.invalidateQueries({ queryKey: ["briefs"] });
          void notify("Le Brief est prêt", e.headline ?? "");
        } else if (e.type === "correction" || e.type === "announcement") {
          void qc.invalidateQueries({ queryKey: [e.type === "correction" ? "corrections" : "announcements"] });
          if (e.type === "announcement") void qc.invalidateQueries({ queryKey: ["calendar"] });
          void notify(e.title ?? "openMedia", e.body ?? "");
        } else if (e.type === "recording") {
          void qc.invalidateQueries({ queryKey: ["recordings"] });
        } else if (e.type === "recurring") {
          void qc.invalidateQueries({ queryKey: ["recurring"] });
        } else if (e.type === "readings") {
          void qc.invalidateQueries({ queryKey: ["readings"] });
          void qc.invalidateQueries({ queryKey: ["settings"] });
        } else if (e.type === "rhythm") {
          for (const key of ["topics", "rhythm", "costs", "calendar"]) void qc.invalidateQueries({ queryKey: [key] });
          if (e.message) pushToast(e.message, "info", e.topic_id);
        } else if (e.type === "topic" || e.type === "warning") {
          void qc.invalidateQueries({ queryKey: ["topics"] });
          if (e.message) pushToast(e.message, e.type === "warning" ? "error" : "info");
        }
      };
      source.onerror = () => {
        source?.close();
        if (!closed) retry = setTimeout(connect, 3000);
      };
    }

    void connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      source?.close();
    };
  }, [qc]);
}
