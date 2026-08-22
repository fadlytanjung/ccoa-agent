/**
 * The composer's two modes — docs/07 §3.6, docs/05 §3.7.
 *
 * Worth testing directly because the failure is silent in the worst way: a message typed
 * during an open checkpoint used to `POST /messages` to a thread whose graph is suspended
 * on an `interrupt()`. Nothing errors visibly; the answer simply never arrives.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";

function setup(props: Partial<Parameters<typeof Composer>[0]> = {}) {
  const onSend = vi.fn();
  const onAnswer = vi.fn();
  render(<Composer disabled={false} onSend={onSend} onAnswer={onAnswer} {...props} />);
  return { onSend, onAnswer };
}

describe("Composer", () => {
  it("sends a message when no checkpoint is open", async () => {
    const { onSend, onAnswer } = setup();
    await userEvent.type(screen.getByTestId("composer-input"), "show me CUST-000042");
    await userEvent.click(screen.getByTestId("composer-send"));

    expect(onSend).toHaveBeenCalledWith("show me CUST-000042");
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("answers the checkpoint instead, while one is open", async () => {
    // The graph is suspended; a new message cannot move it. This is the fix.
    const { onSend, onAnswer } = setup({ answering: "clarify" });
    await userEvent.type(screen.getByTestId("composer-input"), "the gold one");
    await userEvent.click(screen.getByTestId("composer-send"));

    expect(onAnswer).toHaveBeenCalledWith("clarify", "the gold one");
    expect(onSend).not.toHaveBeenCalled();
  });

  it("routes a steer the same way", async () => {
    const { onAnswer } = setup({ answering: "steer" });
    await userEvent.type(screen.getByTestId("composer-input"), "check the motor policy");
    fireEvent.submit(screen.getByTestId("composer-input").closest("form")!);
    expect(onAnswer).toHaveBeenCalledWith("steer", "check the motor policy");
  });

  it("says which question it is answering", () => {
    setup({ answering: "clarify" });
    expect(screen.getByText(/Replying to the assistant/)).toBeInTheDocument();
    expect(screen.getByTestId("composer-input")).toHaveAttribute(
      "placeholder",
      "Answer the question above…",
    );
    expect(screen.getByTestId("composer-send")).toHaveAccessibleName("Send answer");
  });

  it("looks like an ordinary composer when it is one", () => {
    setup();
    expect(screen.queryByText(/Replying to the assistant/)).not.toBeInTheDocument();
    expect(screen.getByTestId("composer-input")).toHaveAttribute(
      "placeholder",
      "Ask about a customer…",
    );
  });

  it("sends nothing while disabled", async () => {
    const { onSend, onAnswer } = setup({ disabled: true });
    const input = screen.getByTestId("composer-input");
    expect(input).toBeDisabled();
    fireEvent.submit(input.closest("form")!);
    expect(onSend).not.toHaveBeenCalled();
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("ignores whitespace", async () => {
    const { onSend } = setup();
    await userEvent.type(screen.getByTestId("composer-input"), "   ");
    fireEvent.submit(screen.getByTestId("composer-input").closest("form")!);
    expect(onSend).not.toHaveBeenCalled();
  });

  it("trims what it sends", async () => {
    const { onSend } = setup();
    await userEvent.type(screen.getByTestId("composer-input"), "  hello  ");
    fireEvent.submit(screen.getByTestId("composer-input").closest("form")!);
    expect(onSend).toHaveBeenCalledWith("hello");
  });

  it("clears after sending, so the next turn starts empty", async () => {
    setup();
    const input = screen.getByTestId("composer-input");
    await userEvent.type(input, "first");
    fireEvent.submit(input.closest("form")!);
    expect(input).toHaveValue("");
  });

  it("sends on Enter and breaks the line on Shift+Enter", async () => {
    const { onSend } = setup();
    const input = screen.getByTestId("composer-input");
    await userEvent.type(input, "one");

    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();

    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("one");
  });
});
