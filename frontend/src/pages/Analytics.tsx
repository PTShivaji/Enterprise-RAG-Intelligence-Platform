import { useState } from "react";
import { Activity, Boxes, Coins, Cpu, FlaskConical, Gauge, Timer, Zap } from "lucide-react";
import { Badge, Card, EmptyState, ErrorBanner, PageIntro, Skeleton, StatCard } from "../components/ui";
import { useApi } from "../hooks/useApi";
import { platformService, providerOf } from "../services/platform.service";
import type { UsagePoint } from "../types/api";
import { cx, formatMs, formatNumber, formatPercent, timeAgo } from "../utils/format";

const SERIES: Record<string, { label: string; color: string }> = {
  chat: { label: "Chat", color: "#8b5cf6" },
  search: { label: "Search", color: "#3b82f6" },
  ingest: { label: "Ingestion", color: "#14b8a6" },
};
const seriesOf = (t: string) => SERIES[t] ?? { label: t, color: "#64748b" };

function ActivityChart({ series, days }: { series: UsagePoint[]; days: number }) {
  // Build a continuous day axis so gaps show as empty days rather than being hidden.
  const end = new Date();
  const axis = Array.from({ length: days }, (_, i) => {
    const d = new Date(end);
    d.setDate(end.getDate() - (days - 1 - i));
    return d.toISOString().slice(0, 10);
  });
  const types = [...new Set(series.map((s) => s.event_type))];
  const byDay = new Map<string, Record<string, number>>();
  for (const p of series) byDay.set(p.day, { ...(byDay.get(p.day) ?? {}), [p.event_type]: p.count });
  const max = Math.max(1, ...axis.map((d) => Object.values(byDay.get(d) ?? {}).reduce((a, b) => a + b, 0)));

  return (
    <div>
      <div className="mb-4 flex flex-wrap gap-4 text-xs text-muted">
        {types.map((t) => (
          <span key={t} className="inline-flex items-center gap-1.5">
            <span className="size-2 rounded-sm" style={{ background: seriesOf(t).color }} /> {seriesOf(t).label}
          </span>
        ))}
      </div>
      <div className="flex h-40 items-end gap-1" role="img" aria-label={`Events per day over the last ${days} days`}>
        {axis.map((day) => {
          const counts = byDay.get(day) ?? {};
          const total = Object.values(counts).reduce((a, b) => a + b, 0);
          return (
            <div key={day} className="group relative flex h-full flex-1 flex-col justify-end" title={`${day}: ${total} event(s)${total ? " — " + Object.entries(counts).map(([t, c]) => `${seriesOf(t).label} ${c}`).join(", ") : ""}`}>
              <div className="flex w-full flex-col-reverse overflow-hidden rounded-t-[3px]" style={{ height: `${(total / max) * 100}%` }}>
                {types.map((t) => counts[t] ? <div key={t} style={{ height: `${(counts[t] / total) * 100}%`, background: seriesOf(t).color }} className="w-full opacity-85 transition-opacity group-hover:opacity-100" /> : null)}
              </div>
              {total === 0 && <div className="h-px w-full bg-line" />}
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-between font-mono text-[10px] text-subtle">
        <span>{axis[0]}</span>
        <span>{axis[axis.length - 1]}</span>
      </div>
    </div>
  );
}

/** Flattens {config: {metric: number}} or {metric: number} into rows for display. */
function metricRows(metrics: Record<string, unknown>): Array<[string, string, number]> {
  const rows: Array<[string, string, number]> = [];
  for (const [k, v] of Object.entries(metrics)) {
    if (typeof v === "number") rows.push(["", k, v]);
    else if (v && typeof v === "object") {
      for (const [m, n] of Object.entries(v as Record<string, unknown>)) if (typeof n === "number") rows.push([k, m, n]);
    }
  }
  return rows;
}

export default function AnalyticsPage() {
  const [days, setDays] = useState(14);
  const overview = useApi(() => platformService.overview(), []);
  const usage = useApi(() => platformService.usage(days), [days]);
  const evals = useApi(() => platformService.evaluations(10), []);
  const models = useApi(() => platformService.models(), []);
  const o = overview.data;

  // Average latency split by stage, from the real usage series (chat events only).
  const chatPoints = usage.data?.series.filter((p) => p.event_type === "chat") ?? [];
  const weighted = (key: "avg_retrieval_ms" | "avg_llm_ms") => {
    const pts = chatPoints.filter((p) => p[key] !== null);
    const n = pts.reduce((a, p) => a + p.count, 0);
    return n ? pts.reduce((a, p) => a + (p[key] as number) * p.count, 0) / n : null;
  };
  const retrievalMs = weighted("avg_retrieval_ms");
  const llmMs = weighted("avg_llm_ms");

  return (
    <>
      <PageIntro title="Analytics" description="Operational metrics recorded by the backend for your account. Nothing on this page is estimated or simulated." />

      {overview.error && <ErrorBanner className="mb-4" message={`Analytics data unavailable: ${overview.error}`} onRetry={() => void overview.reload()} />}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {!o && !overview.error ? (
          [0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[108px] rounded-xl" />)
        ) : o ? (
          <>
            <StatCard label="Queries" icon={Activity} value={formatNumber(o.total_queries)} hint={`${formatNumber(o.total_conversations)} conversations`} />
            <StatCard label="Answer latency" icon={Timer} value={formatMs(o.avg_latency_ms)} hint={o.p95_latency_ms !== null ? `p95 ${formatMs(o.p95_latency_ms)}` : "No queries yet"} />
            <StatCard label="Tokens" icon={Boxes} value={formatNumber(o.prompt_tokens + o.completion_tokens)} hint={`${formatNumber(o.prompt_tokens)} prompt · ${formatNumber(o.completion_tokens)} completion`} />
            <StatCard label="LLM cost" icon={Coins} value={`$${o.cost_usd.toFixed(4)}`} hint="As reported by LiteLLM" />
          </>
        ) : null}
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card
          className="lg:col-span-2"
          title="Query activity"
          description="Events per day by type"
          action={
            <select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Time range" className="rounded-md border border-line bg-surface-2 px-2 py-1 text-xs text-muted">
              {[7, 14, 30].map((d) => <option key={d} value={d}>Last {d} days</option>)}
            </select>
          }
        >
          {usage.error ? (
            <p className="py-10 text-center text-sm text-muted">Analytics data unavailable.</p>
          ) : !usage.data ? (
            <Skeleton className="h-48" />
          ) : usage.data.series.length === 0 ? (
            <EmptyState compact icon={Activity} title="No activity in this period" />
          ) : (
            <ActivityChart series={usage.data.series} days={days} />
          )}
        </Card>

        <Card title="Retrieval performance" description="Chat latency by pipeline stage">
          {!usage.data ? (
            <Skeleton className="h-32" />
          ) : retrievalMs === null && llmMs === null ? (
            <p className="py-6 text-center text-sm text-muted">No chat queries in this period.</p>
          ) : (
            <dl className="space-y-4">
              {[
                ["Retrieval (embed · search · rerank)", retrievalMs],
                ["Generation (LLM)", llmMs],
              ].map(([label, v]) => (
                <div key={label as string}>
                  <dt className="text-xs text-muted">{label}</dt>
                  <dd className="mt-0.5 text-xl font-semibold tabular-nums">{formatMs(v as number | null)}</dd>
                </div>
              ))}
              <p className="text-[11px] text-subtle">Average across {formatNumber(chatPoints.reduce((a, p) => a + p.count, 0))} chat events.</p>
            </dl>
          )}
        </Card>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <Card title="Cache efficiency" description="Redis cache counters" className="lg:col-span-1">
          {!o ? (
            <Skeleton className="h-32" />
          ) : !o.cache || Object.keys(o.cache).length === 0 ? (
            <p className="py-6 text-center text-sm text-muted">Cache metrics unavailable.</p>
          ) : (
            <ul className="space-y-4">
              {Object.entries(o.cache).map(([name, c]) => (
                <li key={name}>
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="inline-flex items-center gap-1.5 capitalize text-muted"><Zap className="size-3.5 text-subtle" aria-hidden />{name}</span>
                    <span className="tabular-nums">{formatPercent(c.hit_rate, 1)}</span>
                  </div>
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-3">
                    <div className="h-full rounded-full bg-info" style={{ width: `${Math.min(100, c.hit_rate * 100)}%` }} />
                  </div>
                  <div className="mt-1 text-[11px] tabular-nums text-subtle">{formatNumber(c.hit)} hits / {formatNumber(c.hit + c.miss)} lookups</div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Evaluation results" description="Benchmark runs stored by POST /evaluation/run" className="lg:col-span-2" bodyClassName="p-0">
          {evals.error ? (
            <p className="p-6 text-center text-sm text-muted">Evaluation data unavailable: {evals.error}</p>
          ) : !evals.data ? (
            <div className="p-5"><Skeleton className="h-24" /></div>
          ) : evals.data.length === 0 ? (
            <EmptyState
              compact
              icon={FlaskConical}
              title="No evaluation runs stored"
              description={<>Run the benchmark with <code className="rounded bg-surface-3 px-1 font-mono text-xs">POST /api/v1/evaluation/run</code> or <code className="rounded bg-surface-3 px-1 font-mono text-xs">evaluation/scripts/run_evaluation.py</code>. Results appear here once a run completes.</>}
            />
          ) : (
            <ul className="divide-y divide-line">
              {evals.data.map((run) => {
                const rows = metricRows(run.metrics).slice(0, 24);
                return (
                  <li key={run.id} className="px-5 py-4">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{run.name}</span>
                      <Badge tone={run.status === "completed" ? "ok" : run.status === "failed" ? "danger" : "info"}>{run.status}</Badge>
                      <span className="ml-auto text-xs text-subtle">{timeAgo(run.created_at)}</span>
                    </div>
                    {rows.length > 0 && (
                      <div className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-[11px] sm:grid-cols-3">
                        {rows.map(([group, k, v]) => (
                          <div key={`${group}.${k}`} className="flex justify-between gap-2">
                            <span className="truncate text-subtle">{group ? `${group}.` : ""}{k}</span>
                            <span className="tabular-nums text-fg">{Number.isInteger(v) ? v : v.toFixed(3)}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>

      <Card className="mt-6" title="Model information" description="Models loaded by the running backend (GET /models)">
        {models.error ? (
          <p className="text-sm text-muted">Model information unavailable.</p>
        ) : !models.data ? (
          <Skeleton className="h-20" />
        ) : (
          <div className="grid gap-6 md:grid-cols-3">
            <div>
              <div className="flex items-center gap-1.5 text-xs text-muted"><Cpu className="size-3.5" aria-hidden /> Embedding</div>
              <div className="mt-1 break-all font-mono text-sm">{models.data.embedding_model}</div>
              <div className="text-xs text-subtle">{models.data.embedding_dimension}-d · max {models.data.embedding_max_seq_length} tokens</div>
            </div>
            <div>
              <div className="flex items-center gap-1.5 text-xs text-muted"><Gauge className="size-3.5" aria-hidden /> Reranker</div>
              <div className="mt-1 break-all font-mono text-sm">{models.data.reranker_model ?? "disabled"}</div>
            </div>
            <div>
              <div className="flex items-center gap-1.5 text-xs text-muted"><Cpu className="size-3.5" aria-hidden /> Generation (default: <span className="font-mono">{models.data.llm_default_model}</span>)</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {models.data.llm_allowed_models.map((m) => {
                  const ok = models.data!.llm_configured_providers[providerOf(m)];
                  return <Badge key={m} tone={ok ? "ok" : "neutral"} className={cx(!ok && "opacity-60")} title={ok ? "Provider configured" : "Provider not configured (no API key / base URL)"}>{m}</Badge>;
                })}
              </div>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}
