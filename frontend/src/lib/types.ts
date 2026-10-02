export type Role = "owner" | "admin" | "member" | "viewer";

export interface Org { id: string; name: string; slug: string; plan: string; role: Role; credits_balance: number }
export interface User { id: string; email: string; name: string; is_superuser: boolean }

export interface Session { access_token: string; refresh_token: string; expires_in: number; user: User; orgs: Org[] }

export interface Region { code: string; name: string; short: string; city: string; mena: boolean; tz_offset: number }
export interface Reference {
  regions: Region[];
  platforms: { key: string; label: string }[];
  stances: string[];
  age_bands: string[];
  education: string[];
  interests: { key: string; label: string }[];
  presets: Record<string, Preset>;
  plans: Record<string, Plan>;
  connectors: { key: string; name: string; category: string }[];
  formats: Format[];
  professions: string[];
  incomes: string[];
}
export interface Format { key: string; label: string; hint: string; type: "video" | "audio" | "image" | "text"; platform: string; group: string; multi?: boolean; poll?: boolean }
export interface Preset { label: string; provider: string; base_url: string; local: boolean; voice_model: string; report_model: string; vision_model: string }
export interface Plan { label: string; monthly_credits: number; max_voice: number; max_crowd: number; max_hours: number; max_concurrent: number; max_members: number }

export interface Project { id: string; name: string; description: string; archived: boolean; created_at: string; simulations: number | SimSummary[]; last_activity?: string; assets?: Asset[] }
export interface Asset { id: string; kind: string; filename: string; mime: string; size: number; created_at: string; excerpt: string }

export type SimStatus = "draft" | "building_graph" | "graph_ready" | "preparing" | "ready" | "queued" | "running" | "paused" | "completed" | "failed" | "cancelled";

export interface SimSummary {
  id: string; project_id: string; name: string; status: SimStatus; step: number; report_status: string; content_type: string; platform: string;
  ab: boolean; regions: string[]; created_at: string; updated_at: string; progress: Record<string, any>; score?: number; viral?: number;
  ab_winner?: string; error?: string; credits_estimate: number; dry: boolean; format?: string; b_kind?: "version" | "competitor";
  parent_id?: string | null; review_status?: "none" | "in_review" | "approved" | "changes_requested";
}

export interface Simulation extends SimSummary {
  requirement: string;
  content: Record<string, any>;
  audience: Record<string, any>;
  publish_at: string | null;
  ontology: Record<string, any>;
  card: Record<string, any>;
  config: Record<string, any>;
  usage: Record<string, any>;
  results: Record<string, any>;
  seed: number;
}

export interface GNode { id: string; kind: string; type: string; label: string; summary: string; attrs: Record<string, any>; round: number; x?: number; y?: number; fx?: number; fy?: number; __born?: number }
export interface GEdge { source: string | GNode; target: string | GNode; relation: string; fact: string; weight: number; round: number }

export interface SimEvent { seq: number; type: string; payload: any; t?: number }
