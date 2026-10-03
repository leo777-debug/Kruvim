import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";
import { BarList } from "@/components/charts";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Bar, Callout, Card, CardHeader, Input, KV, Skeleton, Stat } from "@/components/ui/primitives";
import { SERIES } from "@/components/charts";
import { api } from "@/lib/api";
import { STANCE_COLORS } from "@/lib/colors";
import { fmt } from "@/lib/utils";

export default function PopulationPage() {
  const q = useQuery({ queryKey: ["population"], queryFn: () => api("/datapool/population") });
  const [id, setId] = useState("");
  const agent = useQuery({ queryKey: ["pop-agent", id], queryFn: () => api(`/datapool/population/agents/${id}`), enabled: false });
  const s = q.data?.stats;
  return (
    <Page wide title="Population" subtitle="The synthetic population every simulation draws from. Agents are rows of data, not running models: a language model speaks for a sampled set of voice agents, the crowd acts through a statistical policy, and every agent receives a projected reaction.">
      {!s ? <Skeleton className="h-24" /> : (
        <>
          <Card className="grid grid-cols-2 divide-line md:grid-cols-5 md:divide-x">
            <Stat className="p-4" label="Agents" value={fmt.n(s.n)} sub={q.data.active.label} />
            <Stat className="p-4" label="Follow edges" value={fmt.n(s.edges)} sub="Homophilous, heavy-tailed" />
            <Stat className="p-4" label="Median followers" value={fmt.n(s.followers["50"])} sub={`99th percentile ${fmt.n(s.followers["99"])}`} />
            <Stat className="p-4" label="Largest account" value={fmt.n(s.followers.max)} sub="followers" />
            <Stat className="p-4" label="Male share" value={fmt.pct(s.male_share)} />
          </Card>
          {Object.keys(q.data.active.priors || {}).length === 0 && (
            <Callout tone="warn" className="mt-4" title="Running on built-in priors">Regional demographics are approximate defaults. Import Arab Barometer, Pew or census data under Data pool, Survey data, to calibrate them.</Callout>
          )}
          <div className="mt-5 grid gap-4 lg:grid-cols-3">
            <Card className="p-5"><div className="section-title mb-3">Regions</div>
              <BarList rows={s.regions.map((r: any) => ({ label: r.name, value: r.n }))} max={Math.max(...s.regions.map((r: any) => r.n))} valueFmt={(v) => fmt.k(v)} colorFor={() => SERIES.a} /></Card>
            <Card className="p-5"><div className="section-title mb-3">Age</div><BarList rows={s.age_bands.map((r: any) => ({ label: r.label, value: r.share }))} max={0.4} valueFmt={(v) => fmt.pct(v)} colorFor={() => SERIES.a} />
              <div className="section-title mb-3 mt-6">Education</div><BarList rows={s.education.map((r: any) => ({ label: r.label, value: r.share }))} max={0.7} valueFmt={(v) => fmt.pct(v)} colorFor={() => SERIES.a} /></Card>
            <Card className="p-5"><div className="section-title mb-3">Disposition</div>
              <BarList rows={s.stances.map((r: any) => ({ label: r.label, value: r.share }))} max={0.5} valueFmt={(v) => fmt.pct(v)} colorFor={(v) => STANCE_COLORS[s.stances.find((x: any) => x.share === v)?.label] || "#9aa1ac"} />
              <p className="mt-2 text-xs leading-relaxed text-muted">Anti-herd rule: one contrarian, one skeptic and one disengaged agent in every ten, enforced at generation rather than by a model.</p>
              <div className="section-title mb-3 mt-6">Values</div>
              {Object.entries(s.attitudes || {}).map(([k, v]: any) => <div key={k} className="mb-1.5 grid grid-cols-[130px_1fr_40px] items-center gap-2 text-xs"><span className="capitalize text-muted">{k.replace("_", " ")}</span><Bar value={v} /><span className="num text-right">{v.toFixed(2)}</span></div>)}
            </Card>
          </div>
          <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_420px]">
            <Card className="p-5"><div className="section-title mb-3">Weekly platform use</div>
              <BarList rows={s.platforms.map((r: any) => ({ label: r.label, value: r.share }))} max={1} valueFmt={(v) => fmt.pct(v)} colorFor={() => SERIES.a} /></Card>
            <Card>
              <CardHeader title="Look up an agent" subtitle={`IDs 0 to ${fmt.n(s.n - 1)}`} />
              <div className="flex gap-2 px-4"><Input value={id} onChange={(e) => setId(e.target.value.replace(/\D/g, ""))} placeholder="e.g. 482113" />
                <Button onClick={() => agent.refetch()} disabled={!id}><Search className="h-3.5 w-3.5" />Look up</Button></div>
              {agent.data && (
                <div className="px-4 py-3">
                  <div className="text-[13px] font-semibold">{agent.data.name} <span className="font-normal text-muted">@{agent.data.handle}</span></div>
                  <KV className="mt-2" rows={[["Age, gender", `${agent.data.age}, ${agent.data.gender}`], ["Origin", agent.data.origin], ["City", agent.data.city], ["Work", agent.data.profession],
                    ["Education", agent.data.education], ["Income", agent.data.income], ["Language", agent.data.language], ["Platforms", agent.data.platforms.join(", ")],
                    ["Disposition", <span className="capitalize">{agent.data.stance}</span>], ["Followers", fmt.n(agent.data.followers)]]} />
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </Page>
  );
}
