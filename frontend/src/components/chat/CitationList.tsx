import { useEffect, useRef } from "react";
import { FileText } from "lucide-react";
import type { Citation } from "../../types/api";
import { cx, formatPercent, formatScore, pageLabel } from "../../utils/format";

function CitationCard({ citation, active }: { citation: Citation; active: boolean }) {
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [active]);
  const page = pageLabel(citation.page_number, citation.page_end);

  return (
    <li
      ref={ref}
      id={`cite-${citation.chunk_id}`}
      className={cx(
        "rounded-lg border bg-surface-2/50 p-3 transition-colors",
        active ? "border-accent/60 bg-accent-soft/40" : "border-line",
      )}
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded bg-accent-soft font-mono text-[10px] font-semibold text-violet-200">
          {citation.index}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs">
            <span className="inline-flex min-w-0 items-center gap-1 font-medium text-fg">
              <FileText className="size-3.5 shrink-0 text-subtle" aria-hidden />
              <span className="truncate">{citation.filename}</span>
            </span>
            {citation.section && <span className="truncate text-muted">§ {citation.section}</span>}
            {page && <span className="text-muted">{page}</span>}
          </div>
          <blockquote className="mt-2 border-l-2 border-line-strong pl-3 text-[13px] leading-6 text-muted">
            {citation.text}
          </blockquote>
          <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[10.5px] text-subtle">
            <div title="How well the cited passage supports the sentence(s) citing it (citation verifier)">
              <dt className="inline">support </dt>
              <dd className="inline text-muted">{formatPercent(citation.support_score)}</dd>
            </div>
            {citation.rerank_score !== null && (
              <div title="Cross-encoder relevance logit">
                <dt className="inline">rerank </dt>
                <dd className="inline text-muted">{formatScore(citation.rerank_score, 2)}</dd>
              </div>
            )}
            {citation.vector_score !== null && (
              <div title="Cosine similarity between query and chunk embeddings">
                <dt className="inline">cosine </dt>
                <dd className="inline text-muted">{formatScore(citation.vector_score)}</dd>
              </div>
            )}
            <div title="Chunk id">
              <dt className="inline">chunk </dt>
              <dd className="inline text-muted">{citation.chunk_id.slice(0, 8)}</dd>
            </div>
          </dl>
        </div>
      </div>
    </li>
  );
}

export function CitationList({ citations, activeIndex }: { citations: Citation[]; activeIndex: number | null }) {
  return (
    <ol className="space-y-2" aria-label="Citations">
      {citations.map((c) => (
        <CitationCard key={`${c.index}-${c.chunk_id}`} citation={c} active={activeIndex === c.index} />
      ))}
    </ol>
  );
}
