import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  listRecommendationsMock,
  generateRecommendationMock,
  recordRecommendationDecisionMock,
} = vi.hoisted(() => ({
  listRecommendationsMock: vi.fn(),
  generateRecommendationMock: vi.fn(),
  recordRecommendationDecisionMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listRecommendations: listRecommendationsMock,
  generateRecommendation: generateRecommendationMock,
  recordRecommendationDecision: recordRecommendationDecisionMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import RecommendationsPage from "@/app/app/matters/[id]/recommendations/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("RecommendationsPage", () => {
  beforeEach(() => {
    listRecommendationsMock.mockReset();
    generateRecommendationMock.mockReset();
    recordRecommendationDecisionMock.mockReset();
  });

  it("renders Generate buttons + does NOT show last-error Card initially", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [],
    });
    render(withClient(<RecommendationsPage />));
    await waitFor(() =>
      expect(
        screen.getByTestId("generate-authority-recommendation"),
      ).toBeInTheDocument(),
    );
    // BUG-016: the persistent error Card must NOT render when no
    // generation has failed.
    expect(
      screen.queryByTestId("recommendation-last-error"),
    ).not.toBeInTheDocument();
  });

  it("BUG-016: shows persistent error Card with Try-again button after a failed generate", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [],
    });
    // The mutation rejects with an Error whose message becomes the
    // Card's actionable copy via apiErrorMessage fallback.
    generateRecommendationMock.mockRejectedValue(
      new Error("Add more detail to the matter description."),
    );
    render(withClient(<RecommendationsPage />));
    const trigger = await screen.findByTestId(
      "generate-authority-recommendation",
    );
    fireEvent.click(trigger);
    await waitFor(() =>
      expect(
        screen.getByTestId("recommendation-last-error"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Add more detail to the matter description/),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("recommendation-retry-from-banner"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("recommendation-dismiss-banner"),
    ).toBeInTheDocument();
  });

  it("BUG-016: dismissing the error Card removes it without re-generating", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [],
    });
    generateRecommendationMock.mockRejectedValue(new Error("rejected"));
    render(withClient(<RecommendationsPage />));
    const trigger = await screen.findByTestId(
      "generate-authority-recommendation",
    );
    fireEvent.click(trigger);
    await waitFor(() =>
      expect(
        screen.getByTestId("recommendation-last-error"),
      ).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("recommendation-dismiss-banner"));
    await waitFor(() =>
      expect(
        screen.queryByTestId("recommendation-last-error"),
      ).not.toBeInTheDocument(),
    );
    // Dismiss must NOT trigger a retry — only the explicit Try-again
    // button does that.
    expect(generateRecommendationMock).toHaveBeenCalledTimes(1);
  });
});
