/**
 * The activity trail — docs/07 §3.5, docs/21 §6.
 *
 * The property under test is that the trail stays *short* without becoming *dishonest*:
 * repeated calls to one tool collapse into a single row, and the count is what preserves
 * the information the extra rows were carrying.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ActivityTrail } from "./ActivityTrail";
import type { Activity } from "../hooks/useConversation";

/**
 * Once the turn finishes the trail collapses to one line — quiet enough not to bury the
 * answer. Every row assertion therefore has to open it first, which is also the
 * interaction an agent performs when they want to see what happened.
 */
function expand() {
  fireEvent.click(screen.getByRole("button", { expanded: false }));
}

function activity(tools: Activity["tools"], steps: Activity["steps"] = []): Activity {
  return { steps, tools };
}

function tool(name: string, args_summary = "", ok = true) {
  return { name, args_summary, ok, ref: null };
}

describe("ActivityTrail", () => {
  it("renders nothing when there is no activity", () => {
    const { container } = render(<ActivityTrail activity={activity([])} running={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("collapses repeated calls to one tool into a single row", () => {
    // The reported problem: four `search_kb` rows pushed the answer off the screen while
    // telling the agent nothing the first row had not.
    render(
      <ActivityTrail
        activity={activity([
          tool("search_kb", "claim upload"),
          tool("search_kb", "submission failure"),
          tool("search_kb", "error 422"),
          tool("get_customer", "CUST-000042"),
        ])}
        running={false}
      />,
    );

    expand();
    const rows = screen.getAllByTestId("trail-tool");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveAttribute("data-calls", "3");
    expect(rows[1]).toHaveAttribute("data-calls", "1");
  });

  it("counts the collapsed calls, so nothing is silently dropped", () => {
    render(
      <ActivityTrail
        activity={activity([tool("search_kb"), tool("search_kb")])}
        running={false}
      />,
    );
    expand();
    expect(screen.getByTitle("Called 2 times")).toHaveTextContent("×2");
  });

  it("does not label a single call with a count", () => {
    // "×1" is noise: it says only that something happened once, which the row already says.
    render(<ActivityTrail activity={activity([tool("get_customer")])} running={false} />);
    expand();
    expect(screen.queryByText("×1")).not.toBeInTheDocument();
  });

  it("reports the most recent call's arguments and outcome for a collapsed row", () => {
    // The row stands for the tool's *current* state, so a later failure must not be
    // hidden behind an earlier success.
    render(
      <ActivityTrail
        activity={activity([tool("search_kb", "first", true), tool("search_kb", "second", false)])}
        running={false}
      />,
    );
    expand();
    expect(screen.getByTestId("trail-tool")).toHaveTextContent("second");
  });

  it("keeps call order, because the sequence is part of what the trail shows", () => {
    render(
      <ActivityTrail
        activity={activity([tool("search_customer"), tool("get_claim"), tool("search_customer")])}
        running={false}
      />,
    );
    expand();
    const rows = screen.getAllByTestId("trail-tool");
    expect(rows[0]).toHaveTextContent("search_customer");
    expect(rows[1]).toHaveTextContent("get_claim");
  });

  it("summarises every call, not every row, when collapsed", () => {
    // Three calls shown as one row must still be reported as three lookups — otherwise
    // collapsing would quietly understate the work done.
    render(
      <ActivityTrail
        activity={activity([tool("search_kb"), tool("search_kb"), tool("search_kb")])}
        running={false}
      />,
    );
    expect(screen.getByTestId("activity-trail")).toHaveTextContent("3 lookups");
  });
});
