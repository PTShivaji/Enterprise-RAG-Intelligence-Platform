import { AlertTriangle, ShieldAlert, ShieldCheck, ShieldQuestion } from "lucide-react";
import { Badge } from "../ui";
import type { Verification } from "../../types/api";
import { formatPercent } from "../../utils/format";

/**
 * Reflects exactly what the backend's citation verifier returned:
 *   grounded=true  -> every sentence cited and supported by its cited source
 *   grounded=false -> some sentences uncited or weakly supported (details in tooltip)
 */
export function GroundingBadge({ verification, insufficient }: { verification?: Verification; insufficient?: boolean }) {
  if (insufficient) {
    return <Badge tone="warn" icon={ShieldAlert}>Insufficient evidence</Badge>;
  }
  if (!verification || verification.grounded === undefined) {
    return (
      <Badge tone="neutral" icon={ShieldQuestion} title="The backend did not return verification data for this message">
        Not verified
      </Badge>
    );
  }
  const score = verification.grounding_score;
  const scoreText = score !== undefined ? ` · ${formatPercent(score)}` : "";
  if (verification.grounded) {
    return (
      <Badge tone="ok" icon={ShieldCheck} title="Every sentence carries a citation that supports it (backend citation verifier)">
        Grounded{scoreText}
      </Badge>
    );
  }
  const issues = [
    verification.weakly_supported_sentences ? `${verification.weakly_supported_sentences} weakly supported sentence(s)` : null,
    verification.uncited_sentences ? `${verification.uncited_sentences} uncited sentence(s)` : null,
    verification.invalid_markers_removed?.length ? `${verification.invalid_markers_removed.length} invalid citation(s) removed` : null,
  ].filter(Boolean);
  return (
    <Badge tone="warn" icon={ShieldAlert} title={issues.length ? `Verifier flagged: ${issues.join(", ")}` : "Not fully grounded"}>
      Partially supported{scoreText}
    </Badge>
  );
}

export function InsufficientEvidenceNotice({ reason }: { reason?: string }) {
  const why: Record<string, string> = {
    no_relevant_chunks: "Retrieval found no passage in your documents relevant enough to answer.",
    empty_question: "The question was empty after preprocessing.",
  };
  return (
    <div className="flex gap-3 rounded-lg border border-warn/25 bg-warn-soft px-4 py-3">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
      <div className="text-sm">
        <div className="font-medium text-amber-200">Not enough evidence in your documents</div>
        <p className="mt-0.5 text-amber-100/70">
          {(reason && why[reason]) || "The system declined to answer rather than guess."} Try rephrasing, or upload a document that covers this topic.
        </p>
      </div>
    </div>
  );
}
