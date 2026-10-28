import { API } from "./api";
import { useAuth } from "./auth";

/** Report browser errors to Kruvim's own error log (no third-party tracker). At most 5 per page load, never duplicates. */
const sent = new Set<string>();
const MAX = 5;

export function reportError(message: string, detail = "") {
  const key = message.slice(0, 200);
  if (!message || sent.has(key) || sent.size >= MAX) return;
  sent.add(key);
  const token = useAuth.getState().accessToken;
  fetch(`${API}/client-errors`, {
    method: "POST", keepalive: true,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    // Only the route, never the query string: share links and invite codes live there.
    body: JSON.stringify({ message: message.slice(0, 500), detail: detail.slice(0, 4000), path: window.location.pathname.slice(0, 300) }),
  }).catch(() => { /* reporting must never cause another error */ });
}

export function installErrorReporter() {
  window.addEventListener("error", (e) => reportError(`${e.message}`, e.error?.stack || `${e.filename}:${e.lineno}`));
  window.addEventListener("unhandledrejection", (e) => {
    const reason = e.reason;
    if (reason?.name === "ApiError") return;     // API failures are already logged by the server and shown to the user
    reportError(`Unhandled promise rejection: ${reason?.message || String(reason)}`, reason?.stack || "");
  });
}
