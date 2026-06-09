import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchCaseTrackingStatusMock,
  searchTrackedCasesMock,
  createCaseTrackingBookmarkMock,
  listCaseTrackingBookmarksMock,
  updateCaseTrackingBookmarkMock,
  refreshCaseTrackingBookmarkMock,
  listCaseTrackingUpdatesMock,
} = vi.hoisted(() => ({
  fetchCaseTrackingStatusMock: vi.fn(),
  searchTrackedCasesMock: vi.fn(),
  createCaseTrackingBookmarkMock: vi.fn(),
  listCaseTrackingBookmarksMock: vi.fn(),
  updateCaseTrackingBookmarkMock: vi.fn(),
  refreshCaseTrackingBookmarkMock: vi.fn(),
  listCaseTrackingUpdatesMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchCaseTrackingStatus: fetchCaseTrackingStatusMock,
  searchTrackedCases: searchTrackedCasesMock,
  createCaseTrackingBookmark: createCaseTrackingBookmarkMock,
  listCaseTrackingBookmarks: listCaseTrackingBookmarksMock,
  updateCaseTrackingBookmark: updateCaseTrackingBookmarkMock,
  refreshCaseTrackingBookmark: refreshCaseTrackingBookmarkMock,
  listCaseTrackingUpdates: listCaseTrackingUpdatesMock,
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
    last_error: null,
    metadata: {},
  },
};

describe("CaseTrackingPage", () => {
  beforeEach(() => {
    fetchCaseTrackingStatusMock.mockReset();
    searchTrackedCasesMock.mockReset();
    createCaseTrackingBookmarkMock.mockReset();
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
    listCaseTrackingUpdatesMock.mockResolvedValue({ updates: [] });
    createCaseTrackingBookmarkMock.mockResolvedValue(bookmark);
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
    expect(screen.getByText(/No provider calls made/i)).toBeInTheDocument();
    await user.type(screen.getByTestId("case-tracking-query"), "Example Petitioner");
    await user.type(screen.getByTestId("case-tracking-cnr"), "DLHC010012342026");
    expect(screen.getByTestId("case-tracking-query")).toHaveValue("Example Petitioner");
    expect(screen.getByTestId("case-tracking-cnr")).toHaveValue("DLHC010012342026");
    await user.click(screen.getByTestId("case-tracking-search-submit"));
    expect(searchTrackedCasesMock).not.toHaveBeenCalled();
  });

  it("searches, bookmarks with matter context, and shows bookmark updates", async () => {
    const user = userEvent.setup();
    searchTrackedCasesMock.mockResolvedValue({
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
    expect(searchTrackedCasesMock.mock.calls[0][0]).toEqual({
      query: "Example Petitioner",
      cnr_number: "DLHC010012342026",
      case_number: null,
      court_code: null,
    });
    expect(
      await screen.findAllByText("Example Petitioner v Example Respondent"),
    ).not.toHaveLength(0);

    await user.click(screen.getAllByRole("button", { name: /Bookmark/i })[0]);
    expect(createCaseTrackingBookmarkMock.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        cnr_number: "DLHC010012342026",
        matter_id: "matter-1",
        metadata: {},
      }),
    );
    await user.click(screen.getAllByText("Example Petitioner v Example Respondent")[1]);
    expect(await screen.findByText("Order dated 26 May 2026")).toBeInTheDocument();
    expect(screen.getAllByText(/lawyer review/i).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: /Source/i })).toHaveAttribute(
      "href",
      "http://localhost:8000/api/case-tracking/bookmarks/bm-1/updates/upd-1/source",
    );

    await user.click(screen.getByRole("button", { name: /Refresh/i }));
    expect(refreshCaseTrackingBookmarkMock.mock.calls[0][0]).toBe("bm-1");
    await user.click(screen.getByTitle("Disable notifications"));
    expect(updateCaseTrackingBookmarkMock.mock.calls[0][1]).toEqual({
      notification_enabled: false,
    });
  });

  it("BUG-042: shows an explicit empty-results message instead of nothing", async () => {
    const user = userEvent.setup();
    searchTrackedCasesMock.mockResolvedValue({ provider: "ecourtsindia", results: [] });
    render(withClient(<CaseTrackingPage />));

    await user.type(await screen.findByTestId("case-tracking-query"), "No Such Party");
    await user.click(screen.getByTestId("case-tracking-search-submit"));

    expect(await screen.findByTestId("case-tracking-search-empty")).toHaveTextContent(
      /No cases matched your search/i,
    );
  });

  it("BUG-042: renders the backend error detail verbatim when search fails", async () => {
    const user = userEvent.setup();
    searchTrackedCasesMock.mockRejectedValue(
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
