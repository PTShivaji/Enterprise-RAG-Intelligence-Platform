import { AlertCircle, CheckCircle2, Copy, Loader2, X, XCircle } from "lucide-react";
import type { UploadJob } from "../../hooks/useUploads";
import { cx, formatBytes } from "../../utils/format";

const phaseInfo: Record<UploadJob["phase"], { label: string; tone: string }> = {
  invalid: { label: "Rejected", tone: "text-red-300" },
  uploading: { label: "Uploading", tone: "text-blue-300" },
  processing: { label: "Parsing, chunking & embedding", tone: "text-blue-300" },
  indexed: { label: "Indexed", tone: "text-green-300" },
  failed: { label: "Ingestion failed", tone: "text-red-300" },
  duplicate: { label: "Duplicate", tone: "text-amber-300" },
  error: { label: "Upload failed", tone: "text-red-300" },
};

function PhaseIcon({ phase }: { phase: UploadJob["phase"] }) {
  if (phase === "uploading" || phase === "processing") return <Loader2 className="size-4 animate-spin text-info" aria-hidden />;
  if (phase === "indexed") return <CheckCircle2 className="size-4 text-ok" aria-hidden />;
  if (phase === "duplicate") return <Copy className="size-4 text-warn" aria-hidden />;
  if (phase === "invalid") return <AlertCircle className="size-4 text-danger" aria-hidden />;
  return <XCircle className="size-4 text-danger" aria-hidden />;
}

export function UploadQueue({ jobs, onDismiss, onClear }: { jobs: UploadJob[]; onDismiss: (key: string) => void; onClear: () => void }) {
  if (!jobs.length) return null;
  const active = jobs.some((j) => j.phase === "uploading" || j.phase === "processing");
  return (
    <div className="card overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <span className="text-xs font-medium text-muted">Uploads</span>
        {!active && (
          <button onClick={onClear} className="text-xs text-subtle hover:text-muted">Clear</button>
        )}
      </div>
      <ul className="divide-y divide-line" aria-live="polite">
        {jobs.map((j) => {
          const info = phaseInfo[j.phase];
          const busy = j.phase === "uploading" || j.phase === "processing";
          return (
            <li key={j.key} className="flex items-center gap-3 px-4 py-3">
              <PhaseIcon phase={j.phase} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm text-fg">{j.name}</span>
                  <span className="shrink-0 text-[11px] text-subtle">{formatBytes(j.size)}</span>
                </div>
                <div className={cx("mt-0.5 text-xs", info.tone)}>
                  {info.label}
                  {j.phase === "uploading" && ` · ${j.progress}%`}
                  {j.phase === "indexed" && j.chunks !== undefined && ` · ${j.chunks} chunks`}
                  {j.message && <span className="text-muted"> — {j.message}</span>}
                </div>
                {busy && (
                  <div className="mt-2 h-1 overflow-hidden rounded-full bg-surface-3">
                    <div
                      className={cx("h-full rounded-full bg-linear-to-r from-accent to-info transition-all", j.phase === "processing" && "w-full animate-pulse")}
                      style={j.phase === "uploading" ? { width: `${j.progress}%` } : undefined}
                    />
                  </div>
                )}
              </div>
              {!busy && (
                <button onClick={() => onDismiss(j.key)} aria-label={`Dismiss ${j.name}`} className="rounded p-1 text-subtle hover:bg-surface-2 hover:text-muted">
                  <X className="size-3.5" aria-hidden />
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
