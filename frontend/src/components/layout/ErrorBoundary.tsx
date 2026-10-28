import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { reportError } from "@/lib/errorReporter";

/** A page that throws while rendering shows a recoverable message instead of a blank app. Resets when `resetKey` changes. */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Page failed to render", error, info.componentStack);
    reportError(`Page failed to render: ${error.message}`, `${error.stack || ""}
${info.componentStack || ""}`);
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.failed && prev.resetKey !== this.props.resetKey) this.setState({ failed: false });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div role="alert" className="mx-auto max-w-md px-6 py-16 text-center">
        <h1 className="text-lg font-semibold">This page could not be shown</h1>
        <p className="mt-2 text-[13px] text-muted">Something unexpected happened while displaying it. Your data is safe. Reload to try again, or open another page from the menu.</p>
        <Button variant="primary" className="mt-5" onClick={() => window.location.reload()}>Reload page</Button>
      </div>
    );
  }
}
