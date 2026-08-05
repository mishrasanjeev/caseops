import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchSavedMock, fetchReportsMock } = vi.hoisted(() => ({
  fetchSavedMock: vi.fn(),
  fetchReportsMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchSavedAuthorityAnnotations: fetchSavedMock,
  fetchAuthorityResearchReports: fetchReportsMock,
}));

import SavedResearchPage from "@/app/app/research/saved/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("SavedResearchPage", () => {
  beforeEach(() => {
    fetchSavedMock.mockReset();
    fetchReportsMock.mockReset();
    fetchReportsMock.mockResolvedValue({ reports: [] });
  });

  it("renders immutable research report metadata and a refine action", async () => {
    fetchSavedMock.mockResolvedValue({ annotations: [] });
    fetchReportsMock.mockResolvedValue({
      reports: [
        {
          id: "report-1",
          company_id: "company-1",
          created_by_membership_id: "member-1",
          name: "Section 11 research",
          query: "Trade Marks Act section 11 relative grounds refusal",
          mode: "act_section",
          criteria: { language: "en" },
          results: [
            {
              authority_document_id: "authority-1",
              title: "Relative grounds for refusal",
              court_name: "Delhi High Court",
              forum_level: "high_court",
              document_type: "judgment",
              decision_date: "2026-07-01",
              case_reference: "CS(COMM) 11/2026",
              neutral_citation: "2026:DHC:111",
              source: "official",
              source_reference: "https://official.example/judgment.pdf",
              source_action: {
                state: "available",
                label: "Open source",
                open_url: "/api/source-actions/authority/authority-1/open",
                source_reference: "https://official.example/judgment.pdf",
                reason: null,
                opens_new_tab: true,
              },
            },
          ],
          analysis_version: "authority-search-v3-2026-08-04",
          generated_at: "2026-08-04T10:00:00Z",
          created_at: "2026-08-04T10:00:00Z",
        },
      ],
    });

    render(withClient(<SavedResearchPage />));
    expect(await screen.findByText("Section 11 research")).toBeInTheDocument();
    expect(screen.getByText("Relative grounds for refusal")).toBeInTheDocument();
    expect(screen.getByText(/authority-search-v3-2026-08-04/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Refine search/i })).toHaveAttribute(
      "href",
      expect.stringContaining("mode=act_section"),
    );
  });

  it("renders an empty state when the tenant has nothing saved", async () => {
    fetchSavedMock.mockResolvedValue({ annotations: [] });
    render(withClient(<SavedResearchPage />));
    await waitFor(() => {
      expect(screen.getByText(/Nothing saved yet/i)).toBeInTheDocument();
    });
    expect(fetchSavedMock).toHaveBeenCalledWith({
      includeArchived: false,
      limit: 200,
    });
  });

  it("renders saved annotations with their authority preview", async () => {
    fetchSavedMock.mockResolvedValue({
      annotations: [
        {
          id: "ann-1",
          authority_document_id: "auth-1",
          created_by_membership_id: "mem-1",
          kind: "flag",
          title: "Parity precedent",
          body: "Triple-test.",
          is_archived: false,
          created_at: "2026-04-23T10:00:00Z",
          updated_at: "2026-04-23T10:00:00Z",
          authority_court_name: "Delhi High Court",
          authority_forum_level: "high_court",
          authority_document_type: "judgment",
          authority_title: "State v Kumar",
          authority_source: "official",
          authority_source_reference: "https://www.indiacode.nic.in/document.pdf",
          authority_source_action: {
            state: "available",
            label: "Open source",
            open_url:
              "/api/source-actions/targets/authority_document/authority-available/open",
            source_reference: "https://www.indiacode.nic.in/document.pdf",
            reason: null,
            opens_new_tab: true,
            target_type: "authority_document",
            target_id: "authority-available",
          },
          authority_neutral_citation: "2024:DHC:1111",
          authority_case_reference: "BAIL APPLN. 99/2024",
          authority_decision_date: "2024-06-01",
          authority_summary: "Bail order summary",
        },
      ],
    });
    render(withClient(<SavedResearchPage />));
    await waitFor(() => {
      expect(screen.getByText("State v Kumar")).toBeInTheDocument();
    });
    expect(screen.getByText("Parity precedent")).toBeInTheDocument();
    expect(screen.getByText("Delhi High Court")).toBeInTheDocument();
    expect(screen.getByText("flag")).toBeInTheDocument();
    expect(screen.getByText(/2024:DHC:1111/)).toBeInTheDocument();
    expect(screen.getByText(/Source: official/)).toBeInTheDocument();
    expect(screen.getByTestId("source-action-open")).toHaveAttribute(
      "href",
      expect.stringContaining(
        "/api/source-actions/targets/authority_document/authority-available/open",
      ),
    );
    expect(screen.getByTestId("source-action-open")).toHaveAttribute(
      "href",
      expect.stringContaining("origin=saved_research"),
    );
    expect(screen.getByTestId("source-action-report")).toBeVisible();
    expect(screen.getByText("1 saved")).toBeInTheDocument();
  });

  it("keeps citation metadata when the saved source cannot be opened", async () => {
    fetchSavedMock.mockResolvedValue({
      annotations: [
        {
          id: "ann-blocked",
          authority_document_id: "auth-blocked",
          created_by_membership_id: "mem-1",
          kind: "flag",
          title: "Review source failure",
          body: null,
          is_archived: false,
          created_at: "2026-08-03T00:00:00Z",
          updated_at: "2026-08-03T00:00:00Z",
          authority_court_name: "Delhi High Court",
          authority_forum_level: "high_court",
          authority_document_type: "judgment",
          authority_title: "Citation remains visible",
          authority_source: "provider",
          authority_source_reference: "https://provider.invalid/expired",
          authority_source_action: {
            state: "unverified",
            label: "Open source",
            open_url: null,
            source_reference: "https://provider.invalid/expired",
            reason: "Source access must be refreshed by the provider.",
            opens_new_tab: true,
            target_type: "authority_document",
            target_id: "auth-blocked",
          },
          authority_neutral_citation: "2026:DHC:42",
          authority_case_reference: null,
          authority_decision_date: "2026-01-02",
          authority_summary: "Source failure fixture",
        },
      ],
    });

    render(withClient(<SavedResearchPage />));
    expect(await screen.findByText("Citation remains visible")).toBeInTheDocument();
    expect(screen.getByText(/2026:DHC:42/)).toBeInTheDocument();
    expect(screen.getByTestId("source-action-unverified")).toBeVisible();
    expect(screen.getByTestId("source-action-report")).toBeVisible();
    expect(screen.queryByTestId("source-action-open")).not.toBeInTheDocument();
  });

  it("toggles include_archived when the user clicks Show archived", async () => {
    fetchSavedMock.mockResolvedValue({ annotations: [] });
    const { default: userEventModule } = await import("@testing-library/user-event");
    const user = userEventModule.setup();
    render(withClient(<SavedResearchPage />));
    await waitFor(() =>
      expect(fetchSavedMock).toHaveBeenCalledWith({
        includeArchived: false,
        limit: 200,
      }),
    );
    await user.click(screen.getByTestId("saved-research-toggle-archived"));
    await waitFor(() =>
      expect(fetchSavedMock).toHaveBeenCalledWith({
        includeArchived: true,
        limit: 200,
      }),
    );
  });
});
