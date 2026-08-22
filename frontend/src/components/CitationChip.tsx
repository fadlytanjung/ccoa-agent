/**
 * A citation, as a clickable chip — docs/07 §3.5, docs/21 §6.
 *
 * This is the grounding contract made visible: every claim the assistant makes is one
 * click from the record it came from. A citation that cannot be inspected is a footnote
 * nobody reads.
 */
import { Link2 } from "lucide-react";

interface Props {
  refId: string;
  onFocus?: (refId: string) => void;
}

const LABELS: Record<string, string> = {
  customer: "Customer",
  policy: "Policy",
  claim: "Claim",
  case: "Case",
  interaction: "Contact",
  ticket: "Ticket",
  kb: "Article",
  reference: "Reference",
};

export function CitationChip({ refId, onFocus }: Props) {
  const [kind, id] = refId.split(":");
  const label = LABELS[kind ?? ""] ?? kind ?? "Record";

  return (
    <button
      type="button"
      onClick={() => onFocus?.(refId)}
      title={`${label} ${id ?? ""}`}
      data-testid="citation-chip"
      data-ref={refId}
      className="inline-flex min-h-7 items-center gap-xxs rounded-full border border-border bg-surface px-xs font-mono text-micro text-text-secondary transition-colors duration-(--motion-interactive) hover:border-ring hover:bg-surface-feature hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <Link2 className="size-3 shrink-0" aria-hidden />
      <span className="sr-only">{label} </span>
      {id ?? refId}
    </button>
  );
}
