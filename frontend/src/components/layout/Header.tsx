import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ChevronRight, LogOut, Menu, Settings as SettingsIcon } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import type { BackendHealth } from "../../hooks/useBackendHealth";
import { API_BASE_URL } from "../../services/api";
import { cx, initials } from "../../utils/format";
import { navItemFor } from "./nav";

const healthStyle = {
  checking: { dot: "bg-subtle", label: "Connecting" },
  ready: { dot: "bg-ok", label: "Backend online" },
  degraded: { dot: "bg-warn", label: "Backend degraded" },
  offline: { dot: "bg-danger", label: "Backend offline" },
} as const;

function HealthIndicator({ health }: { health: BackendHealth }) {
  const s = healthStyle[health.state];
  const failing = health.checks
    ? Object.entries(health.checks).filter(([, c]) => !c.ok).map(([k]) => k)
    : [];
  const title =
    health.state === "offline"
      ? `Cannot reach ${API_BASE_URL}`
      : failing.length
        ? `Failing checks: ${failing.join(", ")}`
        : `${API_BASE_URL} · database, pgvector, redis and models ready`;
  return (
    <div title={title} className="hidden items-center gap-2 rounded-full border border-line bg-surface px-2.5 py-1 text-xs text-muted sm:flex">
      <span className="relative flex size-2">
        {health.state === "ready" && <span className="absolute inline-flex size-full animate-ping rounded-full bg-ok/40" />}
        <span className={cx("relative inline-flex size-2 rounded-full", s.dot)} />
      </span>
      {s.label}
    </div>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;
  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        className="flex size-8 items-center justify-center rounded-full bg-linear-to-br from-accent/80 to-info/80 text-xs font-semibold text-white ring-offset-2 ring-offset-canvas transition hover:ring-2 hover:ring-line-strong"
      >
        {initials(user.full_name || user.email)}
      </button>
      {open && (
        <div role="menu" className="card absolute right-0 top-10 z-40 w-64 animate-fade-in p-1.5 shadow-pop">
          <div className="px-3 py-2.5">
            <div className="truncate text-sm font-medium">{user.full_name || user.email}</div>
            <div className="truncate text-xs text-muted">{user.email}</div>
            <div className="mt-1.5 text-[11px] text-subtle">
              Role: <span className="capitalize text-muted">{user.role}</span> · Member since{" "}
              {new Date(user.created_at).toLocaleDateString(undefined, { month: "short", year: "numeric" })}
            </div>
          </div>
          <div className="my-1 h-px bg-line" />
          <Link role="menuitem" to="/settings" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted hover:bg-surface-2 hover:text-fg">
            <SettingsIcon className="size-4" aria-hidden /> Settings
          </Link>
          <button role="menuitem" onClick={() => void logout()} className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-sm text-muted hover:bg-surface-2 hover:text-fg">
            <LogOut className="size-4" aria-hidden /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

export function Header({ health, onOpenNav }: { health: BackendHealth; onOpenNav: () => void }) {
  const { pathname } = useLocation();
  const item = navItemFor(pathname);
  return (
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-line bg-canvas/85 px-4 backdrop-blur-md md:px-6">
      <button onClick={onOpenNav} aria-label="Open navigation" className="-ml-1 rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-fg md:hidden">
        <Menu className="size-5" aria-hidden />
      </button>
      <div className="min-w-0 flex-1">
        <nav aria-label="Breadcrumb" className="flex items-center gap-1 text-[11px] text-subtle">
          <Link to="/" className="hover:text-muted">Workspace</Link>
          <ChevronRight className="size-3" aria-hidden />
          <span className="truncate text-muted">{item.label}</span>
        </nav>
        <div className="truncate text-sm font-semibold text-fg">{item.label}</div>
      </div>
      <HealthIndicator health={health} />
      <UserMenu />
    </header>
  );
}
