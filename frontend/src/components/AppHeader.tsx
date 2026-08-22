/**
 * Global header — docs/07 §3.2, docs/21 §5.
 *
 * On a phone this bar is also the navigation: the thread list and the context panel are
 * rails on a wide screen and sheets here, and these two buttons are the only way into
 * them. They are hidden once both rails are permanently visible, where a button that
 * opens something already on screen is noise rather than navigation.
 *
 * Identity and sign-out are **not** here. They live at the foot of the thread rail, which
 * is where this shape of tool puts them and where people look for them — and it keeps a
 * destructive action out of the one bar visible at every width, a mis-tap away from the
 * panel toggles.
 */
import { PanelLeft, PanelRight } from "lucide-react";

import { BrandMark } from "./Brand";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuth } from "../auth/useAuth";

interface Props {
  subjectId: string | null;
  /** False once both rails are permanently visible. */
  showPanelToggles: boolean;
  onOpenThreads: () => void;
  onOpenContext: () => void;
}

export function AppHeader({
  subjectId,
  showPanelToggles,
  onOpenThreads,
  onOpenContext,
}: Props) {
  const { config } = useAuth();

  return (
    <header className="flex h-(--header-height) shrink-0 items-center gap-sm border-b border-border bg-background px-md">
      {showPanelToggles && (
        <Button
          variant="ghost"
          size="icon"
          onClick={onOpenThreads}
          aria-label="Open conversations"
          data-testid="open-threads"
        >
          <PanelLeft />
        </Button>
      )}

      <div className="flex min-w-0 items-center gap-sm">
        <BrandMark className="size-9" />
        <span className="min-w-0">
          {/* The product name is the page's h1 on every route — the one heading that is
              always correct, and what screen-reader users navigate by. */}
          <h1 className="truncate text-body-medium text-foreground">CCOA Assistant</h1>
          <span className="block truncate text-micro text-text-tertiary">
            Contact centre operations
          </span>
        </span>
      </div>

      {/* No conversation title here. It duplicated the sidebar, which already shows which
          thread is current and shows it better — and "New conversation" as a header for a
          conversation you are already reading is noise dressed as information. */}

      <div className="ml-auto flex items-center gap-xs">
        {config?.auth_mode === "dev" && (
          <Badge
            tone="warning"
            data-testid="dev-badge"
            title="Authentication is bypassed. Local development only."
          >
            dev auth
          </Badge>
        )}
        {showPanelToggles && (
          <Button
            variant="ghost"
            size="icon"
            onClick={onOpenContext}
            aria-label="Open customer context"
            data-testid="open-context"
            className="relative"
          >
            <PanelRight />
            {/* A dot rather than a number: the panel's job is "there is a record behind
                this answer", and a count would imply a precision it does not have. */}
            {subjectId && (
              <span className="absolute right-1.5 top-1.5 size-2 rounded-full bg-primary" />
            )}
          </Button>
        )}
      </div>
    </header>
  );
}
