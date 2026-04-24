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
    expect(screen.getByText("1 saved")).toBeInTheDocument();
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
