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
    expect(screen.getByTestId("recommendation-objective-select")).toBeInTheDocument();
    expect(screen.getByTestId("recommendation-lawyer-thinking")).toBeInTheDocument();
    // BUG-016: the persistent error Card must NOT render when no
    // generation has failed.
    expect(
      screen.queryByTestId("recommendation-last-error"),
    ).not.toBeInTheDocument();
  });

  it("sends lawyer thinking when filled", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [],
    });
    generateRecommendationMock.mockResolvedValue({
      id: "rec-custom",
      matter_id: "m-1",
      type: "authority",
      title: "Custom objective recommendation",
      rationale: "Source-backed observations.",
      primary_option_index: 0,
      assumptions: [],
      missing_facts: [],
      confidence: "medium",
      review_required: true,
      status: "proposed",
      next_action: null,
      created_at: "2026-05-23T00:00:00Z",
      options: [],
      decisions: [],
      retrieved_authorities: [],
      strategy_payload: null,
      analysis: null,
    });

    render(withClient(<RecommendationsPage />));
    const thinking = await screen.findByTestId("recommendation-lawyer-thinking");
    fireEvent.change(thinking, {
      target: { value: "I am considering skipping the next reply filing." },
    });
    fireEvent.click(screen.getByTestId("generate-authority-recommendation"));

    await waitFor(() =>
      expect(generateRecommendationMock).toHaveBeenCalledWith({
        matterId: "m-1",
        type: "authority",
        recommendationContext: null,
        customGoal: null,
        lawyerThinking: "I am considering skipping the next reply filing.",
      }),
    );
  });

  it("omits lawyer thinking when blank", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [],
    });
    generateRecommendationMock.mockResolvedValue({});

    render(withClient(<RecommendationsPage />));
    fireEvent.click(await screen.findByTestId("generate-authority-recommendation"));

    await waitFor(() =>
      expect(generateRecommendationMock).toHaveBeenCalledWith({
        matterId: "m-1",
        type: "authority",
        recommendationContext: null,
        customGoal: null,
        lawyerThinking: null,
      }),
    );
  });

  it("labels AI recommendations distinctly and excludes lawyer strategy entries", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [
        {
          id: "rec-1",
          matter_id: "m-1",
          type: "authority",
          title: "Authority support",
          rationale: "Use cited authority.",
          primary_option_index: 0,
          assumptions: [],
          missing_facts: [],
          confidence: "medium",
          review_required: true,
          status: "proposed",
          next_action: null,
          created_at: "2026-05-07T00:00:00Z",
          options: [
            {
              id: "opt-1",
              rank: 0,
              label: "File reply",
              rationale: "Grounded option.",
              confidence: "medium",
              supporting_citations: ["A v B"],
              risk_notes: null,
            },
          ],
          decisions: [],
          retrieved_authorities: ["A v B"],
          strategy_payload: null,
          analysis: {
            recommendation: "Use cited authority for lawyer review.",
            risk_analysis: ["Record gaps may affect reliance."],
            legal_impact: ["Supports the procedural posture."],
            suggested_actions: ["Verify facts against the record."],
            confidence_score: "medium",
            confidence_explanation: "One verified citation supports the recommendation.",
          },
        },
        {
          id: "rec-2",
          matter_id: "m-1",
          type: "litigation_strategy",
          title: "Legacy AI strategy row",
          rationale: "Should live on the Strategy tab.",
          primary_option_index: 0,
          assumptions: [],
          missing_facts: [],
          confidence: "low",
          review_required: true,
          status: "proposed",
          next_action: null,
          created_at: "2026-05-07T00:00:00Z",
          options: [],
          decisions: [],
          retrieved_authorities: [],
          strategy_payload: null,
          analysis: null,
        },
      ],
    });

    render(withClient(<RecommendationsPage />));

    expect(await screen.findByText("Authority support")).toBeInTheDocument();
    expect(screen.getByText("AI Recommendations")).toBeInTheDocument();
    expect(screen.getByText(/not lawyer-owned strategy/i)).toBeInTheDocument();
    expect(screen.queryByText("Legacy AI strategy row")).not.toBeInTheDocument();
    expect(screen.getByText("Risk analysis")).toBeInTheDocument();
    expect(screen.getByText("Legal impact")).toBeInTheDocument();
    expect(screen.getByText("Suggested actions")).toBeInTheDocument();
    expect(screen.getByText("Confidence score")).toBeInTheDocument();
    expect(screen.getByTestId("ai-recommendations-disclaimer")).toHaveTextContent(
      /does not create or approve a lawyer-owned strategy entry/i,
    );
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

  it("BUG-005: quota exhaustion keeps actionable provider guidance instead of calling it grounding", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [],
    });
    generateRecommendationMock.mockRejectedValue({
      name: "ApiError",
      status: 503,
      problemType: "llm_quota_exhausted",
      detail:
        "Could not generate the recommendation: the configured AI provider quota is exhausted. Restore or top up provider credits, then retry. No output was saved.",
      data: {},
    });

    render(withClient(<RecommendationsPage />));
    fireEvent.click(await screen.findByTestId("generate-remedy-recommendation"));

    await waitFor(() =>
      expect(
        screen.getByTestId("recommendation-last-error"),
      ).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Remedy generation is temporarily unavailable/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/needs more grounding/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/provider quota is exhausted/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No output was saved/i),
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
