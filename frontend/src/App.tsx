import { Loader2 } from "lucide-react";
import { lazy, Suspense, useEffect } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "./components/layout/AppShell";
import { refreshSession } from "./lib/api";
import { useAuth } from "./lib/auth";
import { pageLoaders, preloadRoute } from "./lib/routes";
import { AuthPage, InvitePage } from "./features/auth/AuthPages";

const Dashboard = lazy(pageLoaders.Dashboard);
const Help = lazy(pageLoaders.Help);
const AllRuns = lazy(pageLoaders.AllRuns);
const Projects = lazy(pageLoaders.Projects);
const Project = lazy(pageLoaders.Project);
const NewSimulation = lazy(pageLoaders.NewSimulation);
const Simulation = lazy(pageLoaders.Simulation);
const DataPool = lazy(pageLoaders.DataPool);
const Library = lazy(pageLoaders.Library);
const Population = lazy(pageLoaders.Population);
const Audiences = lazy(pageLoaders.Audiences);
const Calibration = lazy(pageLoaders.Calibration);
const MyAudience = lazy(pageLoaders.MyAudience);
const PublicResults = lazy(pageLoaders.PublicResults);
const PublicAccuracy = lazy(pageLoaders.PublicAccuracy);
const Settings = lazy(pageLoaders.Settings);
const Usage = lazy(pageLoaders.Usage);
const Admin = lazy(pageLoaders.Admin);
const Monitoring = lazy(pageLoaders.Monitoring);

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

function LegacyAudiences() {
  const { search, hash } = useLocation();
  return <Navigate to={{ pathname: "/saved-audiences", search, hash }} replace />;
}

function PlatformDataPool() {
  const allowed = useAuth(state => !!state.user?.is_superuser);
  return allowed ? <DataPool /> : <Navigate to="/data-library" replace />;
}

export default function App() {
  const markReady = useAuth((state) => state.markReady);
  const signedIn = useAuth((state) => !!state.accessToken);
  useEffect(() => {
    // Load the requested page while restoring the session. Refresh already
    // returns the current user and workspaces; /auth/me adds a serial round trip.
    preloadRoute(window.location.pathname.replace(import.meta.env.BASE_URL.replace(/\/$/, ""), "") || "/");
    void refreshSession().finally(markReady);
    const t = setInterval(() => { if (useAuth.getState().accessToken) refreshSession(); }, 20 * 60 * 1000);
    return () => clearInterval(t);
  }, [markReady]);

  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route path="/login" element={<AuthPage key="login" mode="login" />} />
        <Route path="/register" element={<AuthPage key="register" mode="register" />} />
        <Route path="/invite/:token" element={<InvitePage />} />
        <Route path="/share/:token" element={<PublicResults />} />
        <Route path="/accuracy" element={signedIn ? <AppShell /> : <PublicAccuracy />}>
          <Route index element={<PublicAccuracy />} />
        </Route>
        <Route element={<RequireAuth><AppShell /></RequireAuth>}>
          <Route index element={<Navigate to="/home" replace />} />
          <Route path="home" element={<NewSimulation home />} />
          <Route path="overview" element={<Dashboard />} />
          <Route path="help" element={<Help />} />
          <Route path="tests" element={<AllRuns simple />} />
          <Route path="runs" element={<AllRuns />} />
          <Route path="projects" element={<Projects />} />
          <Route path="projects/:projectId" element={<Project />} />
          <Route path="projects/:projectId/new" element={<NewSimulation />} />
          <Route path="simulations/:simId" element={<Simulation />} />
          <Route path="simulations/:simId/edit" element={<NewSimulation />} />
          <Route path="data-pool" element={<PlatformDataPool />} />
          <Route path="data-library" element={<Library />} />
          <Route path="population" element={<Population />} />
          <Route path="saved-audiences" element={<Audiences />} />
          <Route path="audiences" element={<LegacyAudiences />} />
          <Route path="my-audience" element={<MyAudience />} />
          <Route path="monitoring" element={<Monitoring />} />
          <Route path="calibration" element={<Calibration />} />
          <Route path="settings" element={<Settings />} />
          <Route path="usage" element={<Usage />} />
          <Route path="admin" element={<Admin />} />
        </Route>
        <Route path="*" element={<Navigate to="/home" replace />} />
      </Routes>
    </Suspense>
  );
}
