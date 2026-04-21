import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
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
    searchMock.mockResolvedValue({ results: [] });
  });

  it("renders the research query input and submit button", () => {
    render(withClient(<ResearchPage />));
    expect(screen.getByTestId("research-query-input")).toBeInTheDocument();
    expect(screen.getByTestId("research-query-submit")).toBeInTheDocument();
  });
});
