import { useState } from "react";
import { AlertCircle, BookMarked, ChevronDown, Clock, Copy, Check, Cpu, Database, Loader2, Zap } from "lucide-react";
import { AnswerContent } from "./AnswerContent";
import { CitationList } from "./CitationList";
import { GroundingBadge, InsufficientEvidenceNotice } from "./Grounding";
import type { ChatMessage } from "./types";
import { Badge } from "../ui";
import { BrandMark } from "../layout/Brand";
import { cx, formatMs, formatNumber } from "../../utils/format";

export function UserBubble({ message }: { message: ChatMessage }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md border border-line-strong bg-surface-2 px-4 py-2.5 text-[14.5px] leading-6 text-fg sm:max-w-[75%]">
        {message.content}
      </div>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        });
      }}
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] text-subtle transition-colors hover:bg-surface-2 hover:text-muted"
      aria-label="Copy answer"
    >
      {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function AssistantBubble({ message }: { message: ChatMessage }) {
  const [showSources, setShowSources] = useState(false);
  const [active, setActive] = useState<number | null>(null);
  const streaming = message.status === "streaming";
  const citations = message.citations;
  const insufficient = message.insufficientEvidence;

  const onCite = (n: number) => {
    setShowSources(true);
    setActive(n);
  };

  return (
    <div className="flex gap-3">
      <BrandMark className="mt-0.5 size-7 shrink-0" />
      <div className="min-w-0 flex-1">
        {message.status === "error" ? (
          <div role="alert" className="flex items-start gap-2 rounded-lg border border-danger/25 bg-danger-soft px-4 py-3 text-sm text-red-200">
            <AlertCircle className="mt-0.5 size-4 shrink-0 text-danger" aria-hidden />
            <span>{message.error ?? "Something went wrong."}</span>
          </div>
        ) : insufficient && !streaming ? (
          <InsufficientEvidenceNotice reason={message.verification?.reason} />
        ) : (
          <>
            {streaming && !message.content && (
              <div className="flex items-center gap-2 py-1 text-sm text-muted" role="status">
                <Loader2 className="size-4 animate-spin text-accent" aria-hidden />
                {message.pendingSources
                  ? message.pendingSources.length
                    ? `Found ${message.pendingSources.length} relevant passage${message.pendingSources.length === 1 ? "" : "s"} · generating answer`
                    : "No relevant passages found · finishing"
                  : "Searching your documents"}
              </div>
            )}
            {message.content && (
              <AnswerContent
                text={message.content}
                streaming={streaming}
                citationIndexes={streaming ? (message.pendingSources ?? []).map((s) => s.index) : citations.map((c) => c.index)}
                onCite={onCite}
              />
            )}
          </>
        )}

        {message.status === "done" && (
          <div className="mt-3 animate-fade-in">
            <div className="flex flex-wrap items-center gap-1.5">
              <GroundingBadge verification={message.verification} insufficient={insufficient} />
              {!insufficient && (
                <Badge tone={citations.length ? "accent" : "neutral"} icon={BookMarked}>
                  {citations.length} citation{citations.length === 1 ? "" : "s"}
                </Badge>
              )}
              {message.cacheHit && <Badge tone="info" icon={Zap} title="Answered from the semantic answer cache">Cached</Badge>}
              {message.model && <Badge icon={Cpu}>{message.model}</Badge>}
              {message.timings?.total !== undefined && <Badge icon={Clock}>{formatMs(message.timings.total)}</Badge>}
              {message.usage?.total_tokens ? (
                <Badge icon={Database} title={`${formatNumber(message.usage.prompt_tokens)} prompt · ${formatNumber(message.usage.completion_tokens)} completion · ${formatNumber(message.usage.context_tokens)} context`}>
                  {formatNumber(message.usage.total_tokens)} tokens
                </Badge>
              ) : null}
              <div className="ml-auto flex items-center">
                {!insufficient && message.content && <CopyButton text={message.content} />}
              </div>
            </div>

            {citations.length > 0 && (
              <div className="mt-3">
                <button
                  type="button"
                  onClick={() => setShowSources((s) => !s)}
                  aria-expanded={showSources}
                  className="inline-flex items-center gap-1.5 text-xs font-medium text-muted transition-colors hover:text-fg"
                >
                  <ChevronDown className={cx("size-3.5 transition-transform", showSources && "rotate-180")} aria-hidden />
                  {showSources ? "Hide" : "Show"} sources ·{" "}
                  <span className="text-subtle">{[...new Set(citations.map((c) => c.filename))].join(", ")}</span>
                </button>
                {showSources && (
                  <div className="mt-2 animate-fade-in">
                    <CitationList citations={citations} activeIndex={active} />
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
