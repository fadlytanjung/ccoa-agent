/**
 * The records behind the answer — docs/07 §3.2, docs/21 §5.
 *
 * This panel is what makes the product an operations tool rather than a chatbot: the
 * agent can verify the assistant's claims against the same records, side by side, without
 * leaving the conversation. Its content is *verified data*, which is why it is styled as
 * plain bordered cards on the reading surface while the assistant's own output is visibly
 * an interpretation.
 *
 * A citation chip focuses the record it points at, so "where did that come from" is one
 * tap rather than a search.
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { FileText, Inbox, Phone, ShieldCheck, UserRound } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "../api/client";
import { cn } from "@/lib/utils";

interface Props {
  customerId: string | null;
  highlightRef: string | null;
}

function money(cents: number, currency: string): string {
  return new Intl.NumberFormat("en-SG", { style: "currency", currency }).format(cents / 100);
}

function Section({
  icon: Icon,
  title,
  count,
  children,
}: {
  icon: typeof UserRound;
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-xs">
      <h3 className="flex items-center gap-xxs text-micro-uppercase text-text-tertiary">
        <Icon className="size-3.5" aria-hidden />
        {title}
        {count !== undefined && <span className="text-text-tertiary">({count})</span>}
      </h3>
      {children}
    </section>
  );
}

/** A record card that scrolls itself into view when a citation points at it. */
function RecordCard({
  highlighted,
  testId,
  children,
}: {
  highlighted: boolean;
  testId: string;
  children: React.ReactNode;
}) {
  const node = useRef<HTMLLIElement>(null);
  useEffect(() => {
    if (highlighted) node.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [highlighted]);

  return (
    <li
      ref={node}
      data-testid={testId}
      className={cn(
        "rounded-md border bg-card px-sm py-xs transition-colors duration-(--motion-interactive)",
        highlighted ? "border-ring bg-surface-feature" : "border-border",
      )}
    >
      {children}
    </li>
  );
}

export function ContextPanel({ customerId, highlightRef }: Props) {
  const enabled = Boolean(customerId);
  const profile = useQuery({
    queryKey: ["customer", customerId],
    queryFn: () => api.customer(customerId!),
    enabled,
  });
  const cases = useQuery({
    queryKey: ["cases", customerId],
    queryFn: () => api.cases(customerId!),
    enabled,
  });
  const interactions = useQuery({
    queryKey: ["interactions", customerId],
    queryFn: () => api.interactions(customerId!, 5),
    enabled,
  });

  const isHighlighted = (id: string) => highlightRef?.endsWith(id) ?? false;

  return (
    <aside
      aria-label="Customer context"
      data-testid="context-panel"
      className="h-full space-y-lg overflow-y-auto bg-surface p-md lg:w-(--context-width) lg:shrink-0 lg:border-l lg:border-border"
    >
      {!enabled && (
        <div className="flex flex-col items-center gap-xs pt-2xl text-center">
          <Inbox className="size-6 text-text-tertiary" aria-hidden />
          <p className="max-w-[16rem] text-caption text-text-tertiary">
            Once a customer is identified, their policies, cases, and recent contacts
            appear here.
          </p>
        </div>
      )}

      {enabled && profile.isPending && (
        <div className="space-y-xs">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-16 w-full" />
        </div>
      )}

      {profile.data && (
        <section data-testid="customer-card" className="space-y-xxs">
          <p className="font-mono text-micro text-text-tertiary">
            {profile.data.customer.customer_id}
          </p>
          <h2 className="flex items-center gap-xs text-heading-5 text-foreground">
            <UserRound className="size-4 text-text-tertiary" aria-hidden />
            {profile.data.customer.full_name}
          </h2>
          <div className="flex flex-wrap items-center gap-xxs pt-xxs">
            <Badge tone="brand">{profile.data.customer.tier}</Badge>
            <Badge
              tone={profile.data.customer.status === "active" ? "positive" : "unknown"}
            >
              {profile.data.customer.status}
            </Badge>
            {/* A risk flag is a warning, and warnings never rely on colour alone. */}
            {profile.data.customer.risk_flag && (
              <Badge tone="warning">
                <ShieldCheck className="size-3" aria-hidden />
                Risk flagged
              </Badge>
            )}
          </div>
          <p className="text-caption text-text-tertiary">{profile.data.customer.city}</p>
        </section>
      )}

      {profile.data && profile.data.policies.length > 0 && (
        <Section icon={ShieldCheck} title="Policies" count={profile.data.policies.length}>
          <ul className="space-y-xxs">
            {profile.data.policies.map((policy) => (
              <RecordCard
                key={policy.policy_id}
                testId="policy-item"
                highlighted={isHighlighted(policy.policy_id)}
              >
                <span className="block font-mono text-micro text-text-tertiary">
                  {policy.policy_id}
                </span>
                <span className="block text-body-sm-medium text-foreground">
                  {policy.product}
                </span>
                <span className="text-caption text-text-secondary">
                  {policy.status} · {money(policy.premium_cents, policy.currency)}
                </span>
              </RecordCard>
            ))}
          </ul>
        </Section>
      )}

      {cases.data && cases.data.length > 0 && (
        <Section icon={FileText} title="Cases" count={cases.data.length}>
          <ul className="space-y-xxs">
            {cases.data.slice(0, 4).map((item) => (
              <RecordCard
                key={item.case_id}
                testId="case-item"
                highlighted={isHighlighted(item.case_id)}
              >
                <span className="block font-mono text-micro text-text-tertiary">
                  {item.case_id}
                </span>
                <span className="block text-body-sm text-foreground">{item.title}</span>
                <span className="text-caption text-text-secondary">
                  {item.status} · {item.priority}
                </span>
              </RecordCard>
            ))}
          </ul>
        </Section>
      )}

      {interactions.data && interactions.data.length > 0 && (
        <Section icon={Phone} title="Recent contacts">
          <ul className="space-y-xxs">
            {interactions.data.map((item) => (
              <RecordCard
                key={item.interaction_id}
                testId="interaction-item"
                highlighted={isHighlighted(item.interaction_id)}
              >
                <span className="block text-caption text-text-tertiary">
                  {item.occurred_at.slice(0, 10)} · {item.channel}
                </span>
                <span className="block text-body-sm text-foreground">{item.subject}</span>
              </RecordCard>
            ))}
          </ul>
        </Section>
      )}
    </aside>
  );
}
