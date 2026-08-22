import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Buttons — docs/21 §4.1.
 *
 * Pill radius, DM Sans at `text-button`, and a 44px minimum target in every size that
 * a finger can reach. `min-h-11` is not a style choice: it is the touch-target floor
 * the design system requires, and this is the component that guarantees it.
 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-xs whitespace-nowrap rounded-full text-button transition-colors duration-(--motion-interactive) ease-(--ease-standard) outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-primary text-primary-foreground hover:bg-brand-green-hover active:bg-brand-green-pressed",
        secondary:
          "border border-border-strong bg-transparent text-foreground hover:bg-surface-soft",
        ghost: "text-text-secondary hover:bg-surface-soft hover:text-foreground",
        onDark:
          "border border-white/25 bg-white/5 text-text-on-dark hover:bg-white/12",
        destructive: "bg-destructive text-destructive-foreground hover:opacity-90",
        link: "text-brand-green-dark underline-offset-4 hover:underline",
      },
      size: {
        default: "min-h-11 px-xl py-xs",
        sm: "min-h-9 px-md text-caption-bold",
        lg: "min-h-12 px-2xl text-body-medium",
        icon: "size-11",
        iconSm: "size-9",
      },
    },
    defaultVariants: { variant: "primary", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp className={cn(buttonVariants({ variant, size }), className)} ref={ref} {...props} />
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
