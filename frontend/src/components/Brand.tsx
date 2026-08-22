import { cn } from "@/lib/utils";

/**
 * The CCOA mark — docs/21 §3.
 *
 * A speech bubble whose three dots double as the assistant's "thinking" indicator, drawn
 * in the brand green on deep teal. Inline SVG rather than an `<img>`: it inherits colour
 * from the surface it sits on, needs no second request, and cannot be blocked by the CSP.
 */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      className={cn("size-8 shrink-0", className)}
      role="img"
      aria-label="CCOA"
    >
      <rect width="32" height="32" rx="8" className="fill-brand-teal-deep" />
      <path
        d="M9 20.5V13a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v4a4 4 0 0 1-4 4h-6l-4 3.5z"
        fill="none"
        className="stroke-brand-green"
        strokeWidth="2.2"
        strokeLinejoin="round"
      />
      <circle cx="16" cy="15" r="1.6" className="fill-brand-green" />
      <circle cx="21" cy="15" r="1.6" className="fill-brand-green" opacity="0.55" />
      <circle cx="11" cy="15" r="1.6" className="fill-brand-green" opacity="0.55" />
    </svg>
  );
}
