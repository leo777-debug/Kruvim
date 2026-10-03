import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BarList } from "@/components/charts";
import { Card, Empty, Skeleton, Stat } from "@/components/ui/primitives";
import { API } from "@/lib/api";
import { fmt } from "@/lib/utils";

export default function PublicResultsPage() {
  const {token} = useParams();
  const q = useQuery({queryKey:["shared-results", token], retry:false, staleTime:Infinity, queryFn:async () => {
    const r = await fetch(`${API}/shared-results/${encodeURIComponent(token || "")}`);
    if (!r.ok) throw new Error("This share link is unavailable or expired.");
    return r.json();
  }});
  if (q.isLoading) return <div className="mx-auto max-w-4xl p-6"><Skeleton /><Skeleton /></div>;
  if (q.error || !q.data) return <Empty title="This share link is unavailable or expired">Ask the owner for a new link.</Empty>;
  const {branding, report, results:r} = q.data;
  const accent = /^#[0-9a-f]{6}$/i.test(branding.accent) ? branding.accent : "#2155cd";
  return <main className="mx-auto max-w-4xl space-y-5 p-4 sm:p-8">
    <header className="flex items-center gap-3">{branding.logo_url && <img src={branding.logo_url} referrerPolicy="no-referrer" alt="" className="h-10 w-10 object-contain" />}<div><div className="font-semibold">{branding.product_name || "Kruvim"}</div><p className="text-xs text-muted">Read-only results · expires {fmt.date(q.data.expires_at)}</p></div></header>
    <h1 className="break-words text-2xl font-semibold">{q.data.name}</h1>
    {r.provider?.dry && <p className="text-sm text-muted">Dry run: these results demonstrate the simulation and are not measured predictions.</p>}
    <div className="grid gap-4 sm:grid-cols-2"><Stat label="Audience score" value={`${fmt.s1(r.score?.mean)}/10`} /><Stat label="Completion" value={fmt.pct(r.heatmap?.completion)} /></div>
    <Card className="p-5"><h2 className="mb-3 font-medium">Attention heatmap</h2><BarList max={1} valueFmt={fmt.pct} colorFor={() => accent} rows={(r.heatmap?.segments || []).map((s:any) => ({label:s.label,value:s.retention || 0}))} /></Card>
    <Card className="p-5"><h2 className="mb-3 font-medium">Audience segments</h2><BarList colorFor={() => accent} rows={(r.groups?.region || []).map((s:any) => ({label:s.label,value:s.score}))} /></Card>
    <article className="card prose-report min-w-0 break-words p-5 sm:p-8"><ReactMarkdown remarkPlugins={[remarkGfm]} components={{a:({children,href}) => <a href={href} rel="noreferrer noopener">{children}</a>}}>{report.markdown}</ReactMarkdown></article>
    {branding.report_footer && <footer className="text-xs text-muted">{branding.report_footer}</footer>}
  </main>;
}
