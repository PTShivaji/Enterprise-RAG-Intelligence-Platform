import { api, tokenStore } from "./api";
import type { TokenResponse, User } from "../types/api";

export const authService = {
  async login(email: string, password: string): Promise<TokenResponse> {
    const { data } = await api.post<TokenResponse>("/auth/login", { email, password });
    tokenStore.set(data.access_token);
    return data;
  },

  async register(email: string, password: string, fullName: string): Promise<User> {
    const { data } = await api.post<User>("/auth/register", {
      email,
      password,
      full_name: fullName.trim() || null,
    });
    return data;
  },

  async me(): Promise<User> {
    const { data } = await api.get<User>("/auth/me");
    return data;
  },

  /** Revokes the token server-side; local token is cleared even if the call fails. */
  async logout(): Promise<void> {
    try {
      if (tokenStore.get()) await api.post("/auth/logout");
    } finally {
      tokenStore.clear();
    }
  },
};
