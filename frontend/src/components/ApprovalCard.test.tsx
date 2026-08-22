/**
 * The approval card — docs/07 §3.6.
 *
 * This is the one component where a UI bug has consequences beyond the screen: it is
 * the gate between a model's proposal and a row in the database. The properties tested
 * here are the ones that make the gate mean something.
 */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApprovalCard } from "./ApprovalCard";
import type { PendingAsk } from "../api/types";

const approveAsk: PendingAsk = {
  kind: "approve",
  question: "Create a high ticket: Manual document review",
  payload: {
    customer_id: "CUST-000042",
    case_id: "CASE-000008",
    title: "Manual document review",
    category: "claim_issue",
    priority: "high",
    description: "Claim CLM-00000117 failed three times with DOC_UNREADABLE.",
  },
  evidence_refs: ["customer:CUST-000042", "claim:CLM-00000117"],
  skippable: false,
};

const clarifyAsk: PendingAsk = {
  kind: "clarify",
  question: "2 customers match 'John Tan'. Which one is on the call?",
  options: [
    { value: "CUST-000042", label: "John Tan — CUST-000042, gold tier" },
    { value: "CUST-000091", label: "John Tan — CUST-000091, silver tier" },
  ],
  skippable: false,
};

function renderCard(ask: PendingAsk, overrides: Partial<Parameters<typeof ApprovalCard>[0]> = {}) {
  const onRespond = vi.fn();
  const view = render(
    <ApprovalCard ask={ask} decided={false} canApprove onRespond={onRespond} {...overrides} />,
  );
  return { onRespond, ...view };
}

describe("ApprovalCard — approve", () => {
  it("shows the exact payload that will be written", async () => {
    renderCard(approveAsk);
    // Not a paraphrase: the graph writes `proposal.payload` verbatim, so the human has
    // to be able to read the real thing (docs/05 §3.7).
    await userEvent.click(screen.getByText(/exactly what will be saved/i));
    expect(screen.getByTestId("approval-payload")).toHaveTextContent("DOC_UNREADABLE");
    // The customer appears twice on purpose — once in the summary, once as a citation
    // chip that focuses the record — so this asserts presence, not uniqueness.
    expect(screen.getAllByText("CUST-000042").length).toBeGreaterThan(0);
    expect(
      screen.getAllByTestId("citation-chip").map((chip) => chip.getAttribute("data-ref")),
    ).toEqual(["customer:CUST-000042", "claim:CLM-00000117"]);
  });

  it("sends approval with the note", async () => {
    const { onRespond } = renderCard(approveAsk);
    await userEvent.type(screen.getByTestId("approval-note"), "confirmed on the call");
    await userEvent.click(screen.getByTestId("approval-approve"));

    expect(onRespond).toHaveBeenCalledWith({
      kind: "approve",
      approved: true,
      note: "confirmed on the call",
    });
  });

  it("sends a rejection without needing a note", async () => {
    const { onRespond } = renderCard(approveAsk);
    await userEvent.click(screen.getByTestId("approval-reject"));
    expect(onRespond).toHaveBeenCalledWith({ kind: "approve", approved: false, note: "" });
  });

  it("disables approve when the user's role cannot approve", () => {
    renderCard(approveAsk, { canApprove: false });
    const approve = screen.getByTestId("approval-approve");
    expect(approve).toBeDisabled();
    // Explained, not merely greyed out.
    expect(approve).toHaveAttribute("title", expect.stringContaining("cannot approve"));
  });

  it("removes every control once decided, rather than disabling them", () => {
    // Stronger than `disabled`, and the difference is visible: a disabled control still
    // invites the click, still shows a text cursor over the input, and still leaves dead
    // stops in the tab order. The graph has already resumed on this reply — a second one
    // can only ever be a 409 — so the card becomes a record of what was answered.
    renderCard(approveAsk, { decided: true });

    expect(screen.queryByTestId("approval-approve")).not.toBeInTheDocument();
    expect(screen.queryByTestId("approval-reject")).not.toBeInTheDocument();
    expect(screen.queryByTestId("approval-note")).not.toBeInTheDocument();

    // ...and it says so, rather than simply going quiet.
    expect(screen.getByTestId("approval-decided")).toBeInTheDocument();
    expect(screen.getByTestId("approval-settled")).toBeInTheDocument();

    // The whole card is inert: not clickable, not tabbable, not hovered.
    const card = screen.getByTestId("approval-card");
    expect(card).toHaveAttribute("data-decided", "true");
    expect(card.className).toContain("pointer-events-none");
  });

  it("hides the options once a clarify has been answered", () => {
    // The report: after answering, controls stayed on screen under a settled question,
    // reading as an invitation to send a second reply that can only ever 409.
    const { rerender } = renderCard(clarifyAsk);
    expect(screen.getAllByTestId("clarify-option").length).toBeGreaterThan(0);

    rerender(<ApprovalCard ask={clarifyAsk} decided canApprove onRespond={() => {}} />);

    expect(screen.queryByTestId("clarify-option")).not.toBeInTheDocument();
    expect(screen.queryByTestId("answer-below")).not.toBeInTheDocument();
    expect(screen.getByTestId("approval-question")).toBeInTheDocument();
  });

  it("never offers a skip, whatever the ask says", () => {
    renderCard({ ...approveAsk, skippable: true });
    expect(screen.queryByTestId("confirm-no")).not.toBeInTheDocument();
    expect(screen.getByTestId("approval-approve")).toBeInTheDocument();
  });
});

describe("ApprovalCard — clarify", () => {
  it("offers every candidate and reports the choice", async () => {
    const { onRespond } = renderCard(clarifyAsk);
    const options = screen.getAllByTestId("clarify-option");
    expect(options).toHaveLength(2);

    await userEvent.click(options[0]!);
    expect(onRespond).toHaveBeenCalledWith({ kind: "clarify", selection: "CUST-000042" });
  });

  it("has no free-text box of its own", () => {
    // A reply that does not fit the offered shape is still a conversation, not an error
    // (docs/05 §3.7 rule 1) — but it is typed in the composer, not in a second input
    // sitting a few pixels above it. Two identical boxes, one of which answers the
    // question and one of which does not, is the confusion this removes.
    renderCard(clarifyAsk);
    expect(screen.queryByTestId("clarify-text")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("says where to answer when the graph offers no options", () => {
    // Without this the card is a bare question with nothing under it, and the composer
    // below gives no sign that it is what resolves the checkpoint.
    renderCard({ ...clarifyAsk, options: null });
    expect(screen.getByTestId("answer-below")).toBeInTheDocument();
    expect(screen.queryByTestId("clarify-option")).not.toBeInTheDocument();
  });

  it("has no approve control at all", () => {
    renderCard(clarifyAsk);
    expect(screen.queryByTestId("approval-approve")).not.toBeInTheDocument();
  });
});

describe("ApprovalCard — confirm", () => {
  const confirmAsk: PendingAsk = {
    kind: "confirm",
    question: "This customer has 24 contacts. Read all of them?",
    skippable: true,
  };

  it("remembers the preference when asked to", async () => {
    const { onRespond } = renderCard(confirmAsk);
    await userEvent.click(screen.getByLabelText(/don't ask me again/i));
    await userEvent.click(screen.getByTestId("confirm-yes"));

    expect(onRespond).toHaveBeenCalledWith({
      kind: "confirm",
      approved: true,
      remember: true,
    });
  });

  it("allows declining", async () => {
    const { onRespond } = renderCard(confirmAsk);
    await userEvent.click(screen.getByTestId("confirm-no"));
    expect(onRespond).toHaveBeenCalledWith({
      kind: "confirm",
      approved: false,
      remember: false,
    });
  });
});
