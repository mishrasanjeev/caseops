import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  listStatutesMock,
  listLegalUpdateWatchlistsMock,
  createLegalUpdateWatchlistMock,
  updateLegalUpdateWatchlistMock,
  runLegalUpdateWatchlistMock,
  listLegalUpdatesMock,
  updateLegalUpdateMock,
  fetchLegalUpdateDigestPreviewMock,
  listLegalUpdateSourceRecordsMock,
  runLegalUpdateSourceSyncMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  listStatutesMock: vi.fn(),
  listLegalUpdateWatchlistsMock: vi.fn(),
  createLegalUpdateWatchlistMock: vi.fn(),
  updateLegalUpdateWatchlistMock: vi.fn(),
  runLegalUpdateWatchlistMock: vi.fn(),
  listLegalUpdatesMock: vi.fn(),
  updateLegalUpdateMock: vi.fn(),
  fetchLegalUpdateDigestPreviewMock: vi.fn(),
  listLegalUpdateSourceRecordsMock: vi.fn(),
  runLegalUpdateSourceSyncMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listStatutes: listStatutesMock,
  listLegalUpdateWatchlists: listLegalUpdateWatchlistsMock,
  createLegalUpdateWatchlist: createLegalUpdateWatchlistMock,
  updateLegalUpdateWatchlist: updateLegalUpdateWatchlistMock,
  runLegalUpdateWatchlist: runLegalUpdateWatchlistMock,
  listLegalUpdates: listLegalUpdatesMock,
  updateLegalUpdate: updateLegalUpdateMock,
  fetchLegalUpdateDigestPreview: fetchLegalUpdateDigestPreviewMock,
  listLegalUpdateSourceRecords: listLegalUpdateSourceRecordsMock,
  runLegalUpdateSourceSync: runLegalUpdateSourceSyncMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

import StatutesIndexPage from "@/app/app/statutes/page";
import { ApiError } from "@/lib/api/config";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("StatutesIndexPage", () => {
  beforeEach(() => {
    listStatutesMock.mockReset();
    listLegalUpdateWatchlistsMock.mockReset();
    createLegalUpdateWatchlistMock.mockReset();
    updateLegalUpdateWatchlistMock.mockReset();
    runLegalUpdateWatchlistMock.mockReset();
    listLegalUpdatesMock.mockReset();
    updateLegalUpdateMock.mockReset();
    fetchLegalUpdateDigestPreviewMock.mockReset();
    listLegalUpdateSourceRecordsMock.mockReset();
    runLegalUpdateSourceSyncMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation(() => true);
    listLegalUpdateWatchlistsMock.mockResolvedValue({ watchlists: [] });
    createLegalUpdateWatchlistMock.mockResolvedValue({
      id: "wl-new",
      company_id: "company-1",
      name: "Created",
      practice_area: null,
      statute_id: null,
      jurisdiction: null,
      statute_terms: ["Section 138"],
      source_key: null,
      source_category: null,
      update_types: ["amendment", "notification", "order", "practice_direction"],
      since_date: null,
      until_date: null,
      matter_id: null,
      contract_id: null,
      is_archived: false,
      created_by_membership_id: "membership-1",
      created_at: "2026-05-24T00:00:00Z",
      updated_at: "2026-05-24T00:00:00Z",
      archived_at: null,
    });
    updateLegalUpdateWatchlistMock.mockResolvedValue({});
    runLegalUpdateWatchlistMock.mockResolvedValue({
      watchlist_id: "wl-1",
      preview_only: false,
      matched_count: 1,
      created_count: 1,
      matches: [],
      delivery_status: "in_app_only",
    });
    listLegalUpdatesMock.mockResolvedValue({ updates: [] });
    updateLegalUpdateMock.mockResolvedValue({});
    fetchLegalUpdateDigestPreviewMock.mockResolvedValue({
      generated_at: "2026-05-24T00:00:00Z",
      unread_count: 0,
      dismissed_count: 0,
      updates: [],
      delivery_status: "in_app_only",
      delivery_note:
        "In-app preview only. External legal update delivery requires provider-specific approval.",
    });
    listLegalUpdateSourceRecordsMock.mockResolvedValue({ records: [] });
    runLegalUpdateSourceSyncMock.mockResolvedValue({
      id: "run-1",
      source_key: "prs_acts_parliament",
      status: "completed",
      started_at: "2026-05-26T00:00:00Z",
      completed_at: "2026-05-26T00:00:01Z",
      fetched_count: 1,
      created_count: 1,
      changed_count: 0,
      error_message: null,
      metadata: {},
    });
  });

  it("renders an Act tile for each seeded statute", async () => {
    listStatutesMock.mockResolvedValue({
      statutes: [
        {
          id: "bnss-2023",
          short_name: "BNSS",
          long_name: "Bharatiya Nagarik Suraksha Sanhita, 2023",
          enacted_year: 2023,
          jurisdiction: "india",
          source_url: "https://www.indiacode.nic.in/handle/123456789/20062",
          section_count: 17,
        },
      ],
      total_section_count: 17,
    });
    render(withClient(<StatutesIndexPage />));
    expect(
      await screen.findByTestId("statute-tile-bnss-2023"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Bharatiya Nagarik Suraksha Sanhita/i),
    ).toBeInTheDocument();
    // "17 sections" appears in both the page header description
    // (total_section_count) and the per-tile section_count badge.
    // Anchor on the link inside the BNSS tile to disambiguate.
    const browseLinks = screen.getAllByRole("link", {
      name: /Browse sections/i,
    });
    expect(browseLinks[0]).toHaveAttribute("href", "/app/statutes/bnss-2023");
  });

  it("shows the empty state when no acts seeded", async () => {
    listStatutesMock.mockResolvedValue({ statutes: [], total_section_count: 0 });
    render(withClient(<StatutesIndexPage />));
    expect(
      await screen.findByText(/No statutes seeded yet/i),
    ).toBeInTheDocument();
  });

  it("surfaces an error state when the endpoint throws", async () => {
    listStatutesMock.mockRejectedValue(new Error("network"));
    render(withClient(<StatutesIndexPage />));
    expect(
      await screen.findByText(/Could not load statutes/i),
    ).toBeInTheDocument();
  });

  it("supports in-app legal update watchlists and update actions", async () => {
    const user = userEvent.setup();
    listStatutesMock.mockResolvedValue({
      statutes: [
        {
          id: "ni-act-1881",
          short_name: "NI Act",
          long_name: "Negotiable Instruments Act, 1881",
          enacted_year: 1881,
          jurisdiction: "india",
          source_url: "https://www.indiacode.nic.in/handle/123456789/2187",
          section_count: 1,
        },
      ],
      total_section_count: 1,
    });
    listLegalUpdateWatchlistsMock.mockResolvedValue({
      watchlists: [
        {
          id: "wl-1",
          company_id: "company-1",
          name: "Section 138 monitor",
          practice_area: null,
          statute_id: null,
          jurisdiction: null,
          statute_terms: ["Section 138"],
          source_key: null,
          source_category: null,
          update_types: ["amendment", "notification"],
          since_date: null,
          until_date: null,
          matter_id: null,
          contract_id: null,
          is_archived: false,
          created_by_membership_id: "membership-1",
          created_at: "2026-05-24T00:00:00Z",
          updated_at: "2026-05-24T00:00:00Z",
          archived_at: null,
        },
      ],
    });
    listLegalUpdatesMock.mockResolvedValue({
      updates: [
        {
          id: "upd-1",
          company_id: "company-1",
          watchlist_id: "wl-1",
          source_record_id: "src-1",
          update_type: "notification",
          title: "Registry notification",
          statute_id: null,
          statute_section_id: null,
          authority_document_id: "auth-1",
          matter_id: null,
          contract_id: null,
          statute_name: null,
          section_number: null,
          jurisdiction: "Supreme Court of India",
          source_key: "supreme_court_latest_orders",
          source_category: "supreme_court",
          source_url: "https://www.sci.gov.in/notice",
          provenance_status: "ingest_ready",
          relevance_explanation: "Matched statute/section terms against existing authority/source metadata.",
          effective_date: null,
          published_date: null,
          decision_date: "2026-05-20",
          snippet: "Bounded registry notification preview.",
          summary: null,
          is_read: false,
          read_at: null,
          dismissed_at: null,
          created_at: "2026-05-24T00:00:00Z",
        },
      ],
    });
    fetchLegalUpdateDigestPreviewMock.mockResolvedValue({
      generated_at: "2026-05-24T00:00:00Z",
      unread_count: 1,
      dismissed_count: 0,
      updates: [],
      delivery_status: "in_app_only",
      delivery_note:
        "In-app preview only. External legal update delivery requires provider-specific approval.",
    });

    render(withClient(<StatutesIndexPage />));

    expect(await screen.findByTestId("legal-update-center")).toBeInTheDocument();
    await user.type(screen.getByTestId("legal-update-name"), "NI Act updates");
    await user.type(screen.getByTestId("legal-update-terms"), "Section 138");
    await user.click(screen.getByTestId("legal-update-create"));
    expect(createLegalUpdateWatchlistMock.mock.calls[0][0]).toEqual(
      expect.objectContaining({
        name: "NI Act updates",
        statute_terms: ["Section 138"],
      }),
    );

    await user.click(await screen.findByTestId("legal-update-run-wl-1"));
    expect(runLegalUpdateWatchlistMock.mock.calls[0][0]).toEqual({
      watchlistId: "wl-1",
      previewOnly: false,
      limit: 20,
    });
    expect(await screen.findByTestId("legal-update-run-summary")).toHaveTextContent(
      /created 1 in-app records/i,
    );

    await user.click(screen.getByRole("button", { name: /Read/i }));
    expect(updateLegalUpdateMock.mock.calls[0][0]).toBe("upd-1");
    expect(updateLegalUpdateMock.mock.calls[0][1]).toBe("read");
    expect(screen.getByTestId("legal-update-digest-note")).toHaveTextContent(
      /External legal update delivery requires provider-specific approval/i,
    );
  });

  it("BUG-049: surfaces the backend error verbatim when watchlist creation fails", async () => {
    const user = userEvent.setup();
    listStatutesMock.mockResolvedValue({ statutes: [], total_section_count: 0 });
    createLegalUpdateWatchlistMock.mockRejectedValue(
      new ApiError(400, "Watchlist must include at least one bounded filter.", null, null),
    );

    render(withClient(<StatutesIndexPage />));

    await user.type(await screen.findByTestId("legal-update-name"), "NI Act updates");
    await user.type(screen.getByTestId("legal-update-terms"), "Section 138");
    await user.click(screen.getByTestId("legal-update-create"));

    expect(await screen.findByTestId("legal-update-create-error")).toHaveTextContent(
      "Watchlist must include at least one bounded filter.",
    );
  });

  it("shows source-backed updates and gates source sync by capability", async () => {
    const user = userEvent.setup();
    listStatutesMock.mockResolvedValue({
      statutes: [],
      total_section_count: 0,
    });
    listLegalUpdateSourceRecordsMock.mockResolvedValue({
      records: [
        {
          id: "src-1",
          source_key: "prs_acts_parliament",
          source_record_key: "key-1",
          update_type: "act",
          title: "The Example Act, 2026",
          normalized_title: "the example act 2026",
          source_url: "https://prsindia.org/acts/parliament/example-act",
          source_document_url: null,
          published_date: null,
          effective_date: null,
          act_year: 2026,
          statute_id: "example-act-2026",
          statute_section_ids: [],
          sections_changed: [],
          source_category: "prs_india",
          provenance_status: "source_metadata_available",
          content_hash: "hash",
          summary: {
            plain_english_summary:
              "PRS lists a new Act for source-backed lawyer review.",
            affected_acts: ["The Example Act, 2026"],
            affected_sections: [],
            change_kind: "act",
            practical_legal_impact:
              "Review the source before using the change in advice.",
            suggested_lawyer_review_actions: ["Open the source link."],
            confidence: "medium",
            source_url: "https://prsindia.org/acts/parliament/example-act",
            provenance_status: "source_metadata_available",
            review_framing: "Source-backed summary for lawyer review.",
          },
          summary_status: "completed",
          first_seen_at: "2026-05-26T00:00:00Z",
          last_seen_at: "2026-05-26T00:00:00Z",
          updated_at: "2026-05-26T00:00:00Z",
        },
      ],
    });

    const rendered = render(withClient(<StatutesIndexPage />));

    expect(await screen.findByText("The Example Act, 2026")).toBeInTheDocument();
    expect(screen.getByText(/Source-backed summary for lawyer review/i)).toBeInTheDocument();
    await user.click(screen.getByTestId("legal-update-source-sync"));
    expect(runLegalUpdateSourceSyncMock.mock.calls[0][0]).toEqual({
      sourceKey: "prs_acts_parliament",
      limit: 50,
    });
    expect(await screen.findByTestId("legal-update-source-run-summary")).toHaveTextContent(
      /created 1/i,
    );

    rendered.unmount();
    useCapabilityMock.mockImplementation(() => false);
    render(withClient(<StatutesIndexPage />));
    expect(await screen.findByText("The Example Act, 2026")).toBeInTheDocument();
    expect(screen.queryByTestId("legal-update-source-sync")).not.toBeInTheDocument();
  });
});
