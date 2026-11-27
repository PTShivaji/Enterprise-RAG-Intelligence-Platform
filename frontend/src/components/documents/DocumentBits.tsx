import { CheckCircle2, CircleDashed, FileText, Loader2, XCircle } from "lucide-react";
import { Badge } from "../ui";
import type { DocumentStatus } from "../../types/api";
import { cx } from "../../utils/format";

export function StatusBadge({ status, error }: { status: DocumentStatus; error?: string | null }) {
  switch (status) {
    case "indexed":
      return <Badge tone="ok" icon={CheckCircle2}>Indexed</Badge>;
    case "processing":
      return (
        <Badge tone="info" className="gap-1.5">
          <Loader2 className="size-3 animate-spin" aria-hidden /> Processing
        </Badge>
      );
    case "failed":
      return <Badge tone="danger" icon={XCircle} title={error ?? undefined}>Failed</Badge>;
    default:
      return <Badge tone="neutral" icon={CircleDashed}>Queued</Badge>;
  }
}

const typeColor: Record<string, string> = {
  pdf: "text-red-300 bg-red-500/10 border-red-500/20",
  docx: "text-blue-300 bg-blue-500/10 border-blue-500/20",
  txt: "text-slate-300 bg-slate-500/10 border-slate-500/20",
};

export function FileIcon({ type, className }: { type: string; className?: string }) {
  return (
    <div className={cx("relative flex size-9 shrink-0 items-center justify-center rounded-lg border", typeColor[type] ?? typeColor.txt, className)}>
      <FileText className="size-4" aria-hidden />
      <span className="absolute -bottom-1.5 rounded bg-canvas px-1 font-mono text-[8px] font-semibold uppercase tracking-wide">{type}</span>
    </div>
  );
}
