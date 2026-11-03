// The frame around every page you see after logging in: a slim top bar with
// the logo, the menu (Matches, Upload), your name and "Log out", and below it
// the page itself. <Outlet /> is the spot where React Router puts the current page.
// It also guards those pages: if nobody is logged in, it sends you to /login.
import { Link, NavLink, Navigate, Outlet, useNavigate } from "react-router";
import { useAuth } from "../auth";
import { Spinner } from "./ui";

// Menu link style; the page you're on is underlined in amber.
const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `border-b-2 pb-0.5 text-sm font-medium transition-colors ${
    isActive ? "border-accent text-chalk" : "border-transparent text-dim hover:text-chalk"
  }`;

// The name in handwriting, like it was written on the board. Clicking it
// always goes back to the match list.
export function Logo({ className = "text-2xl" }: { className?: string }) {
  return (
    <Link to="/" className={`font-hand leading-none text-accent ${className}`}>
      Tactical Eye
    </Link>
  );
}

export function Layout() {
  const { user, loading, logout } = useAuth();
  const navigate = useNavigate();

  // Right after opening the site we don't know yet if the login cookie is
  // still valid, so show a spinner until the server has answered.
  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center">
        <Spinner />
      </div>
    );
  }
  // Not logged in: send the visitor to the login page.
  if (!user) return <Navigate to="/login" replace />;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-dashed border-line bg-pitch/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1400px] flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3 sm:px-8">
          <Logo />
          <nav className="flex gap-6">
            <NavLink to="/" end className={navLinkClass}>
              Matches
            </NavLink>
            <NavLink to="/upload" className={navLinkClass}>
              Upload
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-2 text-sm text-dim">
            <span>{user.name}</span>
            <span aria-hidden>·</span>
            <button
              className="hover:text-chalk"
              onClick={async () => {
                await logout();
                navigate("/login");
              }}
            >
              Log out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1400px] px-4 py-8 sm:px-8">
        <Outlet />
      </main>
    </div>
  );
}
