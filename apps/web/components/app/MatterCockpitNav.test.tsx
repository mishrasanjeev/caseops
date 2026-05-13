import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/app/matters/m-1/strategy",
}));

import { MatterCockpitNav } from "@/components/app/MatterCockpitNav";

describe("MatterCockpitNav", () => {
  it("uses LW-S11 labels for AI recommendations strategy and audit", () => {
    render(<MatterCockpitNav matterId="m-1" />);

    expect(screen.getByRole("link", { name: "AI Recommendations" })).toHaveAttribute(
      "href",
      "/app/matters/m-1/recommendations",
    );
    expect(screen.getByRole("link", { name: "Strategy Plan" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(
      screen.getByRole("link", { name: "Predictive Intelligence" }),
    ).toHaveAttribute("href", "/app/matters/m-1/predictive-intelligence");
    expect(screen.getByRole("link", { name: "Intelligence Review" })).toHaveAttribute(
      "href",
      "/app/matters/m-1/litigation-intelligence",
    );
    expect(screen.getByRole("link", { name: "Knowledge Graph" })).toHaveAttribute(
      "href",
      "/app/matters/m-1/knowledge-graph",
    );
    expect(screen.getByRole("link", { name: "Matter Audit" })).toHaveAttribute(
      "href",
      "/app/matters/m-1/audit",
    );
  });
});
