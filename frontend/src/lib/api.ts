import { refreshToken, useAuth } from "./auth";
import type { Session, SimEvent } from "./types";

export const API = "/api/v1";

export class ApiError extends Error {
  status: number;
  code: string;
  details?: unknown;
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let refreshing: Promise<boolean> | null = null;

export async function refreshSession(): Promise<boolean> {
  const rt = refreshToken();
  if (!rt) return false;
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const r = await fetch(`${API}/auth/refresh`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: rt }) });
        if (!r.ok) {
          useAuth.getState().clear();
          return false;
        }
        useAuth.getState().setSession((await r.json()) as Session);
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshing = null), 0);
      }
    })();
  }
  return refreshing;
}

function headers(extra?: HeadersInit, json = true): Headers {
  const h = new Headers(extra);
  const { accessToken, orgId } = useAuth.getState();
  if (accessToken) h.set("Authorization", `Bearer ${accessToken}`);
  if (orgId) h.set("X-Org-Id", orgId);
  if (json && !h.has("Content-Type")) h.set("Content-Type", "application/json");
  return h;
}

export async function api<T = any>(path: string, opts: RequestInit & { json?: unknown } = {}, retry = true): Promise<T> {
  const { json, ...init } = opts;
  const isForm = init.body instanceof FormData;
  const req: RequestInit = { ...init, headers: headers(init.headers, !isForm) };
  if (json !== undefined) {
    req.method = req.method || "POST";
    req.body = JSON.stringify(json);
  }
  const r = await fetch(`${API}${path}`, req);
  if (r.status === 401 && retry && (await refreshSession())) return api<T>(path, opts, false);
  const text = await r.text();
  const data = text ? safeJson(text) : null;
  if (!r.ok) {
    const e = (data && (data as any).error) || {};
    throw new ApiError(r.status, e.code || `http_${r.status}`, e.message || r.statusText || "Request failed", e.details);
  }
  return data as T;
}

function safeJson(t: string) {
  try {
    return JSON.parse(t);
  } catch {
    return t;
  }
}

export async function downloadFile(path: string, filename: string, retry = true): Promise<void> {
  const r = await fetch(`${API}${path}`, {headers: headers(undefined, false)});
  if (r.status === 401 && retry && await refreshSession()) return downloadFile(path, filename, false);
  if (!r.ok) throw new Error("The report download failed. Please try again.");
  const url = URL.createObjectURL(await r.blob());
  const a = document.createElement("a");
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Authenticated Server-Sent Events over fetch (EventSource cannot send headers). Reconnects from the last seq. */
export function streamEvents(simId: string, onEvent: (e: SimEvent) => void, opts: { after?: number; onStatus?: (s: "open" | "closed" | "error") => void } = {}) {
  let last = opts.after ?? 0;
  let stopped = false;
  let ctrl: AbortController | null = null;

  async function run() {
    let backoff = 500;
    while (!stopped) {
      ctrl = new AbortController();
      try {
        const r = await fetch(`${API}/simulations/${simId}/events?after=${last}`, { headers: headers(undefined, false), signal: ctrl.signal });
        if (r.status === 401 && (await refreshSession())) continue;
        if (!r.ok || !r.body) throw new Error(`stream ${r.status}`);
        opts.onStatus?.("open");
        backoff = 500;
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          let i;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const chunk = buf.slice(0, i);
            buf = buf.slice(i + 2);
            const data = chunk.split("\n").filter((l) => l.startsWith("data: ")).map((l) => l.slice(6)).join("\n");
            if (!data) continue;
            try {
              const ev = JSON.parse(data) as SimEvent;
              if (ev.seq > last) {
                last = ev.seq;
                onEvent(ev);
              }
            } catch {
              /* ignore malformed chunk */
            }
          }
        }
        opts.onStatus?.("closed");
      } catch (err) {
        if (stopped) return;
        opts.onStatus?.("error");
      }
      if (stopped) return;
      await new Promise((res) => setTimeout(res, backoff));
      backoff = Math.min(backoff * 2, 8000);
    }
  }
  run();
  return () => {
    stopped = true;
    ctrl?.abort();
  };
}
