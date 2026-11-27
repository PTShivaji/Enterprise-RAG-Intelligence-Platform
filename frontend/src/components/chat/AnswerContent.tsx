import { Fragment, type ReactNode } from "react";

/**
 * Minimal, safe renderer for LLM answers: paragraphs, bullet / numbered lists, **bold**, `code`
 * and citation markers like [1] or [1, 2] rendered as interactive chips. No HTML is injected.
 */

const INLINE = /(\[\d+(?:\s*,\s*\d+)*\]|\*\*[^*]+\*\*|`[^`]+`)/g;

function renderInline(text: string, valid: Set<number>, onCite: (n: number) => void, keyPrefix: string): ReactNode[] {
  return text.split(INLINE).map((part, i) => {
    const key = `${keyPrefix}-${i}`;
    if (/^\[\d+(?:\s*,\s*\d+)*\]$/.test(part)) {
      const nums = part.slice(1, -1).split(",").map((n) => Number(n.trim()));
      return (
        <Fragment key={key}>
          {nums.map((n) =>
            valid.has(n) ? (
              <button
                key={n}
                type="button"
                onClick={() => onCite(n)}
                aria-label={`Show source ${n}`}
                className="mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded border border-accent/30 bg-accent-soft px-1 align-middle font-mono text-[10px] font-semibold text-violet-200 transition-colors hover:border-accent hover:bg-accent/30"
              >
                {n}
              </button>
            ) : (
              <span key={n} className="font-mono text-[11px] text-subtle">[{n}]</span>
            ),
          )}
        </Fragment>
      );
    }
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={key} className="font-semibold text-fg">{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={key} className="rounded bg-surface-3 px-1 py-0.5 font-mono text-[0.85em]">{part.slice(1, -1)}</code>;
    return <Fragment key={key}>{part}</Fragment>;
  });
}

type Block = { kind: "p"; lines: string[] } | { kind: "ul" | "ol"; items: string[] } | { kind: "h"; text: string };

function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
    const numbered = /^\s*\d+[.)]\s+(.*)$/.exec(line);
    const heading = /^#{1,4}\s+(.*)$/.exec(line);
    const last = blocks[blocks.length - 1];
    if (!line.trim()) {
      blocks.push({ kind: "p", lines: [] });
    } else if (heading) {
      blocks.push({ kind: "h", text: heading[1] });
    } else if (bullet || numbered) {
      const kind = bullet ? "ul" : "ol";
      const item = (bullet ?? numbered)![1];
      if (last && last.kind === kind) last.items.push(item);
      else blocks.push({ kind, items: [item] });
    } else if (last && last.kind === "p") {
      last.lines.push(line);
    } else {
      blocks.push({ kind: "p", lines: [line] });
    }
  }
  return blocks.filter((b) => (b.kind === "p" ? b.lines.length > 0 : true));
}

export function AnswerContent({ text, citationIndexes, onCite, streaming }: {
  text: string;
  citationIndexes: number[];
  onCite: (n: number) => void;
  streaming?: boolean;
}) {
  const valid = new Set(citationIndexes);
  const blocks = parseBlocks(text);
  return (
    <div className="space-y-3 text-[14.5px] leading-7 text-fg/90">
      {blocks.map((b, i) => {
        const isLast = i === blocks.length - 1;
        const caret = streaming && isLast ? <span className="ml-0.5 inline-block h-4 w-[7px] translate-y-0.5 animate-blink bg-accent/80" /> : null;
        if (b.kind === "h") return <h3 key={i} className="pt-1 text-sm font-semibold text-fg">{renderInline(b.text, valid, onCite, `h${i}`)}</h3>;
        if (b.kind === "p") return <p key={i}>{renderInline(b.lines.join(" "), valid, onCite, `p${i}`)}{caret}</p>;
        const List = b.kind === "ul" ? "ul" : "ol";
        return (
          <List key={i} className={b.kind === "ul" ? "list-disc space-y-1 pl-5 marker:text-subtle" : "list-decimal space-y-1 pl-5 marker:text-subtle"}>
            {b.items.map((item, j) => (
              <li key={j} className="pl-1">
                {renderInline(item, valid, onCite, `l${i}-${j}`)}
                {isLast && j === b.items.length - 1 && caret}
              </li>
            ))}
          </List>
        );
      })}
      {streaming && blocks.length === 0 && <span className="inline-block h-4 w-[7px] animate-blink bg-accent/80" />}
    </div>
  );
}
