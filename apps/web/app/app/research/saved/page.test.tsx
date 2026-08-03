import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchSavedMock } = vi.hoisted(() => ({
  fetchSavedMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchSavedAuthorityAnnotations: fetchSavedMock,
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
              "/api/source-actions/open?url=https%3A%2F%2Fwww.indiacode.nic.in%2Fdocument.pdf",
            source_reference: "https://www.indiacode.nic.in/document.pdf",
            reason: null,
            opens_new_tab: true,
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
      expect.stringContaining("/api/source-actions/open?url="),
    );
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
