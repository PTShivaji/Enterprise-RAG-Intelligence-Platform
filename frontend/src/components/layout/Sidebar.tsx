import { NavLink } from "react-router-dom";
import { LogOut } from "lucide-react";
import { useAuth } from "../../context/AuthContext";
import { cx, initials } from "../../utils/format";
import { Brand } from "./Brand";
import { NAV_ITEMS } from "./nav";

export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { user, logout } = useAuth();

  return (
    <div className="flex h-full flex-col">
      <div className="flex h-14 items-center border-b border-line px-4">
        <Brand />
      </div>

      <nav aria-label="Main" className="flex-1 space-y-0.5 overflow-y-auto p-3">
        <div className="px-2 pb-2 pt-1 text-[10px] font-semibold uppercase tracking-wider text-subtle">Workspace</div>
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            onClick={onNavigate}
            className={({ isActive }) =>
              cx(
                "group flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm transition-colors",
                isActive ? "bg-surface-2 text-fg shadow-[inset_0_0_0_1px_var(--color-line-strong)]" : "text-muted hover:bg-surface-2/60 hover:text-fg",
              )
            }
          >
            {({ isActive }) => (
              <>
                <Icon className={cx("size-4", isActive ? "text-accent" : "text-subtle group-hover:text-muted")} aria-hidden />
                {label}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {user && (
        <div className="border-t border-line p-3">
          <div className="flex items-center gap-3 rounded-lg px-2 py-2">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-linear-to-br from-accent/80 to-info/80 text-xs font-semibold text-white">
              {initials(user.full_name || user.email)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-fg">{user.full_name || user.email.split("@")[0]}</div>
              <div className="truncate text-[11px] text-subtle">
                {user.email} · <span className="capitalize">{user.role}</span>
              </div>
            </div>
            <button
              onClick={() => void logout()}
              aria-label="Sign out"
              title="Sign out"
              className="rounded-md p-1.5 text-subtle transition-colors hover:bg-surface-2 hover:text-fg"
            >
              <LogOut className="size-4" aria-hidden />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
