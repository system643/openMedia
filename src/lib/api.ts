// Client de l'API locale. Dans Tauri, l'adresse et le jeton viennent de la coque Rust ;
// dans un navigateur (développement de l'interface seule), on vise le backend lancé à la main.

import { invoke } from "@tauri-apps/api/core";

export const inTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

interface BackendInfo {
  url: string;
  token: string;
}

let info: Promise<BackendInfo> | null = null;

export function backend(): Promise<BackendInfo> {
  info ??= inTauri ? invoke<BackendInfo>("backend_info") : Promise.resolve({ url: "http://127.0.0.1:8765", token: "" });
  return info;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const { url, token } = await backend();
  const res = await fetch(url + path, {
    method: init.method ?? "GET",
    headers: { "Content-Type": "application/json", "X-Token": token },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (!res.ok) {
    let detail = `Erreur ${res.status}`;
    let code: string | undefined;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : detail;
      code = data.code;
    } catch {
      /* corps non JSON */
    }
    throw new ApiError(detail, res.status, code);
  }
  return res.json() as Promise<T>;
}

/** Le moteur Python met quelques secondes à démarrer : on attend qu'il réponde. */
export async function waitForBackend(timeoutMs = 60_000): Promise<void> {
  const { url } = await backend();
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url + "/health");
      if (res.ok) return;
    } catch {
      /* pas encore prêt */
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  throw new Error("Le moteur d'openMedia ne répond pas.");
}

export async function withToken(path: string): Promise<string> {
  const { url, token } = await backend();
  return `${url}${path}${path.includes("?") ? "&" : "?"}token=${token}`;
}
