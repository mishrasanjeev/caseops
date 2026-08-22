import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ConflictCheckRecord } from "@/lib/api/endpoints";

const {
  listConflictChecksMock,
  resolveConflictCheckMock,
  runConflictCheckMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  listConflictChecksMock: vi.fn(),
  resolveConflictCheckMock: vi.fn(),
  runConflictCheckMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listConflictChecks: listConflictChecksMock,
  resolveConflictCheck: resolveConflictCheckMock,
  runConflictCheck: runConflictCheckMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import { ConflictCheckCard } from "@/components/matters/ConflictCheckCard";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function checkRecord(
  patch: Partial<ConflictCheckRecord> = {},
): ConflictCheckRecord {
  return {
    id: "check-1",
    matter_id: "matter-1",
    opposing_party_name: "Acme Private Limited",
    related_party_names: [],
    candidates: [],
    status: "cleared",
    resolution_note: null,
    resolved_by_membership_id: "member-1",
    resolved_at: "2026-07-22T09:01:00Z",
    ran_by_membership_id: "member-1",
    matter_lifecycle_version: 4,
    ran_at: "2026-07-22T09:00:00Z",
    created_at: "2026-07-22T09:00:00Z",
    ...patch,
  };
}

function renderCheck(
  check: ConflictCheckRecord,
  options: { lifecycleVersion?: number; opposingParty?: string | null } = {},
) {
  listConflictChecksMock.mockResolvedValue({
    matter_id: "matter-1",
    checks: [check],
  });
  return render(
    withClient(
      <ConflictCheckCard
        matterId="matter-1"
        matterLifecycleVersion={options.lifecycleVersion ?? 4}
        opposingParty={options.opposingParty ?? "Acme Private Limited"}
      />,
    ),
  );
}

describe("ConflictCheckCard historical evidence", () => {
  beforeEach(() => {
    listConflictChecksMock.mockReset();
    resolveConflictCheckMock.mockReset();
    runConflictCheckMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
  });

  it("keeps a same-lifecycle, normalized-party clearance current", async () => {
    renderCheck(
      checkRecord({ opposing_party_name: "  Acme,   Private Limited  " }),
      { opposingParty: "ACME PRIVATE LIMITED" },
    );

    expect(
      await screen.findByTestId("conflict-status-cleared"),
    ).toHaveTextContent("Cleared");
    expect(screen.queryByTestId("conflict-status-historical")).toBeNull();
    expect(screen.getByTestId("matter-conflict-card")).toHaveTextContent(
      /clients and matters/i,
    );
    expect(screen.getByTestId("matter-conflict-card")).not.toHaveTextContent(
      /contacts/i,
    );
  });

  it("projects a completed scan before the history revalidation finishes", async () => {
    listConflictChecksMock
      .mockResolvedValueOnce({ matter_id: "matter-1", checks: [] })
      .mockImplementationOnce(() => new Promise(() => undefined));
    runConflictCheckMock.mockResolvedValue(checkRecord());

    render(
      withClient(
        <ConflictCheckCard
          matterId="matter-1"
          matterLifecycleVersion={4}
          opposingParty="Acme Private Limited"
        />,
      ),
    );

    expect(
      await screen.findByText("No conflict check has been run yet."),
    ).toBeVisible();
    fireEvent.click(screen.getByTestId("conflict-run-open"));
    fireEvent.click(await screen.findByTestId("conflict-run-submit"));

    expect(await screen.findByTestId("conflict-status-cleared")).toBeVisible();
    await waitFor(() => expect(listConflictChecksMock).toHaveBeenCalledTimes(2));
  });

  it("labels a pre-reopen clearance historical and retains its original outcome", async () => {
    renderCheck(checkRecord({ matter_lifecycle_version: 2 }), {
      lifecycleVersion: 4,
    });

    const badge = await screen.findByTestId("conflict-status-historical");
    expect(badge).toHaveTextContent(/Historical \(stale\): Cleared/i);
    expect(badge).toHaveAttribute("data-original-status", "cleared");
    expect(screen.queryByTestId("conflict-status-cleared")).toBeNull();
    expect(screen.getByTestId("conflict-historical-notice")).toHaveTextContent(
      /lifecycle version 2/i,
    );
    expect(screen.getByTestId("conflict-historical-notice")).toHaveTextContent(
      /does not block status changes/i,
    );
  });

  it("marks a party-scope mismatch historical after normalization and hides resolution actions", async () => {
    renderCheck(
      checkRecord({
        status: "pending",
        resolved_by_membership_id: null,
        resolved_at: null,
        candidates: [
          {
            kind: "client",
            id: "client-1",
            name: "Legacy Counterparty",
            overlap_reason: "exact name match",
            similarity: 1,
          },
        ],
      }),
      { opposingParty: "Different Counterparty" },
    );

    expect(
      await screen.findByTestId("conflict-status-historical"),
    ).toHaveTextContent(/Pending review/i);
    expect(screen.getByTestId("conflict-historical-notice")).toHaveTextContent(
      /no longer matches/i,
    );
    expect(screen.queryByTestId("conflict-status-pending")).toBeNull();
    expect(screen.queryByTestId("conflict-resolve-clear")).toBeNull();
    expect(screen.queryByTestId("conflict-resolve-conflict")).toBeNull();
    expect(screen.queryByTestId("conflict-resolve-waive")).toBeNull();
  });
});
