export type SectionId = "main" | "advanced";
export type NavIcon = "LayoutGrid" | "FolderKanban" | "Users2" | "Contact" | "Database" | "Gauge" | "BarChart3" | "Settings" | "Shield" | "HelpCircle";
export interface NavItemDefinition {
  to: string;
  label: string;
  description: string;
  icon: NavIcon;
  end?: boolean;
  adminOnly?: boolean;
}
export interface NavSection {
  id: SectionId;
  label: string;
  items: readonly NavItemDefinition[];
}

export const NAV_SECTIONS: readonly NavSection[] = [
  { id: "main", label: "", items: [
    { to: "/", label: "Home", icon: "LayoutGrid", end: true, description: "Home: test a piece of content and see your recent results" },
    { to: "/tests", label: "My tests", icon: "FolderKanban", description: "My tests: find and open every test in your workspace" },
    { to: "/my-audience", label: "My audience", icon: "Contact", description: "My audience: import your analytics and match your own followers" },
    { to: "/data-pool", label: "Data pool", icon: "Database", description: "Data pool: the local news, trends and sources behind your tests" },
    { to: "/settings", label: "Settings", icon: "Settings", description: "Settings: manage your workspace, team and model connection" },
    { to: "/help", label: "Help", icon: "HelpCircle", description: "Help: learn how to test content and understand your results" },
  ] },
  { id: "advanced", label: "Advanced", items: [
    { to: "/overview", label: "Overview", icon: "LayoutGrid", description: "Overview: detailed workspace activity, data coverage and usage" },
    { to: "/projects", label: "Projects", icon: "FolderKanban", description: "Projects: group your tests by campaign, client or channel" },
    { to: "/runs", label: "All runs", icon: "FolderKanban", description: "All runs: search and filter runs across every project" },
    { to: "/saved-audiences", label: "Saved audiences", icon: "Contact", description: "Saved audiences: reusable audience definitions for any test" },
    { to: "/population", label: "Population", icon: "Users2", description: "Population: the synthetic people behind every simulation" },
    { to: "/monitoring", label: "Monitoring", icon: "Gauge", description: "Monitoring: watch feeds and test new posts automatically" },
    { to: "/calibration", label: "Calibration", icon: "Gauge", description: "Calibration: compare predicted and actual post outcomes" },
    { to: "/accuracy", label: "Public accuracy", icon: "BarChart3", description: "Public accuracy: published measurements and their uncertainty" },
    { to: "/usage", label: "Usage and credits", icon: "BarChart3", description: "Usage and credits: review your plan, balance and model usage" },
    { to: "/admin", label: "Platform admin", icon: "Shield", adminOnly: true, description: "Platform admin: manage workspaces, plans and system health" },
  ] },
];

export function visibleSections(isPlatformAdmin: boolean): readonly NavSection[] {
  return NAV_SECTIONS.map((section) => ({ ...section, items: section.items.filter((item) => !item.adminOnly || isPlatformAdmin) }));
}

export function isNavActive(item: NavItemDefinition, pathname: string): boolean {
  // Match the router's case-insensitive paths and optional trailing slash.
  const path = pathname.replace(/\/+$/, "").toLowerCase() || "/";
  const target = item.to.toLowerCase();
  return path === target || (!item.end && path.startsWith(target + "/"));
}

export type CollapsedSections = Partial<Record<SectionId, boolean>>;
type PreferenceStorage = Pick<Storage, "getItem" | "setItem">;
export const sidebarPreferenceKey = (userId: string) => `kruvim.navigation.v2.${encodeURIComponent(userId)}`;

export function readCollapsedSections(userId?: string, storage?: PreferenceStorage): CollapsedSections {
  if (!userId) return { advanced: true };
  try {
    const saved = JSON.parse((storage ?? window.localStorage).getItem(sidebarPreferenceKey(userId)) || "null");
    if (saved?.version !== 2 || !saved.collapsed || typeof saved.collapsed !== "object") return { advanced: true };
    return { advanced: saved.collapsed.advanced !== false };
  } catch { return { advanced: true }; }
}

export function writeCollapsedSections(userId: string | undefined, collapsed: CollapsedSections, storage?: PreferenceStorage): void {
  if (!userId) return;
  try { (storage ?? window.localStorage).setItem(sidebarPreferenceKey(userId), JSON.stringify({ version: 2, collapsed })); }
  catch { /* Navigation remains usable if browser storage is unavailable. */ }
}
