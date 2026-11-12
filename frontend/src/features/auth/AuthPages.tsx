import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { savePassword } from "@/lib/passwords";
import type { Session } from "@/lib/types";

function Shell({ children, title, subtitle }: { children: React.ReactNode; title: string; subtitle: string }) {
  return (
    <div className="flex min-h-full flex-col bg-bg">
      <header className="flex h-14 items-center gap-2 px-6">
        <Logo className="h-[22px] w-[22px]" /><span className="text-[15px] font-semibold tracking-[-0.01em]">Kruvim</span>
      </header>
      <div className="flex flex-1 items-start justify-center px-4 pb-16 pt-[8vh]">
        <div className="w-full max-w-[400px]">
          <div className="rounded-lg border border-line bg-panel p-7 shadow-panel">
            <h1 className="text-lg font-semibold">{title}</h1>
            <p className="mb-6 mt-1 text-[13px] text-muted">{subtitle}</p>
            {children}
          </div>
        </div>
      </div>
      <footer className="flex justify-center gap-4 px-6 py-5 text-xs text-faint">
        <span>Kruvim audience simulation</span><span>·</span><span>Data stays in your workspace</span>
      </footer>
    </div>
  );
}
export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const nav = useNavigate();
  const loc = useLocation() as { state?: { from?: string } };
  const setSession = useAuth((s) => s.setSession);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saveInBrowser, setSaveInBrowser] = useState(true);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    // Read the form itself so browser autofill works even without a change event.
    const data = new FormData(e.currentTarget as HTMLFormElement);
    const email = String(data.get("email") || "").trim();
    const password = String(data.get("password") || "");
    setBusy(true);
    setErr(null);
    try {
      const s = await api<Session>(`/auth/${mode}`, { json: mode === "login" ? { email, password } : {
        email, password, name: String(data.get("name") || ""), org_name: String(data.get("organization") || ""),
      } }, false);
      setSession(s);
      if (saveInBrowser) void savePassword(email, password, s.user.name || undefined);
      nav(loc.state?.from || "/home", { replace: true });
    } catch (ex) {
      setErr(ex instanceof ApiError ? ex.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell title={mode === "login" ? "Sign in" : "Create your workspace"} subtitle={mode === "login" ? "Sign in to your workspace." : "The free plan includes 2,000 credits a month."}>
      <form onSubmit={submit} autoComplete="on" className="space-y-4">
        {mode === "register" && (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Your name"><Input name="name" autoComplete="name" /></Field>
            <Field label="Workspace"><Input name="organization" autoComplete="organization" placeholder="Acme Media" /></Field>
          </div>
        )}
        {/* Keep browser-managed values in the DOM: rerenders must not replace autofill. */}
        <Field label="Email"><Input id="auth-email" name="email" type="email" required autoComplete="username" autoCapitalize="none" spellCheck={false} /></Field>
        <Field label="Password" hint={mode === "register" ? "10+ characters" : undefined}>
          <Input id="auth-password" name="password" type="password" required minLength={mode === "register" ? 10 : undefined} maxLength={200}
            autoComplete={mode === "login" ? "current-password" : "new-password"} />
        </Field>
        <div className="space-y-1.5">
          <label className="flex items-center gap-2 text-[13px] text-fg">
            <input type="checkbox" checked={saveInBrowser} onChange={(e) => setSaveInBrowser(e.target.checked)} className="accent-brand" />
            Save password in this browser
          </label>
          <p className="text-xs text-muted">Your browser may ask to save your password for future sign-ins. You control saved passwords in your browser settings.</p>
        </div>
        {err && <div className="rounded-md border border-neg/25 bg-neg/[0.06] px-3 py-2 text-[13px] text-neg">{err}</div>}
        <Button type="submit" variant="primary" size="lg" className="w-full" loading={busy}>{mode === "login" ? "Sign in" : "Create account"}</Button>
      </form>
      <div className="mt-6 border-t border-line pt-4 text-center text-[13px] text-muted">
        {mode === "login" ? <>New to Kruvim? <Link className="text-brand hover:underline" to="/register">Create an account</Link></>
          : <>Already have an account? <Link className="text-brand hover:underline" to="/login">Sign in</Link></>}
      </div>
    </Shell>
  );
}

export function InvitePage() {
  const { token } = useParams();
  const nav = useNavigate();
  const setSession = useAuth((s) => s.setSession);
  const [f, setF] = useState({ name: "", password: "" });
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const s = await api<Session>("/auth/invites/accept", { json: { token, name: f.name, password: f.password || null } });
      setSession(s);
      toast.success("Welcome to the workspace");
      nav("/home");
    } catch (ex) {
      toast.error(ex instanceof ApiError ? ex.message : "Could not accept the invite");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Shell title="Join workspace" subtitle="Set a password to accept the invitation (or enter your existing one).">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Your name"><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
        <Field label="Password"><Input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field>
        <Button variant="primary" size="lg" className="w-full" loading={busy}>Accept invite</Button>
      </form>
    </Shell>
  );
}
