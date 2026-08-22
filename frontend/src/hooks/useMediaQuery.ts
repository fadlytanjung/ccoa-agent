/**
 * Viewport-driven rendering — docs/21 §5.
 *
 * Tailwind's `hidden lg:block` is the usual way to do this and is the wrong tool when the
 * two branches are *components* rather than decoration: both branches stay mounted, so
 * the thread list and the customer profile are fetched twice, two elements answer to the
 * same `data-testid`, and a phone pays to render a desktop rail it will never show.
 *
 * Matching on the media query instead means each panel is mounted exactly once, wherever
 * it currently belongs.
 */
import { useEffect, useState } from "react";

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);

  useEffect(() => {
    const list = window.matchMedia(query);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    // Re-read on subscribe: the viewport can change between the initial render and this
    // effect (a rotation, or a devtools resize), and that would otherwise stick.
    setMatches(list.matches);
    list.addEventListener("change", onChange);
    return () => list.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

/** The one breakpoint the workspace actually changes shape at (Tailwind's `lg`). */
export const DESKTOP_QUERY = "(min-width: 1024px)";
