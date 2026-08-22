/**
 * The live conversation — docs/07 §3.5, §3.7.
 *
 * One reducer with a short life, as the spec says: server state belongs to TanStack
 * Query, and this is the ephemeral half — steps, tool calls, draft tokens, and the
 * pending checkpoint.
 *
 * The rule that shapes it: **the stream is a preview, the `message` event is truth.**
 * Tokens accumulate into a draft bubble, and the terminal event replaces that draft
 * with the canonical content and its citations. Rendering the accumulated tokens as the
 * final answer would show text the backend never committed to.
 */

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { streamMessage, streamResume } from "../api/stream";
import { ApiError, api } from "../api/client";
import type {
  ApprovalEvent,
  MessageEvent,
  PendingAsk,
  ResumeRequest,
  StepEvent,
  ToolEvent,
} from "../api/types";

export interface ChatTurn {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: string[];
  failed?: boolean;
}

export interface Activity {
  steps: StepEvent[];
  tools: ToolEvent[];
}

export interface ConversationState {
  turns: ChatTurn[];
  activity: Activity;
  draft: string;
  streaming: boolean;
  pending: PendingAsk | null;
  /** Set once a checkpoint is answered, so the card cannot be submitted twice. */
  decided: boolean;
  error: { message: string; traceId?: string } | null;
  status: "idle" | "running" | "interrupted" | "complete" | "error";
}

type Action =
  | { type: "reset"; turns: ChatTurn[]; pending: PendingAsk | null }
  | { type: "send"; content: string }
  | { type: "step"; event: StepEvent }
  | { type: "tool"; event: ToolEvent }
  | { type: "token"; text: string }
  | { type: "message"; event: MessageEvent }
  | { type: "approval"; event: ApprovalEvent }
  | { type: "deciding" }
  | { type: "error"; message: string; traceId?: string }
  | { type: "done"; status: "complete" | "interrupted" | "error" };

export const initialState: ConversationState = {
  turns: [],
  activity: { steps: [], tools: [] },
  draft: "",
  streaming: false,
  pending: null,
  decided: false,
  error: null,
  status: "idle",
};

let counter = 0;
const nextId = () => `turn-${++counter}`;

export function conversationReducer(
  state: ConversationState,
  action: Action,
): ConversationState {
  switch (action.type) {
    case "reset":
      return { ...initialState, turns: action.turns, pending: action.pending };

    case "send":
      return {
        ...state,
        // Rendered immediately — docs/07 §6 question 2. Marked failed on error rather
        // than removed, so the agent can see what they typed and retry it.
        turns: [...state.turns, { id: nextId(), role: "user", content: action.content }],
        activity: { steps: [], tools: [] },
        draft: "",
        streaming: true,
        pending: null,
        decided: false,
        error: null,
        status: "running",
      };

    case "step":
      return {
        ...state,
        activity: { ...state.activity, steps: [...state.activity.steps, action.event] },
      };

    case "tool":
      return {
        ...state,
        activity: { ...state.activity, tools: [...state.activity.tools, action.event] },
      };

    case "token":
      return { ...state, draft: state.draft + action.text };

    case "message":
      return {
        ...state,
        // The draft is discarded, not appended to: the event is canonical.
        draft: "",
        turns: [
          ...state.turns,
          {
            id: action.event.message_id || nextId(),
            role: "assistant",
            content: action.event.content,
            citations: action.event.citations,
          },
        ],
      };

    case "approval":
      return { ...state, pending: action.event, decided: false };

    case "deciding":
      return { ...state, decided: true };

    case "error":
      return {
        ...state,
        streaming: false,
        status: "error",
        error: { message: action.message, traceId: action.traceId },
        turns: state.turns.map((turn, index) =>
          index === state.turns.length - 1 && turn.role === "user"
            ? { ...turn, failed: true }
            : turn,
        ),
      };

    case "done":
      return { ...state, streaming: false, draft: "", status: action.status };

    default:
      return state;
  }
}

export function useConversation(threadId: string | null) {
  const [state, dispatch] = useReducer(conversationReducer, initialState);
  const abort = useRef<AbortController | null>(null);
  // Which thread the reducer has finished loading. A caller that wants to send the moment
  // a conversation opens — the empty state, where typing creates the thread — has to wait
  // for this, or the `/state` fetch below resolves afterwards and its `reset` wipes the
  // message that was just sent.
  const [loadedThreadId, setLoadedThreadId] = useState<string | null>(null);

  // Reconcile from the server whenever the thread changes. This is what makes a
  // pending approval survive a refresh: the card is re-rendered from `/state`, not
  // from anything the browser kept (docs/07 §3.6).
  useEffect(() => {
    if (!threadId) {
      dispatch({ type: "reset", turns: [], pending: null });
      setLoadedThreadId(null);
      return;
    }
    let cancelled = false;
    setLoadedThreadId(null);
    void (async () => {
      try {
        const snapshot = await api.threadState(threadId);
        if (cancelled) return;
        dispatch({
          type: "reset",
          turns: snapshot.messages.map((message) => ({
            id: nextId(),
            role: message.role === "human" ? "user" : "assistant",
            content: message.content,
          })),
          pending: snapshot.pending_ask,
        });
        setLoadedThreadId(threadId);
      } catch {
        if (!cancelled) {
          dispatch({ type: "reset", turns: [], pending: null });
          // Still "loaded": an empty conversation that failed to load is the same thing
          // to send into as an empty one that loaded. Leaving it unset strands the queue.
          setLoadedThreadId(threadId);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [threadId]);

  // Cancelling the request cancels the run server-side (docs/06 §3.4), so leaving a
  // thread does not leave a graph running behind it.
  useEffect(() => () => abort.current?.abort(), []);

  const handlers = useCallback(
    () => ({
      step: (event: StepEvent) => dispatch({ type: "step", event }),
      tool: (event: ToolEvent) => dispatch({ type: "tool", event }),
      token: (text: string) => dispatch({ type: "token", text }),
      message: (event: MessageEvent) => dispatch({ type: "message", event }),
      approval: (event: ApprovalEvent) => dispatch({ type: "approval", event }),
      error: (event: { message: string; trace_id: string }) =>
        dispatch({ type: "error", message: event.message, traceId: event.trace_id }),
      done: (status: "complete" | "interrupted" | "error") =>
        dispatch({ type: "done", status }),
    }),
    [],
  );

  const send = useCallback(
    async (content: string) => {
      if (!threadId) return;
      abort.current?.abort();
      abort.current = new AbortController();
      dispatch({ type: "send", content });
      try {
        await streamMessage(threadId, content, handlers(), abort.current.signal);
      } catch (cause) {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        dispatch({
          type: "error",
          message: cause instanceof Error ? cause.message : String(cause),
          traceId: cause instanceof ApiError ? cause.traceId : undefined,
        });
      }
    },
    [threadId, handlers],
  );

  const respond = useCallback(
    async (payload: ResumeRequest) => {
      if (!threadId || state.decided) return;
      dispatch({ type: "deciding" });
      abort.current?.abort();
      abort.current = new AbortController();
      try {
        await streamResume(threadId, payload, handlers(), abort.current.signal);
      } catch (cause) {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        // A 409 means someone already answered this checkpoint. That is a
        // reconciliation, not a failure — docs/07 §5.
        if (cause instanceof ApiError && cause.status === 409) {
          dispatch({ type: "done", status: "complete" });
          return;
        }
        dispatch({
          type: "error",
          message: cause instanceof Error ? cause.message : String(cause),
          traceId: cause instanceof ApiError ? cause.traceId : undefined,
        });
      }
    },
    [threadId, state.decided, handlers],
  );

  return { state, send, respond, ready: loadedThreadId === threadId && threadId !== null };
}
