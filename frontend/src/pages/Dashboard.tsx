import { Link } from "react-router-dom";
import { Activity, ArrowRight, Boxes, FileText, Layers, MessageSquareText, Search, Upload, Zap } from "lucide-react";
import { FileIcon, StatusBadge } from "../components/documents/DocumentBits";
import { Badge, Card, EmptyState, ErrorBanner, Skeleton, StatCard } from "../components/ui";
import { useAuth } from "../context/AuthContext";
import { useApi } from "../hooks/useApi";
import { documentService } from "../services/document.service";
import { platformService } from "../services/platform.service";
import type { ActivityEvent } from "../types/api";
import { formatMs, formatNumber, formatPercent, timeAgo } from "../utils/format";

const eventLabel: Record<string, string> = {
  chat: "Chat question",
  search: "Search",
  ingest: "Document indexed",
};

function ActivityRow({ e }: { e: ActivityEvent }) {
  const Icon = e.event_type === "chat" ? MessageSquareText : e.event_type === "search" ? Search : Layers;
  return (
    <li className="flex items-start gap-3 py-2.5">
      <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md border border-line bg-surface-2 text-subtle">
        <Icon className="size-3.5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-sm">
          <span className="text-fg">{eventLabel[e.event_type] ?? e.event_type}</span>
          {!e.success && <Badge tone="danger">failed</Badge>}
        </div>
        {e.query && <div className="truncate text-xs text-muted">“{e.query}”</div>}
      </div>
      <div className="shrink-0 text-right text-[11px] text-subtle">
        <div>{timeAgo(e.created_at)}</div>
        {e.latency_ms !== null && <div className="tabular-nums">{formatMs(e.latency_ms)}</div>}
      </div>
    </li>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const overview = useApi(() => platformService.overview(), []);
  const recent = useApi(() => documentService.list(5), []);
  const o = overview.data;
  const firstName = (user?.full_name || user?.email.split("@")[0] || "").split(" ")[0];

  return (
    <>
      <div className="mb-8 flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Welcome back{firstName ? `, ${firstName}` : ""}</h1>
          <p className="mt-1.5 max-w-xl text-sm text-muted">
            Your private knowledge workspace. Documents are chunked, embedded and indexed with hybrid vector + keyword
            retrieval, then answered with cross-encoder reranking and verified citations.
          </p>
        </div>
        <div className="flex gap-2">
          <Link to="/documents" className="inline-flex h-9 items-center gap-2 rounded-lg border border-line-strong bg-surface-2 px-4 text-sm font-medium text-fg transition-colors hover:bg-surface-3">
            <Upload className="size-4" aria-hidden /> Upload documents
          </Link>
          <Link to="/chat" className="inline-flex h-9 items-center gap-2 rounded-lg bg-accent px-4 text-sm font-medium text-white transition-colors hover:bg-accent-strong">
            <MessageSquareText className="size-4" aria-hidden /> Start a conversation
          </Link>
        </div>
      </div>

      {overview.error && <ErrorBanner className="mb-4" message={`Analytics data unavailable: ${overview.error}`} onRetry={() => void overview.reload()} />}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {!o && !overview.error ? (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[108px] rounded-xl" />)
        ) : (
          <>
            <StatCard label="Documents" icon={FileText} value={o ? formatNumber(o.total_documents) : "—"} hint={o ? `${formatNumber(o.documents.indexed ?? 0)} indexed` : "unavailable"} />
            <StatCard label="Indexed chunks" icon={Boxes} value={o ? formatNumber(o.total_chunks) : "—"} hint="Searchable passages" />
            <StatCard label="Queries processed" icon={MessageSquareText} value={o ? formatNumber(o.total_queries) : "—"} hint={o ? `${formatNumber(o.total_conversations)} conversations` : "unavailable"} />
            <StatCard
              label="Avg. answer latency"
              icon={Zap}
              value={o?.avg_latency_ms != null ? formatMs(o.avg_latency_ms) : "—"}
              hint={o?.p95_latency_ms != null ? `p95 ${formatMs(o.p95_latency_ms)}` : "No queries yet"}
            />
          </>
        )}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-5">
        <Card
          className="lg:col-span-3"
          title="Recent documents"
          description="Latest uploads in your knowledge base"
          action={<Link to="/documents" className="inline-flex items-center gap-1 text-xs text-muted hover:text-fg">View all <ArrowRight className="size-3" aria-hidden /></Link>}
          bodyClassName="p-0"
        >
          {recent.error ? (
            <div className="p-5"><ErrorBanner message={recent.error} onRetry={() => void recent.reload()} /></div>
          ) : !recent.data ? (
            <div className="space-y-3 p-5">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-10" />)}</div>
          ) : recent.data.items.length === 0 ? (
            <EmptyState
              compact
              icon={FileText}
              title="No documents yet"
              description="Upload PDF, DOCX or TXT files to build your knowledge base."
              action={<Link to="/documents" className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-accent px-3 text-xs font-medium text-white hover:bg-accent-strong"><Upload className="size-3.5" aria-hidden /> Upload</Link>}
            />
          ) : (
            <ul className="divide-y divide-line">
              {recent.data.items.map((d) => (
                <li key={d.id} className="flex items-center gap-3 px-5 py-3">
                  <FileIcon type={d.file_type} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm text-fg">{d.filename}</div>
                    <div className="text-xs text-subtle">{d.status === "indexed" ? `${formatNumber(d.chunk_count)} chunks · ` : ""}{timeAgo(d.created_at)}</div>
                  </div>
                  <StatusBadge status={d.status} error={d.error_message} />
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="lg:col-span-2" title="Recent activity" description="Questions, searches and ingestion events" bodyClassName="px-5 py-2">
          {!o ? (
            overview.error ? <p className="py-6 text-center text-sm text-muted">Activity data unavailable.</p> : <div className="space-y-3 py-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-9" />)}</div>
          ) : o.recent_activity.length === 0 ? (
            <EmptyState compact icon={Activity} title="No activity yet" description="Ask a question or run a search to see it here." />
          ) : (
            <ul className="divide-y divide-line">{o.recent_activity.slice(0, 7).map((e, i) => <ActivityRow key={`${e.created_at}-${i}`} e={e} />)}</ul>
          )}
        </Card>
      </div>

      {o?.cache && (
        <Card className="mt-6" title="Retrieval activity" description="Live cache counters reported by the backend (Redis)">
          <div className="grid gap-4 sm:grid-cols-3">
            {Object.entries(o.cache).map(([name, c]) => (
              <div key={name}>
                <div className="flex items-baseline justify-between text-sm">
                  <span className="capitalize text-muted">{name} cache</span>
                  <span className="tabular-nums text-fg">{formatPercent(c.hit_rate, 1)}</span>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3">
                  <div className="h-full rounded-full bg-linear-to-r from-accent to-info" style={{ width: `${Math.min(100, c.hit_rate * 100)}%` }} />
                </div>
                <div className="mt-1.5 text-[11px] tabular-nums text-subtle">{formatNumber(c.hit)} hits · {formatNumber(c.miss)} misses</div>
              </div>
            ))}
          </div>
        </Card>
      )}
    </>
  );
}
