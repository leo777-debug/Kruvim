import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, FileAudio, FileImage, FileText, FileUp, FileVideo, Plus, Trash2, Upload, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Page } from "@/components/layout/AppShell";
import { Button } from "@/components/ui/button";
import { Dialog, Select } from "@/components/ui/overlay";
import { RegionPicker } from "@/components/ui/RegionPicker";
import { Card, CheckRow, Field, InfoTip, Input, KV, RangeSlider, Segmented, Switch, Textarea } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useReference } from "@/lib/queries";
import type { Asset, Format, Simulation } from "@/lib/types";
import { cn, fmt } from "@/lib/utils";

const DEPTH = {
  quick: { label: "Quick", voice: 40, crowd: 1500, stakeholders: 3, hours: 12, minutes_per_round: 60 },
  standard: { label: "Standard", voice: 100, crowd: 4000, stakeholders: 5, hours: 24, minutes_per_round: 60 },
  deep: { label: "Deep", voice: 250, crowd: 15000, stakeholders: 8, hours: 48, minutes_per_round: 60 },
} as const;
const WHEN = { now: "Now", schedule: "Scheduled", backtest: "Backtest" } as const;
const GROUP_ICON: Record<string, typeof FileVideo> = { Video: FileVideo, Audio: FileAudio, Image: FileImage, Text: FileText };
const OCEAN = ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"] as const;
const COMPARE = { none: "No comparison", version: "Another version of mine", competitor: "A competitor's content" } as const;

interface Variant { title: string; text: string; transcript: string; description: string; asset_id: string | null; asset_ids: string[]; poll_options: string[]; file?: File | null; files?: File[] }
const blank = (): Variant => ({ title: "", text: "", transcript: "", description: "", asset_id: null, asset_ids: [], poll_options: ["", ""], file: null, files: [] });

function Section({ title, desc, children }: { title: string; desc?: ReactNode; children: ReactNode }) {
  return (
    <section className="grid gap-4 border-t border-line px-5 py-6 first:border-t-0 md:grid-cols-[200px_minmax(0,1fr)] md:gap-8">
      <div>
        <h2 className="text-[14px] font-semibold">{title}</h2>
        {desc && <p className="mt-1 text-[13px] leading-relaxed text-muted">{desc}</p>}
      </div>
      <div className="min-w-0 space-y-4">{children}</div>
    </section>
  );
}

export default function NewSimulationPage() {
  const { projectId, simId } = useParams();
  const nav = useNavigate();
  const ref = useReference();
  const orgId = useAuth((s) => s.orgId);
  const edit = !!simId;
  const existing = useQuery({ queryKey: [orgId, "sim", simId], queryFn: () => api<Simulation>(`/simulations/${simId}`), enabled: edit });
  const pid = projectId || existing.data?.project_id;
  const formats = ref.data?.formats || [];
  const [name, setName] = useState("");
  const [req, setReq] = useState("");
  const [format, setFormat] = useState("short_video");
  const [platform, setPlatform] = useState("tiktok");
  const [platformTouched, setPlatformTouched] = useState(false);
  const [goal, setGoal] = useState("Grow followers");
  const [followers, setFollowers] = useState("");
  const [A, setA] = useState<Variant>(blank());
  const [compare, setCompare] = useState<keyof typeof COMPARE>("none");
  const [B, setB] = useState<Variant>(blank());
  const [seeds, setSeeds] = useState<Asset[]>([]);
  const [aud, setAud] = useState<any>({ regions: ["AE", "SA", "EG", "JO", "MA"], age_min: 16, age_max: 70, genders: [], platforms: [], citizens_only: false,
    expats_only: false, interests: [], professions: [], incomes: [], ocean: {} });
  const [advanced, setAdvanced] = useState(false);
  const [saveTpl, setSaveTpl] = useState(false);
  const [when, setWhen] = useState<"now" | "schedule" | "backtest">("now");
  const [at, setAt] = useState("");
  const [depth, setDepth] = useState<keyof typeof DEPTH>("standard");
  const [ov, setOv] = useState<any>({ ...DEPTH.standard, platforms: ["feed", "forum"], listening: true });
  const [count, setCount] = useState<{ n: number; regions: Record<string, number> } | null>(null);
  const [busy, setBusy] = useState(false);
  const f: Format | undefined = formats.find((x) => x.key === format);
  const type = f?.type || "video";

  useEffect(() => {
    const s = existing.data;
    if (!s) return;
    const c = s.content || {};
    setFollowers(c.creator_followers == null ? "" : String(c.creator_followers));
    setName(s.name); setReq(s.requirement); setFormat(c.format || "short_video"); setPlatform(c.platform || "tiktok"); setPlatformTouched(true); setGoal(c.goal || "");
    setA({ ...blank(), ...c, poll_options: c.poll_options?.length ? c.poll_options : ["", ""], file: null, files: [] });
    if (c.variant_b) { setCompare(c.b_kind === "competitor" ? "competitor" : "version"); setB({ ...blank(), ...c.variant_b, poll_options: c.variant_b.poll_options?.length ? c.variant_b.poll_options : ["", ""] }); }
    setAud((a: any) => ({ ...a, ...s.audience }));
    if (s.publish_at) { setWhen(new Date(s.publish_at) < new Date() ? "backtest" : "schedule"); setAt(s.publish_at.slice(0, 16)); }
    if (s.config?.overrides) setOv((o: any) => ({ ...o, ...s.config.overrides }));
  }, [existing.data]);

  const project = useQuery({ queryKey: [orgId, "project", pid], queryFn: () => api(`/projects/${pid}`), enabled: !!pid });
  const templates = useQuery({ queryKey: [orgId, "templates"], queryFn: () => api<any[]>("/audience-templates") });
  const presets = useQuery({ queryKey: [orgId, "audience-presets"], queryFn: () => api<{ id: string; name: string; description: string; filters: Record<string, unknown> }[]>("/audience-presets") });
  useEffect(() => {
    if (project.data && existing.data) setSeeds((project.data.assets || []).filter((a: Asset) => (existing.data!.content?.seed_asset_ids || []).includes(a.id)));
  }, [project.data, existing.data]);

  useEffect(() => {
    const t = setTimeout(async () => {
      try { setCount(await api("/datapool/population/count", { json: cleanAud(aud) })); } catch { setCount(null); }
    }, 250);
    return () => clearTimeout(t);
  }, [aud]);

  function pickFormat(k: string) {
    setFormat(k);
    const nf = formats.find((x) => x.key === k);
    if (nf && !platformTouched) setPlatform(nf.platform);
  }

  async function upload(file: File, kind: string): Promise<Asset> {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", kind);
    return api<Asset>(`/projects/${pid}/assets`, { method: "POST", body: fd });
  }

  function validate(v: Variant, label: string): string | null {
    if (!f) return "Choose a format.";
    if (f.poll) {
      if (!v.text.trim()) return `${label}: write the poll question.`;
      if (v.poll_options.filter((o) => o.trim()).length < 2) return `${label}: add at least two poll options.`;
      return null;
    }
    if (type === "text" && !v.text.trim() && !v.file && !v.asset_id) return `${label}: paste text or upload a document.`;
    if (f.multi && !(v.files?.length || v.asset_ids.length) && !v.description.trim()) return `${label}: add the slides or describe each one.`;
    if (type === "image" && !f.multi && !v.file && !v.asset_id && !v.description.trim()) return `${label}: add an image or describe it.`;
    if ((type === "video" || type === "audio") && !v.file && !v.asset_id && !v.transcript.trim()) return `${label}: add a file or a transcript.`;
    return null;
  }

  async function payload(v: Variant, kind: string) {
    let asset_id = v.asset_id, asset_ids = v.asset_ids;
    if (v.file) asset_id = (await upload(v.file, kind)).id;
    if (v.files?.length) asset_ids = [...asset_ids, ...(await Promise.all(v.files.map((x) => upload(x, kind)))).map((a) => a.id)];
    return { title: v.title, text: v.text, transcript: v.transcript, description: v.description, asset_id, asset_ids,
      poll_options: f?.poll ? v.poll_options.filter((o) => o.trim()) : [] };
  }

  async function submit(build: boolean) {
    const err = validate(A, compare === "none" ? "Content" : "Your content") || (compare !== "none" ? validate(B, compare === "competitor" ? "Competitor" : "Version B") : null);
    if (err) return toast.error(err);
    if (followers !== "" && (!Number.isInteger(Number(followers)) || Number(followers) < 0 || Number(followers) > 2_000_000_000)) return toast.error("Enter a whole follower count between 0 and 2 billion, or leave it blank.");
    if (!aud.regions.length) return toast.error("Select at least one region.");
    setBusy(true);
    try {
      const a = await payload(A, "content");
      const b = compare !== "none" ? await payload(B, "content_b") : null;
      const body = {
        name: name || A.title || A.text.slice(0, 60) || "Untitled simulation", requirement: req,
        content: { format, platform, goal, creator_followers: followers === "" ? null : Number(followers), ...a, seed_asset_ids: seeds.map((s) => s.id), b_kind: compare === "competitor" ? "competitor" : "version",
          variant_b: b ? { ...b, title: b.title || `${A.title || "Untitled"} (${compare === "competitor" ? "competitor" : "B"})` } : null },
        audience: cleanAud(aud),
        publish_at: when === "now" || !at ? null : new Date(at).toISOString(),
        overrides: ov,
      };
      const sim = edit ? await api<Simulation>(`/simulations/${simId}`, { method: "PATCH", json: body })
        : await api<Simulation>(`/projects/${pid}/simulations`, { json: body });
      if (build) await api(`/simulations/${sim.id}/graph`, { method: "POST" });
      nav(`/simulations/${sim.id}`);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not save");
    } finally { setBusy(false); }
  }

  const toggle = (k: string, v: string) => setAud({ ...aud, [k]: aud[k].includes(v) ? aud[k].filter((x: string) => x !== v) : [...aud[k], v] });
  const groups = useMemo(() => Array.from(new Set(formats.map((x) => x.group))), [formats]);
  const advancedCount = aud.professions.length + aud.incomes.length + Object.keys(aud.ocean).length + (aud.expats_only ? 1 : 0) + (aud.citizens_only ? 1 : 0);

  return (
    <Page title={edit ? "Edit simulation" : "New simulation"} wide
      breadcrumb={<><Link to="/projects" className="hover:text-fg">Projects</Link> / {pid ? <Link to={`/projects/${pid}`} className="hover:text-fg">{project.data?.name || "…"}</Link> : "…"}</>}>
      {!edit && (
        <ol className="mb-5 grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-3">
          {[["1", "Describe the test", "What you are posting, who should see it and what you want to learn."],
            ["2", "Kruvim builds the world", "A knowledge graph, an audience of agents and this moment's news and trends."],
            ["3", "Watch and decide", "Agents react and talk to each other; you get a report, fixes and anyone to interview."]].map(([n, t, d]) => (
            <li key={n} className="flex gap-3 bg-panel px-4 py-3">
              <span className="num flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-soft text-xs font-semibold text-brand">{n}</span>
              <span><span className="block text-[13px] font-medium">{t}</span><span className="block text-xs leading-relaxed text-muted">{d}</span></span>
            </li>
          ))}
        </ol>
      )}
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Card>
          <Section title="Content type" desc="Pick what you are testing. Each format is judged the way people actually encounter it.">
            <div className="space-y-3">
              {groups.map((g) => {
                const Icon = GROUP_ICON[g] || FileText;
                return (
                  <div key={g}>
                    <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted"><Icon className="h-3.5 w-3.5" />{g}</div>
                    <div className="grid gap-2 sm:grid-cols-2 2xl:grid-cols-3">
                      {formats.filter((x) => x.group === g).map((x) => (
                        <button key={x.key} type="button" onClick={() => pickFormat(x.key)}
                          className={cn("flex items-start gap-2.5 rounded-md border px-3 py-2.5 text-left transition-colors",
                            format === x.key ? "border-brand bg-brand-soft/60" : "border-line-strong bg-panel hover:bg-raised")}>
                          <span className={cn("mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border", format === x.key ? "border-brand" : "border-line-strong")}>
                            {format === x.key && <span className="h-2 w-2 rounded-full bg-brand" />}</span>
                          <span className="min-w-0"><span className="block text-[13px] font-medium">{x.label}</span><span className="block text-xs text-muted">{x.hint}</span></span>
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </Section>

          <Section title="Content" desc={f ? `Upload the ${f.label.toLowerCase()} or paste its text. Timed subtitles enable the second-by-second attention curve.` : undefined}>
            {f && <VariantForm v={A} set={setA} f={f} label={compare !== "none" ? "Your content" : undefined} />}
            <div className="rounded-md border border-line bg-raised/40 px-3.5 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[13px] font-medium">Compare against</span>
                <Segmented size="md" value={compare} onChange={setCompare} options={Object.entries(COMPARE).map(([value, label]) => ({ value: value as keyof typeof COMPARE, label }))} />
              </div>
              <p className="mt-1.5 text-xs leading-relaxed text-muted">
                {compare === "none" ? "Optional. The same agents can react to a second piece so you see which one wins and with whom."
                  : compare === "version" ? "A/B test: the same agents react to both versions; you get a winner with confidence and a group-by-group breakdown."
                    : "Benchmark: the same agents react to a competitor's public content; you see where you lead and where you trail."}
              </p>
              {compare !== "none" && f && <div className="mt-4 border-t border-line pt-4"><VariantForm v={B} set={setB} f={f} label={compare === "competitor" ? "Competitor's content" : "Version B"} /></div>}
            </div>
          </Section>

          <Section title="Objective" desc="The analyst answers this question in the report. Name the audience and the decision you need to make.">
            <Field label="Research question">
              <Textarea value={req} onChange={(e) => setReq(e.target.value)} className="min-h-[72px]" placeholder="How will Gulf Gen Z react to this ad, and which version should we run during Ramadan?" />
            </Field>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Simulation name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Ramadan teaser v1" /></Field>
              <Field label="Main platform"><Select value={platform} onChange={(v) => { setPlatform(v); setPlatformTouched(true); }} options={(ref.data?.platforms || []).map((p) => ({ value: p.key, label: p.label }))} /></Field>
              <Field label="Campaign goal"><Input value={goal} onChange={(e) => setGoal(e.target.value)} list="goals" /></Field>
              <Field label="Follower count" hint="Optional" help="Followers on the selected platform. Real-world reach estimates stay hidden when this is blank; estimates are not guaranteed views."><Input aria-label="Follower count" type="number" min={0} max={2000000000} step={1} value={followers} onChange={(e) => setFollowers(e.target.value)} placeholder="e.g. 12000" /></Field>
              <datalist id="goals">{["Grow followers", "Drive sales", "Brand awareness", "Spark discussion", "Inform / educate", "Recruit"].map((g) => <option key={g} value={g} />)}</datalist>
            </div>
          </Section>

          <Section title="Background" desc="Briefs, brand guidelines, competitor notes or prior research. Used to build the knowledge graph and stakeholder accounts.">
            <SeedPicker projectAssets={(project.data?.assets || []).filter((a: Asset) => a.kind === "seed")} selected={seeds} setSelected={setSeeds} upload={(file) => upload(file, "seed")} onUploaded={() => project.refetch()} />
          </Section>

          <Section title="Audience" desc={<>Who sees it, drawn from the 1,000,000-person population <InfoTip term="population" className="align-[-2px]" />. Counts update as you edit.</>}>
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Creator preset" help="Start with a suggested audience, then adjust its filters." className="min-w-0 basis-full sm:basis-auto sm:flex-1">
                <Select value="" placeholder="Apply a creator preset…" options={(presets.data || []).map((p) => ({ value: p.id, label: p.name }))}
                  onChange={(id) => { const p = presets.data?.find((x) => x.id === id); if (p) setAud({ regions: [], age_min: 16, age_max: 70, genders: [], platforms: [], citizens_only: false, expats_only: false, interests: [], professions: [], incomes: [], ocean: {}, ...p.filters }); }} />
              </Field>
              <Field label="Saved audiences" className="min-w-0 basis-full sm:basis-auto sm:flex-1">
                <Select value="" placeholder={templates.data?.length ? "Load a saved audience…" : "No saved audiences yet"}
                  onChange={async (id) => { const t = templates.data?.find((x) => x.id === id); if (t) { setAud({ ...aud, ...t.filters }); api(`/audience-templates/${id}/use`, { method: "POST" }).catch(() => null); toast.success(`Loaded "${t.name}"`); } }}
                  options={(templates.data || []).map((t) => ({ value: t.id, label: `${t.name}${t.mine ? "" : " · community"}${t.accuracy != null ? ` · ${Math.round(t.accuracy * 100)}% accuracy` : ""}` }))} />
              </Field>
              <Button onClick={() => setSaveTpl(true)}>Save this audience</Button>
            </div>
            <Switch checked={!!aud.use_creator_audience} onChange={(v) => setAud({ ...aud, use_creator_audience: v })}
              label="Match my audience" />
            <p className="text-xs text-muted">Uses the breakdown from <Link to="/my-audience" className="text-brand">My audience</Link>, within your selected filters. Unsupported demographics are disclosed in results.</p>
            <Field label="Audience regions"><RegionPicker value={aud.regions} onChange={(value) => setAud({ ...aud, regions: value })} /></Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Age range"><div className="flex items-center gap-2"><Input type="number" min={16} max={70} value={aud.age_min} onChange={(e) => setAud({ ...aud, age_min: Number(e.target.value) })} />
                <span className="text-[13px] text-muted">to</span><Input type="number" min={16} max={70} value={aud.age_max} onChange={(e) => setAud({ ...aud, age_max: Number(e.target.value) })} /></div></Field>
              <Field label="Gender"><Segmented size="md" value={aud.genders.length === 1 ? aud.genders[0] : "all"} onChange={(v) => setAud({ ...aud, genders: v === "all" ? [] : [v] })}
                options={[{ value: "all", label: "All" }, { value: "female", label: "Women" }, { value: "male", label: "Men" }]} /></Field>
            </div>
            <Field label="Platform users" hint={aud.platforms.length ? `${aud.platforms.length} selected` : "Any platform"}>
              <div className="grid grid-cols-2 gap-x-2 rounded-md border border-line p-1.5 sm:grid-cols-4">
                {(ref.data?.platforms || []).map((p) => <CheckRow key={p.key} checked={aud.platforms.includes(p.key)} onChange={() => toggle("platforms", p.key)} label={p.label} />)}
              </div>
            </Field>
            <Field label="Interests" hint={aud.interests.length ? `${aud.interests.length} selected` : "Any interest"}>
              <div className="grid grid-cols-2 gap-x-2 rounded-md border border-line p-1.5 sm:grid-cols-3">
                {(ref.data?.interests || []).map((p) => <CheckRow key={p.key} checked={aud.interests.includes(p.key)} onChange={() => toggle("interests", p.key)} label={p.label} />)}
              </div>
            </Field>
            <div className="rounded-md border border-line">
              <button type="button" onClick={() => setAdvanced(!advanced)} className="flex w-full items-center gap-2 px-3 py-2.5 text-left text-[13px] font-medium hover:bg-raised">
                {advanced ? <ChevronDown className="h-4 w-4 text-muted" /> : <ChevronRight className="h-4 w-4 text-muted" />}
                Advanced filters <span className="font-normal text-muted">· nationality, work, income, personality{advancedCount ? ` · ${advancedCount} active` : ""}</span>
              </button>
              {advanced && (
                <div className="space-y-4 border-t border-line p-3">
                  <Field label="Nationality">
                    <Segmented size="md" value={aud.citizens_only ? "citizens" : aud.expats_only ? "expats" : "all"}
                      onChange={(v) => setAud({ ...aud, citizens_only: v === "citizens", expats_only: v === "expats" })}
                      options={[{ value: "all", label: "Everyone" }, { value: "citizens", label: "Citizens only" }, { value: "expats", label: "Expatriates only" }]} />
                  </Field>
                  <Field label="Occupation" hint={aud.professions.length ? `${aud.professions.length} selected` : "Any"}>
                    <div className="grid grid-cols-2 gap-x-2 rounded-md border border-line p-1.5 sm:grid-cols-3">
                      {(ref.data?.professions || []).map((p) => <CheckRow key={p} checked={aud.professions.includes(p)} onChange={() => toggle("professions", p)} label={p[0].toUpperCase() + p.slice(1)} />)}
                    </div>
                  </Field>
                  <Field label="Income" hint={aud.incomes.length ? `${aud.incomes.length} selected` : "Any"}>
                    <div className="grid grid-cols-2 gap-x-2 rounded-md border border-line p-1.5 sm:grid-cols-5">
                      {(ref.data?.incomes || []).map((p) => <CheckRow key={p} checked={aud.incomes.includes(p)} onChange={() => toggle("incomes", p)} label={p[0].toUpperCase() + p.slice(1)} />)}
                    </div>
                  </Field>
                  <Field label="Personality (Big Five)" help="Limit the audience to a range on any trait; 0 is lowest in the population, 1 highest. Leave a trait at the full range to ignore it.">
                    <div className="space-y-2 rounded-md border border-line p-3">
                      {OCEAN.map((t) => {
                        const v: [number, number] = aud.ocean[t] || [0, 1];
                        return (
                          <div key={t} className="grid grid-cols-[120px_1fr_70px] items-center gap-3 text-[13px]">
                            <span className="capitalize">{t}</span>
                            <RangeSlider value={v} onChange={(nv) => { const o = { ...aud.ocean }; if (nv[0] <= 0 && nv[1] >= 1) delete o[t]; else o[t] = nv; setAud({ ...aud, ocean: o }); }} />
                            <span className="num text-right text-xs text-muted">{v[0].toFixed(2)}–{v[1].toFixed(2)}</span>
                          </div>
                        );
                      })}
                    </div>
                  </Field>
                </div>
              )}
            </div>
          </Section>

          <Section title="Timing" desc={<>Which moment the agents live in: today's news, weather, calendar and trends for each region <InfoTip term="live" className="align-[-2px]" />.</>}>
            <Segmented size="md" value={when} onChange={setWhen} options={Object.entries(WHEN).map(([value, label]) => ({ value: value as keyof typeof WHEN, label }))} />
            {when !== "now" && <Field label={when === "schedule" ? "Publish at" : "Replay the moment"}><Input className="max-w-xs" type="datetime-local" value={at} onChange={(e) => setAt(e.target.value)} /></Field>}
            <p className="text-[13px] leading-relaxed text-muted">{when === "now" ? "Agents are conditioned on what is happening in each region this hour, and the run follows their local clocks from now."
              : when === "schedule" ? "Local clocks and the holiday calendar shift to the publish time; news and trends use the latest snapshot."
                : "Agents see the archived snapshot of that moment: the news, weather and trends people actually saw. The archive must cover the date."}</p>
          </Section>

          <Section title="Depth" desc="How many agents and how much simulated time. More depth means more detail and more model calls. Every value can be changed in step 2.">
            <Segmented size="md" value={depth} onChange={(d) => { setDepth(d); setOv({ ...ov, ...DEPTH[d] }); }} options={Object.entries(DEPTH).map(([k, v]) => ({ value: k as keyof typeof DEPTH, label: v.label }))} />
            <KV className="max-w-md" rows={[
              [<span className="inline-flex items-center gap-1.5">Voice agents <InfoTip term="voice" /></span>, fmt.n(ov.voice)],
              [<span className="inline-flex items-center gap-1.5">Crowd agents <InfoTip term="crowd" /></span>, fmt.n(ov.crowd)],
              [<span className="inline-flex items-center gap-1.5">Stakeholder accounts <InfoTip term="stakeholder" /></span>, ov.stakeholders],
              ["Simulated time", `${ov.hours} h · ${Math.round((ov.hours * 60) / ov.minutes_per_round)} rounds`]]} />
          </Section>
        </Card>

        <div>
          <Card className="sticky top-6">
            <div className="border-b border-line px-4 py-3">
              <div className="text-xs font-medium text-muted">Audience size</div>
              <div className="num mt-0.5 text-[26px] font-semibold leading-tight">{count ? fmt.n(count.n) : "–"}</div>
              <div className="text-xs text-muted">{count ? `${fmt.pct(count.n / 1_000_000, 1)} of the population` : "Calculating…"}</div>
            </div>
            <div className="px-4 py-2">
              <KV rows={[["Format", f?.label || "–"], ["Regions", aud.regions.length ? aud.regions.join(", ") : "None"], ["Ages", `${aud.age_min || 16}–${aud.age_max || 70}`],
                ["Comparison", compare === "none" ? "None" : compare === "version" ? "A/B test" : "Competitor"], ["Timing", WHEN[when]], ["Depth", DEPTH[depth].label],
                ["Advanced filters", advancedCount || "None"], ["Background files", seeds.length]]} />
            </div>
            <div className="space-y-2 border-t border-line p-4">
              <Button variant="primary" className="w-full" onClick={() => submit(true)} loading={busy}>{edit ? "Save and rebuild graph" : "Create and build graph"}</Button>
              <Button className="w-full" onClick={() => submit(false)} loading={busy}>Save as draft</Button>
              <p className="pt-1 text-xs leading-relaxed text-muted">Building the graph takes under a minute. Nothing runs on the audience until you start the simulation in step 3.</p>
            </div>
          </Card>
        </div>
      </div>
      <SaveTemplateDialog open={saveTpl} onClose={() => setSaveTpl(false)} filters={cleanAud(aud)} onSaved={() => templates.refetch()} />
    </Page>
  );
}

function cleanAud(a: any) {
  return { ...a, age_min: a.age_min || null, age_max: a.age_max || null };
}

function SaveTemplateDialog({ open, onClose, filters, onSaved }: { open: boolean; onClose: () => void; filters: any; onSaved: () => void }) {
  const [v, setV] = useState({ name: "", description: "", source_citation: "", shared: false });
  const [busy, setBusy] = useState(false);
  async function save() {
    setBusy(true);
    try {
      await api("/audience-templates", { json: { ...v, filters } });
      toast.success("Audience saved");
      onSaved(); onClose();
    } catch (e) { toast.error(e instanceof ApiError ? e.message : "Could not save"); } finally { setBusy(false); }
  }
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()} title="Save audience" description="Reuse this audience in future simulations. Shared audiences appear in every workspace's library."
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!v.name.trim()} loading={busy} onClick={save}>Save audience</Button></>}>
      <div className="space-y-4">
        <Field label="Name"><Input autoFocus value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} placeholder="Gulf professionals 25-44" /></Field>
        <Field label="Description" hint="Optional"><Textarea className="min-h-[60px]" value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} /></Field>
        <Field label="Source" hint="Optional" help="Where these filters come from, for example a survey wave or client brief."><Input value={v.source_citation} onChange={(e) => setV({ ...v, source_citation: e.target.value })} /></Field>
        <Switch checked={v.shared} onChange={(s) => setV({ ...v, shared: s })} label="Share with the community library" />
      </div>
    </Dialog>
  );
}

function VariantForm({ v, set, f, label }: { v: Variant; set: (v: Variant) => void; f: Format; label?: string }) {
  const input = useRef<HTMLInputElement>(null);
  const multi = useRef<HTMLInputElement>(null);
  const type = f.type;
  const accept = type === "text" ? ".pdf,.docx,.txt,.md" : type === "video" ? "video/*" : type === "audio" ? "audio/*" : "image/*";
  const titleLabel = f.key === "thumbnail" ? "Video title shown next to the thumbnail" : f.poll ? "Poll title (optional)" : type === "text" ? "Headline or first line" : "Title or opening line";
  const transcriptLabel = f.key === "song" ? "Lyrics" : f.key === "podcast" ? "Transcript or show notes" : "Transcript, subtitles or script";
  const descLabel = f.multi ? "Slide captions, one per line" : f.key === "thumbnail" ? "What the thumbnail shows" : type === "image" ? "Caption and description" : "On-screen description";
  const existingSlides = v.asset_ids.length;
  const slides = v.files || [];
  const move = (i: number, d: number) => { const s = [...slides]; const j = i + d; if (j < 0 || j >= s.length) return; [s[i], s[j]] = [s[j], s[i]]; set({ ...v, files: s }); };
  return (
    <div className="space-y-4">
      {label && <div className="text-[13px] font-semibold">{label}</div>}
      <Field label={titleLabel} hint={f.poll ? "Optional" : undefined}><Input value={v.title} onChange={(e) => set({ ...v, title: e.target.value })} placeholder={f.key === "thumbnail" ? "I tried working out while fasting for 30 days" : "3-minute apartment workout"} /></Field>

      {!f.poll && !f.multi && (
        <Field label={`${f.label} file`} hint={type === "text" ? "PDF, Word (.docx), text or Markdown" : type === "image" ? "PNG, JPG or WebP" : "Optional if you paste a transcript"}>
          <div onClick={() => input.current?.click()} onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); const x = e.dataTransfer.files[0]; if (x) set({ ...v, file: x }); }}
            className="flex cursor-pointer items-center gap-3 rounded-md border border-dashed border-line-strong bg-panel px-3.5 py-3 hover:bg-raised/50">
            <Upload className="h-4 w-4 text-faint" />
            <div className="min-w-0 flex-1 text-[13px]">
              {v.file ? <><span className="font-medium">{v.file.name}</span> <span className="text-muted">· {(v.file.size / 1e6).toFixed(1)} MB</span></>
                : v.asset_id ? <span className="text-muted">A file is attached. Drop a new one to replace it.</span>
                  : <span className="text-muted">Drop a {type} file here or <span className="text-brand">browse</span></span>}
            </div>
            {(v.file || v.asset_id) && <button type="button" onClick={(e) => { e.stopPropagation(); set({ ...v, file: null, asset_id: null }); }} className="rounded p-0.5 text-muted hover:text-fg" aria-label="Remove file"><X className="h-4 w-4" /></button>}
            <input ref={input} aria-label={`${label || "Content"} file`} type="file" accept={accept} className="hidden" onChange={(e) => set({ ...v, file: e.target.files?.[0] || null })} />
          </div>
        </Field>
      )}

      {f.multi && (
        <Field label="Slides" hint={`${existingSlides + slides.length} of 10`}>
          <div className="space-y-1.5">
            {existingSlides > 0 && <div className="text-xs text-muted">{existingSlides} slide{existingSlides === 1 ? "" : "s"} already attached. New uploads are added after them.</div>}
            {slides.map((x, i) => (
              <div key={i} className="flex items-center gap-2 rounded-md border border-line px-2.5 py-1.5 text-[13px]">
                <span className="num w-6 text-xs text-muted">{existingSlides + i + 1}</span><span className="min-w-0 flex-1 truncate">{x.name}</span>
                <button type="button" aria-label="Move up" onClick={() => move(i, -1)} className="rounded p-0.5 text-muted hover:text-fg"><ArrowUp className="h-3.5 w-3.5" /></button>
                <button type="button" aria-label="Move down" onClick={() => move(i, 1)} className="rounded p-0.5 text-muted hover:text-fg"><ArrowDown className="h-3.5 w-3.5" /></button>
                <button type="button" aria-label="Remove slide" onClick={() => set({ ...v, files: slides.filter((_, j) => j !== i) })} className="rounded p-0.5 text-muted hover:text-neg"><X className="h-3.5 w-3.5" /></button>
              </div>
            ))}
            <Button size="sm" disabled={existingSlides + slides.length >= 10} onClick={() => multi.current?.click()}><Upload className="h-3.5 w-3.5" />Add slides</Button>
            <input ref={multi} type="file" accept="image/*" multiple className="hidden"
              onChange={(e) => set({ ...v, files: [...slides, ...Array.from(e.target.files || [])].slice(0, 10 - existingSlides) })} />
          </div>
        </Field>
      )}

      {(type === "video" || type === "audio") && (
        <Field label={transcriptLabel} help={f.key === "song" ? "Lyrics let agents judge the words; without them they react to the description only." :
          "SRT or VTT timestamps drive the attention curve. A plain script is timed at 2.5 words per second. Without either, the file is transcribed when faster-whisper is installed on the server."}>
          <Textarea value={v.transcript} onChange={(e) => set({ ...v, transcript: e.target.value })} className="min-h-[140px]" />
        </Field>
      )}
      {(type === "video" || type === "image" || f.key === "song") && (
        <Field label={f.key === "song" ? "Genre, mood and where it would be used" : descLabel} hint={type === "image" && !f.multi ? undefined : "Optional"}
          help={type === "audio" ? undefined : "Frames and images are analysed automatically when the connected provider has a vision model."}>
          <Textarea value={v.description} onChange={(e) => set({ ...v, description: e.target.value })} className="min-h-[72px]" />
        </Field>
      )}
      {type === "text" && !f.poll && (
        <Field label={f.group === "Document" ? "Document text" : f.key === "article" ? "Article text" : "Post text"} help="Paste text or attach a document above.">
          <Textarea value={v.text} onChange={(e) => set({ ...v, text: e.target.value })} className="min-h-[200px]" placeholder={f.key === "article" ? "Paste the article, newsletter or press release." : "Paste the post, caption or thread."} />
        </Field>
      )}
      {f.poll && (
        <>
          <Field label="Question"><Textarea value={v.text} onChange={(e) => set({ ...v, text: e.target.value })} className="min-h-[60px]" placeholder="When do you usually work out during Ramadan?" /></Field>
          <Field label="Options" hint="2 to 6">
            <div className="space-y-1.5">
              {v.poll_options.map((o, i) => (
                <div key={i} className="flex items-center gap-2">
                  <span className="num w-5 text-xs text-muted">{i + 1}</span>
                  <Input value={o} onChange={(e) => set({ ...v, poll_options: v.poll_options.map((x, j) => (j === i ? e.target.value : x)) })} placeholder={`Option ${i + 1}`} />
                  {v.poll_options.length > 2 && <Button size="icon-sm" variant="ghost" aria-label="Remove option" onClick={() => set({ ...v, poll_options: v.poll_options.filter((_, j) => j !== i) })}><Trash2 className="h-3.5 w-3.5" /></Button>}
                </div>
              ))}
              {v.poll_options.length < 6 && <Button size="sm" onClick={() => set({ ...v, poll_options: [...v.poll_options, ""] })}><Plus className="h-3.5 w-3.5" />Add option</Button>}
            </div>
          </Field>
        </>
      )}
    </div>
  );
}

function SeedPicker({ projectAssets, selected, setSelected, upload, onUploaded }: { projectAssets: Asset[]; selected: Asset[]; setSelected: (a: Asset[]) => void; upload: (f: File) => Promise<Asset>; onUploaded: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const all = [...projectAssets, ...selected.filter((s) => !projectAssets.some((p) => p.id === s.id))];
  return (
    <div className="space-y-2">
      {all.length > 0 ? (
        <div className="rounded-md border border-line p-1.5">
          {all.map((a) => {
            const on = selected.some((s) => s.id === a.id);
            return <CheckRow key={a.id} checked={on} onChange={() => setSelected(on ? selected.filter((s) => s.id !== a.id) : [...selected, a])} label={a.filename} meta={fmt.day(a.created_at)} />;
          })}
        </div>
      ) : <p className="text-[13px] text-muted">This project has no background documents yet.</p>}
      <Button size="sm" loading={busy} onClick={() => input.current?.click()}><FileUp className="h-3.5 w-3.5" />Upload documents</Button>
      <input ref={input} type="file" multiple accept=".pdf,.md,.txt,.csv,.json" className="hidden" onChange={async (e) => {
        const files = Array.from(e.target.files || []);
        setBusy(true);
        try {
          const added: Asset[] = [];
          for (const x of files) added.push(await upload(x));
          setSelected([...selected, ...added]);
          onUploaded();
        } catch (ex) { toast.error(ex instanceof ApiError ? ex.message : "Upload failed"); } finally { setBusy(false); }
      }} />
    </div>
  );
}
