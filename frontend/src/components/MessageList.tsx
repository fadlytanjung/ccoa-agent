/**
 * Conversation history, the live draft, and the checkpoint — docs/07 §3.3, docs/21 §6.
 *
 * The reading order the assistant-conversation pattern requires, top to bottom: what the
 * agent asked, what the assistant is doing (labelled as activity, never as evidence), the
 * answer, and the records it came from.
 *
 * Auto-scroll is conditional. Pinning the view to the bottom on every token is right
 * while the agent is watching the answer arrive and infuriating when they have scrolled
 * up to read something — so it only follows the stream when they are already near the
 * bottom.
 */
import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { AlertCircle, Sparkles } from "lucide-react";

import { ActivityTrail } from "./ActivityTrail";
import { ApprovalCard } from "./ApprovalCard";
import { CitationList } from "./CitationList";
import { Markdown } from "./Markdown";
import { cn } from "@/lib/utils";
import type { ConversationState } from "../hooks/useConversation";
import type { ResumeRequest } from "../api/types";

interface Props {
  state: ConversationState;
  canApprove: boolean;
  onRespond: (payload: ResumeRequest) => void;
  onFocusRef: (refId: string) => void;
}

/** How close to the bottom still counts as "following the stream". */
const FOLLOW_THRESHOLD_PX = 120;

const SUGGESTIONS = [
  "Show me the details for customer CUST-000042.",
  "Why did this customer's claim submission fail?",
  "Summarise the last three contacts for this customer.",
];

export function MessageList({ state, canApprove, onRespond, onFocusRef }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const [following, setFollowing] = useState(true);
  const reduced = useReducedMotion();

  useEffect(() => {
    const node = scroller.current;
    if (!node) return;
    const onScroll = () => {
      const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
      setFollowing(distance < FOLLOW_THRESHOLD_PX);
    };
    node.addEventListener("scroll", onScroll, { passive: true });
    return () => node.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!following) return;
    bottom.current?.scrollIntoView({
      behavior: reduced ? "auto" : "smooth",
      block: "end",
    });
  }, [state.turns.length, state.draft, state.pending, following, reduced]);

  const enter = reduced
    ? {}
    : {
        initial: { opacity: 0, y: 8 },
        animate: { opacity: 1, y: 0 },
        transition: { duration: 0.26, ease: [0.16, 1, 0.3, 1] as const },
      };

  const empty = state.turns.length === 0 && !state.streaming;

  return (
    <div
      ref={scroller}
      className="min-h-0 flex-1 overflow-y-auto"
      data-testid="message-list"
    >
      <div className="mx-auto flex w-full max-w-[46rem] flex-col gap-sm px-md py-lg">
        {empty && (
          <div className="mt-2xl text-center">
            <div className="mx-auto mb-md flex size-12 items-center justify-center rounded-full bg-surface-feature">
              <Sparkles className="size-5 text-brand-green-dark" />
            </div>
            <h2 className="text-heading-5 text-foreground">How can I help?</h2>
            <p className="mx-auto mt-xxs max-w-[28rem] text-body-sm text-text-secondary">
              Ask about a customer, their history, or a claim that will not submit. Every
              answer links to the records behind it.
            </p>
            <ul className="mt-lg flex flex-col items-stretch gap-xs text-left">
              {SUGGESTIONS.map((suggestion) => (
                <li key={suggestion}>
                  {/* Deliberately not clickable. The composer is one tap away, and a
                      suggestion that fires a request costs a model call for a prompt the
                      agent may not have meant to send. */}
                  <p className="rounded-md border border-border bg-surface px-sm py-xs text-body-sm text-text-secondary">
                    {suggestion}
                  </p>
                </li>
              ))}
            </ul>
          </div>
        )}

        <AnimatePresence initial={false}>
          {state.turns.map((turn) => (
            <motion.article
              key={turn.id}
              layout={!reduced}
              {...enter}
              data-testid={turn.role === "user" ? "user-message" : "assistant-message"}
              className={cn(
                turn.role === "user"
                  ? "ml-auto max-w-[85%] rounded-xl rounded-br-sm bg-brand-teal-deep px-md py-xs text-text-on-dark"
                  : "max-w-full rounded-xl rounded-bl-sm border border-border bg-card px-md py-sm text-card-foreground",
                turn.failed && "border-semantic-danger",
              )}
            >
              {/* Only the assistant's half is Markdown. What the agent typed is shown
                  exactly as typed — it is their words, not a document to interpret. */}
              {turn.role === "user" ? (
                <p className="whitespace-pre-wrap text-body-sm">{turn.content}</p>
              ) : (
                <Markdown>{turn.content}</Markdown>
              )}

              {turn.failed && (
                <p className="mt-xxs text-caption opacity-80">
                  Not delivered — try sending it again.
                </p>
              )}

              {turn.citations && turn.citations.length > 0 && (
                <div className="mt-xs border-t border-border-soft pt-xs">
                  <CitationList refs={turn.citations} onFocus={onFocusRef} />
                </div>
              )}
            </motion.article>
          ))}
        </AnimatePresence>

        <ActivityTrail activity={state.activity} running={state.streaming} />

        {/* The draft is explicitly provisional: dashed border, and a caret so a partial
            answer reads as "still arriving" rather than "truncated". The `message` event
            replaces it wholesale (see useConversation). */}
        {state.draft && (
          <article
            data-testid="draft-message"
            className="max-w-full rounded-xl rounded-bl-sm border border-dashed border-border bg-card/60 px-md py-sm"
          >
            {/* Rendered as Markdown while streaming too, so the text does not visibly
                re-flow when the canonical message replaces the draft. */}
            <div className="text-text-secondary">
              <Markdown>{state.draft}</Markdown>
            </div>
            <span className="stream-caret" aria-hidden />
          </article>
        )}

        {/* Shown only before the first token — never alongside real output, where it
            would imply work that is not happening. */}
        {state.streaming && !state.draft && !state.pending && (
          <p
            className="thinking-dots px-xs text-caption text-text-tertiary"
            data-testid="thinking"
          >
            <span />
            <span />
            <span />
            <span className="sr-only">The assistant is working.</span>
          </p>
        )}

        {state.pending && (
          <ApprovalCard
            ask={state.pending}
            decided={state.decided}
            canApprove={canApprove}
            onRespond={onRespond}
            onFocusRef={onFocusRef}
          />
        )}

        {state.error && (
          <div
            role="alert"
            data-testid="error-banner"
            className="flex items-start gap-xs rounded-md border border-semantic-danger bg-semantic-danger-bg px-sm py-xs text-semantic-danger-text"
          >
            <AlertCircle className="mt-[2px] size-4 shrink-0" />
            <div className="min-w-0">
              <p className="text-body-sm">{state.error.message}</p>
              {state.error.traceId && (
                <p className="mt-xxs font-mono text-micro opacity-80">
                  trace {state.error.traceId}
                </p>
              )}
            </div>
          </div>
        )}

        <div ref={bottom} />
      </div>
    </div>
  );
}
