import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const PLATFORM_NAMES: Record<string, string> = { youtube: "YouTube", tiktok: "TikTok", instagram: "Instagram", x: "X",
  facebook: "Facebook", snapchat: "Snapchat", linkedin: "LinkedIn", reddit: "Reddit", bluesky: "Bluesky", mastodon: "Mastodon" };
export const platformName = (key?: string) => PLATFORM_NAMES[key || ""] || key || "Platform";

/** API timestamps are UTC; a value without an offset must not be read as local time. */
export function parseTime(iso: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) || !iso.includes("T") ? iso : iso + "Z");
}

export const fmt = {
  n: (x?: number | null) => (x == null ? "–" : Number(x).toLocaleString("en-US")),
  k: (x?: number | null) => {
    if (x == null) return "–";
    const v = Number(x);
    if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(Math.abs(v) >= 1e7 ? 0 : 1) + "M";
    if (Math.abs(v) >= 1e3) return (v / 1e3).toFixed(Math.abs(v) >= 1e4 ? 0 : 1) + "k";
    return String(Math.round(v));
  },
  pct: (x?: number | null, d = 0) => (x == null ? "–" : (x * 100).toFixed(d) + "%"),
  s1: (x?: number | null) => (x == null ? "–" : Number(x).toFixed(1)),
  s2: (x?: number | null) => (x == null ? "–" : Number(x).toFixed(2)),
  t: (s?: number | null) => (s == null ? "" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`),
  date: (iso?: string | null) => (iso ? parseTime(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "–"),
  day: (iso?: string | null) => (iso ? parseTime(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "–"),
  ago: (iso?: string | null) => {
    if (!iso) return "–";
    const s = (Date.now() - parseTime(iso).getTime()) / 1000;
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.round(s / 60)} min ago`;
    if (s < 86400) return `${Math.round(s / 3600)} h ago`;
    return `${Math.round(s / 86400)} d ago`;
  },
  clock: (iso?: string | null) => (iso ? parseTime(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : ""),
};

export function plural(n: number, word: string, pluralWord?: string) {
  return `${fmt.n(n)} ${n === 1 ? word : pluralWord ?? word + "s"}`;
}

export function initials(name?: string) {
  return (name || "?").split(/\s+/).map((p) => p[0]).filter(Boolean).slice(0, 2).join("").toUpperCase();
}
