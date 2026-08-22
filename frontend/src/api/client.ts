/**
 * HTTP client — docs/06.
 *
 * One place that knows how to attach a token, how to read an RFC 9457 problem detail,
 * and how to surface a trace id. Everything else calls through here so an error can
 * never reach the UI as a bare `fetch` rejection with no context.
 */

import type {
  CustomerProfile,
  InteractionSummary,
  ProblemDetail,
  ResumeRequest,
  RuntimeConfig,
  SupportCase,
  ThreadListResponse,
  ThreadState,
  ThreadSummary,
} from "./types";

export class ApiError extends Error {
  readonly status: number;
  readonly traceId?: string;
  readonly code: string;

  constructor(problem: ProblemDetail) {
    super(problem.detail || problem.title);
    this.name = "ApiError";
    this.status = problem.status;
    this.traceId = problem.trace_id;
    // The `type` URI's last segment is a stable machine-readable code; the title is
    // prose and may change.
    this.code = problem.type.split("/").pop() ?? "error";
  }
}

/** Read a failed response as a problem detail, falling back if it is not one. */
export async function problemDetail(response: Response): Promise<ApiError> {
  const traceId = response.headers.get("X-Trace-Id") ?? undefined;
  try {
    const body = (await response.json()) as ProblemDetail;
    return new ApiError({ ...body, trace_id: body.trace_id ?? traceId });
  } catch {
    return new ApiError({
      type: "about:blank",
      title: response.statusText || "Request failed",
      status: response.status,
      detail: `The request failed with status ${response.status}.`,
      trace_id: traceId,
    });
  }
}

/** Supplies the current access token, or `null` when auth is bypassed locally. */
export type TokenSource = () => string | null;

let getToken: TokenSource = () => null;

export function setTokenSource(source: TokenSource): void {
  getToken = source;
}

export function authHeaders(): HeadersInit {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { Accept: "application/json", ...authHeaders(), ...init.headers },
  });
  if (!response.ok) throw await problemDetail(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function send<T>(path: string, method: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export const api = {
  /** Public, and deliberately so: the SPA needs it *before* it can sign in. */
  config: () => request<RuntimeConfig>("/api/v1/config"),

  listThreads: (cursor?: string | null, limit = 30) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (cursor) query.set("cursor", cursor);
    return request<ThreadListResponse>(`/api/v1/threads?${query}`);
  },
  createThread: (title?: string) =>
    send<ThreadSummary>("/api/v1/threads", "POST", { title: title ?? null }),
  deleteThread: (id: string) => send<void>(`/api/v1/threads/${id}`, "DELETE"),
  threadState: (id: string) => request<ThreadState>(`/api/v1/threads/${id}/state`),

  customer: (id: string) => request<CustomerProfile>(`/api/v1/customers/${id}`),
  cases: (id: string) => request<SupportCase[]>(`/api/v1/customers/${id}/cases`),
  interactions: (id: string, limit = 5) =>
    request<InteractionSummary[]>(`/api/v1/customers/${id}/interactions?limit=${limit}`),
};

export type { ResumeRequest };
