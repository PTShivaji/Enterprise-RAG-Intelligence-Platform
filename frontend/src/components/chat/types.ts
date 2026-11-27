import type { ChatResponse, Citation, StoredMessage, Usage, Verification } from "../../types/api";
import type { StreamSource } from "../../services/chat.service";

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  status: "streaming" | "done" | "error";
  error?: string;
  /** Sources retrieved before generation (streaming only, shown while the answer is produced). */
  pendingSources?: StreamSource[];
  citations: Citation[];
  verification?: Verification;
  insufficientEvidence?: boolean;
  model?: string;
  usage?: Usage;
  timings?: Record<string, number>;
  cacheHit?: boolean;
}

export function fromResponse(r: ChatResponse): Partial<ChatMessage> {
  return {
    id: r.message_id,
    content: r.answer,
    status: "done",
    citations: r.citations,
    verification: r.verification,
    insufficientEvidence: r.insufficient_evidence,
    model: r.model,
    usage: r.usage,
    timings: r.timings_ms,
    cacheHit: r.semantic_cache_hit,
    pendingSources: undefined,
  };
}

export function fromStored(m: StoredMessage): ChatMessage {
  return {
    id: m.id,
    role: m.role,
    content: m.content,
    status: "done",
    citations: m.citations ?? [],
    verification: m.metadata?.verification,
    insufficientEvidence: m.metadata?.insufficient_evidence,
    model: m.metadata?.model,
    usage: m.metadata?.usage,
    timings: m.metadata?.timings_ms,
    cacheHit: m.metadata?.semantic_cache_hit,
  };
}
