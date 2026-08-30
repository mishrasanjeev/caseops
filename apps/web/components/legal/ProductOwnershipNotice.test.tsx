import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProductOwnershipNotice } from "./ProductOwnershipNotice";

describe("ProductOwnershipNotice", () => {
  it("publishes the legal owner, inventor/owner, and both owner emails", () => {
    render(<ProductOwnershipNotice />);

    const notice = screen.getByRole("complementary", {
      name: "CaseOps product ownership",
    });
    expect(notice).toHaveTextContent("CaseOps is owned by Orchestrum Technologies LLP");
    expect(notice).toHaveTextContent("Inventor/Owner: Sanjeev Kumar");
    expect(screen.getByRole("group", { name: "Owner emails" })).toBeVisible();
    expect(screen.getByRole("link", { name: "sanjeev@orchestrum.in" })).toHaveAttribute(
      "href",
      "mailto:sanjeev@orchestrum.in",
    );
    expect(
      screen.getByRole("link", { name: "mishra.sanjeev@gmail.com" }),
    ).toHaveAttribute("href", "mailto:mishra.sanjeev@gmail.com");
  });
});
