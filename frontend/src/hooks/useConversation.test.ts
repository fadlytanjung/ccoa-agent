/**
 * The conversation reducer — docs/07 §3.5, §3.7.
 *
 * Pure, so it can be tested without a DOM or a network. The rule it exists to enforce
 * is the one worth guarding: **the stream is a preview, the `message` event is truth.**
 */
import { describe, expect, it } from "vitest";

import { conversationReducer, initialState, type ConversationState } from "./useConversation";

const send = (state: ConversationState, content: string) =>
  conversationReducer(state, { type: "send", content });

describe("conversationReducer", () => {
  it("renders the user's message immediately", () => {
    const state = send(initialState, "Show me John Tan.");
    expect(state.turns).toHaveLength(1);
    expect(state.turns[0]).toMatchObject({ role: "user", content: "Show me John Tan." });
    expect(state.streaming).toBe(true);
  });

  it("clears the previous activity trail when a new turn starts", () => {
    let state = send(initialState, "first");
    state = conversationReducer(state, {
      type: "tool",
      event: { name: "search_customer", args_summary: "", ok: true, ref: null },
    });
    state = send(state, "second");
    expect(state.activity.tools).toEqual([]);
    expect(state.turns).toHaveLength(2);
  });

  it("accumulates tokens into a draft", () => {
    let state = send(initialState, "hi");
    state = conversationReducer(state, { type: "token", text: "John " });
    state = conversationReducer(state, { type: "token", text: "Tan" });
    expect(state.draft).toBe("John Tan");
  });

  it("replaces the draft with the message event rather than appending", () => {
    // If the draft were appended to, a user would see the answer twice — once streamed
    // and once canonical.
    let state = send(initialState, "hi");
    state = conversationReducer(state, { type: "token", text: "partial…" });
    state = conversationReducer(state, {
      type: "message",
      event: { message_id: "m1", content: "The complete answer.", citations: ["customer:CUST-000042"] },
    });

    expect(state.draft).toBe("");
    const last = state.turns.at(-1)!;
    expect(last.content).toBe("The complete answer.");
    expect(last.citations).toEqual(["customer:CUST-000042"]);
    expect(state.turns.filter((t) => t.role === "assistant")).toHaveLength(1);
  });

  it("records a pending checkpoint as undecided", () => {
    let state = send(initialState, "hi");
    state = conversationReducer(state, {
      type: "approval",
      event: { kind: "approve", question: "Create a ticket?", payload: {} },
    });
    expect(state.pending?.kind).toBe("approve");
    expect(state.decided).toBe(false);
  });

  it("locks the checkpoint once answered, so it cannot be submitted twice", () => {
    let state = send(initialState, "hi");
    state = conversationReducer(state, {
      type: "approval",
      event: { kind: "approve", question: "Create a ticket?" },
    });
    state = conversationReducer(state, { type: "deciding" });
    expect(state.decided).toBe(true);
  });

  it("marks the last user turn as failed on error, rather than dropping it", () => {
    let state = send(initialState, "Show me John Tan.");
    state = conversationReducer(state, { type: "error", message: "boom", traceId: "t1" });

    expect(state.turns.at(-1)).toMatchObject({ role: "user", failed: true });
    expect(state.error).toEqual({ message: "boom", traceId: "t1" });
    expect(state.streaming).toBe(false);
  });

  it("stops streaming and clears the draft when done", () => {
    let state = send(initialState, "hi");
    state = conversationReducer(state, { type: "token", text: "partial" });
    state = conversationReducer(state, { type: "done", status: "interrupted" });

    expect(state.streaming).toBe(false);
    expect(state.draft).toBe("");
    expect(state.status).toBe("interrupted");
  });

  it("restores history and a pending ask on reset", () => {
    const state = conversationReducer(initialState, {
      type: "reset",
      turns: [{ id: "a", role: "user", content: "earlier" }],
      pending: { kind: "clarify", question: "Which one?" },
    });
    expect(state.turns).toHaveLength(1);
    expect(state.pending?.kind).toBe("clarify");
    expect(state.decided).toBe(false);
  });
});
