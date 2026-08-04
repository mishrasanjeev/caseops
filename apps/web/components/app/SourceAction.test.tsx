import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("opens only the server-issued source route in a protected new context", () => {
    render(
      <SourceAction
        action={contract({
          state: "available",
          open_url: "/api/source-actions/targets/authority_document/source-proof/open",
          source_reference: "https://www.sci.gov.in/case.pdf",
          target_type: "authority_document",
          target_id: "source-proof",
        })}
        originSurface="research"
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
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("origin=research"),
    );
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

  it("queues a typed report for an unavailable canonical source", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "report-1",
          target_type: "authority_document",
          target_id: "authority-unverified",
          origin_surface: "saved_research",
          issue_type: "wrong_document",
          status: "queued",
          source_state: "unverified",
          destination_class: "unavailable_unverified",
          created_at: "2026-08-04T00:00:00Z",
        }),
        { status: 201, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(
      <SourceAction
        action={contract({
          state: "unverified",
          reason: "Provider verification expired.",
          target_type: "authority_document",
          target_id: "authority-unverified",
        })}
        originSurface="saved_research"
      />,
    );

    fireEvent.click(screen.getByTestId("source-action-report"));
    fireEvent.change(screen.getByLabelText("Issue"), {
      target: { value: "wrong_document" },
    });
    fireEvent.change(screen.getByLabelText("Details (optional)"), {
      target: { value: "The citation opens a different judgment." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Queue report" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock.mock.calls[0]?.[0]).toContain("/api/source-actions/reports");
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: "POST",
      credentials: "include",
    });
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toMatchObject({
      target_type: "authority_document",
      target_id: "authority-unverified",
      origin_surface: "saved_research",
      issue_type: "wrong_document",
    });
  });
});
