import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { BookMarked, Layers, ShieldCheck } from "lucide-react";
import { Brand } from "../components/layout/Brand";
import { Button, ErrorBanner } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { errorMessage } from "../services/api";
import { authService } from "../services/auth.service";

const FEATURES = [
  { icon: Layers, title: "Hybrid retrieval", text: "Vector + full-text search fused with RRF, reranked by a cross-encoder." },
  { icon: BookMarked, title: "Verifiable citations", text: "Every answer links to the exact passage, section and page it came from." },
  { icon: ShieldCheck, title: "Refuses to guess", text: "When the evidence is not there, the system says so instead of hallucinating." },
];

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";

  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (user) return <Navigate to={from} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (mode === "register") await authService.register(email, password, fullName);
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const switchMode = () => {
    setMode((m) => (m === "login" ? "register" : "login"));
    setError(null);
  };

  return (
    <div className="grid min-h-full lg:grid-cols-[1.1fr_1fr]">
      <aside className="relative hidden overflow-hidden border-r border-line bg-surface lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div className="pointer-events-none absolute -left-32 -top-32 size-[520px] rounded-full bg-accent/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-40 right-0 size-[420px] rounded-full bg-info/10 blur-3xl" />
        <div className="relative"><Brand /></div>
        <div className="relative max-w-md">
          <h1 className="text-3xl font-semibold leading-tight tracking-tight">
            Answers from your documents.
            <span className="block text-muted">With the evidence attached.</span>
          </h1>
          <ul className="mt-10 space-y-6">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <li key={title} className="flex gap-4">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-line-strong bg-surface-2 text-accent">
                  <Icon className="size-4" aria-hidden />
                </span>
                <div>
                  <div className="text-sm font-medium">{title}</div>
                  <div className="mt-0.5 text-sm text-muted">{text}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <p className="relative text-xs text-subtle">FastAPI · PostgreSQL + pgvector · Redis · LiteLLM</p>
      </aside>

      <main className="flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden"><Brand /></div>
          <h2 className="text-xl font-semibold tracking-tight">{mode === "login" ? "Sign in" : "Create your account"}</h2>
          <p className="mt-1 text-sm text-muted">
            {mode === "login" ? "Welcome back. Sign in to your workspace." : "Your documents stay private to your account."}
          </p>

          <form onSubmit={submit} className="mt-8 space-y-4" noValidate={false}>
            {mode === "register" && (
              <div>
                <label htmlFor="name" className="label">Full name <span className="text-subtle">(optional)</span></label>
                <input id="name" className="input h-10" autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={200} />
              </div>
            )}
            <div>
              <label htmlFor="email" className="label">Email</label>
              <input id="email" type="email" required className="input h-10" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </div>
            <div>
              <label htmlFor="password" className="label">Password</label>
              <input
                id="password"
                type="password"
                required
                minLength={mode === "register" ? 8 : undefined}
                className="input h-10"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
              {mode === "register" && <p className="mt-1 text-[11px] text-subtle">At least 8 characters.</p>}
            </div>
            {error && <ErrorBanner message={error} />}
            <Button type="submit" loading={busy} className="h-10 w-full">
              {mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>

          <p className="mt-6 text-center text-sm text-muted">
            {mode === "login" ? "New here?" : "Already have an account?"}{" "}
            <button type="button" onClick={switchMode} className="font-medium text-violet-300 hover:text-violet-200 hover:underline">
              {mode === "login" ? "Create an account" : "Sign in"}
            </button>
          </p>
        </div>
      </main>
    </div>
  );
}
