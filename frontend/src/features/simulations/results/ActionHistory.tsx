import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Select } from "@/components/ui/overlay";
import { Card, Empty } from "@/components/ui/primitives";
import { api } from "@/lib/api";

const ACTIONS = ["POST", "COMMENT", "LIKE", "REPOST", "QUOTE", "FOLLOW", "UPVOTE", "DOWNVOTE", "SEARCH_POSTS", "SEARCH_USER", "VIEW_TRENDS", "REFRESH", "MUTE", "LIKE_COMMENT", "DISLIKE_COMMENT"];
export function ActionHistory({ simId }: { simId: string }) {
  const [action, setAction] = useState("*");
  const [platform, setPlatform] = useState("*");
  const q = useQuery({queryKey: ["action-history", simId, action, platform], queryFn: () => api<any[]>(`/simulations/${simId}/actions?limit=300&action=${action === "*" ? "" : action}&platform=${platform === "*" ? "" : platform}`)});
  return <Card className="mt-4 overflow-hidden"><div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
    <h3 className="section-title mr-auto">Action transcript</h3>
    <Select className="w-44" value={action} onChange={setAction} options={[{value:"*",label:"All actions"}, ...ACTIONS.map((a) => ({value:a,label:a.toLowerCase().replaceAll("_", " ")}))]} />
    <Select className="w-36" value={platform} onChange={setPlatform} options={[{value:"*",label:"Both platforms"},{value:"feed",label:"Feed"},{value:"forum",label:"Forum"}]} />
  </div><div className="max-h-96 overflow-y-auto divide-y divide-line">
    {q.data?.map((a) => <div key={a.id} className="p-3 text-sm"><span className="font-medium">{a.actor}</span> · {a.action.toLowerCase().replaceAll("_", " ")} · round {a.round}
      {a.content && <p className="mt-1 text-muted">{a.content}</p>}
      {a.target_ref && <p className="text-xs text-muted">Account {a.target_ref}</p>}
      {a.target_post && <p className="text-xs text-muted">Post #{a.target_post}</p>}
      {a.meta?.results && <details className="mt-1 text-xs text-muted"><summary>Results ({a.meta.results.length})</summary>{a.meta.results.map((r: any, i: number) => <p key={i} className="break-words">{r.content || r.title || r.name || r.handle}</p>)}</details>}
    </div>)}
    {!q.isLoading && !q.data?.length && <Empty title="No actions match" />}
  </div><p className="p-3 text-xs text-muted">Shows the first 300 matching actions.</p></Card>;
}
