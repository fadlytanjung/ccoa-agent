/**
 * The HTTP contract, as TypeScript — docs/06.
 *
 * Hand-written for now. docs/06 §3.10 calls for generating these from the OpenAPI
 * schema in CI so a backend change the frontend has not adopted breaks the build; that
 * is tracked in docs/20 rather than quietly assumed to be done.
 */

export type AuthMode = "cognito" | "dev";

/** `GET /api/v1/config` — public, pre-login. */
export interface RuntimeConfig {
  auth_mode: AuthMode;
  environment: string;
  cognito: {
    user_pool_id: string;
    client_id: string;
    region: string;
    domain: string | null;
  };
}

export interface ThreadSummary {
  thread_id: string;
  title: string;
  subject_customer_id: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

/** `GET /api/v1/threads` — a page, plus where to continue. */
export interface ThreadListResponse {
  items: ThreadSummary[];
  /** `null` marks the last page. A short page does not, and must not be read as one. */
  next_cursor: string | null;
}

export interface MessageView {
  role: "human" | "ai";
  content: string;
}

export interface PendingAsk {
  kind: "clarify" | "confirm" | "approve" | "steer";
  question: string;
  options?: { value: string; label: string }[] | null;
  payload?: Record<string, unknown> | null;
  evidence_refs?: string[];
  skippable?: boolean;
}

/**
 * The ask kinds a free-text reply can satisfy.
 *
 * Deliberately not all four: `approve` and `confirm` are decisions with consequences and
 * need the explicit control on the card, so typing "yes" can never approve a write
 * (docs/07 §3.6a).
 */
export type AnswerKind = Extract<PendingAsk["kind"], "clarify" | "steer">;

export interface ThreadState {
  thread_id: string;
  messages: MessageView[];
  subject_customer_id: string | null;
  evidence_refs: string[];
  pending_ask: PendingAsk | null;
  intent: string | null;
}

export interface Customer {
  customer_id: string;
  full_name: string;
  email: string;
  phone: string;
  city: string;
  tier: string;
  status: string;
  risk_flag: boolean;
}

export interface Policy {
  policy_id: string;
  product: string;
  status: string;
  premium_cents: number;
  currency: string;
  effective_from: string;
}

export interface CustomerProfile {
  customer: Customer;
  policies: Policy[];
  open_case_count: number;
  recent_interaction_count: number;
}

export interface SupportCase {
  case_id: string;
  title: string;
  category: string;
  status: string;
  priority: string;
  summary: string;
  opened_at: string;
}

export interface InteractionSummary {
  interaction_id: string;
  channel: string;
  direction: string;
  subject: string;
  summary: string;
  sentiment: string;
  handled_by: string;
  occurred_at: string;
}

/** RFC 9457 problem detail — docs/06 §3.6. */
export interface ProblemDetail {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance?: string;
  trace_id?: string;
}

// --- SSE event payloads — docs/06 §3.4 -------------------------------------
export interface TraceEvent {
  trace_id: string;
  thread_id: string;
}
export interface StepEvent {
  node: string;
  label: string;
}
export interface ToolEvent {
  name: string;
  args_summary: string;
  ok: boolean;
  ref: string | null;
}
export interface TokenEvent {
  text: string;
}
export interface MessageEvent {
  message_id: string;
  content: string;
  citations: string[];
}
/** An `approval_required` frame carries exactly a pending ask. */
export type ApprovalEvent = PendingAsk;
export interface ErrorEvent {
  code: string;
  message: string;
  trace_id: string;
  retryable: boolean;
}
export interface DoneEvent {
  status: "complete" | "interrupted" | "error";
}

export interface StreamHandlers {
  trace?(event: TraceEvent): void;
  step?(event: StepEvent): void;
  tool?(event: ToolEvent): void;
  token?(text: string): void;
  message?(event: MessageEvent): void;
  approval?(event: ApprovalEvent): void;
  error?(event: ErrorEvent): void;
  done?(status: DoneEvent["status"]): void;
}

/** A resume payload is free-form by design — docs/05 §3.7. */
export interface ResumeRequest {
  kind: PendingAsk["kind"];
  approved?: boolean;
  note?: string;
  text?: string;
  selection?: string;
  remember?: boolean;
}
