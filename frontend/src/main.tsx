import "@fontsource-variable/inter";
import "@fontsource/ibm-plex-mono/400.css";
import "./index.css";
import "./lib/pageRecovery";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import * as RTooltip from "@radix-ui/react-tooltip";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { Toaster } from "sonner";
import App from "./App";
import { ApiError } from "./lib/api";
import { PageErrorBoundary } from "./components/layout/PageErrorBoundary";

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      refetchOnWindowFocus: false,
      retry: (n, err) => !(err instanceof ApiError && err.status < 500) && n < 2,
    },
  },
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={qc}>
      <RTooltip.Provider>
        <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, "") || "/"}>
          <PageErrorBoundary><App /></PageErrorBoundary>
        </BrowserRouter>
        <Toaster position="top-right" closeButton toastOptions={{ className: "!bg-panel !border-line !text-fg !shadow-pop !rounded-md !text-[13px]" }} />
      </RTooltip.Provider>
    </QueryClientProvider>
  </StrictMode>,
);
