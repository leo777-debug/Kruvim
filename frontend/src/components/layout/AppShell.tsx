import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BarChart3, Building2, ChevronRight, Contact, ChevronsUpDown, Database, FolderKanban, Gauge, HelpCircle, LayoutGrid, LogOut, Menu as MenuIcon, Moon, Plus, Settings, Shield, Sun, Users2, X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { refreshToken, useAuth } from "@/lib/auth";
import { cn, fmt, initials } from "@/lib/utils";
import { Logo } from "./Logo";
import { Menu } from "../ui/overlay";
import { AlertsBell } from "@/features/monitoring/AlertsBell";
import { Tip } from "../ui/primitives";
import { isNavActive, readCollapsedSections, visibleSections, writeCollapsedSections, type CollapsedSections, type NavIcon, type NavItemDefinition, type SectionId } from "./navigation";

const ICONS: Record<NavIcon, LucideIcon> = { LayoutGrid, FolderKanban, Users2, Contact, Database, Gauge, HelpCircle, BarChart3, Settings, Shield };

function useTheme() {
  const [dark, setDark] = useState(document.documentElement.classList.contains("dark"));
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("kruvim.theme", dark ? "dark" : "light"); } catch { /* ignore */ }
  }, [dark]);
  return [dark, setDark] as const;
}

function hexToRgb(hex: string) {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || "");
  return m ? `${parseInt(m[1], 16)} ${parseInt(m[2], 16)} ${parseInt(m[3], 16)}` : null;
}

/** White-label: a workspace on Business/Enterprise can set a product name, logo and accent colour. */
export function useBranding() {
  const orgId = useAuth((s) => s.orgId);
  const q = useQuery({ queryKey: [orgId, "branding"], queryFn: () => api<{ product_name?: string; accent?: string; logo_url?: string; report_footer?: string }>("/orgs/current/branding"),
    enabled: !!orgId, staleTime: 300_000 });
  useEffect(() => {
    const rgb = hexToRgb(q.data?.accent || "");
    const root = document.documentElement;
    if (rgb) root.style.setProperty("--brand", rgb); else root.style.removeProperty("--brand");
  }, [q.data?.accent]);
  return q.data || {};
}

export function AppShell() {
  const userId = useAuth((state) => state.user?.id);
  return <ShellContent key={userId ?? "pending"} userId={userId} />;
}

function ShellContent({ userId }: { userId?: string }) {
  const [open, setOpen] = useState(false);
  const [collapsed, setCollapsed] = useState<CollapsedSections>(() => readCollapsedSections(userId));
  function toggleSection(id: SectionId) {
    const next = { ...collapsed, [id]: !collapsed[id] };
    setCollapsed(next);
    writeCollapsedSections(userId, next);
  }
  useBranding();
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  return (
    <div className="flex h-full">
      <aside className="hidden w-[228px] shrink-0 border-r border-line bg-side lg:flex"><Sidebar collapsed={collapsed} onToggle={toggleSection} /></aside>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-[#0b1220]/30" onClick={() => setOpen(false)} />
          <aside className="relative flex h-full w-[260px] border-r border-line bg-side shadow-pop animate-fade-in"><Sidebar collapsed={collapsed} onToggle={toggleSection} onClose={() => setOpen(false)} /></aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-12 shrink-0 items-center gap-2 border-b border-line bg-panel px-3 lg:hidden">
          <button onClick={() => setOpen(true)} className="rounded p-1.5 text-muted hover:bg-raised hover:text-fg" aria-label="Open navigation"><MenuIcon className="h-5 w-5" /></button>
          <Logo className="h-5 w-5" /><span className="text-[14px] font-semibold">Kruvim</span>
          <AlertsBell />
        </div>
        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

function Sidebar({ onClose, collapsed, onToggle }: { onClose?: () => void; collapsed: CollapsedSections; onToggle: (id: SectionId) => void }) {
  const brand = useBranding();
  const { user, orgs, orgId, switchOrg, clear } = useAuth();
  const org = orgs.find((o) => o.id === orgId) ?? orgs[0];
  const qc = useQueryClient();
  const nav = useNavigate();
  const [dark, setDark] = useTheme();
  const { pathname } = useLocation();
  const navigationId = useId();

  async function logout() {
    const rt = refreshToken();
    if (rt) await api("/auth/logout", { json: { refresh_token: rt } }).catch(() => null);
    clear();
    qc.clear();
    nav("/login");
  }

  return (
    <div className="flex w-full flex-col">
      <div className="flex h-12 items-center gap-2 px-4">
        {brand.logo_url ? <img src={brand.logo_url} alt="" className="h-[22px] w-[22px] rounded object-contain" /> : <Logo className="h-[22px] w-[22px]" />}
        <span className="truncate text-[15px] font-semibold tracking-[-0.01em]">{brand.product_name || "Kruvim"}</span>
        <AlertsBell />
        {onClose && <button onClick={onClose} className="ml-auto rounded p-1 text-muted hover:bg-raised" aria-label="Close navigation"><X className="h-4 w-4" /></button>}
      </div>
      <div className="px-2 pb-2">
        <Menu align="start" trigger={
          <button className="flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left hover:bg-raised">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-line-strong bg-panel text-[11px] font-semibold text-muted">{initials(org?.name)}</div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-[13px] font-medium">{org?.name ?? "No workspace"}</div>
              <div className="truncate text-xs text-muted"><span className="capitalize">{org?.plan}</span> plan · {fmt.k(org?.credits_balance)} credits</div>
            </div>
            <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-faint" />
          </button>
        } items={[
          ...orgs.map((o) => ({ label: <span className="flex w-full justify-between gap-3"><span>{o.name}</span><span className="text-xs capitalize text-muted">{o.role}</span></span>,
            icon: <Building2 className="h-3.5 w-3.5 text-muted" />, onSelect: () => { switchOrg(o.id); qc.clear(); nav("/"); } })),
          "sep" as const,
          { label: "New workspace", icon: <Plus className="h-3.5 w-3.5" />, onSelect: () => nav("/settings?tab=org&new=1") },
        ]} />
      </div>
      <nav aria-label="Main navigation" className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {visibleSections(!!user?.is_superuser).map((section) => {
          if (section.id === "main") return <div key={section.id} className="space-y-px">{section.items.map((item) => <NavItem key={item.to} {...item} />)}</div>;
          const current = section.items.find((item) => isNavActive(item, pathname));
          const isCollapsed = !!collapsed[section.id];
          const sectionId = `${navigationId}-${section.id}`;
          return <section key={section.id} aria-labelledby={`${sectionId}-heading`} className="pt-3 first:pt-0">
            <h2 id={`${sectionId}-heading`} aria-label={section.label} className="text-xs font-medium text-faint">
              <button type="button" aria-label={`${isCollapsed ? "Expand" : "Collapse"} ${section.label} navigation`} aria-expanded={!isCollapsed}
                aria-controls={`${sectionId}-links`} onClick={() => onToggle(section.id)}
                className="flex w-full items-center gap-2 rounded px-2.5 pb-1 pt-2 text-left hover:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/30">
                <span className="flex-1">{section.label}</span>
                {current && isCollapsed && <span className="h-1.5 w-1.5 rounded-full bg-brand"><span className="sr-only">Current page: {current.label}</span></span>}
                <ChevronRight aria-hidden className={cn("h-3 w-3 transition-transform", !isCollapsed && "rotate-90")} />
              </button>
            </h2>
            <div id={`${sectionId}-links`} hidden={isCollapsed} className="space-y-px">
              {section.items.map((item) => <NavItem key={item.to} {...item} />)}
            </div>
          </section>;
        })}
      </nav>
      <div className="border-t border-line p-2">
        <div className="flex items-center gap-2 px-1.5 py-1">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-raised text-[11px] font-semibold text-muted">{initials(user?.name)}</div>
          <div className="min-w-0 flex-1">
            <div className="truncate text-[13px] font-medium">{user?.name}</div>
            <div className="truncate text-xs text-muted">{user?.email}</div>
          </div>
          <button onClick={() => setDark(!dark)} className="rounded p-1.5 text-muted hover:bg-raised hover:text-fg" aria-label="Toggle theme" title={dark ? "Light theme" : "Dark theme"}>
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <button onClick={logout} className="rounded p-1.5 text-muted hover:bg-raised hover:text-fg" aria-label="Sign out" title="Sign out"><LogOut className="h-4 w-4" /></button>
        </div>
      </div>
    </div>
  );
}

function NavItem({ to, label, icon, end, description }: NavItemDefinition) {
  const Icon = ICONS[icon];
  const { pathname } = useLocation();
  const isActive = isNavActive({ to, label, icon, end, description }, pathname);
  return (
    <Tip content={description} side="right" contentClassName="max-w-[calc(100vw-24px)] sm:max-w-none sm:whitespace-nowrap">
      <NavLink to={to} end={end} className={cn("flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[13px] transition-colors",
        isActive ? "bg-line/70 font-medium text-fg" : "text-muted hover:bg-raised hover:text-fg")}>
        <Icon className="h-4 w-4" strokeWidth={1.75} />
        {label}
      </NavLink>
    </Tip>
  );
}

export function Page({ title, subtitle, actions, children, breadcrumb, wide }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; breadcrumb?: ReactNode; wide?: boolean }) {
  return (
    <div className={cn("mx-auto px-4 py-6 sm:px-6 lg:px-8", wide ? "max-w-[1600px]" : "max-w-[1280px]")}>
      {breadcrumb && <div className="mb-1.5 text-[13px] text-muted">{breadcrumb}</div>}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold">{title}</h1>
          {subtitle && <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children}
    </div>
  );
}
