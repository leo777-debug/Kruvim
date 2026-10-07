export type SectionId = "create" | "audience" | "intelligence" | "accuracy" | "workspace";
export type NavIcon = "LayoutGrid" | "FolderKanban" | "Users2" | "Contact" | "Database" | "Gauge" | "BarChart3" | "Settings" | "Shield";
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
  { id: "create", label: "Create", items: [
    { to: "/", label: "Overview", icon: "LayoutGrid", end: true, description: "Overview: your workspace's simulations, data coverage and credit usage" },
    { to: "/projects", label: "Projects", icon: "FolderKanban", description: "Projects: organise content tests by campaign, client or channel" },
    { to: "/runs", label: "All runs", icon: "LayoutGrid", description: "All runs: find and compare tests across all your projects" },
  ] },
  { id: "audience", label: "Audience", items: [
    { to: "/my-audience", label: "My audience", icon: "Users2", description: "My audience: connect your analytics and simulate your own followers" },
    { to: "/saved-audiences", label: "Saved audiences", icon: "Contact", description: "Saved audiences: reusable audience definitions you can load into any test" },
    { to: "/population", label: "Population", icon: "Users2", description: "Population: the 1M synthetic people behind every simulation" },
  ] },
  { id: "intelligence", label: "Intelligence", items: [
    { to: "/data-pool", label: "Data pool", icon: "Database", description: "Data pool: regional news, trends and other live inputs for your tests" },
    { to: "/monitoring", label: "Monitoring", icon: "Gauge", description: "Monitoring: watch competitor feeds and test new posts automatically" },
  ] },
  { id: "accuracy", label: "Accuracy", items: [
    { to: "/calibration", label: "Calibration", icon: "Gauge", description: "Calibration: use actual post outcomes to improve your predictions" },
    { to: "/accuracy", label: "Public accuracy", icon: "BarChart3", description: "Public accuracy: see published accuracy measurements and their uncertainty" },
  ] },
  { id: "workspace", label: "Workspace", items: [
    { to: "/settings", label: "Settings", icon: "Settings", description: "Settings: manage your workspace, team and model connection" },
    { to: "/usage", label: "Usage and credits", icon: "BarChart3", description: "Usage and credits: review your plan, credit balance and model usage" },
    { to: "/admin", label: "Platform admin", icon: "Shield", adminOnly: true, description: "Platform admin: manage platform workspaces, plans and system health" },
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
export const sidebarPreferenceKey = (userId: string) => `kruvim.navigation.v1.${encodeURIComponent(userId)}`;

export function readCollapsedSections(userId?: string, storage?: PreferenceStorage): CollapsedSections {
  if (!userId) return {};
  try {
    const saved = JSON.parse((storage ?? window.localStorage).getItem(sidebarPreferenceKey(userId)) || "null");
    if (saved?.version !== 1 || !saved.collapsed || typeof saved.collapsed !== "object") return {};
    return Object.fromEntries(NAV_SECTIONS.filter(({ id }) => saved.collapsed[id] === true).map(({ id }) => [id, true]));
  } catch { return {}; }
}

export function writeCollapsedSections(userId: string | undefined, collapsed: CollapsedSections, storage?: PreferenceStorage): void {
  if (!userId) return;
  try { (storage ?? window.localStorage).setItem(sidebarPreferenceKey(userId), JSON.stringify({ version: 1, collapsed })); }
  catch { /* Navigation remains usable if browser storage is unavailable. */ }
}
