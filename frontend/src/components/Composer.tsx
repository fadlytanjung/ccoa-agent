/**
 * The message box — docs/07 §3.2, docs/21 §5.
 *
 * It has two jobs, and which one it is doing depends on the graph.
 *
 * Normally it sends a message. **While a `clarify` or `steer` checkpoint is open it
 * answers that instead**, because the graph is suspended on an `interrupt()` and a new
 * message cannot move it — that is what "human-in-the-loop is conversational, not a single
 * gate" means in practice (docs/05 §3.7). Before this, typing here during a checkpoint
 * posted to `/messages` on a blocked thread.
 *
 * `approve` and `confirm` deliberately do **not** work this way. Those are decisions with
 * consequences — a ticket gets written — and they need the explicit control on the card.
 * Typing "yes" must never approve a write.
 *
 * Mobile-first, which here means three specific things:
 *
 * * the textarea grows with its content instead of being resized by a drag handle no
 *   touch device has;
 * * `pb-[env(safe-area-inset-bottom)]` keeps the send button clear of the iOS home
 *   indicator, which otherwise sits directly on top of it;
 * * the font size stays at 16px, because iOS Safari zooms the whole page when a focused
 *   input is any smaller — and never zooms back out.
 */
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowUp, CornerDownLeft } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { AnswerKind } from "../api/types";

interface Props {
  disabled: boolean;
  onSend: (content: string) => void;
  /** Set while a checkpoint is open that free text can answer. */
  answering?: AnswerKind | null;
  onAnswer?: (kind: AnswerKind, text: string) => void;
}

const MAX_HEIGHT_PX = 160;

export function Composer({ disabled, onSend, answering = null, onAnswer }: Props) {
  const [value, setValue] = useState("");
  const field = useRef<HTMLTextAreaElement>(null);

  // Reset before measuring: scrollHeight only ever grows against a fixed height, so
  // without this the box can expand but never shrink again.
  useEffect(() => {
    const node = field.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, MAX_HEIGHT_PX)}px`;
  }, [value]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const content = value.trim();
    if (!content || disabled) return;
    if (answering && onAnswer) onAnswer(answering, content);
    else onSend(content);
    setValue("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends, Shift+Enter breaks the line. An agent on a call types fast and should
    // not have to reach for a button.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit(event);
    }
  };

  return (
    <form
      onSubmit={submit}
      data-answering={answering ?? undefined}
      className="shrink-0 border-t border-border bg-background px-md pt-sm pb-[max(var(--space-sm),env(safe-area-inset-bottom))]"
    >
      {answering && (
        <p className="mx-auto mb-xxs flex w-full max-w-[46rem] items-center gap-xxs text-caption text-brand-green-dark">
          <CornerDownLeft className="size-3.5 shrink-0" aria-hidden />
          Replying to the assistant&rsquo;s question
        </p>
      )}
      <div
        className={cn(
          "mx-auto flex w-full max-w-[46rem] items-end gap-xs rounded-xl border bg-card p-xs focus-within:ring-2 focus-within:ring-ring/30",
          // Tinted while it is answering a checkpoint, so it is obvious that Enter
          // resolves the question rather than starting a new turn.
          answering ? "border-ring" : "border-border-strong focus-within:border-ring",
        )}
      >
        <textarea
          ref={field}
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          disabled={disabled}
          aria-label={answering ? "Answer the assistant's question" : "Message"}
          placeholder={
            disabled
              ? "Waiting for the assistant…"
              : answering
                ? "Answer the question above…"
                : "Ask about a customer…"
          }
          data-testid="composer-input"
          className="max-h-40 flex-1 resize-none bg-transparent px-xs py-[10px] text-body text-foreground outline-none placeholder:text-muted-foreground disabled:opacity-60"
        />
        <Button
          type="submit"
          size="icon"
          disabled={disabled || !value.trim()}
          data-testid="composer-send"
          aria-label={answering ? "Send answer" : "Send message"}
        >
          <ArrowUp />
        </Button>
      </div>
      <p className="mx-auto mt-xxs max-w-[46rem] text-micro text-text-tertiary">
        The assistant interprets records; it does not replace them. Check the sources
        before acting.
      </p>
    </form>
  );
}
