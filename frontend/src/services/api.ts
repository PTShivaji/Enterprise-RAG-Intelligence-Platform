import axios, { AxiosError } from "axios";
import type { ApiErrorBody } from "../types/api";

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001").replace(/\/+$/, "");
export const API_PREFIX = `${API_BASE_URL}/api/v1`;

/*
 * Token storage: the backend returns a bearer JWT in the response body (no cookie flow),
 * so the token must live in JS. sessionStorage is used rather than localStorage so it is
 * dropped when the tab closes; logout also revokes the token server-side (jti denylist).
 */
const TOKEN_KEY = "rag.access_token";

export const tokenStore = {
  get(): string | null {
    try {
      return sessionStorage.getItem(TOKEN_KEY);
    } catch {
      return null;
    }
  },
  set(token: string) {
    try {
      sessionStorage.setItem(TOKEN_KEY, token);
    } catch {
      /* storage unavailable: token lives only for this page load */
    }
  },
  clear() {
    try {
      sessionStorage.removeItem(TOKEN_KEY);
    } catch {
      /* ignore */
    }
  },
};

/** Fired when an authenticated request returns 401 so the auth context can sign out. */
export const UNAUTHORIZED_EVENT = "rag:unauthorized";

export const api = axios.create({ baseURL: API_PREFIX, timeout: 300_000 });

api.interceptors.request.use((config) => {
  const token = tokenStore.get();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const url = error.config?.url ?? "";
    if (error.response?.status === 401 && !url.startsWith("/auth/login")) {
      window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    }
    return Promise.reject(error);
  },
);

/** Human-readable message from any error thrown by the API layer. */
export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    if (!error.response) {
      return error.code === "ECONNABORTED"
        ? "The request timed out."
        : `Cannot reach the backend at ${API_BASE_URL}. Is it running?`;
    }
    const body = error.response.data as Partial<ApiErrorBody> & { detail?: unknown } | undefined;
    if (body?.message) return body.message;
    if (Array.isArray(body?.detail)) {
      return body.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ") || "Validation failed";
    }
    return `Request failed (HTTP ${error.response.status})`;
  }
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}
