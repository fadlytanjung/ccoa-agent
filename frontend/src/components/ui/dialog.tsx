import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Centred modal — docs/21 §4.3.
 *
 * Radix supplies focus trap, focus restore on close, `Escape`, scroll lock, and
 * `aria-modal`. On a phone it stays a dialog rather than becoming a sheet: it holds a
 * short, bounded list, and a bottom sheet would imply more content below the fold than
 * there is.
 */
const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogClose = DialogPrimitive.Close;

const DialogContent = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    title: string;
    description?: string;
  }
>(({ className, children, title, description, ...props }, ref) => (
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
        "fixed left-1/2 top-1/2 z-50 flex max-h-[85vh] w-[min(32rem,92vw)] -translate-x-1/2 -translate-y-1/2 flex-col",
        "rounded-xl border border-border bg-popover text-popover-foreground shadow-overlay",
        "duration-(--motion-reveal) data-[state=open]:animate-in data-[state=open]:zoom-in-95",
        "data-[state=closed]:animate-out data-[state=closed]:zoom-out-95",
        "motion-reduce:animate-none",
        className,
      )}
      {...props}
    >
      <div className="flex items-start justify-between gap-sm border-b border-border-soft px-md py-sm">
        <span className="min-w-0">
          <DialogPrimitive.Title className="text-heading-5 text-foreground">
            {title}
          </DialogPrimitive.Title>
          {description && (
            <DialogPrimitive.Description className="mt-xxs text-caption text-text-secondary">
              {description}
            </DialogPrimitive.Description>
          )}
        </span>
        <DialogPrimitive.Close
          className="inline-flex size-9 shrink-0 items-center justify-center rounded-full text-text-tertiary transition-colors hover:bg-surface-soft hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="Close"
        >
          <X className="size-4" />
        </DialogPrimitive.Close>
      </div>
      {/* Radix warns when a dialog has no description; when none is supplied the title
          stands in, announced but not shown. */}
      {!description && (
        <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
      )}
      <div className="min-h-0 flex-1 overflow-y-auto p-md">{children}</div>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
DialogContent.displayName = "DialogContent";

export { Dialog, DialogClose, DialogContent, DialogTrigger };
