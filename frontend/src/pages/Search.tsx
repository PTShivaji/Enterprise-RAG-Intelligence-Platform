import { Fragment, useState, type FormEvent, type ReactNode } from "react";
import { Clock, FileSearch, Search as SearchIcon, Zap } from "lucide-react";
import { FileIcon } from "../components/documents/DocumentBits";
import { Badge, Button, Card, EmptyState, ErrorBanner, PageIntro, Skeleton } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { errorMessage } from "../services/api";
import { platformService } from "../services/platform.service";
import type { SearchMode, SearchResponse, SearchResultItem } from "../types/api";
import { cx, formatMs, formatScore, pageLabel, timeAgo } from "../utils/format";

const STOP = new Set(["the", "and", "for", "are", "with", "what", "when", "how", "does", "that", "this", "from", "into", "which", "who", "why", "is", "of", "to", "in", "on", "a", "an", "be", "do"]);

function highlight(text: string, query: string): ReactNode {
  const terms = [...new Set(query.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [])].filter((t) => t.length > 2 && !STOP.has(t));
  if (!terms.length) return text;
  // Whole words that start with a query term ("password" -> "Passwords"), matched case-insensitively.
  const alt = terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  const re = new RegExp(`((?<![\\p{L}\\p{N}])(?:${alt})[\\p{L}\\p{N}]*)`, "giu");
  return text.split(re).map((part, i) =>
    i % 2 === 1 ? <mark key={i} className="rounded-sm bg-accent/25 text-violet-100">{part}</mark> : <Fragment key={i}>{part}</Fragment>,
  );
}

function Score({ label, value, title }: { label: string; value: string; title: string }) {
  return (
    <div title={title} className="rounded-md border border-line bg-surface-2/60 px-2 py-1">
      <div className="text-[9.5px] uppercase tracking-wider text-subtle">{label}</div>
      <div className="font-mono text-xs tabular-nums text-fg">{value}</div>
    </div>
  );
}

function ResultCard({ r, query, rank }: { r: SearchResultItem; query: string; rank: number }) {
  const page = pageLabel(r.page_number, r.page_end);
  return (
    <li className="card p-4 animate-fade-in">
      <div className="flex items-start gap-3">
        <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-surface-3 font-mono text-[11px] text-muted">{rank}</div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="truncate text-sm font-medium text-fg">{r.filename}</span>
            {r.section && <span className="truncate text-xs text-muted">§ {r.section}</span>}
            {page && <span className="text-xs text-subtle">{page}</span>}
            <span className="text-xs text-subtle">· chunk {r.chunk_index}</span>
          </div>
          <p className="mt-2 whitespace-pre-wrap text-[13px] leading-6 text-muted">{highlight(r.content, query)}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {r.rerank_score !== null && <Score label="rerank" value={formatScore(r.rerank_score, 2)} title="Cross-encoder relevance logit (final ordering)" />}
            {r.fused_score !== null && <Score label="rrf" value={formatScore(r.fused_score, 4)} title="Reciprocal Rank Fusion score (k=60)" />}
            {r.vector_score !== null && <Score label={`cosine${r.vector_rank ? ` #${r.vector_rank}` : ""}`} value={formatScore(r.vector_score)} title="Embedding cosine similarity and rank in the vector list" />}
            {r.keyword_score !== null && <Score label={`bm/fts${r.keyword_rank ? ` #${r.keyword_rank}` : ""}`} value={formatScore(r.keyword_score, 4)} title="PostgreSQL full-text ts_rank and rank in the keyword list" />}
          </div>
        </div>
        <FileIcon type={r.file_type} className="hidden sm:flex" />
      </div>
    </li>
  );
}

export default function SearchPage() {
  const [query, setQuery] = useState("");
  const [mode, setMode] = useState<SearchMode>("hybrid");
  const [rerank, setRerank] = useState(true);
  const [topK, setTopK] = useState(5);
  const [result, setResult] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const history = useApi(() => platformService.searchHistory(8), []);

  const run = async (q: string) => {
    const text = q.trim();
    if (!text) return;
    setQuery(text);
    setLoading(true);
    setError(null);
    try {
      setResult(await platformService.search({ query: text, search_mode: mode, rerank, top_k: topK }));
      void history.reload();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void run(query);
  };

  return (
    <>
      <PageIntro title="Search" description="Query the retrieval layer directly — the same hybrid search, fusion and reranking that grounds AI Chat answers, with every score exposed." />

      <form onSubmit={onSubmit} className="card p-3">
        <div className="flex flex-col gap-2 sm:flex-row">
          <div className="relative flex-1">
            <SearchIcon className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-subtle" aria-hidden />
            <label htmlFor="search-q" className="sr-only">Search query</label>
            <input id="search-q" value={query} onChange={(e) => setQuery(e.target.value)} maxLength={1000} placeholder="Search across your documents…" className="input h-10 pl-9" />
          </div>
          <Button type="submit" icon={SearchIcon} loading={loading} disabled={!query.trim()} className="h-10">Search</Button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 px-1 text-xs text-muted">
          <div role="radiogroup" aria-label="Search mode" className="inline-flex rounded-lg border border-line bg-surface-2 p-0.5">
            {(["hybrid", "vector", "keyword"] as SearchMode[]).map((m) => (
              <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => setMode(m)} className={cx("rounded-md px-2.5 py-1 capitalize transition-colors", mode === m ? "bg-surface-3 text-fg shadow-sm" : "hover:text-fg")}>
                {m}
              </button>
            ))}
          </div>
          <label className="inline-flex cursor-pointer items-center gap-2">
            <input type="checkbox" checked={rerank} onChange={(e) => setRerank(e.target.checked)} className="size-3.5 accent-accent" />
            Cross-encoder rerank
          </label>
          <label className="inline-flex items-center gap-2">
            Top-k
            <select value={topK} onChange={(e) => setTopK(Number(e.target.value))} className="rounded-md border border-line bg-surface-2 px-1.5 py-0.5 text-fg">
              {[3, 5, 10, 20].map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
          </label>
        </div>
      </form>

      <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_260px]">
        <div>
          {error && <ErrorBanner message={error} className="mb-4" />}
          {loading && !result ? (
            <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-32 rounded-xl" />)}</div>
          ) : result ? (
            <>
              <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted">
                <span data-testid="result-count" className="text-fg">{result.results.length} result{result.results.length === 1 ? "" : "s"}</span>
                <Badge tone="accent">{result.search_mode}</Badge>
                {result.reranked && <Badge tone="info">reranked</Badge>}
                {result.cache_hit && <Badge tone="info" icon={Zap}>cache hit</Badge>}
                {result.candidates_considered > 0 && <span>· {result.candidates_considered} candidates</span>}
                {result.timings_ms.total !== undefined && <span className="inline-flex items-center gap-1">· <Clock className="size-3" aria-hidden />{formatMs(result.timings_ms.total)}</span>}
              </div>
              {Object.keys(result.timings_ms).length > 1 && (
                <div className="mb-4 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-subtle">
                  {Object.entries(result.timings_ms).filter(([k]) => k !== "total").map(([k, v]) => <span key={k}>{k.replace(/_/g, " ")} {formatMs(v)}</span>)}
                </div>
              )}
              {result.results.length === 0 ? (
                <Card><EmptyState icon={FileSearch} title="No matching passages" description="Nothing passed the similarity threshold. Try different wording or keyword mode." /></Card>
              ) : (
                <ol className={cx("space-y-3", loading && "opacity-60")}>{result.results.map((r, i) => <ResultCard key={r.chunk_id} r={r} query={result.query} rank={i + 1} />)}</ol>
              )}
            </>
          ) : (
            <Card><EmptyState icon={FileSearch} title="Search your knowledge base" description="Results show which chunks are retrieved, from which document and section, and why they ranked where they did." /></Card>
          )}
        </div>

        <Card title="Recent searches" bodyClassName="px-2 py-2">
          {history.error ? (
            <p className="px-3 py-2 text-xs text-muted">History unavailable.</p>
          ) : !history.data ? (
            <div className="space-y-2 p-2">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-8" />)}</div>
          ) : history.data.length === 0 ? (
            <p className="px-3 py-2 text-xs text-subtle">No searches yet.</p>
          ) : (
            <ul>
              {history.data.filter((h) => h.query).map((h) => (
                <li key={h.id}>
                  <button onClick={() => void run(h.query ?? "")} className="w-full rounded-lg px-3 py-2 text-left hover:bg-surface-2">
                    <div className="truncate text-[13px] text-muted">{h.query}</div>
                    <div className="text-[11px] text-subtle">{h.results ?? 0} result{h.results === 1 ? "" : "s"} · {formatMs(h.latency_ms)} · {timeAgo(h.created_at)}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
