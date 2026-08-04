import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SourceAction, type SourceActionContract } from "@/components/app/SourceAction";

function contract(
  input: Partial<SourceActionContract>,
): SourceActionContract {
  return {
    state: "missing",
    label: "Open source",
    open_url: null,
    source_reference: null,
    reason: "No source reference is available.",
    opens_new_tab: true,
    ...input,
  };
}

describe("SourceAction", () => {
  it("opens only the server-issued source route in a protected new context", () => {
    render(
      <SourceAction
        action={contract({
          state: "available",
          open_url: "/api/source-actions/targets/authority_document/source-proof/open",
          source_reference: "https://www.sci.gov.in/case.pdf",
        })}
      />,
    );

    const link = screen.getByTestId("source-action-open");
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining(
        "/api/source-actions/targets/authority_document/source-proof/open",
      ),
    );
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("referrerpolicy", "no-referrer");
  });

  it.each(["missing", "unverified", "blocked", "quarantined"] as const)(
    "renders %s as a typed non-link state while keeping its reason",
    (state) => {
      render(
        <SourceAction
          action={contract({
            state,
            source_reference: "citation:fixture",
            reason: `${state} source fixture`,
          })}
        />,
      );

      expect(screen.getByTestId(`source-action-${state}`)).toHaveTextContent(
        `${state} source fixture`,
      );
      expect(screen.queryByTestId("source-action-open")).not.toBeInTheDocument();
    },
  );
});
