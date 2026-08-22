import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Status badges — docs/21 §4.2.
 *
 * Every semantic variant must be given visible text, and an icon where the meaning is
 * not obvious from the words. Colour alone never carries status: that rule is why
 * `neutral` is the default rather than something tinted.
 */
const badgeVariants = cva(
  "inline-flex items-center gap-xxs rounded-full px-xs py-[3px] text-caption-bold",
  {
    variants: {
      tone: {
        neutral: "bg-surface-soft text-text-secondary",
        brand: "bg-brand-green-soft text-brand-green-dark",
        positive: "bg-semantic-positive-bg text-semantic-positive-text",
        warning: "bg-semantic-warning-bg text-semantic-warning-text",
        danger: "bg-semantic-danger-bg text-semantic-danger-text",
        unknown: "bg-semantic-unknown-bg text-semantic-unknown-text",
        onDark: "bg-white/10 text-text-on-dark",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}

export { Badge, badgeVariants };
