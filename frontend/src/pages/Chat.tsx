import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { FileStack, History, MessageSquarePlus, MessageSquareText, Sparkles, Trash2, Upload, X } from "lucide-react";
import { Composer } from "../components/chat/Composer";
import { AssistantBubble, UserBubble } from "../components/chat/MessageBubble";
import { fromResponse, fromStored, type ChatMessage } from "../components/chat/types";
import { Button, ConfirmDialog, ErrorBanner, IconButton, Skeleton } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { errorMessage } from "../services/api";
import { chatService } from "../services/chat.service";
import { platformService } from "../services/platform.service";
import type { ConversationSummary } from "../types/api";
import { cx, timeAgo } from "../utils/format";

const EXAMPLES = [
  "Summarize the uploaded documents.",
  "Explain the key technical requirements.",
  "Find important information in my documents.",
  "Compare information across multiple documents.",
];

let tempId = 0;
const nextId = () => `tmp-${++tempId}`;

function ConversationList({ items, loading, activeId, onSelect, onNew }: {
  items: ConversationSummary[] | null;
  loading: boolean;
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <div className="flex h-full flex-col">
      <div className="p-3">
        <Button variant="secondary" icon={MessageSquarePlus} className="w-full" onClick={onNew}>
          New conversation
        </Button>
      </div>
      <div className="px-4 pb-2 text-[10px] font-semibold uppercase tracking-wider text-subtle">History</div>
      <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {loading && !items && [0, 1, 2, 3].map((i) => <Skeleton key={i} className="mx-2 my-2 h-8" />)}
        {items?.length === 0 && <p className="px-3 py-2 text-xs text-subtle">No conversations yet.</p>}
        {items?.map((c) => (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={cx(
              "block w-full rounded-lg px-3 py-2 text-left transition-colors",
              c.id === activeId ? "bg-surface-2 text-fg" : "text-muted hover:bg-surface-2/60 hover:text-fg",
            )}
          >
            <div className="truncate text-[13px]">{c.title || "Untitled"}</div>
            <div className="text-[11px] text-subtle">{timeAgo(c.updated_at)}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

function Welcome({ onPick, docCount }: { onPick: (q: string) => void; docCount: number | null }) {
  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center px-4 pt-[8vh] text-center sm:pt-[12vh]">
      <div className="flex size-11 items-center justify-center rounded-xl border border-line-strong bg-surface-2 text-accent">
        <Sparkles className="size-5" aria-hidden />
      </div>
      <h1 className="mt-5 text-2xl font-semibold tracking-tight text-fg sm:text-[28px]">
        Your knowledge. One intelligent interface.
      </h1>
      <p className="mt-2 max-w-md text-sm text-muted">
        Ask questions across your documents and get evidence-backed answers with verifiable citations.
      </p>

      {docCount === 0 && (
        <div className="mt-6 flex w-full items-center gap-3 rounded-xl border border-info/25 bg-info-soft px-4 py-3 text-left text-sm">
          <FileStack className="size-4 shrink-0 text-info" aria-hidden />
          <span className="flex-1 text-blue-100/80">Your knowledge base is empty. Upload a document so answers have evidence to cite.</span>
          <Link to="/documents" className="inline-flex items-center gap-1.5 text-xs font-medium text-blue-200 hover:underline">
            <Upload className="size-3.5" aria-hidden /> Upload
          </Link>
        </div>
      )}

      <div className="mt-8 grid w-full gap-2 sm:grid-cols-2">
        {EXAMPLES.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            className="group rounded-xl border border-line bg-surface px-4 py-3 text-left text-sm text-muted transition-colors hover:border-line-strong hover:bg-surface-2 hover:text-fg"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function ChatPage() {
  const [params, setParams] = useSearchParams();
  const conversationId = params.get("c");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadingConversation, setLoadingConversation] = useState(false);
  const [loadKey, setLoadKey] = useState(0);
  const [model, setModel] = useState("");
  const [historyOpen, setHistoryOpen] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [clearError, setClearError] = useState<string | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  /** Conversation id created by the current stream: its URL update must not trigger a reload. */
  const createdHereRef = useRef<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);

  const conversations = useApi(() => chatService.conversations(50), []);
  const models = useApi(() => platformService.models(), []);
  const settings = useApi(() => platformService.settings(), []);
  const overview = useApi(() => platformService.overview(), []);

  // Load a conversation when the URL points to one we did not just create.
  useEffect(() => {
    if (!conversationId) {
      setMessages([]);
      return;
    }
    if (createdHereRef.current === conversationId) return;
    let cancelled = false;
    setLoadingConversation(true);
    setLoadError(null);
    chatService
      .conversation(conversationId)
      .then((c) => !cancelled && setMessages(c.messages.map(fromStored)))
      .catch((err) => !cancelled && setLoadError(errorMessage(err)))
      .finally(() => !cancelled && setLoadingConversation(false));
    return () => {
      cancelled = true;
    };
  }, [conversationId, loadKey]);

  // Auto-scroll while the user is at the bottom.
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickRef.current) el.scrollTop = el.scrollHeight;
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const patchLast = useCallback((patch: Partial<ChatMessage> | ((m: ChatMessage) => Partial<ChatMessage>)) => {
    setMessages((prev) => {
      const next = prev.slice();
      const last = next[next.length - 1];
      if (!last || last.role !== "assistant") return prev;
      next[next.length - 1] = { ...last, ...(typeof patch === "function" ? patch(last) : patch) };
      return next;
    });
  }, []);

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    setInput("");
    setBusy(true);
    stickRef.current = true;
    setMessages((prev) => [
      ...prev,
      { id: nextId(), role: "user", content: question, status: "done", citations: [] },
      { id: nextId(), role: "assistant", content: "", status: "streaming", citations: [] },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;
    await chatService.stream(
      { message: question, conversation_id: conversationId, model: model || null },
      {
        onConversation: (id) => {
          if (id !== conversationId) {
            createdHereRef.current = id;
            setParams({ c: id }, { replace: true });
          }
        },
        onSources: (sources) => patchLast({ pendingSources: sources }),
        onToken: (t) => patchLast((m) => ({ content: m.content + t })),
        onDone: (r) => patchLast(fromResponse(r)),
        onError: (message) => patchLast({ status: "error", error: message }),
      },
      controller.signal,
    );
    if (controller.signal.aborted) patchLast((m) => (m.status === "streaming" ? { status: "error", error: "Generation stopped." } : {}));
    abortRef.current = null;
    setBusy(false);
    void conversations.reload();
  };

  const newConversation = () => {
    abortRef.current?.abort();
    createdHereRef.current = null;
    setParams({}, { replace: false });
    setMessages([]);
    setLoadError(null);
    setHistoryOpen(false);
  };

  const selectConversation = (id: string) => {
    if (busy) abortRef.current?.abort();
    createdHereRef.current = null;
    setParams({ c: id });
    setHistoryOpen(false);
  };

  const clearConversation = async () => {
    if (!conversationId) return;
    setClearing(true);
    setClearError(null);
    try {
      await chatService.deleteConversation(conversationId);
      setConfirmClear(false);
      newConversation();
      void conversations.reload();
    } catch (err) {
      setClearError(errorMessage(err));
    } finally {
      setClearing(false);
    }
  };

  const list = (
    <ConversationList
      items={conversations.data}
      loading={conversations.loading}
      activeId={conversationId}
      onSelect={selectConversation}
      onNew={newConversation}
    />
  );

  return (
    <div className="flex h-full">
      <aside className="hidden w-64 shrink-0 border-r border-line bg-surface/30 lg:block">{list}</aside>

      {historyOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Conversation history">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setHistoryOpen(false)} />
          <aside className="absolute inset-y-0 right-0 w-72 animate-fade-in border-l border-line bg-surface shadow-pop">
            <div className="flex justify-end p-2">
              <IconButton icon={X} label="Close history" onClick={() => setHistoryOpen(false)} />
            </div>
            <div className="h-[calc(100%-48px)]">{list}</div>
          </aside>
        </div>
      )}

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-11 shrink-0 items-center justify-between gap-2 border-b border-line px-4">
          <div className="flex min-w-0 items-center gap-2 text-xs text-muted">
            <MessageSquareText className="size-3.5 shrink-0 text-subtle" aria-hidden />
            <span className="truncate">
              {conversationId
                ? conversations.data?.find((c) => c.id === conversationId)?.title ?? "Conversation"
                : "New conversation"}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <IconButton icon={History} label="Conversation history" className="lg:hidden" onClick={() => setHistoryOpen(true)} />
            <IconButton icon={MessageSquarePlus} label="New conversation" onClick={newConversation} />
            <IconButton icon={Trash2} label="Delete conversation" disabled={!conversationId || busy} onClick={() => setConfirmClear(true)} />
          </div>
        </div>

        <div
          ref={scrollRef}
          onScroll={(e) => {
            const el = e.currentTarget;
            stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
          className="min-h-0 flex-1 overflow-y-auto"
        >
          {loadError ? (
            <div className="mx-auto max-w-3xl p-6">
              <ErrorBanner message={loadError} onRetry={() => setLoadKey((k) => k + 1)} />
            </div>
          ) : loadingConversation ? (
            <div className="mx-auto max-w-3xl space-y-6 p-6">
              <Skeleton className="ml-auto h-10 w-2/5" />
              <Skeleton className="h-24 w-4/5" />
            </div>
          ) : messages.length === 0 ? (
            <Welcome onPick={(q) => void send(q)} docCount={overview.data?.total_documents ?? null} />
          ) : (
            <div className="mx-auto max-w-3xl space-y-7 px-4 py-6 sm:px-6">
              {messages.map((m) =>
                m.role === "user" ? <UserBubble key={m.id} message={m} /> : <AssistantBubble key={m.id} message={m} />,
              )}
            </div>
          )}
        </div>

        <div className="shrink-0 px-4 pb-4 pt-2 sm:px-6">
          <div className="mx-auto max-w-3xl">
            <Composer
              value={input}
              onChange={setInput}
              onSubmit={() => void send(input)}
              onStop={() => abortRef.current?.abort()}
              busy={busy}
              models={models.data}
              model={model}
              onModelChange={setModel}
              defaultModel={settings.data?.llm_model ?? null}
            />
            <p className="mt-2 text-center text-[11px] text-subtle">
              Answers are generated only from your documents and checked by a citation verifier. Verify important facts against the sources.
            </p>
          </div>
        </div>
      </section>

      <ConfirmDialog
        open={confirmClear}
        title="Delete this conversation?"
        description={
          <>
            The conversation and its messages are permanently removed. Your documents are not affected.
            {clearError && <ErrorBanner className="mt-3" message={clearError} />}
          </>
        }
        confirmLabel="Delete"
        destructive
        busy={clearing}
        onConfirm={() => void clearConversation()}
        onClose={() => setConfirmClear(false)}
      />
    </div>
  );
}
