/**
 * The SSE parser — docs/07 §3.5.
 *
 * Worth testing directly because its failures are quiet. A parser that mishandles the
 * heartbeat injects blank events every fifteen seconds; one that splits on the wrong
 * boundary truncates the answer. Neither throws.
 */
import { describe, expect, it } from "vitest";

import { parseSSE } from "./stream";

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const events = [];
  for await (const event of parseSSE(stream)) events.push(event);
  return events;
}

describe("parseSSE — the real wire format", () => {
  // These use CRLF, which is what `sse_starlette` actually emits. The original tests
  // below used bare LF and all passed while the browser rendered nothing: they encoded
  // an assumption about the format rather than the format itself.
  it("splits CRLF-separated records", async () => {
    const events = await collect(
      streamOf(
        'event: trace\r\ndata: {"a":1}\r\n\r\nevent: step\r\ndata: {"b":2}\r\n\r\n',
      ),
    );
    expect(events).toEqual([
      { event: "trace", data: '{"a":1}' },
      { event: "step", data: '{"b":2}' },
    ]);
  });

  it("handles a chunk that ends between the CR and the LF", async () => {
    // The network splits wherever it likes. Normalising the trailing CR eagerly would
    // manufacture a blank line here and cut the record in half.
    const events = await collect(
      streamOf('event: step\r\ndata: {"a":1}\r', '\n\r\nevent: done\r\ndata: {"s":1}\r\n\r\n'),
    );
    expect(events).toEqual([
      { event: "step", data: '{"a":1}' },
      { event: "done", data: '{"s":1}' },
    ]);
  });

  it("handles a bare CR as a line ending", async () => {
    const events = await collect(streamOf('event: step\rdata: {"a":1}\r\r'));
    expect(events).toEqual([{ event: "step", data: '{"a":1}' }]);
  });

  it("ignores a CRLF heartbeat comment", async () => {
    const events = await collect(
      streamOf(': ping\r\n\r\nevent: token\r\ndata: {"text":"a"}\r\n\r\n'),
    );
    expect(events).toEqual([{ event: "token", data: '{"text":"a"}' }]);
  });
});

describe("parseSSE", () => {
  it("parses a single event", async () => {
    const events = await collect(streamOf('event: step\ndata: {"node":"guard"}\n\n'));
    expect(events).toEqual([{ event: "step", data: '{"node":"guard"}' }]);
  });

  it("parses several events in one chunk", async () => {
    const events = await collect(
      streamOf('event: step\ndata: {"a":1}\n\nevent: tool\ndata: {"b":2}\n\n'),
    );
    expect(events.map((e) => e.event)).toEqual(["step", "tool"]);
  });

  it("reassembles an event split across chunks", async () => {
    // The network decides where chunks end, not the protocol. A parser that assumes
    // one chunk is one event drops the second half of every long answer.
    const events = await collect(streamOf('event: mess', 'age\ndata: {"conte', 'nt":"hi"}\n\n'));
    expect(events).toEqual([{ event: "message", data: '{"content":"hi"}' }]);
  });

  it("ignores heartbeat comments", async () => {
    // The backend sends `: ping` every 15 s to keep the connection open (docs/06 §3.4).
    const events = await collect(
      streamOf(': ping\n\nevent: token\ndata: {"text":"a"}\n\n: ping\n\n'),
    );
    expect(events).toEqual([{ event: "token", data: '{"text":"a"}' }]);
  });

  it("keeps a multi-line data payload together", async () => {
    const events = await collect(streamOf("event: message\ndata: line one\ndata: line two\n\n"));
    expect(events[0]!.data).toBe("line one\nline two");
  });

  it("emits a trailing event with no final blank line", async () => {
    const events = await collect(streamOf('event: done\ndata: {"status":"complete"}\n'));
    expect(events).toEqual([{ event: "done", data: '{"status":"complete"}' }]);
  });

  it("tolerates a field with no space after the colon", async () => {
    const events = await collect(streamOf("event:step\ndata:{}\n\n"));
    expect(events).toEqual([{ event: "step", data: "{}" }]);
  });

  it("produces nothing from an empty stream", async () => {
    expect(await collect(streamOf(""))).toEqual([]);
  });
});
