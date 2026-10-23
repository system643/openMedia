// Brouillons de sujet : la saisie est enregistrée au fil de la frappe, pour survivre à une
// fermeture de la feuille, de la fenêtre ou de l'application.

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, backend } from "./api";
import type { Cadence } from "./types";

export interface WizardState {
  step: 1 | 2 | 3;
  subject: string;
  angle: string | null;
  custom: string;
  importance: string;
  languages: string;
  cadence?: Cadence | null; // null : le rythme des réglages
  /** Brouillons d'avant les rythmes : fréquence en jours (« general ») et heure. */
  runHour?: string;
  every?: string;
  name?: string;
  kind?: "actualite" | "recherche";
  fields?: string[];
}

export interface Draft {
  id: number;
  title: string;
  data: WizardState;
  updated_at: string;
}

export type SaveStatus = "idle" | "saving" | "saved" | "error";

const DELAY = 700;

export function hasContent(s: WizardState): boolean {
  return !!(s.subject.trim() || s.custom.trim());
}

/** Envoi de dernière chance (fermeture de la page) : `keepalive` laisse partir la requête. */
async function sendNow(id: number | null, data: WizardState) {
  const { url, token } = await backend();
  const path = id ? `/drafts/${id}` : "/drafts";
  void fetch(`${url}${path}?token=${token}`, { method: id ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ data }), keepalive: true });
}

export function useDraftAutosave(state: WizardState, initialId: number | null) {
  const qc = useQueryClient();
  const [draftId, setDraftId] = useState<number | null>(initialId);
  const [status, setStatus] = useState<SaveStatus>(initialId ? "saved" : "idle");
  const idRef = useRef<number | null>(initialId);
  const latest = useRef(state);
  const dirty = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  latest.current = state;

  // Les sauvegardes passent l'une après l'autre : jamais deux brouillons pour une même saisie.
  const save = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
    if (!dirty.current || !hasContent(latest.current)) return chain.current;
    dirty.current = false;
    const data = latest.current;
    setStatus("saving");
    chain.current = chain.current
      .then(async () => {
        const d = idRef.current
          ? await api<Draft>(`/drafts/${idRef.current}`, { method: "PUT", body: { data } })
          : await api<Draft>("/drafts", { method: "POST", body: { data } });
        idRef.current = d.id;
        setDraftId(d.id);
        setStatus("saved");
        void qc.invalidateQueries({ queryKey: ["drafts"] });
      })
      .catch(() => {
        dirty.current = true;
        setStatus("error");
      });
    return chain.current;
  }, [qc]);

  useEffect(() => {
    if (!hasContent(state)) return;
    dirty.current = true;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(save, DELAY);
  }, [state, save]);

  // Fermeture de la page ou démontage de la feuille : ce qui n'est pas encore parti part maintenant.
  useEffect(() => {
    const flushOnExit = () => {
      if (dirty.current && hasContent(latest.current)) {
        dirty.current = false;
        void sendNow(idRef.current, latest.current);
      }
    };
    window.addEventListener("pagehide", flushOnExit);
    window.addEventListener("beforeunload", flushOnExit);
    return () => {
      window.removeEventListener("pagehide", flushOnExit);
      window.removeEventListener("beforeunload", flushOnExit);
      if (timer.current) clearTimeout(timer.current);
      flushOnExit();
      setTimeout(() => qc.invalidateQueries({ queryKey: ["drafts"] }), 300);
    };
  }, [qc]);

  const discard = useCallback(async () => {
    if (timer.current) clearTimeout(timer.current);
    dirty.current = false;
    await chain.current;
    if (idRef.current) await api(`/drafts/${idRef.current}`, { method: "DELETE" });
    idRef.current = null;
    void qc.invalidateQueries({ queryKey: ["drafts"] });
  }, [qc]);

  /** Une fois le sujet créé, le brouillon est supprimé côté serveur : plus rien à envoyer. */
  const settle = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    dirty.current = false;
  }, []);

  const currentId = useCallback(() => idRef.current, []);

  return { draftId, status, flush: save, discard, settle, currentId };
}
