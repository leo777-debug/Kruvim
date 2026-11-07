import { Component, type ReactNode } from "react";
import { isPageLoadFailure, reloadAfterPageLoadFailure } from "@/lib/pageRecovery";

export class PageErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error) {
    console.error("Kruvim page failed to render", error);
    if (isPageLoadFailure(error)) reloadAfterPageLoadFailure();
  }

  render() {
    if (this.state.failed) return <div role="alert" className="flex min-h-screen items-center justify-center bg-bg p-6 text-fg">
      <div className="max-w-md rounded-lg border border-line bg-panel p-6">
        <h1 className="text-lg font-semibold">This page couldn’t open</h1>
        <p className="mt-2 text-sm text-muted">Reload Kruvim to try again. Your saved work is still available.</p>
        <button type="button" className="mt-5 rounded-md bg-brand px-4 py-2 text-sm font-medium text-brand-fg" onClick={() => window.location.reload()}>Reload Kruvim</button>
      </div>
    </div>;
    return this.props.children;
  }
}
