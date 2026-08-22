/**
 * Recognising a record identifier — docs/21 §4.7.
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

/** `CUST-000042`, `POL-00000073`, `CASE-000008`, `TCK-000031`, `INT-000114`, `KB-0007`. */
export const ID_PATTERN = /^(CUST|POL|CLM|CASE|TCK|INT|KB|REF)-[A-Z0-9]+$/;

/** Also matched inside a `kind:id` citation form, which is how the graph emits refs. */
export const PREFIXED = /^(customer|policy|claim|case|ticket|interaction|kb|reference):(.+)$/i;

export const TONES: Record<string, string> = {
  CUST: "bg-brand-green-soft text-brand-green-dark",
  POL: "bg-semantic-positive-bg text-semantic-positive-text",
  CLM: "bg-semantic-warning-bg text-semantic-warning-text",
  CASE: "bg-semantic-warning-bg text-semantic-warning-text",
  TCK: "bg-semantic-danger-bg text-semantic-danger-text",
  INT: "bg-semantic-unknown-bg text-semantic-unknown-text",
  KB: "bg-surface-feature text-brand-green-dark",
  REF: "bg-surface-soft text-text-secondary",
};

export const KIND_TO_PREFIX: Record<string, string> = {
  customer: "CUST",
  policy: "POL",
  claim: "CLM",
  case: "CASE",
  ticket: "TCK",
  interaction: "INT",
  kb: "KB",
  reference: "REF",
};

/** The record kind of an identifier, or `null` if it is not one. */
export function recordKind(value: string): string | null {
  const trimmed = value.trim();
  const prefixed = PREFIXED.exec(trimmed);
  if (prefixed) return KIND_TO_PREFIX[prefixed[1]!.toLowerCase()] ?? null;
  if (!ID_PATTERN.test(trimmed)) return null;
  return trimmed.split("-")[0]!;
}
