/**
 * SSE consumption — docs/07 §3.5.
 *
 * `EventSource` cannot attach an `Authorization` header, so this reads the body as a
 * `ReadableStream` and parses the wire format itself. That is the whole reason a parser
 * lives here rather than a two-line browser API call.
 */

import { authHeaders, problemDetail } from "./client";
import type { ResumeRequest, StreamHandlers } from "./types";

export interface RawEvent {
  event: string;
  data: string;
}

/**
 * Parse an SSE byte stream into events.
 *
 * Three details the format demands, each of which a naive split gets wrong:
 *
 * 1. **Line endings may be CRLF, LF, or a bare CR.** `sse_starlette` emits CRLF, so a
 *    parser that only looks for `\n\n` finds no record boundary at all, buffers the
 *    entire response, and then parses it as one malformed record whose fields overwrite
 *    each other. The visible symptom is an assistant that never replies and a composer
 *    stuck on "Waiting for the assistant…", with a clean 200 in the network tab.
 * 2. A record ends at a **blank line**, not at every newline.
 * 3. A line beginning with `:` is a **comment** — which is exactly what the backend's
 *    15-second heartbeat sends (docs/06 §3.4). Treating one as data would inject an
 *    empty event into the conversation every fifteen seconds.
 */
export async function* parseSSE(
  stream: ReadableStream<Uint8Array>,
): AsyncGenerator<RawEvent> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  // A chunk can end mid-CRLF. Normalising that trailing "\r" immediately would turn it
  // into a newline, and the "\n" opening the next chunk would then look like a blank
  // line — splitting one record into two. So it is held back instead.
  let danglingCR = false;

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      let text = decoder.decode(value, { stream: true });
      if (danglingCR) {
        text = `\r${text}`;
        danglingCR = false;
      }
      if (text.endsWith("\r")) {
        text = text.slice(0, -1);
        danglingCR = true;
      }
      buffer += normalise(text);

      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const parsed = parseRecord(raw);
        if (parsed) yield parsed;
        boundary = buffer.indexOf("\n\n");
      }
    }
    // A final record with no trailing blank line still counts.
    if (danglingCR) buffer += "\n";
    const trailing = parseRecord(buffer);
    if (trailing) yield trailing;
  } finally {
    reader.releaseLock();
  }
}

/** CRLF and bare CR both mean "end of line" in SSE; only LF is kept internally. */
function normalise(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}

function parseRecord(raw: string): RawEvent | null {
  let event = "message";
  const data: string[] = [];

  for (const line of raw.split("\n")) {
    if (!line || line.startsWith(":")) continue; // blank or heartbeat comment
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    const value = separator === -1 ? "" : line.slice(separator + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }

  return data.length ? { event, data: data.join("\n") } : null;
}

async function consume(
  response: Response,
  handlers: StreamHandlers,
): Promise<void> {
  if (!response.ok) throw await problemDetail(response);
  if (!response.body) throw new Error("the response carried no stream");

  for await (const raw of parseSSE(response.body)) {
    let payload: unknown;
    try {
      payload = JSON.parse(raw.data);
    } catch {
      continue; // an unparseable frame is skipped rather than killing the stream
    }

    switch (raw.event) {
      case "trace":
        handlers.trace?.(payload as never);
        break;
      case "step":
        handlers.step?.(payload as never);
        break;
      case "tool":
        handlers.tool?.(payload as never);
        break;
      case "token":
        handlers.token?.((payload as { text: string }).text);
        break;
      case "message":
        handlers.message?.(payload as never);
        break;
      case "approval_required":
        handlers.approval?.(payload as never);
        break;
      case "error":
        handlers.error?.(payload as never);
        break;
      case "done":
        handlers.done?.((payload as { status: never }).status);
        return;
      default:
        break;
    }
  }
}

export async function streamMessage(
  threadId: string,
  content: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/v1/threads/${threadId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ content }),
    signal,
  });
  await consume(response, handlers);
}

export async function streamResume(
  threadId: string,
  payload: ResumeRequest,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/v1/threads/${threadId}/resume`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(payload),
    signal,
  });
  await consume(response, handlers);
}
