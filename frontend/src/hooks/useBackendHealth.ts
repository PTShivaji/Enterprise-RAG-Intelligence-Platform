import { useEffect, useState } from "react";
import { platformService } from "../services/platform.service";
import type { ReadinessResponse } from "../types/api";

export type BackendState = "checking" | "ready" | "degraded" | "offline";

export interface BackendHealth {
  state: BackendState;
  checks: ReadinessResponse["checks"] | null;
  checkedAt: Date | null;
}

/** Polls GET /health/ready. "degraded" = backend reachable but a readiness check failed. */
export function useBackendHealth(intervalMs = 30_000): BackendHealth {
  const [health, setHealth] = useState<BackendHealth>({ state: "checking", checks: null, checkedAt: null });

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      try {
        const r = await platformService.readiness();
        if (!cancelled) {
          setHealth({ state: r.status === "ready" ? "ready" : "degraded", checks: r.checks, checkedAt: new Date() });
        }
      } catch {
        if (!cancelled) setHealth({ state: "offline", checks: null, checkedAt: new Date() });
      }
    };
    void check();
    const timer = window.setInterval(check, intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [intervalMs]);

  return health;
}
