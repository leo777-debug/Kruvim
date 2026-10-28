import { useQuery } from "@tanstack/react-query";
import { Check, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { SimSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

const key = (userId?: string) => `kruvim.getting-started.dismissed.${userId || "anon"}`;

function Step({ n, done, title, children }: { n: number; done: boolean; title: string; children: ReactNode }) {
  return (
    <li className="flex gap-3">
      <span aria-hidden className={cn("mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold",
        done ? "border-pos bg-pos text-white" : "border-line-strong text-muted")}>{done ? <Check className="h-3.5 w-3.5" /> : n}</span>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium">{title}<span className="sr-only">{done ? " (done)" : " (to do)"}</span></div>
        <div className="mt-0.5 text-[13px] text-muted">{children}</div>
      </div>
    </li>
  );
}

/** First-run guide on Home: what Kruvim is, how agents think (key / shared key / dry run), a first test, the results. */
export function GettingStarted({ recent, onExample }: { recent?: SimSummary[]; onExample: () => void }) {
  const user = useAuth((s) => s.user);
  const orgId = useAuth((s) => s.orgId);
  const [dismissed, setDismissed] = useState(() => { try { return localStorage.getItem(key(user?.id)) === "1"; } catch { return false; } });
  const providers = useQuery({ queryKey: [orgId, "providers"], queryFn: () => api("/providers"), meta: { silent: true } });
  const source: string | undefined = providers.data?.active?.source;
  const finished = recent?.find((s) => s.score != null);
  const steps = [true, !!source && source !== "dryrun", !!recent?.length, !!finished];
  if (dismissed || (recent === undefined) || steps.every(Boolean)) return null;
  const dismiss = () => { setDismissed(true); try { localStorage.setItem(key(user?.id), "1"); } catch { /* private mode */ } };

  return (
    <Card role="region" className="relative mb-6 p-5" aria-labelledby="getting-started-title">
      <Button size="icon-sm" variant="ghost" className="absolute right-3 top-3" aria-label="Hide the getting started guide" onClick={dismiss}><X className="h-4 w-4" /></Button>
      <h2 id="getting-started-title" className="pr-8 text-base font-semibold">Welcome to the Kruvim beta</h2>
      <p className="mt-1 max-w-3xl text-[13px] text-muted">
        Kruvim tests content and questions on simulated people before you publish. Each simulated person has a realistic background drawn from
        public data, reacts in their own words, talks with others, and Kruvim turns it all into a verdict, the reasons behind it and what to fix.
      </p>
      <ol className="mt-4 grid gap-4 md:grid-cols-2">
        <Step n={1} done title="Know what you're looking at">Results are predictions from synthetic people, not polls. <Link className="text-brand" to="/help">How it works</Link></Step>
        <Step n={2} done={steps[1]} title="Choose how the agents think">
          {source === "org" ? "Using your own model key." : source === "platform" || source === "env" ? <>Using Kruvim's shared beta key with a daily allowance. <Link className="text-brand" to="/settings?tab=model-keys">Add your own key</Link> for more.</>
            : <>No model connected yet, so tests run as a free <em>dry run</em> with formula-based answers. <Link className="text-brand" to="/settings?tab=model-keys">Add a model key</Link> (OpenAI, Anthropic, Gemini, OpenRouter…) for real reactions.</>}
        </Step>
        <Step n={3} done={steps[2]} title="Run your first test">
          Paste a script, post or headline below, or <button type="button" className="text-brand underline decoration-brand/35 underline-offset-2 hover:decoration-brand" onClick={onExample}>fill in an example</button>, then press Test it. A dry run takes under a minute.
        </Step>
        <Step n={4} done={steps[3]} title="Read the verdict and ask why">
          {finished ? <>Open <Link className="text-brand" to={`/simulations/${finished.id}`}>{finished.name}</Link> to see who it works for, where attention drops and the first fix, then interview any simulated person.</>
            : "You'll see who it works for, where attention drops and the first fix, and you can interview any simulated person."}
        </Step>
      </ol>
    </Card>
  );
}
