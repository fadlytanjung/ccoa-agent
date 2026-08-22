/**
 * The human-in-the-loop checkpoint — docs/07 §3.6, docs/05 §3.7, docs/21 §5.
 *
 * Four kinds of ask share one card, because they share one mechanism. The differences
 * that matter are which controls appear and whether the human can decline to answer:
 *
 * | kind      | controls                    | skippable |
 * |-----------|-----------------------------|-----------|
 * | `clarify` | options, or free text       | no        |
 * | `confirm` | yes / no, "don't ask again" | yes       |
 * | `approve` | approve / reject + note     | **never** |
 * | `steer`   | free text                   | yes       |
 *
 * For `approve` the card shows the **exact payload that will be written** — not a
 * paraphrase of it. That is what makes the approval meaningful: the graph writes
 * `proposal.payload` verbatim and never consults the model in between, so what is on
 * screen is what lands in the database. The design system's decision-safety rule says the
 * same thing from the other direction: a safety-critical detail is never hidden behind
 * progressive disclosure, which is why the field summary is always visible and only the
 * verbatim text is foldable.
 */

import { useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { AlertTriangle, Check, HelpCircle, X } from "lucide-react";

import { CitationList } from "./CitationList";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { PendingAsk, ResumeRequest } from "../api/types";

interface Props {
  ask: PendingAsk;
  decided: boolean;
  canApprove: boolean;
  onRespond: (payload: ResumeRequest) => void;
  onFocusRef?: (refId: string) => void;
}

const FIELD_ORDER = ["customer_id", "case_id", "title", "category", "priority", "assignee"];

export function ApprovalCard({ ask, decided, canApprove, onRespond, onFocusRef }: Props) {
  const [note, setNote] = useState("");
  const [remember, setRemember] = useState(false);
  const reduced = useReducedMotion();

  const payload = (ask.payload ?? {}) as Record<string, unknown>;
  const description = typeof payload.description === "string" ? payload.description : null;
  const summary = FIELD_ORDER.filter((key) => payload[key] != null).map((key) => [
    key,
    String(payload[key]),
  ]);

  const isApprove = ask.kind === "approve";
  const heading = isApprove
    ? "Approval required"
    : ask.kind === "confirm"
      ? "Confirm"
      : "A question for you";

  return (
    <motion.section
      {...(reduced
        ? {}
        : {
            initial: { opacity: 0, y: 10 },
            animate: { opacity: 1, y: 0 },
            transition: { duration: 0.26, ease: [0.16, 1, 0.3, 1] as const },
          })}
      role="group"
      aria-label={heading}
      data-testid="approval-card"
      data-kind={ask.kind}
      className={cn(
        "overflow-hidden rounded-xl border bg-card",
        // A pending write is the one thing on this screen that stops the work, so it is
        // also the one place a shadow is warranted.
        isApprove ? "border-semantic-warning shadow-raised" : "border-border",
        // Answered: the graph has already resumed on this reply and a second one is a
        // 409. `disabled` on each control was not enough — the card still invited
        // clicks, still showed a text cursor over the input, and still let a keyboard
        // user tab into dead controls. `pointer-events-none` plus `inert` makes it what
        // it now is: a record of what was answered.
        decided && "pointer-events-none select-none border-border-soft opacity-70",
      )}
      // `inert` also takes it out of the tab order and hides it from assistive tech as
      // an interactive region, which `pointer-events-none` alone does not do.
      {...(decided ? { inert: true } : {})}
      data-decided={decided ? "true" : undefined}
    >
      <header
        className={cn(
          "flex items-center gap-xs border-b px-md py-xs",
          isApprove
            ? "border-semantic-warning/40 bg-semantic-warning-bg text-semantic-warning-text"
            : "border-border-soft bg-surface text-text-secondary",
        )}
      >
        {/* Never colour alone — the icon and the word both carry the meaning. */}
        {isApprove ? (
          <AlertTriangle className="size-4 shrink-0" aria-hidden />
        ) : (
          <HelpCircle className="size-4 shrink-0" aria-hidden />
        )}
        <span className="text-caption-bold">{heading}</span>
        {decided && (
          <Badge tone="neutral" className="ml-auto" data-testid="approval-decided">
            answered
          </Badge>
        )}
      </header>

      <div className="space-y-sm px-md py-sm">
        {decided && (
          <p className="text-caption text-text-tertiary" data-testid="approval-settled">
            {/* Not "continued below": the pending card always renders last in the
                transcript, so once it is answered the reply it produced sits *above* it.
                Naming a direction that is wrong is worse than naming none. */}
            Answered — this checkpoint is closed.
          </p>
        )}
        <p data-testid="approval-question" className="text-body-sm text-foreground">
          {ask.question}
        </p>

        {summary.length > 0 && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-md gap-y-xxs rounded-md bg-surface p-sm">
            {summary.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-caption text-text-tertiary">
                  {key!.replace(/_/g, " ")}
                </dt>
                <dd className="font-mono text-micro text-foreground">{value}</dd>
              </div>
            ))}
          </dl>
        )}

        {description && (
          <details className="rounded-md border border-border bg-surface p-xs">
            <summary className="cursor-pointer text-caption text-text-secondary">
              Exactly what will be saved
            </summary>
            <pre
              data-testid="approval-payload"
              className="mt-xs max-h-64 overflow-auto whitespace-pre-wrap font-mono text-micro text-foreground"
            >
              {description}
            </pre>
          </details>
        )}

        {ask.evidence_refs && ask.evidence_refs.length > 0 && (
          <CitationList
            refs={ask.evidence_refs}
            onFocus={onFocusRef}
            label="Based on"
          />
        )}

        {/* An ask with no options is answered in the composer. Saying so beats leaving
            a question on screen with nothing under it. */}
        {!decided &&
          (ask.kind === "clarify" || ask.kind === "steer") &&
          !ask.options?.length && (
            <p className="text-caption text-text-tertiary" data-testid="answer-below">
              Answer in the message box below.
            </p>
          )}

        {/* clarify: pick one of the offered records */}
        {ask.kind === "clarify" && !decided && ask.options && ask.options.length > 0 && (
          <div className="flex flex-col gap-xs">
            {ask.options.map((option) => (
              <button
                key={option.value}
                type="button"
                disabled={decided}
                data-testid="clarify-option"
                data-value={option.value}
                onClick={() => onRespond({ kind: "clarify", selection: option.value })}
                className="min-h-11 rounded-md border border-border bg-background px-sm py-xs text-left text-body-sm text-foreground transition-colors duration-(--motion-interactive) hover:border-ring hover:bg-surface-feature focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
              >
                {option.label}
              </button>
            ))}
          </div>
        )}

        {/* No free-text box here. It duplicated the composer sitting a few pixels below,
            and when the graph offers no options it was the *only* control in the card —
            two identical inputs, one of which answers the question and one of which does
            not. Free-text answers now go through the composer itself, which is where
            someone in a conversation types (docs/07 §3.6). */}

        {ask.kind === "confirm" && !decided && (
          <div className="flex flex-wrap items-center gap-xs">
            <label className="mr-auto flex min-h-11 items-center gap-xs text-caption text-text-secondary">
              <input
                type="checkbox"
                checked={remember}
                onChange={(event) => setRemember(event.target.checked)}
                className="size-4 accent-(--brand-green-dark)"
              />
              Don&apos;t ask me again in this conversation
            </label>
            <Button
              variant="secondary"
              disabled={decided}
              data-testid="confirm-no"
              onClick={() => onRespond({ kind: "confirm", approved: false, remember })}
            >
              <X />
              No
            </Button>
            <Button
              disabled={decided}
              data-testid="confirm-yes"
              onClick={() => onRespond({ kind: "confirm", approved: true, remember })}
            >
              <Check />
              Yes, go ahead
            </Button>
          </div>
        )}

        {isApprove && !decided && (
          <div className="space-y-xs">
            <label className="block text-caption text-text-secondary">
              Note (optional)
              <Input
                value={note}
                onChange={(event) => setNote(event.target.value)}
                disabled={decided}
                data-testid="approval-note"
                className="mt-xxs"
              />
            </label>
            <div className="flex flex-wrap justify-end gap-xs">
              <Button
                variant="secondary"
                disabled={decided}
                data-testid="approval-reject"
                onClick={() => onRespond({ kind: "approve", approved: false, note })}
              >
                Reject
              </Button>
              <Button
                /* Hidden capability, not hidden truth: the backend re-checks the group
                   on the resuming actor regardless of what this button allows. */
                disabled={decided || !canApprove}
                title={canApprove ? undefined : "Your role cannot approve this action"}
                data-testid="approval-approve"
                onClick={() => onRespond({ kind: "approve", approved: true, note })}
              >
                Approve
              </Button>
            </div>
          </div>
        )}
      </div>
    </motion.section>
  );
}
