import { useEffect, useRef, type KeyboardEvent } from "react";
import { ArrowUp, Square } from "lucide-react";
import type { ModelInfo } from "../../types/api";
import { providerOf } from "../../services/platform.service";
import { cx } from "../../utils/format";

export function Composer({ value, onChange, onSubmit, onStop, busy, models, model, onModelChange, defaultModel }: {
  value: string;
  onChange: (v: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  busy: boolean;
  models: ModelInfo | null;
  model: string;
  onModelChange: (m: string) => void;
  defaultModel: string | null;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [value]);

  useEffect(() => {
    if (!busy) ref.current?.focus();
  }, [busy]);

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      if (!busy && value.trim()) onSubmit();
    }
  };

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!busy && value.trim()) onSubmit();
      }}
      className="rounded-2xl border border-line-strong bg-surface shadow-card transition-colors focus-within:border-accent/50"
    >
      <label htmlFor="chat-input" className="sr-only">Ask a question about your documents</label>
      <textarea
        id="chat-input"
        ref={ref}
        rows={1}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="Ask anything about your documents…"
        maxLength={4000}
        className="block max-h-[200px] w-full resize-none bg-transparent px-4 pt-3.5 pb-2 text-[14.5px] leading-6 text-fg placeholder:text-subtle focus:outline-none"
      />
      <div className="flex items-center justify-between gap-2 px-3 pb-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <label htmlFor="model-select" className="sr-only">Model</label>
          <select
            id="model-select"
            value={model}
            onChange={(e) => onModelChange(e.target.value)}
            disabled={busy || !models}
            className="max-w-[200px] truncate rounded-md border border-line bg-surface-2 px-2 py-1 text-xs text-muted focus:border-accent/50 focus:outline-none sm:max-w-none"
          >
            <option value="">Default{defaultModel ? ` · ${defaultModel}` : ""}</option>
            {models?.llm_allowed_models.map((m) => {
              const configured = models.llm_configured_providers[providerOf(m)] ?? false;
              return (
                <option key={m} value={m} disabled={!configured}>
                  {m === "local" ? "local (extractive, no LLM)" : m}
                  {configured ? "" : " — not configured"}
                </option>
              );
            })}
          </select>
          <span className="hidden text-[11px] text-subtle sm:inline">
            <kbd className="kbd">Enter</kbd> send · <kbd className="kbd">Shift</kbd>+<kbd className="kbd">Enter</kbd> new line
          </span>
        </div>
        {busy ? (
          <button type="button" onClick={onStop} aria-label="Stop generating" className="flex size-8 items-center justify-center rounded-lg border border-line-strong bg-surface-2 text-fg hover:bg-surface-3">
            <Square className="size-3.5 fill-current" aria-hidden />
          </button>
        ) : (
          <button
            type="submit"
            disabled={!value.trim()}
            aria-label="Send message"
            className={cx(
              "flex size-8 items-center justify-center rounded-lg transition-colors",
              value.trim() ? "bg-accent text-white hover:bg-accent-strong" : "bg-surface-3 text-subtle",
            )}
          >
            <ArrowUp className="size-4" aria-hidden />
          </button>
        )}
      </div>
    </form>
  );
}
