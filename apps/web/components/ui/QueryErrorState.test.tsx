import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { QueryErrorState } from "@/components/ui/QueryErrorState";
import { NetworkError } from "@/lib/api/config";

describe("QueryErrorState", () => {
  it("renders the supplied title and the error message as the description", () => {
    render(
      <QueryErrorState
        title="Could not load matters"
        error={new Error("Database exploded")}
      />,
    );
    expect(
      screen.getByRole("heading", { name: "Could not load matters" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Database exploded")).toBeInTheDocument();
  });

  it("shows the offline phrasing when the error is a NetworkError", () => {
    render(
      <QueryErrorState
        error={new NetworkError("API host unreachable.", null)}
      />,
    );
    expect(
      screen.getByRole("heading", { name: /Workspace is offline/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("API host unreachable.")).toBeInTheDocument();
  });

  it("invokes onRetry when Try again is clicked and disables the button mid-flight", async () => {
    const user = userEvent.setup();
    let resolve: () => void = () => {};
    const onRetry = vi.fn(
      () => new Promise<void>((r) => (resolve = r)),
    );

    render(
      <QueryErrorState
        title="Could not load matters"
        error={new Error("boom")}
        onRetry={onRetry}
      />,
    );

    const button = screen.getByTestId("query-error-retry");
    expect(button).toHaveTextContent("Try again");
    await user.click(button);
    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(button).toBeDisabled();
    expect(button).toHaveTextContent(/Retrying/i);

    // Resolve the retry promise inside act() so React's post-resolve
    // re-render (button re-enabled + label reset) is flushed before the
    // test ends — otherwise Testing Library warns about an un-act'd update.
    await act(async () => {
      resolve();
    });
  });

  it("renders a secondary action alongside retry when provided", () => {
    render(
      <QueryErrorState
        title="Matter not found"
        error={new Error("404")}
        secondaryAction={<a href="/app/matters">Back to portfolio</a>}
      />,
    );
    expect(
      screen.getByRole("link", { name: "Back to portfolio" }),
    ).toBeInTheDocument();
  });

  it("omits the retry button entirely when onRetry is not supplied", () => {
    render(<QueryErrorState error={new Error("boom")} />);
    expect(screen.queryByTestId("query-error-retry")).not.toBeInTheDocument();
  });
});
