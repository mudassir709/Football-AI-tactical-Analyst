// Login and registration form (one component, two modes).
import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { useAuth } from "../auth";
import { Logo } from "../components/Layout";
import { Button, Card, ErrorMessage } from "../components/ui";

const inputClass =
  "w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm outline-none focus:border-emerald-400";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  // useState holds values that change while the page is open;
  // changing one re-renders the component with the new value.
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/" replace />;
  const isRegister = mode === "register";

  async function handleSubmit(event: FormEvent) {
    event.preventDefault(); // stop the browser's default full-page form submit
    setError(null);
    setSubmitting(true);
    try {
      if (isRegister) await register(name, email, password);
      else await login(email, password);
      navigate("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex justify-center text-xl">
          <Logo />
        </div>
        <Card>
          <h1 className="mb-1 text-lg font-semibold">{isRegister ? "Create an account" : "Log in"}</h1>
          <p className="mb-5 text-sm text-slate-400">
            {isRegister
              ? "Upload match footage and get AI tactical analysis."
              : "Welcome back. Log in to see your matches."}
          </p>
          <form onSubmit={handleSubmit} className="space-y-4">
            {isRegister && (
              <label className="block space-y-1 text-sm">
                <span className="text-slate-300">Name</span>
                <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
              </label>
            )}
            <label className="block space-y-1 text-sm">
              <span className="text-slate-300">Email</span>
              <input className={inputClass} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
            </label>
            <label className="block space-y-1 text-sm">
              <span className="text-slate-300">Password</span>
              <input
                className={inputClass}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={isRegister ? 8 : undefined}
                autoComplete={isRegister ? "new-password" : "current-password"}
              />
              {isRegister && <span className="text-xs text-slate-500">At least 8 characters</span>}
            </label>
            {error && <ErrorMessage>{error}</ErrorMessage>}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Please wait…" : isRegister ? "Create account" : "Log in"}
            </Button>
          </form>
        </Card>
        <p className="mt-4 text-center text-sm text-slate-400">
          {isRegister ? "Already have an account? " : "New here? "}
          <Link to={isRegister ? "/login" : "/register"} className="font-medium text-emerald-400 hover:underline">
            {isRegister ? "Log in" : "Create an account"}
          </Link>
        </p>
      </div>
    </div>
  );
}
