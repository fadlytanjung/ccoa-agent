/**
 * Sources for one answer — docs/07 §3.5, docs/21 §4.7.
 *
 * An investigation can cite a dozen records, and a dozen chips wrapped across four lines
 * buries the answer they belong to. Worse, it makes the citations *less* useful: a wall of
 * identifiers is not scannable, so nobody reads any of them.
 *
 * So: the first three inline, and the rest behind a `+N` chip that opens a dialog. The
 * dialog paginates, because "a lot" has no upper bound — the graph's evidence list grows
 * with the investigation, and a modal that scrolls for two screens has the same problem
 * one line down.
 *
 * The three shown are not arbitrary: they are the first three the graph recorded, which is
 * the order it gathered them in, so the most directly relevant record is normally first.
 */
import { useState } from "react";

import { CitationChip } from "./CitationChip";
import { RecordBadge } from "./RecordBadge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent } from "@/components/ui/dialog";

/** Shown inline before the rest collapse into a `+N` chip. */
const INLINE_LIMIT = 3;

/** Rows per page inside the dialog. */
const PAGE_SIZE = 8;

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

export function CitationList({
  refs,
  onFocus,
  label = "Sources",
}: {
  refs: string[];
  onFocus?: (refId: string) => void;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(0);

  if (refs.length === 0) return null;

  const inline = refs.slice(0, INLINE_LIMIT);
  const overflow = refs.length - inline.length;

  const pages = Math.max(1, Math.ceil(refs.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const shown = refs.slice(current * PAGE_SIZE, current * PAGE_SIZE + PAGE_SIZE);

  return (
    <div className="flex flex-wrap items-center gap-xxs" data-testid="citation-list">
      <span className="text-micro-uppercase text-text-tertiary">{label}</span>

      {inline.map((refId) => (
        <CitationChip key={refId} refId={refId} onFocus={onFocus} />
      ))}

      {overflow > 0 && (
        <button
          type="button"
          onClick={() => {
            setPage(0);
            setOpen(true);
          }}
          data-testid="citation-overflow"
          aria-label={`Show all ${refs.length} sources`}
          className="inline-flex min-h-7 items-center rounded-full border border-border-strong bg-surface-soft px-xs font-mono text-micro text-text-secondary transition-colors duration-(--motion-interactive) hover:border-ring hover:bg-surface-feature hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          +{overflow}
        </button>
      )}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          title={`Sources (${refs.length})`}
          description="Every record this answer was built from."
        >
          <ul className="space-y-xxs" data-testid="citation-dialog-list">
            {shown.map((refId) => {
              const [kind, id] = refId.split(":");
              return (
                <li
                  key={refId}
                  data-testid="citation-dialog-item"
                  className="flex items-center gap-xs rounded-md border border-border bg-card px-sm py-xs"
                >
                  <RecordBadge value={refId} />
                  <span className="min-w-0 flex-1 truncate text-body-sm text-text-secondary">
                    {LABELS[kind ?? ""] ?? kind ?? "Record"}
                  </span>
                  {onFocus && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        onFocus(refId);
                        setOpen(false);
                      }}
                    >
                      {/* Closing on select is the point: the record it reveals is behind
                          this dialog, and leaving it open hides what was just asked for. */}
                      Show
                      <span className="sr-only"> {id ?? refId}</span>
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>

          {pages > 1 && (
            <div className="mt-md flex items-center justify-between gap-xs border-t border-border-soft pt-sm">
              <Button
                variant="secondary"
                size="sm"
                disabled={current === 0}
                onClick={() => setPage(current - 1)}
                data-testid="citation-prev"
              >
                Previous
              </Button>
              <span className="text-caption text-text-tertiary" data-testid="citation-page">
                Page {current + 1} of {pages}
              </span>
              <Button
                variant="secondary"
                size="sm"
                disabled={current >= pages - 1}
                onClick={() => setPage(current + 1)}
                data-testid="citation-next"
              >
                Next
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
