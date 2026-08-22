/**
 * Record identifiers, as badges — docs/21 §4.7.
 *
 * `CUST-000042` and `POL-00000073` are not prose and should not read as prose. They are
 * the join between what the assistant says and what the records hold, and the agent scans
 * for them: in a wall of monospace they all look alike, and finding the policy in a
 * paragraph that also names a customer, a case, and two more policies is real work.
 *
 * One colour per record kind, taken from the semantic palette, so the kind is legible
 * before the digits are read. Colour is never the only signal — the prefix is right there
 * in the text — so this stays inside the "no colour alone" rule.
 */
import { PREFIXED, TONES, recordKind } from "@/lib/records";
import { cn } from "@/lib/utils";

export function RecordBadge({
  value,
  onFocus,
  className,
}: {
  value: string;
  onFocus?: (refId: string) => void;
  className?: string;
}) {
  const trimmed = value.trim();
  const kind = recordKind(trimmed);
  const prefixed = PREFIXED.exec(trimmed);
  const shown = prefixed ? prefixed[2]! : trimmed;
  const tone = (kind && TONES[kind]) ?? "bg-surface-soft text-text-secondary";

  // Non-interactive when there is nowhere to go: a badge that looks clickable and does
  // nothing is worse than one that plainly does not.
  if (!onFocus) {
    return (
      <span
        data-testid="record-badge"
        className={cn(
          "inline-block rounded-sm px-[5px] py-[1px] align-baseline font-mono text-micro",
          tone,
          className,
        )}
      >
        {shown}
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onFocus(trimmed)}
      title={`Show ${shown}`}
      data-testid="record-badge"
      data-ref={trimmed}
      className={cn(
        "inline-block rounded-sm px-[5px] py-[1px] align-baseline font-mono text-micro transition-opacity duration-(--motion-interactive) hover:opacity-80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        tone,
        className,
      )}
    >
      {shown}
    </button>
  );
}
