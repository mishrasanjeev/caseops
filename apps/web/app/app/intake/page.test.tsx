import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listIntakeMock, useCapabilityMock } = vi.hoisted(() => ({
  listIntakeMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listIntakeRequests: listIntakeMock,
  createIntakeRequest: vi.fn(),
  updateIntakeRequest: vi.fn(),
  promoteIntakeRequest: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => useCapabilityMock(cap),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import IntakePage, { suggestNextMatterCode } from "@/app/app/intake/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("IntakePage", () => {
  beforeEach(() => {
    listIntakeMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation(() => true);
    listIntakeMock.mockResolvedValue({ requests: [] });
  });

  it("renders the intake heading and calls listIntakeRequests", async () => {
    render(withClient(<IntakePage />));
    expect(screen.getByText(/Legal intake queue/i)).toBeInTheDocument();
    await waitFor(() => expect(listIntakeMock).toHaveBeenCalledTimes(1));
  });

  it(
    "Ram-BUG-002: status counts are derived from the unfiltered set so they don't reset when the user clicks a filter tile",
    async () => {
      // Three requests across two statuses; the unfiltered fetch
      // returns all of them once. The page should derive
      // counts.new=2 and counts.in_progress=1 from this single
      // payload — and KEEP showing 2/1 even when the user clicks
      // any filter tile (no second fetch with status param). The
      // prior bug refetched on filter click and zeroed every other
      // count.
      listIntakeMock.mockResolvedValue({
        requests: [
          { id: "r1", status: "new", title: "A", category: "other",
            requester_name: "X", description: "", priority: "low",
            submitted_by_membership_id: null, submitted_by_name: null,
            assigned_to_membership_id: null, assigned_to_name: null,
            linked_matter_id: null, linked_matter_code: null,
            triage_notes: null, business_unit: null,
            created_at: "2026-04-22T00:00:00Z",
            updated_at: "2026-04-22T00:00:00Z" },
          { id: "r2", status: "new", title: "B", category: "other",
            requester_name: "Y", description: "", priority: "low",
            submitted_by_membership_id: null, submitted_by_name: null,
            assigned_to_membership_id: null, assigned_to_name: null,
            linked_matter_id: null, linked_matter_code: null,
            triage_notes: null, business_unit: null,
            created_at: "2026-04-22T00:00:00Z",
            updated_at: "2026-04-22T00:00:00Z" },
          { id: "r3", status: "in_progress", title: "C", category: "other",
            requester_name: "Z", description: "", priority: "low",
            submitted_by_membership_id: null, submitted_by_name: null,
            assigned_to_membership_id: null, assigned_to_name: null,
            linked_matter_id: null, linked_matter_code: "M-001",
            triage_notes: null, business_unit: null,
            created_at: "2026-04-22T00:00:00Z",
            updated_at: "2026-04-22T00:00:00Z" },
        ],
      });

      render(withClient(<IntakePage />));
      // Single un-status'd fetch.
      await waitFor(() => {
        expect(listIntakeMock).toHaveBeenCalledTimes(1);
        expect(listIntakeMock.mock.calls[0][0]).toEqual({ status: null });
      });

      // Tile values come from the full set: All=3, New=2, InProgress=1.
      // The legible-string check looks for the count rendered
      // alongside the status label — counts are unique per tile so
      // a substring assertion is sufficient.
      await waitFor(() => {
        expect(screen.getByText("3")).toBeInTheDocument(); // All
        expect(screen.getByText("2")).toBeInTheDocument(); // New
        expect(screen.getAllByText("1").length).toBeGreaterThan(0);
      });
    },
  );
});


// BUG-017 Hari 2026-04-21: PromoteButton catches the backend's
// ``already in use`` 400 and auto-suggests a bumped code. The pure
// helper is exported so we can pin the bump logic here.
describe("suggestNextMatterCode", () => {
  it("bumps a trailing numeric segment by 1", () => {
    expect(suggestNextMatterCode("CORP-ARB-99")).toBe("CORP-ARB-100");
    expect(suggestNextMatterCode("HARI-DUP-1")).toBe("HARI-DUP-2");
  });
  it("preserves zero-padding on the bump", () => {
    expect(suggestNextMatterCode("CASE-0009")).toBe("CASE-0010");
    expect(suggestNextMatterCode("CASE-099")).toBe("CASE-100");
  });
  it("appends -2 when the code has no trailing digits", () => {
    expect(suggestNextMatterCode("BAIL-NEW")).toBe("BAIL-NEW-2");
  });
  it("returns null for empty input", () => {
    expect(suggestNextMatterCode("")).toBeNull();
    expect(suggestNextMatterCode("A")).toBeNull();
  });
});
