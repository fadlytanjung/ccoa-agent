/**
 * The agent's conversations — docs/07 §3.2, §3.10.
 *
 * Each row is a real `<Link>` to `/threads/:threadId`, not a button that mutates state.
 * That is what makes a conversation addressable: it can be bookmarked, reopened after a
 * crash, and pasted to a colleague — and the browser's back button behaves the way the
 * agent expects instead of leaving the app.
 *
 * The list is **cursor-paginated** (docs/06 §3.2). It loads a page at a time rather than
 * everything at once, because the sort key is "last activity" and that changes under the
 * reader: see `ThreadRepository.page_for_owner` for why an offset would drop rows here.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { LogOut, MessageSquarePlus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "../api/client";
import { useAuth } from "../auth/useAuth";
import { cn, relativeTime } from "@/lib/utils";
import { useThreadPages } from "../hooks/useThreads";
import type { ThreadSummary } from "../api/types";

interface Props {
  activeId: string | null;
  onNavigate: (id: string) => void;
  /** Closes the sheet on a phone; a no-op when the rail is permanently visible. */
  onAfterSelect?: () => void;
}

export function ThreadSidebar({ activeId, onNavigate, onAfterSelect }: Props) {
  const queryClient = useQueryClient();
  const threads = useThreadPages();
  const { session, signOut, config } = useAuth();

  const create = useMutation({
    mutationFn: () => api.createThread(),
    onSuccess: async (thread) => {
      await queryClient.invalidateQueries({ queryKey: ["threads"] });
      onNavigate(thread.thread_id);
      onAfterSelect?.();
    },
  });

  const items: ThreadSummary[] = threads.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <nav
      aria-label="Conversations"
      className="flex h-full min-h-0 flex-col bg-surface lg:w-(--rail-width) lg:shrink-0 lg:border-r lg:border-border"
    >
      <div className="p-sm">
        <Button
          className="w-full"
          onClick={() => create.mutate()}
          disabled={create.isPending}
          data-testid="new-thread"
        >
          <MessageSquarePlus />
          New conversation
        </Button>
      </div>

      <ul
        className="min-h-0 flex-1 space-y-xxs overflow-y-auto px-xs pb-md"
        data-testid="thread-list"
      >
        {threads.isPending &&
          [0, 1, 2, 3].map((row) => (
            <li key={row} className="px-xs py-xxs">
              <Skeleton className="h-10 w-full" />
            </li>
          ))}

        {items.map((thread) => {
          const active = thread.thread_id === activeId;
          return (
            <li key={thread.thread_id}>
              <Link
                to={`/threads/${thread.thread_id}`}
                onClick={onAfterSelect}
                aria-current={active ? "true" : undefined}
                data-testid="thread-item"
                className={cn(
                  "flex min-h-11 flex-col justify-center gap-[2px] rounded-md px-sm py-xs transition-colors duration-(--motion-interactive)",
                  active
                    ? "bg-surface-feature text-foreground"
                    : "text-text-secondary hover:bg-surface-soft hover:text-foreground",
                )}
              >
                <span className="flex items-center gap-xs">
                  <span className="truncate text-body-sm-medium">{thread.title}</span>
                  <span className="ml-auto shrink-0 text-micro text-text-tertiary">
                    {relativeTime(thread.updated_at)}
                  </span>
                </span>
                {thread.subject_customer_id && (
                  <span className="truncate font-mono text-micro text-text-tertiary">
                    {thread.subject_customer_id}
                  </span>
                )}
              </Link>
            </li>
          );
        })}

        {threads.isSuccess && items.length === 0 && (
          <li className="px-sm py-xs text-caption text-text-tertiary">
            No conversations yet.
          </li>
        )}

        {threads.hasNextPage && (
          <li className="px-xs pt-xs">
            <Button
              variant="secondary"
              size="sm"
              className="w-full"
              onClick={() => void threads.fetchNextPage()}
              disabled={threads.isFetchingNextPage}
              data-testid="load-more-threads"
            >
              {threads.isFetchingNextPage ? "Loading…" : "Load older"}
            </Button>
          </li>
        )}
      </ul>

      {/*
        The account block. It lives at the foot of the rail rather than in the header for
        two reasons: it is where every tool of this shape puts it, so it is where people
        look; and the header is the one bar visible at every width, which makes it the
        wrong place for a destructive action sitting one mis-tap from the panel toggles.

        `mt-auto` plus a border is what separates it from the history — without the gap
        the last conversation and the sign-out button read as one list, which is how you
        end up signing out while trying to open a thread.
      */}
      <div className="mt-auto shrink-0 border-t border-border bg-surface p-sm">
        <div className="flex items-center gap-xs">
          <span
            aria-hidden
            className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-teal-deep text-caption-bold text-text-on-dark"
          >
            {(session?.email ?? "?").slice(0, 1).toUpperCase()}
          </span>
          <span className="min-w-0 flex-1">
            <span
              className="block truncate text-body-sm-medium text-foreground"
              data-testid="account-email"
              title={session?.email}
            >
              {session?.email ?? "Not signed in"}
            </span>
            <span className="block truncate text-micro text-text-tertiary">
              {session?.groups.join(" · ") || "no groups"}
            </span>
          </span>
        </div>

        <Button
          variant="secondary"
          size="sm"
          className="mt-xs w-full"
          onClick={signOut}
          data-testid="sign-out"
        >
          <LogOut />
          Sign out
        </Button>

        {config?.auth_mode === "dev" && (
          // Sign-out is a real control in dev too — it drops the local session — but it
          // cannot end a Cognito session that was never started. Saying so beats a button
          // that appears to do nothing.
          <p className="mt-xxs text-micro text-text-tertiary">
            Development sign-in — no identity provider is involved.
          </p>
        )}
      </div>
    </nav>
  );
}
