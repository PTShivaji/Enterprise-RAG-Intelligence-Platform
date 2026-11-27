import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { BookOpen, Hash, Layers, Upload } from "lucide-react";
import { FileIcon } from "../components/documents/DocumentBits";
import { Badge, Button, Card, EmptyState, ErrorBanner, PageIntro, Skeleton } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { errorMessage } from "../services/api";
import { documentService } from "../services/document.service";
import type { Chunk, DocumentItem } from "../types/api";
import { cx, formatMs, formatNumber, pageLabel } from "../utils/format";

const PAGE = 25;

function DocumentDetail({ doc }: { doc: DocumentItem }) {
  const [chunks, setChunks] = useState<Chunk[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async (offset: number) => {
    setLoading(true);
    setError(null);
    try {
      const page = await documentService.chunks(doc.id, PAGE, offset);
      setChunks((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
      setTotal(page.total);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setChunks([]);
    setTotal(null);
    void load(0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc.id]);

  const sections = doc.metadata.section_titles ?? [];
  const facts: Array<[string, string]> = [
    ["Chunks", formatNumber(doc.chunk_count)],
    ["Tokens", formatNumber(doc.token_count)],
    ["Strategy", doc.chunking_config.strategy ?? "—"],
    ["Chunk size", doc.chunking_config.chunk_size ? `${doc.chunking_config.chunk_size} tok / ${doc.chunking_config.overlap ?? 0} overlap` : "—"],
    ["Pages", doc.page_count ? String(doc.page_count) : "—"],
    ["Ingestion", formatMs(doc.ingestion_ms)],
  ];

  return (
    <div className="space-y-4">
      <Card>
        <div className="flex items-start gap-3">
          <FileIcon type={doc.file_type} />
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold">{doc.title || doc.filename}</h2>
            <p className="truncate text-xs text-muted">{doc.filename} · embedded with {doc.embedding_model ?? "—"}</p>
          </div>
        </div>
        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
          {facts.map(([k, v]) => (
            <div key={k}>
              <dt className="text-[11px] uppercase tracking-wider text-subtle">{k}</dt>
              <dd className="mt-0.5 text-sm tabular-nums text-fg">{v}</dd>
            </div>
          ))}
        </dl>
        {sections.length > 0 && (
          <div className="mt-5">
            <div className="text-[11px] uppercase tracking-wider text-subtle">Detected sections</div>
            <div className="mt-2 flex flex-wrap gap-1.5">{sections.map((s, i) => <Badge key={`${s}-${i}`}>{s}</Badge>)}</div>
          </div>
        )}
      </Card>

      <Card title="Indexed chunks" description={total !== null ? `${formatNumber(total)} chunks — the exact passages retrieval searches and cites` : undefined} bodyClassName="p-0">
        {error && <div className="p-5"><ErrorBanner message={error} onRetry={() => void load(chunks.length)} /></div>}
        {chunks.length === 0 && loading ? (
          <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-20" />)}</div>
        ) : (
          <ol className="divide-y divide-line">
            {chunks.map((c) => (
              <li key={c.id} className="px-5 py-4">
                <div className="mb-2 flex flex-wrap items-center gap-1.5 text-[11px] text-subtle">
                  <Badge icon={Hash}>{c.chunk_index}</Badge>
                  {c.section && <span className="text-muted">§ {c.section}</span>}
                  {pageLabel(c.page_number, c.page_end) && <span>· {pageLabel(c.page_number, c.page_end)}</span>}
                  <span className="ml-auto font-mono tabular-nums">{c.token_count} tok</span>
                </div>
                <p className="whitespace-pre-wrap text-[13px] leading-6 text-muted">{c.content}</p>
              </li>
            ))}
          </ol>
        )}
        {total !== null && chunks.length < total && (
          <div className="border-t border-line p-3 text-center">
            <Button variant="ghost" size="sm" loading={loading} onClick={() => void load(chunks.length)}>
              Load more ({formatNumber(total - chunks.length)} remaining)
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}

export default function KnowledgeBasePage() {
  const docs = useApi(() => documentService.list(200), []);
  const [params, setParams] = useSearchParams();
  const indexed = (docs.data?.items ?? []).filter((d) => d.status === "indexed");
  const selectedId = params.get("doc") ?? indexed[0]?.id ?? null;
  const selected = indexed.find((d) => d.id === selectedId) ?? null;

  return (
    <>
      <PageIntro title="Knowledge Base" description="Inspect exactly what the retriever sees: every indexed document, its detected structure and its chunks." />
      {docs.error && !docs.data ? (
        <ErrorBanner message={docs.error} onRetry={() => void docs.reload()} />
      ) : !docs.data ? (
        <div className="grid gap-4 lg:grid-cols-[280px_1fr]"><Skeleton className="h-64 rounded-xl" /><Skeleton className="h-64 rounded-xl" /></div>
      ) : indexed.length === 0 ? (
        <Card>
          <EmptyState
            icon={BookOpen}
            title="Your knowledge base is empty"
            description="Indexed documents appear here with their sections and chunks."
            action={<Link to="/documents" className="inline-flex h-9 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-medium text-white hover:bg-accent-strong"><Upload className="size-4" aria-hidden /> Upload documents</Link>}
          />
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
          <nav aria-label="Indexed documents" className="card h-fit p-2 lg:sticky lg:top-4">
            <div className="flex items-center gap-2 px-2 py-1.5 text-[11px] font-medium uppercase tracking-wider text-subtle">
              <Layers className="size-3.5" aria-hidden /> {indexed.length} indexed
            </div>
            <ul className="mt-1 max-h-[60vh] space-y-0.5 overflow-y-auto">
              {indexed.map((d) => (
                <li key={d.id}>
                  <button
                    onClick={() => setParams({ doc: d.id })}
                    className={cx("w-full rounded-lg px-2.5 py-2 text-left transition-colors", d.id === selected?.id ? "bg-surface-2 text-fg" : "text-muted hover:bg-surface-2/60 hover:text-fg")}
                  >
                    <div className="truncate text-[13px]">{d.filename}</div>
                    <div className="text-[11px] text-subtle">{formatNumber(d.chunk_count)} chunks · {d.file_type.toUpperCase()}</div>
                  </button>
                </li>
              ))}
            </ul>
          </nav>
          {selected ? <DocumentDetail doc={selected} /> : <Card><EmptyState icon={BookOpen} title="Document not found" description="It may have been deleted or is not indexed yet." /></Card>}
        </div>
      )}
    </>
  );
}
