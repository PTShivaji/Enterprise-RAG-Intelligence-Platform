import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { BookOpen, FileText, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import { FileIcon, StatusBadge } from "../components/documents/DocumentBits";
import { UploadQueue } from "../components/documents/UploadQueue";
import { UploadZone } from "../components/documents/UploadZone";
import { Button, ConfirmDialog, EmptyState, ErrorBanner, IconButton, PageIntro, Skeleton } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { useUploads } from "../hooks/useUploads";
import { errorMessage } from "../services/api";
import { documentService } from "../services/document.service";
import type { DocumentItem } from "../types/api";
import { formatBytes, formatMs, formatNumber, timeAgo } from "../utils/format";

export default function DocumentsPage() {
  const docs = useApi(() => documentService.list(200), []);
  const { jobs, upload, dismiss, clearFinished } = useUploads(() => void docs.reload());
  const [toDelete, setToDelete] = useState<DocumentItem | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const items = docs.data?.items ?? [];
  const inFlight = items.some((d) => d.status === "processing" || d.status === "uploaded");

  // Keep the table fresh while any document is still being ingested.
  const reloadDocs = docs.reload;
  useEffect(() => {
    if (!inFlight) return;
    const t = window.setInterval(() => void reloadDocs(), 3000);
    return () => window.clearInterval(t);
  }, [inFlight, reloadDocs]);

  const confirmDelete = async () => {
    if (!toDelete) return;
    setDeleting(true);
    setActionError(null);
    try {
      await documentService.remove(toDelete.id);
      setToDelete(null);
      await docs.reload();
    } catch (err) {
      setActionError(errorMessage(err));
    } finally {
      setDeleting(false);
    }
  };

  const reingest = async (doc: DocumentItem) => {
    setActionError(null);
    try {
      await documentService.reingest(doc.id);
      await docs.reload();
    } catch (err) {
      setActionError(errorMessage(err));
    }
  };

  return (
    <>
      <PageIntro
        title="Documents"
        description="Upload PDF, DOCX and TXT files. Each file is parsed, split into section-aware chunks, embedded and indexed for hybrid retrieval."
        actions={<Button variant="secondary" icon={RefreshCw} onClick={() => void docs.reload()} loading={docs.loading && !!docs.data}>Refresh</Button>}
      />

      <div className="space-y-4">
        <UploadZone onFiles={upload} />
        <UploadQueue jobs={jobs} onDismiss={dismiss} onClear={clearFinished} />
        {actionError && <ErrorBanner message={actionError} />}

        <div className="card overflow-hidden">
          <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
            <h2 className="text-sm font-semibold">
              Library <span className="ml-1 font-normal text-subtle">{docs.data ? formatNumber(docs.data.total) : ""}</span>
            </h2>
          </div>

          {docs.error && !docs.data ? (
            <div className="p-5"><ErrorBanner message={docs.error} onRetry={() => void docs.reload()} /></div>
          ) : !docs.data ? (
            <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-12" />)}</div>
          ) : items.length === 0 ? (
            <EmptyState icon={FileText} title="No documents yet" description="Upload your first file above. Once indexed it becomes searchable and citable in AI Chat." />
          ) : (
            <>
              <div className="hidden grid-cols-[minmax(0,1fr)_90px_80px_110px_100px_76px] gap-4 border-b border-line px-5 py-2 text-[11px] font-medium uppercase tracking-wider text-subtle md:grid">
                <span>Name</span><span className="text-right">Size</span><span className="text-right">Chunks</span><span>Status</span><span>Uploaded</span><span />
              </div>
              <ul className="divide-y divide-line">
                {items.map((d) => (
                  <li key={d.id} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 px-5 py-3 transition-colors hover:bg-surface-2/40 md:grid-cols-[minmax(0,1fr)_90px_80px_110px_100px_76px]">
                    <div className="flex min-w-0 items-center gap-3">
                      <FileIcon type={d.file_type} />
                      <div className="min-w-0">
                        <div className="truncate text-sm font-medium text-fg" title={d.filename}>{d.filename}</div>
                        <div className="truncate text-xs text-subtle">
                          {d.title && d.title !== d.filename ? d.title : d.content_type}
                          {d.page_count ? ` · ${d.page_count} pages` : ""}
                          {d.ingestion_ms ? ` · indexed in ${formatMs(d.ingestion_ms)}` : ""}
                        </div>
                        {d.status === "failed" && d.error_message && <div className="mt-0.5 truncate text-xs text-red-300">{d.error_message}</div>}
                      </div>
                    </div>
                    <span className="hidden text-right text-sm tabular-nums text-muted md:block">{formatBytes(d.size_bytes)}</span>
                    <span className="hidden text-right text-sm tabular-nums text-muted md:block">{d.status === "indexed" ? formatNumber(d.chunk_count) : "—"}</span>
                    <span className="hidden md:block"><StatusBadge status={d.status} error={d.error_message} /></span>
                    <span className="hidden text-xs text-muted md:block" title={new Date(d.created_at).toLocaleString()}>{timeAgo(d.created_at)}</span>
                    <div className="flex items-center justify-end gap-0.5">
                      <span className="mr-2 md:hidden"><StatusBadge status={d.status} error={d.error_message} /></span>
                      {d.status === "failed" ? (
                        <IconButton icon={RotateCcw} label={`Retry ingestion of ${d.filename}`} onClick={() => void reingest(d)} />
                      ) : (
                        <Link
                          to={`/knowledge?doc=${d.id}`}
                          aria-label={`Browse chunks of ${d.filename}`}
                          title="Browse chunks"
                          className={`inline-flex size-8 items-center justify-center rounded-lg text-muted transition-colors hover:bg-surface-2 hover:text-fg ${d.status !== "indexed" ? "pointer-events-none opacity-40" : ""}`}
                        >
                          <BookOpen className="size-4" aria-hidden />
                        </Link>
                      )}
                      <IconButton icon={Trash2} label={`Delete ${d.filename}`} onClick={() => setToDelete(d)} className="hover:text-red-300" />
                    </div>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={toDelete !== null}
        title="Delete document?"
        description={
          <>
            <span className="font-medium text-fg">{toDelete?.filename}</span> and its {formatNumber(toDelete?.chunk_count ?? 0)} indexed chunks will be
            permanently removed. It will no longer appear in search results or citations.
          </>
        }
        confirmLabel="Delete document"
        destructive
        busy={deleting}
        onConfirm={() => void confirmDelete()}
        onClose={() => setToDelete(null)}
      />
    </>
  );
}
