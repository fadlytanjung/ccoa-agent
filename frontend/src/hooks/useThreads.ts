/**
 * The conversation list — docs/06 §3.2, docs/07 §3.10.
 *
 * Its own module so both the sidebar and the workspace can read the same cache without
 * either importing the other, and so neither file mixes a hook export with a component
 * export (which disables Fast Refresh for the whole file).
 */
import { useMemo } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { ThreadSummary } from "../api/types";

export function useThreadPages() {
  return useInfiniteQuery({
    queryKey: ["threads"],
    queryFn: ({ pageParam }: { pageParam: string | null }) => api.listThreads(pageParam),
    initialPageParam: null as string | null,
    // Stop on a null cursor, never on a short page: under a keyset scheme a full page
    // can still be the last one, and a short page can still have a successor.
    getNextPageParam: (last) => last.next_cursor,
  });
}

/**
 * The pages flattened into one list, with a stable identity.
 *
 * `pages.flatMap(...)` allocates a new array on every render, so an effect that depends
 * on it re-runs every render — which for the "open the newest conversation" effect means
 * a navigation attempt per frame.
 */
export function useThreadItems(): { items: ThreadSummary[]; isSuccess: boolean } {
  const query = useThreadPages();
  const pages = query.data?.pages;
  const items = useMemo(() => pages?.flatMap((page) => page.items) ?? [], [pages]);
  return { items, isSuccess: query.isSuccess };
}
