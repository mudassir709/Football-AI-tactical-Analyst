// The login page and the registration page. They are almost the same form,
// so one component does both: "mode" says which one to show (registration
// just adds the Name field and a different button text).
import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import { useAuth } from "../auth";
import { ChalkPitch } from "../components/ChalkPitch";
import { Logo } from "../components/Layout";
import { Button, ErrorMessage, inputClasses } from "../components/ui";

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

  // Already logged in? Then there's nothing to do here, go to the match list.
  if (user) return <Navigate to="/" replace />;
  const isRegister = mode === "register";

  // Send the form to the server. On success we're logged in and go to the
  // match list; on failure the server's message (e.g. "Invalid email or
  // password") is shown above the button. "submitting" disables the button
  // so the form can't be sent twice.
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
    // Two halves on wide screens: the chalk drawing on the left, the form on
    // the right. On phones only the form is shown.
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <div className="hidden flex-col justify-between border-r border-dashed border-line p-12 lg:flex">
        <Logo className="text-3xl" />
        <ChalkPitch className="mx-auto w-full max-w-lg" />
        <p className="max-w-md font-hand text-2xl leading-snug text-chalk/90">
          Upload a match. See every run, shape and formation, drawn right on the video.
        </p>
      </div>

      <div className="grid place-items-center px-4 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo className="text-3xl" />
          </div>
          <h1 className="text-2xl font-semibold">{isRegister ? "Create an account" : "Log in"}</h1>
          <p className="mt-1 mb-8 text-sm text-dim">
            {isRegister
              ? "Upload match footage and get AI tactical analysis."
              : "Welcome back. Log in to see your matches."}
          </p>
          <form onSubmit={handleSubmit} className="space-y-5">
            {isRegister && (
              <label className="block space-y-1.5 text-sm">
                <span className="text-dim">Name</span>
                <input className={inputClasses} value={name} onChange={(e) => setName(e.target.value)} required autoComplete="name" />
              </label>
            )}
            <label className="block space-y-1.5 text-sm">
              <span className="text-dim">Email</span>
              <input className={inputClasses} type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
            </label>
            <label className="block space-y-1.5 text-sm">
              <span className="text-dim">Password</span>
              <input
                className={inputClasses}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={isRegister ? 8 : undefined}
                autoComplete={isRegister ? "new-password" : "current-password"}
              />
              {isRegister && <span className="font-mono text-xs text-dim">at least 8 characters</span>}
            </label>
            {error && <ErrorMessage>{error}</ErrorMessage>}
            <Button type="submit" className="w-full" disabled={submitting}>
              {submitting ? "Please wait…" : isRegister ? "Create account" : "Log in"}
            </Button>
          </form>
          <p className="mt-8 border-t border-dashed border-line pt-6 text-sm text-dim">
            {isRegister ? "Already have an account? " : "New here? "}
            <Link to={isRegister ? "/login" : "/register"} className="font-medium text-accent hover:underline">
              {isRegister ? "Log in" : "Create an account"}
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
