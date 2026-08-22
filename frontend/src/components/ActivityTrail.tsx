/**
 * The live progress trail — docs/07 §3.5, docs/21 §6.
 *
 * Expanded while running, collapsed to one line once the answer arrives: visible enough
 * to build trust, quiet enough not to bury the answer. It is not chat, so it does not
 * render as messages.
 *
 * The motion here is load-bearing rather than decorative. A graph turn is several seconds
 * of silence, and silence is indistinguishable from a hang; each row animating in as its
 * event arrives is the evidence that work is still happening. The design system's rule
 * still applies — under `prefers-reduced-motion` every animation stops and **not one row
 * disappears**, because the information was never in the movement.
 *
 * What it must not do is invent activity. Every row corresponds to an event the backend
 * actually sent (docs/21 §6, "do not fabricate tool logs").
 *
 * **Repeated calls to one tool collapse into a single row with a count.** An investigation
 * calls `search_kb` four times with different arguments, and four near-identical monospace
 * lines push the answer off the screen while telling the agent nothing they did not learn
 * from the first. The count keeps the information — how much work happened — without the
 * height. Collapsing is presentational only: nothing is dropped, and the last call's
 * arguments and outcome are what the row reports, because that is the state the tool is
 * actually in.
 */
import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Check, ChevronDown, Loader2, X } from "lucide-react";

import { cn } from "@/lib/utils";
import type { Activity } from "../hooks/useConversation";

interface ToolGroup {
  name: string;
  calls: number;
  /** The most recent call's summary and outcome — the tool's current state. */
  args_summary: string;
  ok: boolean;
}

function groupTools(tools: Activity["tools"]): ToolGroup[] {
  const groups = new Map<string, ToolGroup>();
  for (const tool of tools) {
    const existing = groups.get(tool.name);
    if (existing) {
      existing.calls += 1;
      existing.args_summary = tool.args_summary;
      existing.ok = tool.ok;
    } else {
      groups.set(tool.name, {
        name: tool.name,
        calls: 1,
        args_summary: tool.args_summary,
        ok: tool.ok,
      });
    }
  }
  // Insertion order, which is call order — the sequence is part of what the trail shows.
  return [...groups.values()];
}

export function ActivityTrail({ activity, running }: { activity: Activity; running: boolean }) {
  const [open, setOpen] = useState(false);
  const reduced = useReducedMotion();
  const { steps, tools } = activity;
  if (!steps.length && !tools.length) return null;

  const grouped = groupTools(tools);
  // Only the tool that most recently reported is still plausibly open, and only while the
  // turn is running. Pulsing every row would claim work that has already finished.
  const openTool = running ? grouped.at(-1)?.name : undefined;

  const expanded = running || open;
  const current = steps.at(-1);

  const row = (index: number) =>
    reduced
      ? {}
      : {
          initial: { opacity: 0, x: -6 },
          animate: { opacity: 1, x: 0 },
          transition: { duration: 0.22, ease: [0.16, 1, 0.3, 1] as const, delay: index * 0.04 },
        };

  return (
    <div
      className={cn(
        "rounded-lg border px-sm py-xs transition-colors duration-(--motion-interactive)",
        // Tinted while the graph is working, plain once it has finished. The trail is
        // *process*, not output, and at a glance the colour is what separates the two —
        // a running lookup should never be mistaken for part of the answer. It settles
        // back to a quiet bordered box so a finished turn reads as one thing.
        running
          ? "border-brand-green-dark/30 bg-surface-feature"
          : "border-border bg-surface",
      )}
      data-testid="activity-trail"
      data-running={running ? "true" : undefined}
    >
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-xs text-left"
      >
        {running ? (
          <Loader2 className="size-4 shrink-0 animate-spin text-brand-green-dark motion-reduce:animate-none" />
        ) : (
          <Check className="size-4 shrink-0 text-semantic-positive" />
        )}
        {/* Labelled explicitly as the assistant's own activity — it is never evidence. */}
        <span
          className={cn(
            "flex-1 truncate text-caption",
            running ? "text-brand-green-dark" : "text-text-secondary",
          )}
        >
          {running
            ? (current?.label ?? "Working")
            : `Assistant activity · ${tools.length} lookup${tools.length === 1 ? "" : "s"}`}
        </span>
        <ChevronDown
          aria-hidden
          className={cn(
            "size-4 shrink-0 text-text-tertiary transition-transform duration-(--motion-interactive)",
            expanded && "rotate-180",
          )}
        />
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.ul
            {...(reduced
              ? {}
              : {
                  initial: { height: 0, opacity: 0 },
                  animate: { height: "auto", opacity: 1 },
                  exit: { height: 0, opacity: 0 },
                  transition: { duration: 0.26, ease: [0.16, 1, 0.3, 1] as const },
                })}
            className="overflow-hidden"
            /* Announced politely, and only the step labels — a per-token live region
               would make a screen reader unusable during streaming (docs/07 §3.8). */
            aria-live="polite"
          >
            <div
              className={cn(
                "mt-xs space-y-xxs border-l pl-sm",
                running ? "border-brand-green-dark/40" : "border-border-soft",
              )}
            >
              {steps.map((step, index) => (
                <motion.li
                  key={`${step.node}-${index}`}
                  {...row(index)}
                  data-testid="trail-step"
                  className={cn(
                    "text-caption",
                    running && index === steps.length - 1
                      ? "text-brand-green-dark"
                      : "text-text-tertiary",
                  )}
                >
                  {step.label}
                </motion.li>
              ))}
              {grouped.map((tool, index) => {
                const busy = tool.name === openTool;
                return (
                  <motion.li
                    key={tool.name}
                    {...row(steps.length + index)}
                    data-testid="trail-tool"
                    data-calls={tool.calls}
                    className={cn(
                      "flex items-center gap-xxs rounded-xs px-xxs font-mono text-micro",
                      // The open call is highlighted; the finished ones recede. Without
                      // this every row looks equally live and the eye has nothing to
                      // land on while a long investigation runs.
                      busy
                        ? "bg-brand-green-soft/60 text-brand-green-dark"
                        : "text-text-tertiary",
                    )}
                  >
                    {busy ? (
                      <Loader2
                        className="size-3 shrink-0 animate-spin text-brand-green-dark motion-reduce:animate-none"
                        aria-hidden
                      />
                    ) : tool.ok ? (
                      <Check className="size-3 shrink-0 text-semantic-positive" aria-hidden />
                    ) : (
                      <X className="size-3 shrink-0 text-semantic-danger" aria-hidden />
                    )}
                    <span className="truncate">
                      {tool.name}
                      {tool.args_summary ? ` (${tool.args_summary})` : ""}
                    </span>
                    {/* The count only appears when it says something. "×1" is noise. */}
                    {tool.calls > 1 && (
                      <span
                        className="ml-auto shrink-0 rounded-full bg-surface-soft px-[5px] text-micro text-text-secondary"
                        title={`Called ${tool.calls} times`}
                      >
                        ×{tool.calls}
                      </span>
                    )}
                  </motion.li>
                );
              })}
            </div>
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}
