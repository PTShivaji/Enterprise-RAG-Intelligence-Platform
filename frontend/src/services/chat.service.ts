import { api, API_PREFIX, tokenStore, UNAUTHORIZED_EVENT } from "./api";
import type { ChatRequest, ChatResponse, ConversationDetail, ConversationSummary } from "../types/api";

export interface StreamSource {
  index: number;
  filename: string;
  section: string | null;
  page_number: number | null;
}

export interface StreamHandlers {
  onConversation?: (conversationId: string) => void;
  onSources?: (sources: StreamSource[]) => void;
  onToken?: (text: string) => void;
  onDone: (response: ChatResponse) => void;
  onError: (message: string) => void;
}

/**
 * POST /chat/stream returns Server-Sent Events:
 *   conversation -> sources -> token* -> done | error
 * EventSource cannot send a POST body or Authorization header, so the stream is read with fetch.
 */
async function stream(body: ChatRequest, handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        Authorization: `Bearer ${tokenStore.get() ?? ""}`,
      },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    handlers.onError("Cannot reach the backend. Is it running?");
    return;
  }

  if (!response.ok || !response.body) {
    if (response.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    let message = `Request failed (HTTP ${response.status})`;
    try {
      const data = (await response.json()) as { message?: string };
      if (data.message) message = data.message;
    } catch {
      /* non-JSON error body */
    }
    handlers.onError(message);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finished = false;

  const dispatch = (raw: string) => {
    let event = "message";
    const dataLines: string[] = [];
    for (const line of raw.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
    }
    if (!dataLines.length) return;
    const data: unknown = JSON.parse(dataLines.join("\n"));
    switch (event) {
      case "conversation":
        handlers.onConversation?.((data as { conversation_id: string }).conversation_id);
        break;
      case "sources":
        handlers.onSources?.((data as { sources: StreamSource[] }).sources);
        break;
      case "token":
        handlers.onToken?.((data as { text: string }).text);
        break;
      case "done":
        finished = true;
        handlers.onDone(data as ChatResponse);
        break;
      case "error":
        finished = true;
        handlers.onError((data as { message?: string }).message ?? "Generation failed");
        break;
    }
  };

  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        dispatch(buffer.slice(0, sep));
        buffer = buffer.slice(sep + 2);
      }
    }
    if (buffer.trim()) dispatch(buffer);
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    handlers.onError("The response stream was interrupted.");
    return;
  }
  if (!finished) handlers.onError("The stream ended before the answer was complete.");
}

export const chatService = {
  stream,

  async ask(body: ChatRequest): Promise<ChatResponse> {
    const { data } = await api.post<ChatResponse>("/chat", body);
    return data;
  },

  async conversations(limit = 50): Promise<ConversationSummary[]> {
    const { data } = await api.get<ConversationSummary[]>("/conversations", { params: { limit } });
    return data;
  },

  async conversation(id: string): Promise<ConversationDetail> {
    const { data } = await api.get<ConversationDetail>(`/conversations/${id}`);
    return data;
  },

  async deleteConversation(id: string): Promise<void> {
    await api.delete(`/conversations/${id}`);
  },
};
