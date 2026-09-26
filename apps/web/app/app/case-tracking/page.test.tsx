import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchCaseTrackingStatusMock,
  searchTrackedCasesMock,
  resolveMatterCaseMock,
  searchMatterCasesMock,
  linkMatterCaseMock,
  createCaseTrackingBookmarkMock,
  fetchCaseTrackingSupportMatrixMock,
  listCaseTrackingBookmarksMock,
  updateCaseTrackingBookmarkMock,
  refreshCaseTrackingBookmarkMock,
  listCaseTrackingUpdatesMock,
} = vi.hoisted(() => ({
  fetchCaseTrackingStatusMock: vi.fn(),
  searchTrackedCasesMock: vi.fn(),
  resolveMatterCaseMock: vi.fn(),
  searchMatterCasesMock: vi.fn(),
  linkMatterCaseMock: vi.fn(),
  createCaseTrackingBookmarkMock: vi.fn(),
  fetchCaseTrackingSupportMatrixMock: vi.fn(),
  listCaseTrackingBookmarksMock: vi.fn(),
  updateCaseTrackingBookmarkMock: vi.fn(),
  refreshCaseTrackingBookmarkMock: vi.fn(),
  listCaseTrackingUpdatesMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchCaseTrackingStatus: fetchCaseTrackingStatusMock,
  fetchCaseTrackingSupportMatrix: fetchCaseTrackingSupportMatrixMock,
  searchTrackedCases: searchTrackedCasesMock,
  createCaseTrackingBookmark: createCaseTrackingBookmarkMock,
  listCaseTrackingBookmarks: listCaseTrackingBookmarksMock,
  updateCaseTrackingBookmark: updateCaseTrackingBookmarkMock,
  refreshCaseTrackingBookmark: refreshCaseTrackingBookmarkMock,
  listCaseTrackingUpdates: listCaseTrackingUpdatesMock,
}));

vi.mock("@/lib/api/case-tracking-matter-resolution", () => ({
  resolveMatterCase: resolveMatterCaseMock,
  searchMatterCases: searchMatterCasesMock,
  linkMatterCase: linkMatterCaseMock,
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("matterId=matter-1"),
}));

import CaseTrackingPage from "@/app/app/case-tracking/page";
import { ApiError } from "@/lib/api/config";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const bookmark = {
  id: "bm-1",
  company_id: "company-1",
  tracked_case_id: "tc-1",
  created_by_membership_id: "membership-1",
  matter_id: "matter-1",
  name: null,
  notification_enabled: true,
  is_archived: false,
  created_at: "2026-05-26T00:00:00Z",
  updated_at: "2026-05-26T00:00:00Z",
  archived_at: null,
  update_count: 1,
  tracked_case: {
    id: "tc-1",
    provider: "ecourtsindia",
    cnr_number: "DLHC010012342026",
    case_number: "WP(C) 1/2026",
    court_code: "DLHC",
    court_name: "Delhi High Court",
    case_title: "Example Petitioner v Example Respondent",
    party_names: ["Example Petitioner", "Example Respondent"],
    current_status: "Pending",
    current_stage: "Arguments",
    next_hearing_on: "2026-06-15",
    last_provider_checked_at: "2026-05-26T00:00:00Z",
    last_provider_attempted_at: "2026-05-26T00:00:00Z",
    last_provider_successful_at: "2026-05-26T00:00:00Z",
    next_provider_refresh_at: "2026-05-27T10:30:00Z",
    freshness_status: "fresh" as const,
    response_class: "no_change",
    last_operation_id: "operation-1",
    provider_health: "healthy" as const,
    manual_refresh_allowed: true,
    manual_refresh_disabled_reason: null,
    refresh_cost_minor: 10,
    refresh_currency: "INR",
    last_error: null,
    metadata: {},
  },
};

describe("CaseTrackingPage", () => {
  it("cancels stale Matter reads and invalidates every hearing surface after refresh", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const surfaces = [
      ["matters", "list", {}], ["matters", "dashboard-overview"],
      ["matters", "hearings-aggregate"], ["matters", "portfolio"],
      ["matters", "matter-1", "workspace"],
    ];
    for (const key of surfaces) client.setQueryData(key, { next_hearing_on: null });
    let finishOldRead!: (value: { next_hearing_on: string }) => void;
    const oldRead = client.fetchQuery({
      queryKey: surfaces[0],
      queryFn: () => new Promise<{ next_hearing_on: string }>(resolve => { finishOldRead = resolve; }),
    }).catch(() => undefined);
    listCaseTrackingBookmarksMock.mockResolvedValue({ bookmarks: [bookmark] });
    listCaseTrackingUpdatesMock.mockResolvedValue({ updates: [] });
    refreshCaseTrackingBookmarkMock.mockResolvedValue({ bookmark, created_update_count: 1 });
    render(<QueryClientProvider client={client}><CaseTrackingPage /></QueryClientProvider>);
    await userEvent.click(await screen.findByRole("button", { name: /^Refresh$/ }));
    await waitFor(() => {
      for (const key of surfaces) expect(client.getQueryState(key)?.isInvalidated).toBe(true);
    });
    finishOldRead({ next_hearing_on: "2026-01-01" });
    await oldRead;
    expect(client.getQueryData(surfaces[0])).toEqual({ next_hearing_on: null });
    expect(screen.queryByText(/Could not refresh/i)).not.toBeInTheDocument();
  });

  it("distinguishes scheduled QA exclusion from live human availability", async () => {
    fetchCaseTrackingStatusMock.mockResolvedValue({
      enabled: true, configured: true, provider: "ecourtsindia", reason: null,
      scheduled_sync_eligible: false, scheduled_sync_disabled_reason: "configured_test_tenant",
      scheduled_sync_local_time: "18:00", scheduled_sync_timezone: "Asia/Kolkata",
    });
    render(withClient(<CaseTrackingPage />));
    expect(await screen.findByRole("region", { name: "Scheduled hearing updates" })).toHaveTextContent("18:00 (Asia/Kolkata)");
    expect(screen.getByText(/Scheduled paid updates are excluded/)).toHaveTextContent("Human-initiated search and refresh remain available");
    await userEvent.type(screen.getByRole("textbox", { name: "CNR number" }), "DLHC010012342026");
    expect(screen.getByRole("button", { name: /^Search$/ })).toBeEnabled();
    expect(searchTrackedCasesMock).not.toHaveBeenCalled();
    expect(refreshCaseTrackingBookmarkMock).not.toHaveBeenCalled();
    expect(screen.queryByTestId("case-tracking-disabled")).not.toBeInTheDocument();
  });

  it("shows normal scheduled eligibility without claiming a provider refresh succeeded", async () => {
    fetchCaseTrackingStatusMock.mockResolvedValue({
      enabled: true, configured: true, provider: "ecourtsindia", reason: null,
      scheduled_sync_eligible: true, scheduled_sync_disabled_reason: null,
      scheduled_sync_local_time: "18:00", scheduled_sync_timezone: "Asia/Kolkata",
      scheduled_sync_window_end_local_time: "20:00",
    });
    render(withClient(<CaseTrackingPage />));
    expect(await screen.findByRole("region", { name: "Scheduled hearing updates" })).toHaveTextContent("Eligible for scheduled updates from uniquely matched court records.");
    expect(screen.getByRole("region", { name: "Scheduled hearing updates" })).toHaveTextContent("18:00-20:00 (Asia/Kolkata)");
    expect(screen.queryByText(/Scheduled paid updates are excluded/)).not.toBeInTheDocument();
  });

  beforeEach(() => {
    fetchCaseTrackingStatusMock.mockReset();
    searchTrackedCasesMock.mockReset();
    resolveMatterCaseMock.mockReset();
    searchMatterCasesMock.mockReset();
    linkMatterCaseMock.mockReset();
    createCaseTrackingBookmarkMock.mockReset();
    fetchCaseTrackingSupportMatrixMock.mockReset();
    listCaseTrackingBookmarksMock.mockReset();
    updateCaseTrackingBookmarkMock.mockReset();
    refreshCaseTrackingBookmarkMock.mockReset();
    listCaseTrackingUpdatesMock.mockReset();
    fetchCaseTrackingStatusMock.mockResolvedValue({
      enabled: true,
      provider: "ecourtsindia",
      configured: true,
      reason: null,
    });
    listCaseTrackingBookmarksMock.mockResolvedValue({ bookmarks: [] });
    fetchCaseTrackingSupportMatrixMock.mockResolvedValue({
      rows: [
        {
          id: "support-1",
          provider: "ecourtsindia",
          court: "Delhi High Court",
          bench_jurisdiction: "Delhi",
          lookup_method: "provider_api",
          rate_limit: "60/min",
          freshness_sla: "Daily",
          legal_tos_status: "approved",
          failure_code_mapping: {},
          enabled: true,
          status_notes: "Supported",
        },
      ],
    });
    listCaseTrackingUpdatesMock.mockResolvedValue({ updates: [] });
    createCaseTrackingBookmarkMock.mockResolvedValue(bookmark);
    linkMatterCaseMock.mockResolvedValue(bookmark);
    refreshCaseTrackingBookmarkMock.mockResolvedValue({
      bookmark,
      created_updates: [],
      delivery_status: "in_app_only",
    });
    updateCaseTrackingBookmarkMock.mockResolvedValue(bookmark);
  });

  it("shows disabled state and never searches when provider is unconfigured", async () => {
    const user = userEvent.setup();
    fetchCaseTrackingStatusMock.mockResolvedValue({
      enabled: false,
      provider: "disabled",
      configured: false,
      reason: "Case tracking is disabled.",
    });
    render(withClient(<CaseTrackingPage />));

    expect(await screen.findByTestId("case-tracking-disabled")).toBeInTheDocument();
    expect(screen.getByText("Delhi High Court / Delhi")).toBeInTheDocument();
    expect(screen.queryByText(/refresh cost/i)).not.toBeInTheDocument();
    expect(screen.getByText(/No provider calls made/i)).toBeInTheDocument();
    await user.type(screen.getByTestId("case-tracking-query"), "Example Petitioner");
    await user.type(screen.getByTestId("case-tracking-cnr"), "DLHC010012342026");
    expect(screen.getByTestId("case-tracking-query")).toHaveValue("Example Petitioner");
    expect(screen.getByTestId("case-tracking-cnr")).toHaveValue("DLHC010012342026");
    await user.click(screen.getByTestId("case-tracking-search-submit"));
    expect(searchTrackedCasesMock).not.toHaveBeenCalled();
  });

  it("resolves the saved Matter only after an explicit click and shows one verified candidate", async () => {
    resolveMatterCaseMock.mockResolvedValue({
      provider: "ecourtsindia",
      status: "matched",
      results: [{
        provider: "ecourtsindia",
        cnr_number: "DLHC010012342026",
        case_number: "WP(C) 1/2026",
        court_code: "DLHC",
        court_name: "Delhi High Court",
        case_title: "Example Petitioner v Example Respondent",
        party_names: ["Example Petitioner", "Example Respondent"],
        current_status: "Pending",
        current_stage: "Arguments",
        next_hearing_on: "2026-10-05",
        source_url: null,
        provenance_label: "Provider-normalized case status",
        link_token: "signed-selection-1",
        existing_matters: [],
        linked_to_matter: false,
      }],
    });
    render(withClient(<CaseTrackingPage />));
    const find = await screen.findByTestId("matter-case-resolve-submit");
    expect(resolveMatterCaseMock).not.toHaveBeenCalled();
    await userEvent.click(find);
    expect(resolveMatterCaseMock).toHaveBeenCalledWith("matter-1", expect.anything());
    expect(await screen.findByText("One case matches the Matter identifiers.")).toBeInTheDocument();
    expect(screen.getAllByTestId("matter-case-candidate")).toHaveLength(1);
    expect(screen.queryByRole("link", { name: /eCourts/i })).not.toBeInTheDocument();
    expect(linkMatterCaseMock).not.toHaveBeenCalled();
    await userEvent.click(screen.getByTestId("matter-case-link-submit"));
    expect(linkMatterCaseMock).toHaveBeenCalledWith(
      { matterId: "matter-1", linkToken: "signed-selection-1" },
      expect.anything(),
    );
    expect(await screen.findByTestId("matter-case-linked")).toHaveTextContent("Linked to this Matter.");
    expect(screen.getByRole("link", { name: "View Matter" })).toHaveAttribute("href", "/app/matters/matter-1");
  });

  it("keeps failed selection visible and offers a retry", async () => {
    resolveMatterCaseMock.mockResolvedValue({
      provider: "ecourtsindia", status: "matched",
      results: [{ provider: "ecourtsindia", cnr_number: "DLHC010012342026", case_number: "WP(C) 1/2026",
        court_code: "DLHC", court_name: "Delhi High Court", case_title: "Example case",
        party_names: [], current_status: "Pending", current_stage: null, next_hearing_on: null,
        source_url: null, link_token: "signed-selection-2", existing_matters: [], linked_to_matter: false }],
    });
    linkMatterCaseMock.mockRejectedValue(new ApiError(409, "Matter identity changed. Find the case again.", null));
    render(withClient(<CaseTrackingPage />));
    await userEvent.click(await screen.findByTestId("matter-case-resolve-submit"));
    await userEvent.click(await screen.findByTestId("matter-case-link-submit"));
    expect(await screen.findByTestId("matter-case-link-error")).toHaveTextContent("Matter identity changed");
    expect(screen.queryByTestId("matter-case-linked")).not.toBeInTheDocument();
    expect(screen.getByTestId("matter-case-link-submit")).toBeEnabled();
  });

  it.each([
    ["no_match", "No matching eCourts case found."],
    ["insufficient_identifiers", "Insufficient case identifiers."],
  ])("shows %s without inventing a destination", async (status, message) => {
    resolveMatterCaseMock.mockResolvedValue({ provider: "ecourtsindia", status, results: [] });
    render(withClient(<CaseTrackingPage />));
    await userEvent.click(await screen.findByTestId("matter-case-resolve-submit"));
    expect(await screen.findByText(new RegExp(message))).toBeInTheDocument();
    expect(screen.queryByTestId("matter-case-candidate")).not.toBeInTheDocument();
  });

  it("searches with Matter context, links signed result, and shows bookmark updates", async () => {
    const user = userEvent.setup();
    searchMatterCasesMock.mockResolvedValue({
      provider: "ecourtsindia",
      results: [
        {
          provider: "ecourtsindia",
          cnr_number: "DLHC010012342026",
          case_number: "WP(C) 1/2026",
          court_code: "DLHC",
          court_name: "Delhi High Court",
          case_title: "Example Petitioner v Example Respondent",
          party_names: ["Example Petitioner", "Example Respondent"],
          current_status: "Pending",
          current_stage: "Arguments",
          next_hearing_on: "2026-06-15",
          source_url: null,
          provenance_label: "Provider-normalized case status",
          link_token: "manual-search-selection",
          existing_matters: [],
          linked_to_matter: false,
        },
      ],
    });
    listCaseTrackingBookmarksMock.mockResolvedValue({ bookmarks: [bookmark] });
    listCaseTrackingUpdatesMock.mockResolvedValue({
      updates: [
        {
          id: "upd-1",
          company_id: "company-1",
          tracked_case_id: "tc-1",
          update_type: "new_order",
          source_record_key: "order:1",
          title: "Order dated 26 May 2026",
          summary: "Source-backed case update summary for lawyer review.",
          ai_summary: { review_framing: "Source-backed case update summary for lawyer review." },
          source_url: "/api/case-tracking/bookmarks/bm-1/updates/upd-1/source",
          order_date: "2026-05-26",
          hearing_date: null,
          provider_metadata: {},
          created_at: "2026-05-26T00:00:00Z",
        },
      ],
    });

    render(withClient(<CaseTrackingPage />));

    await user.type(await screen.findByTestId("case-tracking-query"), "Example Petitioner");
    await user.type(screen.getByTestId("case-tracking-cnr"), "DLHC010012342026");
    await user.click(screen.getByTestId("case-tracking-search-submit"));
    expect(searchMatterCasesMock.mock.calls[0][0]).toEqual({
      matterId: "matter-1",
      input: {
        query: "Example Petitioner",
        cnr_number: "DLHC010012342026",
        case_number: null,
        court_code: null,
      },
    });
    expect(
      await screen.findAllByText("Example Petitioner v Example Respondent"),
    ).not.toHaveLength(0);

    await user.click(screen.getByTestId("matter-search-link-submit"));
    expect(linkMatterCaseMock).toHaveBeenCalledWith(
      { matterId: "matter-1", linkToken: "manual-search-selection" },
      expect.anything(),
    );
    expect(createCaseTrackingBookmarkMock).not.toHaveBeenCalled();
    expect(await screen.findByTestId("matter-search-linked")).toBeInTheDocument();
    await user.click(screen.getAllByText("Example Petitioner v Example Respondent")[1]);
    expect(screen.getByTestId("case-tracking-bookmark-bm-1")).toBeInTheDocument();
    expect(await screen.findByText("Order dated 26 May 2026")).toBeInTheDocument();
    expect(screen.getByTestId("case-tracking-update-upd-1")).toBeInTheDocument();
    expect(screen.getAllByText(/lawyer review/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /Source/i })).toHaveAttribute(
      "href",
      "http://localhost:8000/api/case-tracking/bookmarks/bm-1/updates/upd-1/source",
    );
    expect(screen.getByText(/ecourtsindia · healthy/i)).toBeInTheDocument();
    expect(screen.getByText(/Refresh cost INR 0.10/i)).toBeInTheDocument();
    expect(screen.getByText(/Last good/i)).toBeInTheDocument();
    expect(
      screen.getByText(
        (content) => content.startsWith("Next ") && !content.startsWith("Next hearing"),
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Refresh/i }));
    expect(refreshCaseTrackingBookmarkMock.mock.calls[0][0]).toBe("bm-1");
    await user.click(screen.getByTitle("Disable notifications"));
    expect(updateCaseTrackingBookmarkMock.mock.calls[0][1]).toEqual({
      notification_enabled: false,
    });
  });

  it("does not offer a Matter link for a search result without server verification", async () => {
    searchMatterCasesMock.mockResolvedValue({
      provider: "ecourtsindia",
      results: [{ provider: "ecourtsindia", cnr_number: "DLHC010099992026",
        case_number: "WP(C) 99/2026", court_code: "DLHC", court_name: "Delhi High Court",
        case_title: "Different case", party_names: [], current_status: null,
        current_stage: null, next_hearing_on: null, source_url: null,
        provenance_label: "Provider-normalized case status", link_token: null,
        existing_matters: [], linked_to_matter: false }],
    });
    render(withClient(<CaseTrackingPage />));
    await userEvent.type(await screen.findByTestId("case-tracking-query"), "Different case");
    await userEvent.click(screen.getByTestId("case-tracking-search-submit"));
    expect(await screen.findByText("Does not match this Matter")).toBeInTheDocument();
    expect(screen.queryByTestId("matter-search-link-submit")).not.toBeInTheDocument();
    expect(createCaseTrackingBookmarkMock).not.toHaveBeenCalled();
  });

  it("disables manual refresh when provider health is red and preserves fallback guidance", async () => {
    listCaseTrackingBookmarksMock.mockResolvedValue({
      bookmarks: [
        {
          ...bookmark,
          tracked_case: {
            ...bookmark.tracked_case,
            freshness_status: "stale",
            provider_health: "unhealthy",
            manual_refresh_allowed: false,
            manual_refresh_disabled_reason: "Case tracking provider health is red.",
            last_error: "Provider authentication failed.",
          },
        },
      ],
    });

    render(withClient(<CaseTrackingPage />));

    const refresh = await screen.findByRole("button", { name: /Refresh/i });
    expect(refresh).toBeDisabled();
    expect(screen.getByText(/Provider authentication failed/i)).toBeInTheDocument();
    expect(screen.getByText(/manual docketing/i)).toBeInTheDocument();
  });

  it("shows a failed refresh and reloads the bookmark instead of keeping stale data", async () => {
    const user = userEvent.setup();
    const recoveryReason =
      "The provider is temporarily unavailable. Automatic recovery is scheduled for 2026-09-15T04:24:25+00:00.";
    listCaseTrackingBookmarksMock
      .mockResolvedValueOnce({ bookmarks: [bookmark] })
      .mockResolvedValue({
        bookmarks: [
          {
            ...bookmark,
            tracked_case: {
              ...bookmark.tracked_case,
              freshness_status: "stale",
              provider_health: "degraded",
              response_class: "provider_error",
              manual_refresh_allowed: false,
              manual_refresh_disabled_reason: recoveryReason,
              last_error: "Case tracking provider refresh failed.",
            },
          },
        ],
      });
    refreshCaseTrackingBookmarkMock.mockRejectedValue(
      new ApiError(502, "Case tracking provider refresh failed.", null, null),
    );
    render(withClient(<CaseTrackingPage />));

    await user.click(await screen.findByRole("button", { name: /^Refresh$/ }));

    expect(await screen.findByTestId("case-tracking-refresh-error")).toHaveTextContent(
      "Case tracking provider refresh failed.",
    );
    await waitFor(() => expect(listCaseTrackingBookmarksMock).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /^Refresh$/ })).toBeDisabled(),
    );
    expect(screen.getByText("provider_error")).toBeInTheDocument();
  });

  it("BUG-032: a case the Matter already tracks is shown as linked, never as unmatched", async () => {
    searchMatterCasesMock.mockResolvedValue({
      provider: "ecourtsindia",
      results: [{ provider: "ecourtsindia", cnr_number: "DLHC010317282019",
        case_number: "6209/2019", court_code: "DLHC01", court_name: "High Court of Delhi",
        case_title: "Satish Kumar Mehani v Punjab National Bank & ORS.",
        party_names: ["Satish Kumar Mehani", "Punjab National Bank & ORS."],
        current_status: "Pending", current_stage: null, next_hearing_on: null,
        source_url: null, provenance_label: "Provider-normalized case status",
        link_token: "signed-selection", linked_to_matter: true,
        existing_matters: [{ matter_id: "matter-1", matter_code: "M-1", title: "This matter", status: "active" }] }],
    });
    render(withClient(<CaseTrackingPage />));
    await userEvent.type(await screen.findByTestId("case-tracking-query"), "Mehani");
    await userEvent.click(screen.getByTestId("case-tracking-search-submit"));
    expect(await screen.findByTestId("matter-search-linked")).toHaveTextContent("Linked to this Matter");
    expect(screen.queryByTestId("matter-search-unmatched")).not.toBeInTheDocument();
    expect(screen.queryByTestId("matter-search-link-submit")).not.toBeInTheDocument();
    // The scoped Matter is represented by the linked state, not listed again.
    expect(screen.queryByTestId("existing-matter-open-matter-1")).not.toBeInTheDocument();
  });

  it("BUG-032: lists other visible Matters that record the same case with an open link", async () => {
    searchMatterCasesMock.mockResolvedValue({
      provider: "ecourtsindia",
      results: [{ provider: "ecourtsindia", cnr_number: "DLHC010317282019",
        case_number: "6209/2019", court_code: "DLHC01", court_name: "High Court of Delhi",
        case_title: "Satish Kumar Mehani v Punjab National Bank & ORS.", party_names: [],
        current_status: "Pending", current_stage: null, next_hearing_on: null,
        source_url: null, provenance_label: "Provider-normalized case status",
        link_token: "signed-selection", linked_to_matter: false,
        existing_matters: [{ matter_id: "matter-2", matter_code: "WP-6209", title: "Mehani appeal", status: "active" }] }],
    });
    render(withClient(<CaseTrackingPage />));
    await userEvent.type(await screen.findByTestId("case-tracking-query"), "Mehani");
    await userEvent.click(screen.getByTestId("case-tracking-search-submit"));
    const open = await screen.findByTestId("existing-matter-open-matter-2");
    expect(open).toHaveAttribute("href", "/app/matters/matter-2");
    expect(screen.getByRole("list", { name: "Existing matters for this case" })).toHaveTextContent(
      "WP-6209 - Mehani appeal",
    );
    expect(screen.getByTestId("matter-search-link-submit")).toBeInTheDocument();
    expect(screen.queryByTestId("matter-search-unmatched")).not.toBeInTheDocument();
  });

  it("BUG-042: shows an explicit empty-results message instead of nothing", async () => {
    const user = userEvent.setup();
    searchMatterCasesMock.mockResolvedValue({ provider: "ecourtsindia", results: [] });
    render(withClient(<CaseTrackingPage />));

    await user.type(await screen.findByTestId("case-tracking-query"), "No Such Party");
    await user.click(screen.getByTestId("case-tracking-search-submit"));

    expect(await screen.findByTestId("case-tracking-search-empty")).toHaveTextContent(
      /No cases matched your search/i,
    );
  });

  it("BUG-042: renders the backend error detail verbatim when search fails", async () => {
    const user = userEvent.setup();
    searchMatterCasesMock.mockRejectedValue(
      new ApiError(502, "eCourtsIndia provider returned an error.", null, null),
    );
    render(withClient(<CaseTrackingPage />));

    await user.type(await screen.findByTestId("case-tracking-query"), "Example Petitioner");
    await user.click(screen.getByTestId("case-tracking-search-submit"));

    expect(await screen.findByTestId("case-tracking-search-error")).toHaveTextContent(
      "eCourtsIndia provider returned an error.",
    );
  });
});
