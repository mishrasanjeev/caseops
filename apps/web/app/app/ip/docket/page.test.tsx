import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchIpDailyDocketMock,
  fetchIpAssignedCoverageMock,
  fetchIpDocketQueuesMock,
  bulkAcknowledgeIpCoverageMock,
  saveIpDocketQueueMock,
  deleteIpDocketQueueMock,
  createIpControlReviewMock,
  signOffIpControlReviewMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  fetchIpDailyDocketMock: vi.fn(),
  fetchIpAssignedCoverageMock: vi.fn(),
  fetchIpDocketQueuesMock: vi.fn(),
  bulkAcknowledgeIpCoverageMock: vi.fn(),
  saveIpDocketQueueMock: vi.fn(),
  deleteIpDocketQueueMock: vi.fn(),
  createIpControlReviewMock: vi.fn(),
  signOffIpControlReviewMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchIpDailyDocket: fetchIpDailyDocketMock,
  fetchIpAssignedCoverage: fetchIpAssignedCoverageMock,
  fetchIpDocketQueues: fetchIpDocketQueuesMock,
  bulkAcknowledgeIpCoverage: bulkAcknowledgeIpCoverageMock,
  saveIpDocketQueue: saveIpDocketQueueMock,
  deleteIpDocketQueue: deleteIpDocketQueueMock,
  createIpControlReview: createIpControlReviewMock,
  signOffIpControlReview: signOffIpControlReviewMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import IpDailyDocketPage from "@/app/app/ip/docket/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const FRESH_DOCKET = {
  generated_at: "2026-08-15T06:30:00Z",
  filters: {},
  stale_sources: [],
  counts_are_complete: true,
  queues: [
    {
      membership_id: "member-1",
      label: "Priya Raghavan",
      active: true,
      capacity_state: "available" as const,
      assigned_count: 12,
      critical_count: 3,
      unacknowledged_count: 2,
    },
    {
      membership_id: "member-2",
      label: "Anand Rao",
      active: false,
      capacity_state: "unavailable" as const,
      assigned_count: 4,
      critical_count: 0,
      unacknowledged_count: 4,
    },
  ],
  escalations: [],
};

const REVIEW = {
  id: "review-1",
  generated_at: "2026-08-15T06:31:00Z",
  filters: {},
  freshness: {},
  completeness_status: "complete",
  incompleteness_reasons: [] as string[],
  mandatory_exceptions: [] as { docket_id: string; kind: string; critical: boolean }[],
  manifest_sha256: "a".repeat(64),
  export_status: "not_requested",
  export_error_redacted: null,
  signer_label_snapshot: null,
  signed_off_at: null,
  version: 1,
  report: {
    generated_at: "2026-08-15T06:31:00Z",
    docket_count: 18,
    ready_count: 15,
    uncovered_deadline_count: 1,
    open_incident_count: 0,
    unprojected_calendar_count: 2,
    inactive_coverage_count: 1,
    total_cost_minor_by_currency: {},
  },
};

describe("IpDailyDocketPage", () => {
  beforeEach(() => {
    fetchIpDailyDocketMock.mockReset();
    fetchIpAssignedCoverageMock.mockReset();
    fetchIpDocketQueuesMock.mockReset();
    bulkAcknowledgeIpCoverageMock.mockReset();
    saveIpDocketQueueMock.mockReset();
    deleteIpDocketQueueMock.mockReset();
    createIpControlReviewMock.mockReset();
    signOffIpControlReviewMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    fetchIpDailyDocketMock.mockResolvedValue(FRESH_DOCKET);
    fetchIpAssignedCoverageMock.mockResolvedValue({ coverages: [] });
    fetchIpDocketQueuesMock.mockResolvedValue({ queues: [] });
  });

  it("fails closed when the role cannot read IP records", () => {
    useCapabilityMock.mockReturnValue(false);

    render(withClient(<IpDailyDocketPage />));

    expect(screen.getByText("You do not have access to the IP docket")).toBeVisible();
    expect(fetchIpDailyDocketMock).not.toHaveBeenCalled();
  });

  it("shows generation time, filters and freshness with the workload", async () => {
    render(withClient(<IpDailyDocketPage />));

    // The card renders "Generating…" first; wait for the resolved stamp.
    expect(await screen.findByText(/^Generated /)).toBeVisible();
    const provenance = screen.getByTestId("ip-docket-provenance");
    expect(within(provenance).getByText("No filters applied")).toBeVisible();
    expect(within(provenance).getByText("All sources current")).toBeVisible();

    const capacity = screen.getByTestId("ip-docket-capacity");
    const priya = within(capacity).getByTestId("ip-docket-queue-member-1");
    expect(within(priya).getByText("12")).toBeVisible();
    const anand = within(capacity).getByTestId("ip-docket-queue-member-2");
    expect(within(anand).getByText("Unavailable")).toBeVisible();
  });

  it("renders unknown, never zero, when a source is stale", async () => {
    // UJ-50-EXC-03: the API returns null rather than 0 so that unknown work is
    // not reported as no work. A UI that renders null as 0 silently undoes it.
    fetchIpDailyDocketMock.mockResolvedValue({
      ...FRESH_DOCKET,
      stale_sources: ["matter_deadlines"],
      counts_are_complete: false,
      queues: [
        {
          membership_id: "member-1",
          label: "Priya Raghavan",
          active: true,
          capacity_state: "available" as const,
          assigned_count: null,
          critical_count: null,
          unacknowledged_count: null,
        },
      ],
    });

    render(withClient(<IpDailyDocketPage />));

    const row = await screen.findByTestId("ip-docket-queue-member-1");
    expect(within(row).getAllByText("Unknown")).toHaveLength(3);
    expect(within(row).queryByText("0")).toBeNull();

    const provenance = screen.getByTestId("ip-docket-provenance");
    expect(within(provenance).getByText(/1 stale source — counts unavailable/)).toBeVisible();
  });

  it("acknowledges selected deadlines and names every one it could not", async () => {
    fetchIpAssignedCoverageMock.mockResolvedValue({
      coverages: [
        {
          coverage_id: "cov-1",
          docket_id: "ip-1",
          docket_title: "ACME WORDMARK",
          docket_identifier: "TM 4412330",
          deadline_title: "Opposition reply",
          due_on: "2026-08-20",
          days_until_due: 5,
          critical: true,
          acknowledged: false,
          coverage_status: "pending",
          transfer_pending: false,
          reassignment_version: 2,
        },
        {
          coverage_id: "cov-2",
          docket_id: "ip-2",
          docket_title: "BETA DEVICE",
          docket_identifier: null,
          deadline_title: "Renewal",
          due_on: "2026-09-01",
          days_until_due: 17,
          critical: false,
          acknowledged: false,
          coverage_status: "pending",
          transfer_pending: false,
          reassignment_version: 1,
        },
      ],
    });
    bulkAcknowledgeIpCoverageMock.mockResolvedValue({
      acknowledged_count: 1,
      rejected_count: 1,
      outcomes: [
        { coverage_id: "cov-1", acknowledged: true, reason: "acknowledged", reassignment_version: 2 },
        {
          coverage_id: "cov-2",
          acknowledged: false,
          reason: "version_conflict",
          reassignment_version: 3,
        },
      ],
    });

    render(withClient(<IpDailyDocketPage />));

    // Wait for the rows themselves; the card renders a loading state first.
    await screen.findByTestId("ip-docket-ack-cov-1");
    const card = screen.getByTestId("ip-docket-acknowledge");
    // Soonest first, and the version each row was read at is fenced.
    fireEvent.click(within(card).getByRole("button", { name: "Select all 2" }));
    fireEvent.click(within(card).getByRole("button", { name: "Acknowledge selected" }));

    await waitFor(() => expect(bulkAcknowledgeIpCoverageMock).toHaveBeenCalledTimes(1));
    expect(bulkAcknowledgeIpCoverageMock).toHaveBeenCalledWith({
      coverageIds: ["cov-1", "cov-2"],
      expectedVersions: { "cov-1": 2, "cov-2": 1 },
    });

    // A row that did not acknowledge must never look like one that did.
    const rejected = await screen.findByTestId("ip-docket-ack-rejected");
    expect(within(rejected).getByText(/cov-2/)).toBeVisible();
    expect(within(rejected).getByText(/Changed since you loaded this page/)).toBeVisible();
  });

  it("does not offer to acknowledge a deadline with an outstanding transfer", async () => {
    fetchIpAssignedCoverageMock.mockResolvedValue({
      coverages: [
        {
          coverage_id: "cov-3",
          docket_id: "ip-3",
          docket_title: "GAMMA MARK",
          docket_identifier: null,
          deadline_title: "Statement of use",
          due_on: "2026-08-25",
          days_until_due: 10,
          critical: false,
          acknowledged: false,
          coverage_status: "transfer_pending",
          transfer_pending: true,
          reassignment_version: 4,
        },
      ],
    });

    render(withClient(<IpDailyDocketPage />));

    const row = await screen.findByTestId("ip-docket-ack-cov-3");
    expect(within(row).getByRole("checkbox", { hidden: false })).toBeDisabled();
    expect(within(row).getByText(/transfer decision is outstanding/)).toBeVisible();
    // Nothing selectable, so the bulk action cannot quietly skip it.
    const card = screen.getByTestId("ip-docket-acknowledge");
    expect(within(card).getByRole("button", { name: "Select all 0" })).toBeDisabled();
  });

  it("refuses sign-off while the review is incomplete and says why", async () => {
    createIpControlReviewMock.mockResolvedValue({
      ...REVIEW,
      completeness_status: "incomplete",
      incompleteness_reasons: ["matter_deadlines is stale"],
      mandatory_exceptions: [{ docket_id: "ip-9", kind: "uncovered", critical: true }],
    });

    render(withClient(<IpDailyDocketPage />));

    const card = await screen.findByTestId("ip-docket-control-review");
    fireEvent.click(within(card).getByRole("button", { name: "Generate control review" }));

    expect(await within(card).findByTestId("ip-docket-review-blocked")).toHaveTextContent(
      "This review is incomplete, so it cannot be signed.",
    );
    expect(within(card).queryByRole("button", { name: "Sign off" })).toBeNull();
    // An exception cannot be filtered away or cleared by signing.
    expect(within(card).getByTestId("ip-docket-review-exceptions")).toHaveTextContent(
      "Deadline has no coverage",
    );
  });

  it("signs off a complete review with an attestation", async () => {
    createIpControlReviewMock.mockResolvedValue(REVIEW);
    signOffIpControlReviewMock.mockResolvedValue({
      ...REVIEW,
      version: 2,
      signed_off_at: "2026-08-15T07:00:00Z",
      signer_label_snapshot: "Priya Raghavan",
    });

    render(withClient(<IpDailyDocketPage />));

    const card = await screen.findByTestId("ip-docket-control-review");
    fireEvent.click(within(card).getByRole("button", { name: "Generate control review" }));

    const sign = await within(card).findByRole("button", { name: "Sign off" });
    // The attestation is the substance of a sign-off, not paperwork round it.
    expect(sign).toBeDisabled();
    fireEvent.change(within(card).getByLabelText("What are you attesting to?"), {
      target: { value: "Reviewed every exception on today's docket." },
    });
    expect(sign).toBeEnabled();
    fireEvent.click(sign);

    await waitFor(() => expect(signOffIpControlReviewMock).toHaveBeenCalledTimes(1));
    expect(signOffIpControlReviewMock).toHaveBeenCalledWith("review-1", {
      expectedVersion: 1,
      attestation: "Reviewed every exception on today's docket.",
    });
    expect(await within(card).findByTestId("ip-docket-review-signed")).toHaveTextContent(
      "Priya Raghavan",
    );
  });

  it("saves the current filters as a reusable queue", async () => {
    saveIpDocketQueueMock.mockResolvedValue({
      id: "queue-1",
      name: "Critical this week",
      description: null,
      filters: { team: "tm-bench" },
      team_id: null,
      owner_membership_id: "member-1",
      scope: "personal",
      created_at: "2026-08-15T06:00:00Z",
      updated_at: "2026-08-15T06:00:00Z",
    });

    render(withClient(<IpDailyDocketPage />));

    // Apply a filter first, so the saved queue captures what is on screen.
    const provenance = await screen.findByTestId("ip-docket-provenance");
    fireEvent.change(within(provenance).getByLabelText("Team filter"), {
      target: { value: "tm-bench" },
    });
    fireEvent.click(within(provenance).getByRole("button", { name: "Apply filter" }));

    const queues = screen.getByTestId("ip-docket-queues");
    const save = within(queues).getByRole("button", { name: "Save queue" });
    expect(save).toBeDisabled();
    fireEvent.change(within(queues).getByLabelText("Save current filters as"), {
      target: { value: "Critical this week" },
    });
    fireEvent.click(save);

    await waitFor(() => expect(saveIpDocketQueueMock).toHaveBeenCalledTimes(1));
    expect(saveIpDocketQueueMock).toHaveBeenCalledWith({
      name: "Critical this week",
      filters: { team: "tm-bench" },
    });
  });

  it("hides controls the API would refuse for a read-only member", async () => {
    // The gates must mirror the API: daily docket is ip:read, acting on
    // coverage or queues is ip:write, signing off is ip:approve. Showing a
    // control that 403s is worse than hiding it.
    useCapabilityMock.mockImplementation((capability: string) => capability === "ip:read");

    render(withClient(<IpDailyDocketPage />));

    expect(await screen.findByTestId("ip-docket-capacity")).toBeVisible();
    expect(screen.queryByTestId("ip-docket-acknowledge")).toBeNull();
    expect(screen.queryByTestId("ip-docket-queues")).toBeNull();

    // The review can be generated with ip:read, but not signed without approve.
    const card = screen.getByTestId("ip-docket-control-review");
    createIpControlReviewMock.mockResolvedValue(REVIEW);
    fireEvent.click(within(card).getByRole("button", { name: "Generate control review" }));
    expect(
      await within(card).findByText("Your role cannot sign off a control review."),
    ).toBeVisible();
    expect(within(card).queryByRole("button", { name: "Sign off" })).toBeNull();
  });
});
