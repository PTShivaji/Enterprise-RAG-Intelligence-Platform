// Types mirror the backend's OpenAPI schemas (GET /api/v1/openapi.json).
// Free-form `dict` fields are typed from responses captured from the running backend.

export interface ApiErrorBody {
  error: string;
  message: string;
  request_id?: string;
  details?: unknown;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: string;
  is_active: boolean;
  created_at: string;
}

export type DocumentStatus = "uploaded" | "processing" | "indexed" | "failed";

export interface DocumentItem {
  id: string;
  filename: string;
  file_type: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  status: DocumentStatus;
  error_message: string | null;
  page_count: number | null;
  chunk_count: number;
  token_count: number;
  title: string | null;
  metadata: { section_titles?: string[]; words?: number; [k: string]: unknown };
  embedding_model: string | null;
  chunking_config: { strategy?: string; chunk_size?: number; overlap?: number };
  ingestion_ms: number | null;
  created_at: string;
  updated_at: string;
  indexed_at: string | null;
}

export interface DocumentList {
  items: DocumentItem[];
  total: number;
}

export interface DocumentUploadResponse {
  document: DocumentItem;
  duplicate: boolean;
  ingestion_queued: boolean;
}

export interface DocumentStatusResponse {
  id: string;
  status: DocumentStatus;
  chunk_count: number;
  error_message: string | null;
  indexed_at: string | null;
}

export interface Chunk {
  id: string;
  chunk_index: number;
  content: string;
  page_number: number | null;
  page_end: number | null;
  section: string | null;
  token_count: number;
  char_start: number;
  char_end: number;
}

export interface ChunkList {
  items: Chunk[];
  total: number;
}

export type SearchMode = "vector" | "keyword" | "hybrid";

export interface SearchFilters {
  document_ids?: string[] | null;
  file_types?: string[] | null;
  filename_contains?: string | null;
  page_from?: number | null;
  page_to?: number | null;
}

export interface SearchRequest {
  query: string;
  top_k?: number | null;
  search_mode?: SearchMode | null;
  rerank?: boolean | null;
  filters?: SearchFilters;
}

export interface SearchResultItem {
  chunk_id: string;
  document_id: string;
  filename: string;
  file_type: string;
  content: string;
  chunk_index: number;
  page_number: number | null;
  page_end: number | null;
  section: string | null;
  vector_score: number | null;
  keyword_score: number | null;
  vector_rank: number | null;
  keyword_rank: number | null;
  fused_score: number | null;
  rerank_score: number | null;
  final_rank: number | null;
}

export interface SearchResponse {
  query: string;
  search_mode: SearchMode;
  reranked: boolean;
  results: SearchResultItem[];
  expanded_terms: string[];
  query_variants: string[];
  cache_hit: boolean;
  embedding_cache_hit: boolean;
  candidates_considered: number;
  timings_ms: Record<string, number>;
}

export interface SearchHistoryItem {
  id: string;
  query: string | null;
  latency_ms: number;
  results: number | null;
  cache_hit: boolean | null;
  created_at: string;
}

export interface Citation {
  index: number;
  document_id: string;
  filename: string;
  chunk_id: string;
  chunk_ids: string[];
  page_number: number | null;
  page_end: number | null;
  section: string | null;
  text: string;
  retrieval_score: number | null;
  rerank_score: number | null;
  vector_score: number | null;
  support_score: number;
}

export interface Verification {
  grounded?: boolean;
  grounding_score?: number;
  citation_count?: number;
  uncited_sentences?: number;
  weakly_supported_sentences?: number;
  invalid_markers_removed?: string[];
  insufficient_evidence?: boolean;
  reason?: string;
}

export interface Usage {
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  context_tokens?: number;
  cost_usd?: number;
}

export interface ChatRequest {
  message: string;
  conversation_id?: string | null;
  model?: string | null;
}

export interface ChatResponse {
  conversation_id: string;
  message_id: string;
  answer: string;
  citations: Citation[];
  insufficient_evidence: boolean;
  verification: Verification;
  model: string;
  provider: string;
  usage: Usage;
  timings_ms: Record<string, number>;
  retrieval: Record<string, unknown>;
  context: Record<string, unknown>;
  semantic_cache_hit: boolean;
  retrieval_query: string;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface StoredMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  metadata: {
    model?: string;
    provider?: string;
    usage?: Usage;
    timings_ms?: Record<string, number>;
    verification?: Verification;
    insufficient_evidence?: boolean;
    semantic_cache_hit?: boolean;
  };
  created_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  messages: StoredMessage[];
}

export interface RAGSettings {
  top_k: number;
  search_mode: SearchMode;
  rerank: boolean;
  candidate_multiplier: number;
  similarity_threshold: number;
  rerank_min_score: number;
  query_expansion: string;
  llm_model: string;
  temperature: number;
  max_output_tokens: number;
  context_max_tokens: number;
  chunk_strategy: string;
  chunk_size_tokens: number;
  chunk_overlap_tokens: number;
  semantic_cache: boolean;
}

export interface ModelInfo {
  embedding_model: string;
  embedding_dimension: number;
  embedding_max_seq_length: number;
  reranker_model: string | null;
  llm_allowed_models: string[];
  llm_default_model: string;
  llm_configured_providers: Record<string, boolean>;
}

export interface CacheStat {
  hit: number;
  miss: number;
  hit_rate: number;
}

export interface ActivityEvent {
  event_type: string;
  query: string | null;
  latency_ms: number | null;
  success: boolean;
  created_at: string;
}

export interface AnalyticsOverview {
  documents: Record<string, number>;
  total_documents: number;
  total_chunks: number;
  total_conversations: number;
  total_queries: number;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  prompt_tokens: number;
  completion_tokens: number;
  cost_usd: number;
  query_cache_hit_rate: number;
  cache?: Record<string, CacheStat>;
  recent_activity: ActivityEvent[];
}

export interface UsagePoint {
  day: string;
  event_type: string;
  count: number;
  avg_latency_ms: number | null;
  avg_retrieval_ms: number | null;
  avg_llm_ms: number | null;
  tokens: number;
}

export interface UsageResponse {
  days: number;
  series: UsagePoint[];
}

export interface EvaluationRunSummary {
  id: string;
  name: string;
  status: string;
  metrics: Record<string, unknown>;
  created_at: string;
  completed_at: string | null;
}

export interface ReadinessResponse {
  status: string;
  checks: Record<string, { ok: boolean; [k: string]: unknown }>;
}
