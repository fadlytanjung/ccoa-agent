import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * The composite typography classes (`text-heading-1`, `text-button`, …) set font size,
 * weight, and line height — but **not** colour. Stock tailwind-merge sees `text-*` and
 * assumes a colour, so `cn("text-button", "text-text-on-dark")` drops one of them at
 * random depending on order. Registering them in the `font-size` group gives the right
 * behaviour on both counts: a later type class replaces an earlier one, and a colour
 * class applied alongside survives.
 */
const TYPOGRAPHY = [
  "heading-1",
  "heading-2",
  "heading-3",
  "heading-4",
  "heading-5",
  "subtitle",
  "body",
  "body-medium",
  "body-sm",
  "body-sm-medium",
  "caption",
  "caption-bold",
  "micro",
  "micro-uppercase",
  "button",
  "code",
];

const twMerge = extendTailwindMerge({
  extend: { classGroups: { "font-size": [{ text: TYPOGRAPHY }] } },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Relative time for conversation lists — "2m", "3h", "Tue". */
export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, (Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 604_800) return `${Math.floor(seconds / 86_400)}d ago`;
  return new Date(then).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
