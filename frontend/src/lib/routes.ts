// Keep imports shared by React.lazy and navigation preloading so both use the
// same chunks. Preloading fetches code only, never workspace data.
export const pageLoaders = {
  Dashboard: () => import("../features/dashboard/DashboardPage"),
  Help: () => import("../features/help/HelpPage"),
  AllRuns: () => import("../features/simulations/AllRunsPage"),
  Projects: () => import("../features/projects/ProjectsPage"),
  Project: () => import("../features/projects/ProjectPage"),
  NewSimulation: () => import("../features/simulations/NewSimulationPage"),
  Simulation: () => import("../features/simulations/SimulationPage"),
  DataPool: () => import("../features/datapool/DataPoolPage"),
  Library: () => import("../features/datapool/LibraryPage"),
  Population: () => import("../features/population/PopulationPage"),
  Audiences: () => import("../features/audiences/AudiencesPage"),
  Calibration: () => import("../features/calibration/CalibrationPage"),
  MyAudience: () => import("../features/audiences/MyAudiencePage"),
  PublicResults: () => import("../features/simulations/PublicResultsPage"),
  PublicAccuracy: () => import("../features/calibration/PublicAccuracyPage"),
  Settings: () => import("../features/settings/SettingsPage"),
  Usage: () => import("../features/settings/UsagePage"),
  Admin: () => import("../features/admin/AdminPage"),
  Monitoring: () => import("../features/monitoring/MonitoringPage"),
};

const routes: Record<string, keyof typeof pageLoaders> = {
  "/": "NewSimulation", "/overview": "Dashboard", "/help": "Help",
  "/tests": "AllRuns", "/runs": "AllRuns", "/projects": "Projects",
  "/data-pool": "DataPool", "/data-library": "Library", "/population": "Population",
  "/saved-audiences": "Audiences", "/audiences": "Audiences", "/calibration": "Calibration",
  "/my-audience": "MyAudience", "/accuracy": "PublicAccuracy", "/settings": "Settings",
  "/usage": "Usage", "/admin": "Admin", "/monitoring": "Monitoring",
};

export function preloadRoute(pathname: string) {
  const path = pathname.replace(/\/$/, "") || "/";
  const page = routes[path]
    ?? (/^\/projects\/[^/]+\/new$/.test(path) || /^\/simulations\/[^/]+\/edit$/.test(path) ? "NewSimulation"
      : /^\/projects\/[^/]+$/.test(path) ? "Project"
        : /^\/simulations\/[^/]+$/.test(path) ? "Simulation"
          : /^\/share\/[^/]+$/.test(path) ? "PublicResults" : undefined);
  if (page) void pageLoaders[page]().catch(() => { /* React.lazy handles failed navigation loads. */ });
}
