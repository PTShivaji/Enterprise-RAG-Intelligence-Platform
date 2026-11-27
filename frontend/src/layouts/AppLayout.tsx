import { useEffect, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { X } from "lucide-react";
import { Header } from "../components/layout/Header";
import { Sidebar } from "../components/layout/Sidebar";
import { useBackendHealth } from "../hooks/useBackendHealth";

export function AppLayout() {
  const health = useBackendHealth();
  const [navOpen, setNavOpen] = useState(false);
  const { pathname } = useLocation();
  const fullBleed = pathname.startsWith("/chat");

  useEffect(() => setNavOpen(false), [pathname]);

  return (
    <div className="flex h-full">
      <aside className="hidden w-60 shrink-0 border-r border-line bg-surface/60 md:block">
        <Sidebar />
      </aside>

      {navOpen && (
        <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setNavOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 animate-fade-in border-r border-line bg-surface shadow-pop">
            <button onClick={() => setNavOpen(false)} aria-label="Close navigation" className="absolute right-3 top-3.5 rounded-md p-1 text-muted hover:bg-surface-2">
              <X className="size-4" aria-hidden />
            </button>
            <Sidebar onNavigate={() => setNavOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <Header health={health} onOpenNav={() => setNavOpen(true)} />
        {health.state === "offline" && (
          <div role="alert" className="border-b border-danger/20 bg-danger-soft px-6 py-2 text-xs text-red-200">
            The backend is unreachable. Start it on port 8001 — requests will fail until it is back.
          </div>
        )}
        <main className={fullBleed ? "min-h-0 flex-1" : "min-h-0 flex-1 overflow-y-auto"}>
          {fullBleed ? (
            <Outlet />
          ) : (
            <div className="mx-auto w-full max-w-6xl px-4 py-6 md:px-8 md:py-8">
              <Outlet />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
