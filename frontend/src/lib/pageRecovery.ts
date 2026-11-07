const RELOAD_KEY = "kruvim.page-recovery";

// A tab left open during a deployment can still request an old chunk filename.
// Reload the document once to get the current asset map, retaining the session.
export function reloadAfterPageLoadFailure(): boolean {
  try {
    const lastReload = Number(sessionStorage.getItem(RELOAD_KEY));
    if (lastReload && Date.now() - lastReload < 60_000) return false;
    sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
  } catch {
    // Without a persistent guard, automatic retries could create a reload loop.
    return false;
  }
  window.location.reload();
  return true;
}

export function isPageLoadFailure(error: unknown): boolean {
  return error instanceof Error && /Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module|Loading chunk .+ failed/i.test(error.message);
}

window.addEventListener("vite:preloadError", (event) => {
  if (reloadAfterPageLoadFailure()) event.preventDefault();
});
