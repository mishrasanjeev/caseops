import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { statsMock, searchMock, useCapabilityMock } = vi.hoisted(() => ({
  statsMock: vi.fn(),
  searchMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchAuthorityCorpusStats: statsMock,
  searchAuthorities: searchMock,
  createAuthorityAnnotation: vi.fn(),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => useCapabilityMock(cap),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import ResearchPage from "@/app/app/research/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("ResearchPage", () => {
  beforeEach(() => {
    statsMock.mockReset();
    searchMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation(() => true);
    statsMock.mockResolvedValue({ document_count: 0 });
    searchMock.mockResolvedValue({
      query: "",
      mode: "keyword",
      provider: "caseops-authority-search-v2",
      generated_at: "2026-05-23T00:00:00Z",
      results: [],
      contextual_plan: null,
      coverage_notice: null,
      total_after_filter: 0,
      offset: 0,
    });
  });

  it("renders the research query input and submit button", () => {
    render(withClient(<ResearchPage />));
    expect(screen.getByTestId("research-query-input")).toBeInTheDocument();
    expect(screen.getByTestId("research-query-submit")).toBeInTheDocument();
  });

  it("submits contextual mode for fact-pattern research", async () => {
    render(withClient(<ResearchPage />));

    fireEvent.click(screen.getByTestId("research-mode-contextual"));
    fireEvent.change(screen.getByTestId("research-query-input"), {
      target: {
        value:
          "Cheque bounced due to insufficient funds and notice was sent after 35 days",
      },
    });
    fireEvent.click(screen.getByTestId("research-query-submit"));

    await waitFor(() => {
      expect(searchMock).toHaveBeenCalledWith(
        expect.objectContaining({
          mode: "contextual",
          query:
            "Cheque bounced due to insufficient funds and notice was sent after 35 days",
        }),
      );
    });
  });
});
