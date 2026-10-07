import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Callout, Field, Input, Switch } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Preset } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Shared by organisation settings (BYO key) and platform admin (shared metered key). */
export function ProviderForm({ presets, current, endpoint, onSaved, canClear }: {
  presets: Record<string, Preset>; current: any | null; endpoint: { save: string; test: string; models: string; clear?: string }; onSaved: () => void; canClear?: boolean;
}) {
  const [f, setF] = useState<any>(() => ({
    name: "Default", preset: "dryrun", base_url: "", api_key: null, voice_model: "", report_model: "", vision_model: "", concurrency: 6, temperature: 0.9,
    json_mode: true, price_in: null, price_cached: null, price_out: null, ...(current || {}), api_key_input: "",
  }));
  useEffect(() => { if (current) setF((x: any) => ({ ...x, ...current, api_key_input: "" })); }, [current]);
  const [models, setModels] = useState<string[]>([]);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const p = presets[f.preset] || presets.custom;
  const body = () => { const { api_key_input, api_key_set, api_key_hint, id, scope, provider, is_default, ...rest } = f; return { ...rest, api_key: api_key_input ? api_key_input : null }; };
  const save = useMutation({ mutationFn: () => api(endpoint.save, { method: "PUT", json: body() }), onSuccess: () => { toast.success("Model provider saved"); onSaved(); },
    onError: (e) => toast.error(e instanceof ApiError ? e.message : "Failed") });
  const test = useMutation({ mutationFn: () => api(endpoint.test, { json: body() }), onSuccess: (r) => setResult(r) });
  const list = useMutation({ mutationFn: () => api(endpoint.models, { json: body() }), onSuccess: (r) => { setModels(r.models || []); if (r.error) toast.error(r.error); else toast.success(`${r.models.length} models found`); } });
  const groups = [
    { label: "Cloud APIs", keys: ["deepseek", "openrouter", "openai", "anthropic", "groq", "together", "custom"] },
    { label: "Local and self-hosted", keys: ["ollama", "lmstudio", "llamacpp", "vllm"] },
    { label: "No model", keys: ["dryrun"] },
  ];
  function pick(k: string) {
    const pr = presets[k];
    setF({ ...f, preset: k, base_url: pr.base_url, voice_model: pr.voice_model, report_model: pr.report_model, vision_model: pr.vision_model,
      concurrency: pr.local ? Math.min(f.concurrency, 2) : Math.max(f.concurrency, 6) });
    setResult(null);
  }
  return (
    <div className="space-y-5">
      {groups.map((g) => (
        <div key={g.label}>
          <div className="mb-2 text-[13px] font-medium">{g.label}</div>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {g.keys.filter((k) => presets[k]).map((k) => (
              <button key={k} onClick={() => pick(k)} className={cn("flex items-start gap-2.5 rounded-md border px-3 py-2.5 text-left transition-colors",
                f.preset === k ? "border-brand bg-brand-soft/50" : "border-line-strong bg-panel hover:bg-raised")}>
                <span className={cn("mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border", f.preset === k ? "border-brand" : "border-line-strong")}>
                  {f.preset === k && <span className="h-2 w-2 rounded-full bg-brand" />}</span>
                <span className="min-w-0">
                <span className="block text-[13px] font-medium">{presets[k].label}</span>
                <span className="block text-xs text-muted">{presets[k].provider === "anthropic" ? "official SDK" : presets[k].provider === "dryrun" ? "synthetic output" : presets[k].local ? "runs on your hardware" : "OpenAI-compatible"}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      ))}
      {f.preset === "dryrun" ? (
        <Callout tone="warn" title="Dry run">The full pipeline runs with formula-driven output tagged [dry run]. Use it to explore the product; select a provider above for agent-written reactions.</Callout>
      ) : (
        <div className="grid gap-x-5 gap-y-4 rounded-md border border-line p-4 md:grid-cols-2">
          <Field label={p.provider === "anthropic" ? "Base URL (optional)" : "Base URL"} help={p.local ? "The model server must be reachable from the Kruvim workers (in Docker use http://host.docker.internal:11434/v1 or the ollama service)." : undefined}>
            <Input value={f.base_url} onChange={(e) => setF({ ...f, base_url: e.target.value })} placeholder="https://…/v1" /></Field>
          <Field label="API key" hint={f.api_key_set ? `Saved ${f.api_key_hint}` : p.local ? "Usually not needed" : "Required"}
            help="Stored encrypted. Leave blank to keep the saved key.">
            <Input type="password" autoComplete="off" value={f.api_key_input} onChange={(e) => setF({ ...f, api_key_input: e.target.value })} placeholder={f.api_key_set ? "••••••••" : ""} /></Field>
          <Field label="Voice agent model" help="Called for every agent turn. A fast, inexpensive model works well."><Input list="mlist" value={f.voice_model} onChange={(e) => setF({ ...f, voice_model: e.target.value })} placeholder={p.local ? "qwen3:8b" : ""} /></Field>
          <Field label="Analyst and content model" help="Reads content, builds the graph and writes the report. Use your strongest model."><Input list="mlist" value={f.report_model} onChange={(e) => setF({ ...f, report_model: e.target.value })} /></Field>
          <Field label="Vision model (optional)" help="Analyses images and video frames."><Input list="mlist" value={f.vision_model} onChange={(e) => setF({ ...f, vision_model: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Parallel requests"><Input type="number" min={1} max={64} value={f.concurrency} onChange={(e) => setF({ ...f, concurrency: Number(e.target.value) })} /></Field>
            <Field label="Temperature"><Input type="number" step={0.1} min={0} max={2} value={f.temperature} onChange={(e) => setF({ ...f, temperature: Number(e.target.value) })} /></Field>
          </div>
          <div className="grid grid-cols-3 gap-3 md:col-span-2">
            <Field label="Price in ($/1M)"><Input type="number" step="0.001" value={f.price_in ?? ""} onChange={(e) => setF({ ...f, price_in: e.target.value === "" ? null : Number(e.target.value) })} /></Field>
            <Field label="Cached in ($/1M)"><Input type="number" step="0.001" value={f.price_cached ?? ""} onChange={(e) => setF({ ...f, price_cached: e.target.value === "" ? null : Number(e.target.value) })} /></Field>
            <Field label="Price out ($/1M)"><Input type="number" step="0.001" value={f.price_out ?? ""} onChange={(e) => setF({ ...f, price_out: e.target.value === "" ? null : Number(e.target.value) })} /></Field>
          </div>
          <div className="md:col-span-2"><Switch checked={f.json_mode} onChange={(v) => setF({ ...f, json_mode: v })} label="Request JSON mode (disabled automatically if the server rejects it)" /></div>
          <datalist id="mlist">{models.map((m) => <option key={m} value={m} />)}</datalist>
        </div>
      )}
      {result && <div className={cn("flex items-start gap-2 rounded-md border px-3 py-2 text-[13px]", result.ok ? "border-pos/25 bg-pos/[0.05]" : "border-neg/25 bg-neg/[0.05]")}>
        {result.ok ? <CheckCircle2 className="h-4 w-4 text-pos" /> : <XCircle className="h-4 w-4 text-neg" />}<span>{result.message}</span></div>}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" onClick={() => save.mutate()} loading={save.isPending}>Save</Button>
        {f.preset !== "dryrun" && <Button onClick={() => test.mutate()} loading={test.isPending}>Test connection</Button>}
        {f.preset !== "dryrun" && <Button onClick={() => list.mutate()} loading={list.isPending}>Load model list</Button>}
        {canClear && endpoint.clear && current && <Button variant="danger" className="ml-auto" onClick={async () => { await api(endpoint.clear!, { method: "DELETE" }); toast.success("Removed. Using the platform default."); onSaved(); }}>Remove</Button>}
      </div>
      {current?.scope && <div className="text-xs text-muted">Scope: {current.scope === "org" ? "this workspace" : current.scope}</div>}
    </div>
  );
}
