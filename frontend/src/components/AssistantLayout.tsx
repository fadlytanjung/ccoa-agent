/**
 * The workspace — docs/07 §3.2, docs/21 §5.
 *
 * **Mobile-first, and transformed by task priority rather than by squeezing.** The
 * responsive guideline is explicit that three columns must not simply be narrowed until
 * they fit, so:
 *
 * | width     | composition                                                   |
 * |-----------|---------------------------------------------------------------|
 * | `< lg`    | the conversation, full width; threads and context are sheets   |
 * | `>= lg`   | thread rail + conversation + context panel                     |
 *
 * The conversation is the primary task at every width, so it is the region that never
 * moves. The two rails are supporting context and become sheets reached from the header.
 *
 * **The thread lives in the URL** (`/threads/:threadId`). That makes a conversation
 * addressable — bookmarkable, reopenable after a crash, shareable with a colleague — and
 * it removes a whole class of bug: selection is no longer a piece of state that an
 * asynchronous list refresh can race, because the router owns it.
 */
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { AppHeader } from "./AppHeader";
import { Composer } from "./Composer";
import { ContextPanel } from "./ContextPanel";
import { MessageList } from "./MessageList";
import { ThreadSidebar } from "./ThreadSidebar";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { api } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { useConversation } from "../hooks/useConversation";
import { DESKTOP_QUERY, useMediaQuery } from "../hooks/useMediaQuery";
import type { AnswerKind } from "../api/types";

export function AssistantLayout() {
  const { threadId = null } = useParams<{ threadId: string }>();
  const navigate = useNavigate();
  // Each panel is mounted once, in whichever region currently holds it. Rendering both
  // and hiding one with CSS would fetch every record twice and leave two elements
  // answering to the same test id.
  const isDesktop = useMediaQuery(DESKTOP_QUERY);
  const { session } = useAuth();
  const [highlight, setHighlight] = useState<string | null>(null);
  const [threadsOpen, setThreadsOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);

  const { state, send, respond, ready } = useConversation(threadId);
  const queryClient = useQueryClient();

  /**
   * Typing is how a conversation starts — no "New conversation" click first.
   *
   * The composer is live on the empty screen. Sending from there creates the thread,
   * puts its id in the URL, and delivers the message, in that order. The message has to
   * be held while that happens: `useConversation` is keyed by the thread id, and its
   * `/state` load resolves *after* the navigation and resets the reducer — so a message
   * sent before `ready` would be wiped by the reset a moment later.
   */
  const queued = useRef<string | null>(null);
  const [starting, setStarting] = useState(false);

  const startConversation = async (content: string) => {
    queued.current = content;
    setStarting(true);
    try {
      const thread = await api.createThread();
      await queryClient.invalidateQueries({ queryKey: ["threads"] });
      navigate(`/threads/${thread.thread_id}`);
    } catch {
      queued.current = null;
      setStarting(false);
    }
  };

  useEffect(() => {
    if (!ready || !queued.current) return;
    const content = queued.current;
    queued.current = null;
    setStarting(false);
    void send(content);
  }, [ready, send]);

  // The backend titles a thread from its first message, so the row the sidebar drew at
  // creation time says "New conversation" until something refetches it. Refreshing when a
  // turn settles is what makes the title appear — and it also picks up `updated_at`, which
  // is the sort key, so the active conversation moves to the top where it belongs.
  useEffect(() => {
    if (state.status === "complete" || state.status === "interrupted") {
      void queryClient.invalidateQueries({ queryKey: ["threads"] });
    }
  }, [state.status, queryClient]);

  const handleSend = (content: string) => {
    if (threadId) void send(content);
    else void startConversation(content);
  };

  const goToThread = (id: string) => navigate(`/threads/${id}`);

  // The subject follows the conversation: once the graph resolves a customer, the
  // context panel fills in without the agent asking for it.
  const snapshot = useQuery({
    queryKey: ["thread-state", threadId, state.turns.length, state.status],
    queryFn: () => api.threadState(threadId!),
    enabled: Boolean(threadId),
  });
  const subject = snapshot.data?.subject_customer_id ?? null;

  const canApprove =
    state.pending?.kind !== "approve" || (session?.groups.includes("agent") ?? false);

  // Only `clarify` and `steer` can be answered by typing. `approve` and `confirm` are
  // decisions with consequences and need the explicit control on the card.
  const answering: AnswerKind | null =
    !state.decided && (state.pending?.kind === "clarify" || state.pending?.kind === "steer")
      ? state.pending.kind
      : null;

  // Opening the context panel is how a phone user checks a citation, so a chip tap has
  // to open it — otherwise it silently highlights a record behind a closed sheet.
  const focusRef = (refId: string) => {
    setHighlight(refId);
    setContextOpen(true);
  };

  return (
    <div className="flex h-full flex-col bg-background">
      <AppHeader
        subjectId={subject}
        showPanelToggles={!isDesktop}
        onOpenThreads={() => setThreadsOpen(true)}
        onOpenContext={() => setContextOpen(true)}
      />

      <div className="flex min-h-0 flex-1">
        {isDesktop && <ThreadSidebar activeId={threadId} onNavigate={goToThread} />}

        {/* `min-h-0` as well as `min-w-0`: a flex item defaults to `min-height: auto`,
            which lets it grow to fit its content instead of clipping — so the message
            list inside it never becomes the scroller. */}
        <main className="flex min-h-0 min-w-0 flex-1 flex-col">
          <MessageList
            state={state}
            canApprove={canApprove}
            onRespond={respond}
            onFocusRef={focusRef}
          />
          <Composer
            // Deliberately not gated on `threadId`: with no conversation open, typing is
            // what creates one. A checkpoint still suspends the graph, so the composer
            // either answers the question or is disabled — it never posts into a blocked
            // thread.
            disabled={
              starting ||
              state.streaming ||
              (state.pending !== null && !state.decided && answering === null)
            }
            answering={answering}
            onAnswer={(kind, text) => respond({ kind, text })}
            onSend={handleSend}
          />
        </main>

        {isDesktop && <ContextPanel customerId={subject} highlightRef={highlight} />}
      </div>

      {!isDesktop && (
        <>
          <Sheet open={threadsOpen} onOpenChange={setThreadsOpen}>
            <SheetContent side="left" title="Conversations">
              <ThreadSidebar
                activeId={threadId}
                onNavigate={goToThread}
                onAfterSelect={() => setThreadsOpen(false)}
              />
            </SheetContent>
          </Sheet>

          <Sheet open={contextOpen} onOpenChange={setContextOpen}>
            <SheetContent
              side="right"
              title="Customer context"
              description="Policies, cases, and recent contacts for the customer in this conversation."
            >
              <ContextPanel customerId={subject} highlightRef={highlight} />
            </SheetContent>
          </Sheet>
        </>
      )}
    </div>
  );
}
