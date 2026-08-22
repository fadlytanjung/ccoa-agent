/**
 * Assistant prose — docs/21 §5.
 *
 * The agent writes Markdown: headings for sections, bold for field names, backticks for
 * record ids. Rendering that as plain text put `### Policies` and `**Motor**` on screen
 * verbatim, which reads as a bug in the agent rather than in the view.
 *
 * Two constraints shape the implementation:
 *
 * * **No raw HTML.** `react-markdown` ignores embedded HTML unless `rehype-raw` is added,
 *   and it is deliberately not added. The content is model output built from customer
 *   records; treating it as markup would be an injection path straight through the CSP.
 * * **Tokens, not a prose plugin.** Every element maps to the same typography and colour
 *   tokens the rest of the interface uses, so assistant text sits at the same scale as
 *   the surrounding UI instead of importing a second type system.
 */
import { useMemo, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { RecordBadge } from "./RecordBadge";
import { recordKind } from "@/lib/records";

const COMPONENTS: Components = {
  p: ({ children }) => (
    <p className="text-body-sm text-foreground">{withBadges(children)}</p>
  ),
  // Headings inside a message are section labels, not page structure — they render at
  // label scale so a model that reaches for `#` cannot out-shout the page's real h1.
  h1: ({ children }) => (
    <p className="mt-xs text-micro-uppercase text-text-tertiary">{children}</p>
  ),
  h2: ({ children }) => (
    <p className="mt-xs text-micro-uppercase text-text-tertiary">{children}</p>
  ),
  h3: ({ children }) => (
    <p className="mt-xs text-micro-uppercase text-text-tertiary">{children}</p>
  ),
  h4: ({ children }) => (
    <p className="mt-xs text-micro-uppercase text-text-tertiary">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="list-disc space-y-xxs pl-md text-body-sm text-foreground marker:text-text-tertiary">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="list-decimal space-y-xxs pl-md text-body-sm text-foreground marker:text-text-tertiary">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="text-body-sm">{withBadges(children)}</li>,
  strong: ({ children }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  em: ({ children }) => <em className="italic text-text-secondary">{children}</em>,
  // Record ids arrive in backticks. One that is recognisably an identifier becomes a
  // coloured badge rather than another run of grey monospace, so the agent can pick the
  // policy out of a paragraph that also names a customer and two cases. Anything else in
  // backticks is ordinary inline code and stays that way.
  code: ({ children }) => {
    const text = typeof children === "string" ? children : null;
    if (text && recordKind(text)) return <RecordBadge value={text} />;
    return (
      <code className="rounded-xs bg-surface-soft px-[3px] py-[1px] font-mono text-micro text-foreground">
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="overflow-x-auto rounded-md bg-surface-soft p-sm font-mono text-micro text-foreground">
      {children}
    </pre>
  ),
  a: ({ children, href }) => (
    <a
      href={href}
      // Model-authored links are untrusted: no referrer, no window handle back.
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="text-brand-green-dark underline underline-offset-2"
    >
      {children}
    </a>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-border pl-sm text-body-sm text-text-secondary">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="border-border-soft" />,
  // A wide table must scroll inside its own box; the page itself never scrolls sideways.
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-body-sm">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border-b border-border px-xs py-xxs text-left text-caption-bold text-text-secondary">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border-b border-border-soft px-xs py-xxs align-top">
      {withBadges(children)}
    </td>
  ),
};

/**
 * Identifiers the model wrote as bare words rather than in backticks.
 *
 * It is inconsistent about this, and an id is an id either way. Applied to text nodes
 * only — never to a URL or a code block, where a substitution would corrupt the content.
 */
function badgeBareIds(node: ReactNode): ReactNode {
  if (typeof node !== "string") return node;
  const parts = node.split(/\b((?:CUST|POL|CLM|CASE|TCK|INT|KB|REF)-[A-Z0-9]+)\b/g);
  if (parts.length === 1) return node;
  return parts.map((part, index) =>
    index % 2 === 1 ? <RecordBadge key={`${part}-${index}`} value={part} /> : part,
  );
}

function withBadges(children: ReactNode): ReactNode {
  if (Array.isArray(children)) return children.map(badgeBareIds);
  return badgeBareIds(children);
}

export function Markdown({ children }: { children: string }) {
  // `components` is stable, but memoising the parse keeps a long answer from re-rendering
  // on every token of the *next* one.
  const rendered = useMemo(
    () => (
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
    ),
    [children],
  );
  return <div className="space-y-xs">{rendered}</div>;
}

