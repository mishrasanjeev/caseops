import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatusBadge } from "@/components/ui/StatusBadge";

describe("StatusBadge", () => {
  it("renders disposed and legacy closed matter statuses as Dispose", () => {
    const { rerender } = render(<StatusBadge status="disposed" />);
    expect(screen.getByText("Dispose")).toBeInTheDocument();
    expect(screen.queryByText("Closed")).not.toBeInTheDocument();
    expect(screen.queryByText("Close")).not.toBeInTheDocument();

    rerender(<StatusBadge status="closed" />);
    expect(screen.getByText("Dispose")).toBeInTheDocument();
    expect(screen.queryByText("Closed")).not.toBeInTheDocument();
    expect(screen.queryByText("Close")).not.toBeInTheDocument();
  });
});
