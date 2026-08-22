/**
 * Sources for one answer — docs/07 §3.5.
 *
 * The behaviour under test is a readability rule: an investigation can cite a dozen
 * records, and a dozen chips wrapped over four lines buries the answer they belong to.
 * Three inline, the rest behind a `+N` that opens a paginated dialog.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CitationList } from "./CitationList";

const refs = (count: number) =>
  Array.from({ length: count }, (_, index) => `policy:POL-${String(index).padStart(8, "0")}`);

describe("CitationList", () => {
  it("renders nothing without sources", () => {
    const { container } = render(<CitationList refs={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows every chip inline while there are three or fewer", () => {
    render(<CitationList refs={refs(3)} />);
    expect(screen.getAllByTestId("citation-chip")).toHaveLength(3);
    expect(screen.queryByTestId("citation-overflow")).not.toBeInTheDocument();
  });

  it("collapses the rest into a +N chip past three", () => {
    render(<CitationList refs={refs(9)} />);
    expect(screen.getAllByTestId("citation-chip")).toHaveLength(3);
    expect(screen.getByTestId("citation-overflow")).toHaveTextContent("+6");
  });

  it("opens a dialog listing all of them, not just the overflow", () => {
    // The chip says "+6", but the dialog is "all sources" — showing only the hidden six
    // would make the agent cross-reference two lists to see the whole set.
    render(<CitationList refs={refs(9)} />);
    fireEvent.click(screen.getByTestId("citation-overflow"));
    expect(screen.getByTestId("citation-dialog-list")).toBeInTheDocument();
    expect(screen.getByTestId("citation-page")).toHaveTextContent("Page 1 of 2");
  });

  it("paginates rather than scrolling for two screens", () => {
    render(<CitationList refs={refs(20)} />);
    fireEvent.click(screen.getByTestId("citation-overflow"));

    expect(screen.getAllByTestId("citation-dialog-item")).toHaveLength(8);
    expect(screen.getByTestId("citation-page")).toHaveTextContent("Page 1 of 3");
    expect(screen.getByTestId("citation-prev")).toBeDisabled();

    fireEvent.click(screen.getByTestId("citation-next"));
    expect(screen.getByTestId("citation-page")).toHaveTextContent("Page 2 of 3");
    expect(screen.getByTestId("citation-prev")).toBeEnabled();

    fireEvent.click(screen.getByTestId("citation-next"));
    expect(screen.getByTestId("citation-page")).toHaveTextContent("Page 3 of 3");
    expect(screen.getByTestId("citation-next")).toBeDisabled();
    // The last page holds the remainder, not a padded eight.
    expect(screen.getAllByTestId("citation-dialog-item")).toHaveLength(4);
  });

  it("shows no pagination when everything fits on one page", () => {
    render(<CitationList refs={refs(5)} />);
    fireEvent.click(screen.getByTestId("citation-overflow"));
    expect(screen.queryByTestId("citation-page")).not.toBeInTheDocument();
  });

  it("closes the dialog when a record is selected", () => {
    // The record it reveals is behind this dialog; leaving it open hides what was asked for.
    const onFocus = vi.fn();
    render(<CitationList refs={refs(9)} onFocus={onFocus} />);
    fireEvent.click(screen.getByTestId("citation-overflow"));
    fireEvent.click(screen.getAllByRole("button", { name: /^Show/ })[0]!);

    expect(onFocus).toHaveBeenCalledWith("policy:POL-00000000");
    expect(screen.queryByTestId("citation-dialog-list")).not.toBeInTheDocument();
  });

  it("reopens on the first page after being closed", () => {
    // Otherwise the second visit lands on page 3 of the last investigation.
    render(<CitationList refs={refs(20)} />);
    fireEvent.click(screen.getByTestId("citation-overflow"));
    fireEvent.click(screen.getByTestId("citation-next"));
    expect(screen.getByTestId("citation-page")).toHaveTextContent("Page 2 of 3");

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByTestId("citation-overflow"));
    expect(screen.getByTestId("citation-page")).toHaveTextContent("Page 1 of 3");
  });
});
