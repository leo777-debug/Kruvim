// Score ramp (0..10): red → neutral grey → green. Muted so it reads on white and on dark panels.
const LO = [196, 58, 44];
const MID = [160, 166, 176];
const HI = [34, 134, 84];

function mix(a: number[], b: number[], t: number) {
  return a.map((v, i) => Math.round(v + (b[i] - v) * t));
}

export function scoreRGB(s: number): number[] {
  const t = Math.max(0, Math.min(1, s / 10));
  return t < 0.5 ? mix(LO, MID, t / 0.5) : mix(MID, HI, (t - 0.5) / 0.5);
}

export function scoreColor(s?: number | null, a = 1): string {
  if (s == null || Number.isNaN(s)) return `rgba(150,156,166,${a})`;
  const [r, g, b] = scoreRGB(s);
  return a === 1 ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},${a})`;
}

// Attention hold rate: 0.85 is "normal" for a segment
export function engColor(e: number, a = 1) {
  return scoreColor(Math.max(0, Math.min(10, 5 + (e - 0.85) * 40)), a);
}

// Categorical palette (Tableau 10): distinguishable, print-safe, not neon.
export const CATEGORICAL = ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#76b7b2", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"];

export const REGION_COLORS: Record<string, string> = {
  AE: "#4e79a7", SA: "#59a14f", EG: "#f28e2b", JO: "#b07aa1", MA: "#e15759", US: "#76b7b2", GB: "#9c755f", IN: "#edc948", "*": "#9aa1ac",
};

export const STANCE_COLORS: Record<string, string> = {
  enthusiast: "#3d8b5f", neutral: "#9aa1ac", skeptic: "#c99a2e", contrarian: "#c43a2c", disengaged: "#6b7280",
  supportive: "#3d8b5f", opposing: "#c43a2c", observer: "#9aa1ac",
};

export const KIND_COLORS: Record<string, string> = {
  content: "#2155cd", entity: "#6f7fbf", region: "#4b5563", signal: "#a3a9b3", agent: "#4e79a7", stakeholder: "#b07aa1",
  post: "#b8bec7", crowd: "#8b939f", event: "#c43a2c",
};

export const ENTITY_PALETTE = CATEGORICAL;

export const ACTION_COLORS: Record<string, string> = {
  POST: "#4b5563", COMMENT: "#4e79a7", REPOST: "#59a14f", QUOTE: "#b07aa1", LIKE: "#e15759", FOLLOW: "#c99a2e",
  UPVOTE: "#59a14f", DOWNVOTE: "#e15759", EVENT: "#c43a2c", CROWD_LIKE: "#e15759", CROWD_REPOST: "#59a14f", CROWD_UPVOTE: "#59a14f",
};
