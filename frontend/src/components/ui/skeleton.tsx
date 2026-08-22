import { cn } from "@/lib/utils";

/** Loading placeholder. Shaped like the content it replaces, so the layout does not jump. */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-md bg-surface-soft motion-reduce:animate-none", className)}
      {...props}
    />
  );
}
