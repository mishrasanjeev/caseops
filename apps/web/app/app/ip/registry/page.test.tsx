import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  capabilityMock,
  coreMock,
  createReferenceMock,
  decideMatchMock,
  diffsMock,
  docketsMock,
  bookmarksMock,
  recordSnapshotMock,
  referencesMock,
  workspacesMock,
} = vi.hoisted(() => ({
  capabilityMock: vi.fn(),
  coreMock: vi.fn(),
  createReferenceMock: vi.fn(),
  decideMatchMock: vi.fn(),
  diffsMock: vi.fn(),
  docketsMock: vi.fn(),
  bookmarksMock: vi.fn(),
  recordSnapshotMock: vi.fn(),
  referencesMock: vi.fn(),
  workspacesMock: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => capabilityMock(capability),
}));

vi.mock("@/lib/use-session", () => ({
  useSession: () => ({
    status: "authenticated",
    token: null,
    context: { membership: { id: "member-1" } },
    signOut: vi.fn(),
  }),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/lib/api/endpoints", () => ({
  createIpRegistryLink: vi.fn(),
  createIpTrackedCaseReference: createReferenceMock,
  decideIpRegistryMatch: decideMatchMock,
  decideIpTrackedCaseReference: vi.fn(),
  fetchIpCoreRecords: coreMock,
  fetchIpDockets: docketsMock,
  fetchIpRegistryDiffs: diffsMock,
  fetchIpRegistryWorkspaces: workspacesMock,
  fetchIpTrackedCaseReferences: referencesMock,
  listCaseTrackingBookmarks: bookmarksMock,
  recordIpRegistryFailure: vi.fn(),
  recordIpRegistryManualSnapshot: recordSnapshotMock,
  resolveIpRegistryDiff: vi.fn(),
}));

import IpRegistryPage from "@/app/app/ip/registry/page";

const DOCKET = {
  id: "docket-1",
  matter_id: "matter-1",
  title: "ASTER mark",
  primary_identifier: "TM-1234567",
};

const LINK = {
  id: "registry-link-1",
  company_id: "company-1",
  docket_id: "docket-1",
  application_id: "application-1",
  proceeding_id: null,
  provider_key: "ipindia-registry",
  office: "IP India",
  jurisdiction: "IN",
  identifier_kind: "application",
  raw_identifier: "TM-1234567",
  normalized_identifier: "TM1234567",
  source_url: "https://ipindia.gov.in/registry/TM-1234567",
  match_status: "candidate" as const,
  match_confidence: "0.9500",
  match_evidence_json: { identifier: "TM-1234567" },
  accepted_state_json: { office: "IP India", jurisdiction: "IN", status: "draft" },
  terms_version: null,
  capability_version: "manual-evidence-v1",
  freshness_status: "never_succeeded" as const,
  last_attempted_at: null,
  last_successful_at: null,
  last_snapshot_id: null,
  last_normalized_hash: null,
  last_error_redacted: null,
  version: 1,
  created_by_membership_id: "member-1",
  created_at: "2026-08-24T08:00:00Z",
  updated_at: "2026-08-24T08:00:00Z",
};

const CORE = {
  assets: [],
  applications: [
    {
      id: "application-1",
      office: "IP India",
      filing_phase: "draft",
    },
  ],
  proceedings: [
    {
      id: "proceeding-1",
      proceeding_kind: "opposition",
      stage: "draft",
    },
  ],
  identifiers: [],
};

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("IP registry reconciliation page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capabilityMock.mockReturnValue(true);
    docketsMock.mockResolvedValue({ dockets: [DOCKET], count: 1 });
    coreMock.mockResolvedValue(CORE);
    workspacesMock.mockResolvedValue({
      items: [{ link: LINK, attempts: [], snapshots: [] }],
      total: 1,
      limit: 25,
      offset: 0,
    });
    diffsMock.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
    referencesMock.mockResolvedValue([]);
    bookmarksMock.mockResolvedValue({
      bookmarks: [
        {
          id: "bookmark-1",
          tracked_case_id: "tracked-1",
          matter_id: "matter-1",
          tracked_case: {
            id: "tracked-1",
            case_title: "Aster LLP v Registrar of Trade Marks",
          },
        },
      ],
    });
  });

  it("fails closed without IP read access", () => {
    capabilityMock.mockReturnValue(false);

    render(<IpRegistryPage />, { wrapper: wrapper() });

    expect(screen.getByText("IP access required")).toBeVisible();
    expect(workspacesMock).not.toHaveBeenCalled();
  });

  it("shows official provenance and records an explicit match decision", async () => {
    const user = userEvent.setup();
    decideMatchMock.mockResolvedValue({ ...LINK, match_status: "confirmed", version: 2 });

    render(<IpRegistryPage />, { wrapper: wrapper() });

    expect(await screen.findByRole("heading", { name: "TM-1234567" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Open source" })).toHaveAttribute(
      "href",
      LINK.source_url,
    );
    expect(screen.getByText("Manual evidence intake only. No provider call is made.")).toBeVisible();

    await user.type(screen.getByLabelText("Reason"), "Identifier and office match the source.");
    await user.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() =>
      expect(decideMatchMock).toHaveBeenCalledWith({
        linkId: LINK.id,
        expectedVersion: 1,
        decision: "confirm",
        reason: "Identifier and office match the source.",
      }),
    );
  });

  it("records immutable manual evidence after the registry match is confirmed", async () => {
    const user = userEvent.setup();
    const confirmed = { ...LINK, match_status: "confirmed" as const, version: 2 };
    workspacesMock.mockResolvedValue({
      items: [{ link: confirmed, attempts: [], snapshots: [] }],
      total: 1,
      limit: 25,
      offset: 0,
    });
    recordSnapshotMock.mockResolvedValue({
      link: { ...confirmed, version: 3 },
      attempt: { id: "attempt-1", status: "no_change" },
      snapshot: { id: "snapshot-1" },
      diffs: [],
      no_change: true,
      idempotent_replay: false,
    });

    render(<IpRegistryPage />, { wrapper: wrapper() });

    await user.click(await screen.findByRole("button", { name: "Record immutable snapshot" }));

    await waitFor(() => expect(recordSnapshotMock).toHaveBeenCalledTimes(1));
    expect(recordSnapshotMock.mock.calls[0][0]).toMatchObject({
      linkId: LINK.id,
      expectedLinkVersion: 2,
      sourceUrl: LINK.source_url,
      parserVersion: "manual-normalizer-v1",
      normalizedSnapshot: LINK.accepted_state_json,
    });
  });

  it("adds a reference to the existing Matter tracked case", async () => {
    const user = userEvent.setup();
    createReferenceMock.mockResolvedValue({ id: "reference-1" });

    render(<IpRegistryPage />, { wrapper: wrapper() });

    expect(await screen.findByText(/court updates are never copied/i)).toBeVisible();
    await user.type(screen.getByLabelText("Evidence reference"), "matter-bookmark:bookmark-1");
    await user.click(screen.getByRole("button", { name: "Add reference" }));

    await waitFor(() =>
      expect(createReferenceMock).toHaveBeenCalledWith({
        docketId: "docket-1",
        proceedingId: "proceeding-1",
        trackedCaseId: "tracked-1",
        purpose: "Opposition or appeal tracking",
        evidenceReference: "matter-bookmark:bookmark-1",
      }),
    );
  });
});
