import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export type ReportSource = { number: number; label: string; kind?: "node" | "edge"; id?: string; node_id?: string; edge_id?: number; agent_ref?: string };

export function ReportFootnotes({ content, sources = [], onSource }: { content: string; sources?: ReportSource[]; onSource?: (source: ReportSource) => void }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: ({ children, href }) => {
    const match = /^#source-(\d+)$/.exec(href || "");
    if (!match) return <a href={href} rel="noreferrer noopener">{children}</a>;
    const source = sources.find((item) => item.number === Number(match[1]));
    return <sup>{source && onSource ? <button type="button" className="text-brand hover:underline" aria-label={`Open source ${source.number}: ${source.label}`} onClick={() => onSource(source)}>[{source.number}]</button> : <span>[{match[1]}]</span>}</sup>;
  } }}>{content}</ReactMarkdown>;
}
