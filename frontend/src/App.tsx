import { Loader2 } from "lucide-react";
import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { api, refreshSession } from "./lib/api";
import { useAuth } from "./lib/auth";
import { AuthPage, InvitePage } from "./features/auth/AuthPages";

const Dashboard = lazy(() => import("./features/dashboard/DashboardPage"));
const Projects = lazy(() => import("./features/projects/ProjectsPage"));
const Project = lazy(() => import("./features/projects/ProjectPage"));
const NewSimulation = lazy(() => import("./features/simulations/NewSimulationPage"));
const Simulation = lazy(() => import("./features/simulations/SimulationPage"));
const DataPool = lazy(() => import("./features/datapool/DataPoolPage"));
const Population = lazy(() => import("./features/population/PopulationPage"));
const Audiences = lazy(() => import("./features/audiences/AudiencesPage"));
const Calibration = lazy(() => import("./features/calibration/CalibrationPage"));
const MyAudience = lazy(() => import("./features/audiences/MyAudiencePage"));
const PublicResults = lazy(() => import("./features/simulations/PublicResultsPage"));
const PublicAccuracy = lazy(() => import("./features/calibration/PublicAccuracyPage"));
const Settings = lazy(() => import("./features/settings/SettingsPage"));
const Usage = lazy(() => import("./features/settings/UsagePage"));
const Admin = lazy(() => import("./features/admin/AdminPage"));
const Monitoring = lazy(() => import("./features/monitoring/MonitoringPage"));

function Spinner() {
  return <div className="flex h-full items-center justify-center text-muted"><Loader2 className="h-5 w-5 animate-spin" /></div>;
}

function RequireAuth({ children }: { children: JSX.Element }) {
  const { accessToken, ready } = useAuth();
  const loc = useLocation();
  if (!ready) return <Spinner />;
  if (!accessToken) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  return children;
}

export default function App() {
  const { markReady, setOrgs } = useAuth();
  useEffect(() => {
    (async () => {
      if (await refreshSession()) {
        try {
          const me = await api("/auth/me");
          setOrgs(me.orgs, me.user);
        } catch { /* handled by guard */ }
      }
      markReady();
    })();
    const t = setInterval(() => { if (useAuth.getState().accessToken) refreshSession(); }, 20 * 60 * 1000);
    return () => clearInterval(t);
  }, [markReady, setOrgs]);

  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/register" element={<AuthPage mode="register" />} />
        <Route path="/invite/:token" element={<InvitePage />} />
        <Route path="/share/:token" element={<PublicResults />} />
        <Route path="/accuracy" element={<PublicAccuracy />} />
        <Route element={<RequireAuth><AppShell /></RequireAuth>}>
          <Route index element={<Dashboard />} />
          <Route path="projects" element={<Projects />} />
          <Route path="projects/:projectId" element={<Project />} />
          <Route path="projects/:projectId/new" element={<NewSimulation />} />
          <Route path="simulations/:simId" element={<Simulation />} />
          <Route path="simulations/:simId/edit" element={<NewSimulation />} />
          <Route path="data-pool" element={<DataPool />} />
          <Route path="population" element={<Population />} />
          <Route path="audiences" element={<Audiences />} />
          <Route path="my-audience" element={<MyAudience />} />
          <Route path="monitoring" element={<Monitoring />} />
          <Route path="calibration" element={<Calibration />} />
          <Route path="settings" element={<Settings />} />
          <Route path="usage" element={<Usage />} />
          <Route path="admin" element={<Admin />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  );
}
