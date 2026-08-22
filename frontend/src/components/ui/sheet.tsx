import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Slide-over panel — docs/21 §4.3, docs/07 §3.2.
 *
 * This is what the desktop rails become below `lg`. The responsive guideline is explicit
 * that three columns must not simply be squeezed: the conversation stays the whole screen
 * on a phone, and the thread list and context panel become sheets reached from the header.
 *
 * Radix's Dialog supplies the parts that are tedious and easy to get wrong — focus trap,
 * focus restore on close, `Escape`, scroll lock, and `aria-modal` — so none of that is
 * reimplemented here.
 */
const Sheet = DialogPrimitive.Root;
const SheetTrigger = DialogPrimitive.Trigger;
const SheetClose = DialogPrimitive.Close;

const SheetContent = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    side?: "left" | "right" | "bottom";
    title: string;
    description?: string;
  }
>(({ className, children, side = "left", title, description, ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay
      className={cn(
        "fixed inset-0 z-40 bg-surface-scrim",
        "data-[state=open]:animate-in data-[state=open]:fade-in-0",
        "data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
        "motion-reduce:animate-none",
      )}
    />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed z-50 flex flex-col gap-md bg-background shadow-overlay",
        "duration-(--motion-reveal) data-[state=open]:animate-in data-[state=closed]:animate-out",
        "motion-reduce:animate-none motion-reduce:transition-none",
        side === "left" &&
          "inset-y-0 left-0 w-[min(20rem,85vw)] border-r border-border data-[state=open]:slide-in-from-left data-[state=closed]:slide-out-to-left",
        side === "right" &&
          "inset-y-0 right-0 w-[min(22rem,90vw)] border-l border-border data-[state=open]:slide-in-from-right data-[state=closed]:slide-out-to-right",
        side === "bottom" &&
          "inset-x-0 bottom-0 max-h-[85vh] rounded-t-xl border-t border-border data-[state=open]:slide-in-from-bottom data-[state=closed]:slide-out-to-bottom",
        className,
      )}
      {...props}
    >
      <div className="flex items-center justify-between border-b border-border-soft px-md py-sm">
        <DialogPrimitive.Title className="text-heading-5 text-foreground">
          {title}
        </DialogPrimitive.Title>
        <DialogPrimitive.Close
          className="inline-flex size-9 items-center justify-center rounded-full text-text-tertiary transition-colors hover:bg-surface-soft hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`Close ${title.toLowerCase()}`}
        >
          <X className="size-4" />
        </DialogPrimitive.Close>
      </div>
      {/* Radix warns when a dialog has no description; supplying one that is only ever
          announced keeps the panel labelled without adding visual noise. */}
      <DialogPrimitive.Description className="sr-only">
        {description ?? title}
      </DialogPrimitive.Description>
      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
SheetContent.displayName = "SheetContent";

export { Sheet, SheetClose, SheetContent, SheetTrigger };
