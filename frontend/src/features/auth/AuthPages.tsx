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
      if (mode === "register") toast.success("Check your email to verify your account.");
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
      {mode === "login" && <div className="mt-4 flex justify-between text-[13px] text-brand">
        <Link to="/forgot-password">Forgot password?</Link><Link to="/verification-email">Verify email</Link>
      </div>}
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
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    const data = new FormData(e.currentTarget as HTMLFormElement);
    setBusy(true);
    try {
      const s = await api<Session>("/auth/invites/accept", { json: {
        token, name: String(data.get("name") || ""), password: String(data.get("password") || ""),
      } }, false);
      setSession(s);
      toast.success("Welcome to the workspace");
      nav("/");
    } catch (ex) {
      toast.error(ex instanceof ApiError ? ex.message : "Could not accept the invite");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Shell title="Join workspace" subtitle="Already have an account? Enter its password. New to Kruvim? Choose a password with at least 10 characters.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Your name"><Input name="name" autoComplete="name" /></Field>
        <Field label="Password"><Input name="password" type="password" required minLength={10} maxLength={200} /></Field>
        <Button variant="primary" size="lg" className="w-full" loading={busy}>Accept invite</Button>
      </form>
    </Shell>
  );
}


export function AccountRecoveryPage({ mode }: { mode: "forgot" | "reset" | "verify" | "resend" }) {
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get("token") || "");
  const accountEmail = useAuth((state) => state.user?.email || "");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const needsToken = mode === "reset" || mode === "verify";
  const title = { forgot: "Forgot password", reset: "Choose a new password", verify: "Verify your email", resend: "Request verification email" }[mode];
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      const endpoint = { forgot: "forgot-password", reset: "reset-password", verify: "verify-email", resend: "verification-email" }[mode];
      await api(`/auth/${endpoint}`, { json: needsToken ? { token, ...(mode === "reset" ? { new_password: String(form.get("password") || "") } : {}) } : { email: String(form.get("email") || "").trim() } }, false);
      if (mode === "reset") useAuth.getState().clear();
      if (mode === "verify" && useAuth.getState().accessToken) {
        try {
          const me = await api("/auth/me");
          useAuth.getState().setOrgs(me.orgs, me.user);
        } catch {
          // Verification already succeeded; a session refresh failure must not undo its confirmation.
          useAuth.getState().clear();
        }
      }
      setDone(true);
      window.history.replaceState(null, "", window.location.pathname);
    } catch (ex) {
      setError(ex instanceof ApiError ? ex.message : "Could not complete your request. Please try again.");
    } finally { setBusy(false); }
  }
  return <Shell title={title} subtitle={mode === "verify" ? "Confirm to verify the email address linked to this account." : "Keep access to your Kruvim account."}>
    {done ? <p role="status" className="text-sm">{mode === "reset" ? "Your password has been reset. Sign in with your new password." : mode === "verify" ? "Your email is verified." : "If this account is eligible, an email will be sent shortly. Check your inbox and spam folder."}</p> :
      <form onSubmit={submit} className="space-y-4">
        {!needsToken && <Field label="Email"><Input name="email" type="email" required autoComplete="email" defaultValue={accountEmail} /></Field>}
        {mode === "reset" && <Field label="New password" hint="10+ characters"><Input name="password" type="password" required minLength={10} maxLength={200} autoComplete="new-password" /></Field>}
        {needsToken && !token && <p role="alert" className="text-sm text-neg">This link is missing its token. Request a new email.</p>}
        {error && <p role="alert" className="text-sm text-neg">{error}</p>}
        <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={needsToken && !token}>{mode === "verify" ? "Verify email" : mode === "reset" ? "Reset password" : "Send email"}</Button>
      </form>}
    <div className="mt-5 flex justify-between text-sm text-brand"><Link to="/login">Back to sign in</Link>{mode === "verify" && done && <Link to="/">Continue to workspace</Link>}{needsToken && <Link to={mode === "reset" ? "/forgot-password" : "/verification-email"}>Request a new link</Link>}</div>
  </Shell>;
}
