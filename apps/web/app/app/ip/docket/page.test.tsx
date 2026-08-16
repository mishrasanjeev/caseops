import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  recordIpControlReviewExportMock,
  downloadControlReviewManifestMock,
  checkIpCalendarDriftMock,
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
  recordIpControlReviewExportMock: vi.fn(),
  downloadControlReviewManifestMock: vi.fn(),
  checkIpCalendarDriftMock: vi.fn(),
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
  recordIpControlReviewExport: recordIpControlReviewExportMock,
  checkIpCalendarDrift: checkIpCalendarDriftMock,
}));

vi.mock("@/lib/ip/control-review-manifest", () => ({
  downloadControlReviewManifest: downloadControlReviewManifestMock,
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
    recordIpControlReviewExportMock.mockReset();
    downloadControlReviewManifestMock.mockReset();
    checkIpCalendarDriftMock.mockReset();
    checkIpCalendarDriftMock.mockResolvedValue({
      checked_at: "2026-08-15T08:00:00Z",
      findings: [],
    });
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

  it("announces structured docket loaders without premature empty states", () => {
    fetchIpDailyDocketMock.mockReturnValue(new Promise(() => undefined));
    fetchIpAssignedCoverageMock.mockReturnValue(new Promise(() => undefined));

    render(withClient(<IpDailyDocketPage />));

    const escalations = screen.getByTestId("ip-docket-escalations-loading");
    expect(escalations).toHaveAttribute("role", "status");
    expect(escalations).toHaveAttribute("aria-live", "polite");
    expect(escalations).toHaveAttribute("aria-busy", "true");
    expect(within(escalations).getByText("Loading deadline escalations.")).toHaveClass(
      "sr-only",
    );

    const acknowledgements = screen.getByTestId("ip-docket-acknowledgements-loading");
    expect(acknowledgements).toHaveAttribute("role", "status");
    expect(acknowledgements).toHaveAttribute("aria-live", "polite");
    expect(
      within(acknowledgements).getByText("Loading your unacknowledged deadlines."),
    ).toHaveClass("sr-only");
    expect(screen.queryByText(/Nothing is escalating/)).not.toBeInTheDocument();
    expect(screen.queryByText(/acknowledged every deadline/)).not.toBeInTheDocument();
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
    // The user saw these deadlines by name a moment ago; a failure report that
    // refers to them by UUID cannot be matched up against that list.
    expect(
      within(rejected).getByText("BETA DEVICE · Renewal · due 1 Sept 2026"),
    ).toBeVisible();
    expect(within(rejected).queryByText(/cov-2/)).toBeNull();
    expect(within(rejected).getByText(/Changed since you loaded this page/)).toBeVisible();
  });

  it("keeps unique human labels for every rejection after selected rows become stale", async () => {
    const rows = [
      {
        coverage_id: "11111111-1111-4111-8111-111111111111",
        docket_id: "ip-1",
        docket_title: "SHARED MARK",
        docket_identifier: "TM 1001",
        deadline_title: "Renewal",
        due_on: "2026-08-20",
        days_until_due: 5,
        critical: false,
        acknowledged: false,
        coverage_status: "pending",
        transfer_pending: false,
        reassignment_version: 1,
      },
      {
        coverage_id: "22222222-2222-4222-8222-222222222222",
        docket_id: "ip-2",
        docket_title: "SHARED MARK",
        docket_identifier: "TM 1002",
        deadline_title: "Renewal",
        due_on: "2026-08-21",
        days_until_due: 6,
        critical: false,
        acknowledged: false,
        coverage_status: "pending",
        transfer_pending: false,
        reassignment_version: 2,
      },
      {
        coverage_id: "33333333-3333-4333-8333-333333333333",
        docket_id: "ip-3",
        docket_title: "SHARED MARK",
        docket_identifier: "TM 1003",
        deadline_title: "Renewal",
        due_on: "2026-08-22",
        days_until_due: 7,
        critical: false,
        acknowledged: false,
        coverage_status: "pending",
        transfer_pending: false,
        reassignment_version: 3,
      },
      {
        coverage_id: "44444444-4444-4444-8444-444444444444",
        docket_id: "ip-4",
        docket_title: "SHARED MARK",
        docket_identifier: "TM 1004",
        deadline_title: "Renewal",
        due_on: "2026-08-23",
        days_until_due: 8,
        critical: false,
        acknowledged: false,
        coverage_status: "pending",
        transfer_pending: false,
        reassignment_version: 4,
      },
      {
        coverage_id: "55555555-5555-4555-8555-555555555555",
        docket_id: "ip-5",
        docket_title: "SHARED MARK",
        docket_identifier: "TM 1005",
        deadline_title: "Renewal",
        due_on: "2026-08-24",
        days_until_due: 9,
        critical: false,
        acknowledged: false,
        coverage_status: "pending",
        transfer_pending: false,
        reassignment_version: 5,
      },
    ];
    fetchIpAssignedCoverageMock.mockResolvedValue({ coverages: rows });

    let resolveBulk!: (value: {
      acknowledged_count: number;
      rejected_count: number;
      outcomes: {
        coverage_id: string;
        acknowledged: boolean;
        reason: string;
        reassignment_version: number | null;
      }[];
    }) => void;
    bulkAcknowledgeIpCoverageMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveBulk = resolve;
        }),
    );

    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    render(
      <QueryClientProvider client={client}>
        <IpDailyDocketPage />
      </QueryClientProvider>,
    );

    await screen.findByTestId(`ip-docket-ack-${rows[4].coverage_id}`);
    const card = screen.getByTestId("ip-docket-acknowledge");
    fireEvent.click(within(card).getByRole("button", { name: "Select all 5" }));

    // Four selected ids disappear and the remaining row is renamed before
    // submit. The selection snapshots must remain authoritative.
    act(() => {
      client.setQueryData(["ip-assigned-coverage"], {
        coverages: [{ ...rows[0], docket_title: "RENAMED AFTER SELECTION" }],
      });
    });
    await waitFor(() =>
      expect(screen.queryByTestId(`ip-docket-ack-${rows[1].coverage_id}`)).toBeNull(),
    );

    fireEvent.click(within(card).getByRole("button", { name: "Acknowledge selected" }));
    await waitFor(() => expect(bulkAcknowledgeIpCoverageMock).toHaveBeenCalledTimes(1));
    expect(bulkAcknowledgeIpCoverageMock).toHaveBeenCalledWith({
      coverageIds: rows.map((row) => row.coverage_id),
      expectedVersions: {
        [rows[0].coverage_id]: 1,
        [rows[1].coverage_id]: 2,
        [rows[2].coverage_id]: 3,
        [rows[3].coverage_id]: 4,
        [rows[4].coverage_id]: 5,
      },
    });

    // The last visible row also disappears while the request is pending, and
    // the success refetch returns no rows.
    fetchIpAssignedCoverageMock.mockResolvedValue({ coverages: [] });
    act(() => {
      client.setQueryData(["ip-assigned-coverage"], { coverages: [] });
    });
    act(() => {
      resolveBulk({
        acknowledged_count: 0,
        rejected_count: 5,
        outcomes: [
          {
            coverage_id: rows[0].coverage_id,
            acknowledged: false,
            reason: "already_acknowledged",
            reassignment_version: 1,
          },
          {
            coverage_id: rows[1].coverage_id,
            acknowledged: false,
            reason: "not_found",
            reassignment_version: null,
          },
          {
            coverage_id: rows[2].coverage_id,
            acknowledged: false,
            reason: "not_responsible",
            reassignment_version: 3,
          },
          {
            coverage_id: rows[3].coverage_id,
            acknowledged: false,
            reason: "version_conflict",
            reassignment_version: 5,
          },
          {
            coverage_id: rows[4].coverage_id,
            acknowledged: false,
            reason: "transfer_pending",
            reassignment_version: 5,
          },
        ],
      });
    });

    const rejected = await screen.findByTestId("ip-docket-ack-rejected");
    for (const [index, row] of rows.entries()) {
      expect(
        within(rejected).getByText(
          `SHARED MARK (${row.docket_identifier}) · Renewal · due ${20 + index} Aug 2026`,
        ),
      ).toBeVisible();
    }
    for (const reason of [
      "Already acknowledged",
      "No longer available to you",
      "You are not the responsible member",
      "Changed since you loaded this page",
      "A transfer decision is outstanding",
    ]) {
      expect(rejected).toHaveTextContent(reason);
    }
    expect(rejected).not.toHaveTextContent(/[0-9a-f]{8}-[0-9a-f-]{27,}/i);
    expect(rejected).not.toHaveTextContent("RENAMED AFTER SELECTION");
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

  it("refuses sign-off while a complete review still has mandatory exceptions", async () => {
    createIpControlReviewMock.mockResolvedValue({
      ...REVIEW,
      mandatory_exceptions: [{ docket_id: "ip-9", kind: "uncovered", critical: true }],
    });

    render(withClient(<IpDailyDocketPage />));

    const card = await screen.findByTestId("ip-docket-control-review");
    fireEvent.click(within(card).getByRole("button", { name: "Generate control review" }));

    expect(await within(card).findByTestId("ip-docket-review-blocked")).toHaveTextContent(
      "Resolve every mandatory exception and generate a clean review before signing.",
    );
    expect(within(card).queryByRole("button", { name: "Sign off" })).toBeNull();
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
    expect(screen.queryByTestId("ip-docket-drift")).toBeNull();

    // Generating a review persists an immutable record and audit event, so it
    // is a write just like recording its export.
    const card = screen.getByTestId("ip-docket-control-review");
    expect(within(card).queryByRole("button", { name: "Generate control review" })).toBeNull();
    expect(
      within(card).getByText(
        "Your role can view the docket but cannot create a control-review record.",
      ),
    ).toBeVisible();
    expect(createIpControlReviewMock).not.toHaveBeenCalled();
    expect(within(card).queryByRole("button", { name: "Sign off" })).toBeNull();
    // Recording an export is a write too, so that control is absent as well.
    expect(within(card).queryByTestId("ip-docket-review-export")).toBeNull();
  });

  it("produces the manifest before reporting the export succeeded", async () => {
    // The API only records the outcome, so reporting "generated" without having
    // produced a document would claim an export that never happened.
    createIpControlReviewMock.mockResolvedValue(REVIEW);
    recordIpControlReviewExportMock.mockResolvedValue({
      ...REVIEW,
      export_status: "generated",
      version: 2,
    });

    render(withClient(<IpDailyDocketPage />));

    const card = await screen.findByTestId("ip-docket-control-review");
    fireEvent.click(within(card).getByRole("button", { name: "Generate control review" }));

    const exportButton = await within(card).findByTestId("ip-docket-review-export");
    fireEvent.click(exportButton);

    await waitFor(() => expect(recordIpControlReviewExportMock).toHaveBeenCalledTimes(1));
    expect(downloadControlReviewManifestMock).toHaveBeenCalledTimes(1);
    expect(recordIpControlReviewExportMock).toHaveBeenCalledWith("review-1", {
      outcome: "generated",
    });
  });

  it("records a failure, and blocks sign-off, when the manifest cannot be produced", async () => {
    createIpControlReviewMock.mockResolvedValue(REVIEW);
    downloadControlReviewManifestMock.mockImplementation(() => {
      throw new Error("blob unavailable");
    });
    recordIpControlReviewExportMock.mockResolvedValue({
      ...REVIEW,
      export_status: "failed",
      export_error_redacted: "The manifest could not be produced in this browser.",
      version: 2,
    });

    render(withClient(<IpDailyDocketPage />));

    const card = await screen.findByTestId("ip-docket-control-review");
    fireEvent.click(within(card).getByRole("button", { name: "Generate control review" }));
    fireEvent.click(await within(card).findByTestId("ip-docket-review-export"));

    await waitFor(() => expect(recordIpControlReviewExportMock).toHaveBeenCalledTimes(1));
    expect(recordIpControlReviewExportMock).toHaveBeenCalledWith("review-1", {
      outcome: "failed",
      errorRedacted: "The manifest could not be produced in this browser.",
    });
    // The recorded failure is kept and shown, not discarded for a toast.
    expect(await within(card).findByTestId("ip-docket-review-blocked")).toHaveTextContent(
      "The last export failed, so this review cannot be signed. Export it again.",
    );
    expect(within(card).queryByRole("button", { name: "Sign off" })).toBeNull();
  });

  it("does not offer to re-export a signed review", async () => {
    createIpControlReviewMock.mockResolvedValue({
      ...REVIEW,
      signed_off_at: "2026-08-15T07:00:00Z",
      signer_label_snapshot: "Priya Raghavan",
    });

    render(withClient(<IpDailyDocketPage />));

    const card = await screen.findByTestId("ip-docket-control-review");
    fireEvent.click(within(card).getByRole("button", { name: "Generate control review" }));

    // The API refuses re-export of a signed review, so the control is absent
    // rather than present and failing.
    expect(await within(card).findByTestId("ip-docket-review-signed")).toBeVisible();
    expect(within(card).queryByTestId("ip-docket-review-export")).toBeNull();
  });

  it("reports a drifted calendar copy, and never rewrites it silently", async () => {
    // UJ-62-EXC-03: the copy sits in someone's own calendar, so a change is
    // surfaced rather than repaired behind their back.
    checkIpCalendarDriftMock.mockResolvedValue({
      checked_at: "2026-08-15T08:00:00Z",
      findings: [
        {
          sync_id: "sync-1",
          connection_id: "conn-1",
          membership_id: "member-1",
          source_type: "matter_deadline",
          source_id: "deadline-1",
          ip_docket_id: "ip-1",
          drift_status: "moved",
          detail: "The event was moved away from the CaseOps date.",
        },
        {
          sync_id: "sync-2",
          connection_id: "conn-2",
          membership_id: "member-2",
          source_type: "matter_deadline",
          source_id: "deadline-2",
          ip_docket_id: "ip-2",
          drift_status: "unknown",
          detail: "The calendar connection could not be read.",
        },
      ],
    });

    render(withClient(<IpDailyDocketPage />));

    const card = await screen.findByTestId("ip-docket-drift");
    fireEvent.click(within(card).getByRole("button", { name: "Check calendar copies" }));

    const findings = await within(card).findByTestId("ip-docket-drift-findings");
    expect(within(findings).getByText("Moved away from the CaseOps date")).toBeVisible();
    // "unknown" is its own outcome, never folded in with the healthy ones.
    expect(within(findings).getByText("Could not be checked")).toBeVisible();
    expect(within(findings).getByText("Unverified")).toBeVisible();
    expect(
      within(card).getByText(/could not be read, so it is unverified rather than confirmed/),
    ).toBeVisible();
  });

  it("says plainly when every copy still matches", async () => {
    render(withClient(<IpDailyDocketPage />));

    const card = await screen.findByTestId("ip-docket-drift");
    fireEvent.click(within(card).getByRole("button", { name: "Check calendar copies" }));

    expect(await within(card).findByTestId("ip-docket-drift-clean")).toHaveTextContent(
      "Every projected event matched when checked",
    );
  });
});
