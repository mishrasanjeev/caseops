import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchMock } = vi.hoisted(() => ({ fetchMock: vi.fn() }));

vi.mock("next/navigation", () => ({ useParams: () => ({ id: "ans-1" }) }));
vi.mock("@/lib/api/research-answers", async (load) => ({
  ...(await load<typeof import("@/lib/api/research-answers")>()),
  fetchResearchAnswer: fetchMock,
}));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => false }));

import ResearchAnswerPage from "./page";

function withClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("research answer permalink page", () => {
  beforeEach(() => fetchMock.mockReset());

  it("reads the answer by id and shows a failed answer's message, not a model response", async () => {
    fetchMock.mockResolvedValue({
      id: "ans-1", status: "failed", query: "Section 138 notice period?", error_code: "provider_unavailable",
      message: "The AI provider did not return a usable answer. Try again shortly.",
      analysis_version: "v1", created_at: "2026-11-24T10:00:00Z", completed_at: "2026-11-24T10:01:00Z",
      context_matter: null, saved_matter: null, saved_at: null, answer: null, sources: [],
    });
    render(withClient(<ResearchAnswerPage />));
    expect(await screen.findByTestId("research-answer-unavailable")).toHaveTextContent("did not return a usable answer");
    expect(fetchMock).toHaveBeenCalledWith("ans-1", expect.anything());
    expect(screen.queryByTestId("research-answer")).not.toBeInTheDocument();
  });
});
