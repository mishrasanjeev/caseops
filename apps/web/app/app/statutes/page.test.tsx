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
} = vi.hoisted(() => ({
  listStatutesMock: vi.fn(),
  listLegalUpdateWatchlistsMock: vi.fn(),
  createLegalUpdateWatchlistMock: vi.fn(),
  updateLegalUpdateWatchlistMock: vi.fn(),
  runLegalUpdateWatchlistMock: vi.fn(),
  listLegalUpdatesMock: vi.fn(),
  updateLegalUpdateMock: vi.fn(),
  fetchLegalUpdateDigestPreviewMock: vi.fn(),
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
}));

import StatutesIndexPage from "@/app/app/statutes/page";

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
});
