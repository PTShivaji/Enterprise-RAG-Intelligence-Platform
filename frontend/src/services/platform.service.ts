import axios from "axios";
import { api, API_PREFIX } from "./api";
import type {
  AnalyticsOverview,
  EvaluationRunSummary,
  ModelInfo,
  RAGSettings,
  ReadinessResponse,
  SearchHistoryItem,
  SearchRequest,
  SearchResponse,
  UsageResponse,
} from "../types/api";

/** Search, analytics, settings, models and health. */
export const platformService = {
  async search(body: SearchRequest): Promise<SearchResponse> {
    const { data } = await api.post<SearchResponse>("/search", body);
    return data;
  },

  async searchHistory(limit = 10): Promise<SearchHistoryItem[]> {
    const { data } = await api.get<SearchHistoryItem[]>("/search/history", { params: { limit } });
    return data;
  },

  async overview(): Promise<AnalyticsOverview> {
    const { data } = await api.get<AnalyticsOverview>("/analytics/overview");
    return data;
  },

  async usage(days = 14): Promise<UsageResponse> {
    const { data } = await api.get<UsageResponse>("/analytics/usage", { params: { days } });
    return data;
  },

  async evaluations(limit = 10): Promise<EvaluationRunSummary[]> {
    const { data } = await api.get<EvaluationRunSummary[]>("/evaluation/results", { params: { limit } });
    return data;
  },

  async models(): Promise<ModelInfo> {
    const { data } = await api.get<ModelInfo>("/models");
    return data;
  },

  async settings(): Promise<RAGSettings> {
    const { data } = await api.get<RAGSettings>("/settings");
    return data;
  },

  async updateSettings(patch: Partial<RAGSettings>): Promise<RAGSettings> {
    const { data } = await api.put<RAGSettings>("/settings", patch);
    return data;
  },

  /** Unauthenticated readiness probe; a 503 still carries the per-check body. */
  async readiness(): Promise<ReadinessResponse> {
    try {
      const { data } = await axios.get<ReadinessResponse>(`${API_PREFIX}/health/ready`, { timeout: 8000 });
      return data;
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.data) return err.response.data as ReadinessResponse;
      throw err;
    }
  },
};

/** Maps a LiteLLM model id to the provider key used in ModelInfo.llm_configured_providers. */
export function providerOf(model: string): string {
  if (model === "local") return "local";
  if (model.startsWith("ollama/")) return "ollama";
  if (model.startsWith("anthropic/")) return "anthropic";
  if (model.startsWith("gemini/")) return "gemini";
  return "openai";
}
