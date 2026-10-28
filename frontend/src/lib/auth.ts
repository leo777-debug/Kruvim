import { create } from "zustand";
import type { Org, Session, User } from "./types";

// The refresh token lives in an httpOnly cookie the page cannot read; this flag only says a session may exist.
const SIGNED_IN = "kruvim.signed-in";
const ORG = "kruvim.org";
try { localStorage.removeItem("kruvim.rt"); } catch { /* tokens from older versions */ }

interface AuthState {
  accessToken: string | null;
  user: User | null;
  orgs: Org[];
  orgId: string | null;
  ready: boolean;
  setSession: (s: Session) => void;
  setOrgs: (orgs: Org[], user?: User) => void;
  switchOrg: (id: string) => void;
  clear: () => void;
  markReady: () => void;
}

export const useAuth = create<AuthState>((set, get) => ({
  accessToken: null,
  user: null,
  orgs: [],
  orgId: localStorage.getItem(ORG),
  ready: false,
  setSession: (s) => {
    localStorage.setItem(SIGNED_IN, "1");
    const keep = get().orgId && s.orgs.some((o) => o.id === get().orgId) ? get().orgId : s.orgs[0]?.id ?? null;
    if (keep) localStorage.setItem(ORG, keep);
    set({ accessToken: s.access_token, user: s.user, orgs: s.orgs, orgId: keep });
  },
  setOrgs: (orgs, user) => {
    const id = get().orgId && orgs.some((o) => o.id === get().orgId) ? get().orgId : orgs[0]?.id ?? null;
    set({ orgs, orgId: id, ...(user ? { user } : {}) });
  },
  switchOrg: (id) => {
    localStorage.setItem(ORG, id);
    set({ orgId: id });
  },
  clear: () => {
    localStorage.removeItem(SIGNED_IN);
    set({ accessToken: null, user: null, orgs: [] });
  },
  markReady: () => set({ ready: true }),
}));

export const maySignIn = () => localStorage.getItem(SIGNED_IN) === "1";

export function currentOrg(): Org | undefined {
  const { orgs, orgId } = useAuth.getState();
  return orgs.find((o) => o.id === orgId) ?? orgs[0];
}

export function can(role: "owner" | "admin" | "member" | "viewer") {
  const rank = { viewer: 0, member: 1, admin: 2, owner: 3 } as const;
  const r = currentOrg()?.role ?? "viewer";
  return rank[r] >= rank[role];
}
