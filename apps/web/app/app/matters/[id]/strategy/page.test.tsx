import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listRecommendationsMock, generateRecommendationMock } = vi.hoisted(
  () => ({
    listRecommendationsMock: vi.fn(),
    generateRecommendationMock: vi.fn(),
  }),
);

vi.mock("@/lib/api/endpoints", () => ({
  listRecommendations: listRecommendationsMock,
  generateRecommendation: generateRecommendationMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import StrategyPage from "@/app/app/matters/[id]/strategy/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const SAMPLE_PAYLOAD = {
  current_posture:
    "Matter at the High Court stage with FIR registered under BNS s.318.",
  recommended_route: {
    label: "Quashing under BNSS s.528 + escalate via SLP if dismissed",
    rationale:
      "HC inherent powers cover the fact pattern. SLP is the natural escalation if the HC declines.",
    confidence: "medium" as const,
    availability: "available" as const,
    supporting_citations: ["Sushila Aggarwal v. State of NCT (2020)"],
    risk_notes: "Quashing is discretionary.",
  },
  alternative_routes: [
    {
      label: "Compromise petition",
      rationale: "Settle and compound under BNSS s.359.",
      confidence: "low" as const,
      availability: "uncertain" as const,
      supporting_citations: ["Sushila Aggarwal v. State of NCT (2020)"],
      risk_notes: null,
    },
  ],
  forum_sequence: [
    {
      forum_level: "high_court_single_bench" as const,
      stage_label: "Quashing petition",
      forum_name: "Delhi High Court",
      rationale: "HC inherent powers under BNSS s.528.",
      statutory_basis: ["BNSS s.528"],
      expected_filings: ["quashing_petition", "vakalatnama"],
    },
    {
      forum_level: "supreme_court" as const,
      stage_label: "SLP if HC declines",
      forum_name: "Supreme Court of India",
      rationale: "Article 136 SLP grounds.",
      statutory_basis: ["Constitution Article 136"],
      expected_filings: ["special_leave_petition", "synopsis_list_of_dates"],
    },
  ],
  recommended_drafts: [
    {
      template_type: "quashing_petition",
      display_name: "Quashing Petition",
      purpose: "BNSS s.528 inherent powers.",
      available: true,
      reason_unavailable: null,
    },
    {
      template_type: "special_leave_petition",
      display_name: "Special Leave Petition (Article 136)",
      purpose: "SC escalation route.",
      available: false,
      reason_unavailable: "Move the matter to the SC stage first.",
    },
  ],
  limitation_flags: [
    {
      label: "SLP filing window",
      description:
        "Article 132 limitation period — 60 days. HC dismissal date not on file.",
      statutory_basis: "Limitation Act Article 132",
      deadline_iso: null,
      severity: "warning" as const,
    },
  ],
  required_documents: ["Certified copy of FIR", "Certified copy of HC order"],
  missing_facts: ["Date of HC pronouncement"],
  risks: [
    {
      label: "Cost of escalation",
      description: "SC-stage costs are material.",
      severity: "medium" as const,
      mitigation: "Estimate at outset.",
    },
  ],
  next_best_actions: ["Wait for HC listing", "Prepare SLP within 60 days"],
  disclaimer:
    "This strategy is a citation-grounded starting point and requires lawyer review.",
};

const SAMPLE_STRATEGY = {
  id: "rec-1",
  matter_id: "m-1",
  type: "litigation_strategy" as const,
  title: "Quashing route at HC, escalation to SC",
  rationale: "Two-stage strategy: quash at HC, escalate via SLP.",
  primary_option_index: 0,
  assumptions: [],
  missing_facts: ["Date of HC pronouncement"],
  confidence: "medium" as const,
  review_required: true,
  status: "proposed" as const,
  next_action: "Await HC listing",
  created_at: "2026-05-03T10:00:00Z",
  options: [],
  decisions: [],
  retrieved_authorities: ["Sushila Aggarwal v. State of NCT (2020)"],
  strategy_payload: SAMPLE_PAYLOAD,
};

const FORBIDDEN_PHRASES = [
  "perfect strategy",
  "guaranteed",
  "will win",
  "will succeed",
  "will be granted",
  "certain outcome",
  "no lawyer needed",
  "replace advocate",
];

describe("MatterStrategyPage", () => {
  beforeEach(() => {
    listRecommendationsMock.mockReset();
    generateRecommendationMock.mockReset();
  });

  it("renders the empty state when there is no strategy yet", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [],
    });
    render(withClient(<StrategyPage />));
    await waitFor(() =>
      expect(screen.getByTestId("strategy-generate")).toBeInTheDocument(),
    );
    expect(screen.getByText(/No strategy yet/i)).toBeInTheDocument();
  });

  it("renders the strategy card with route timeline + recommended drafts", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [SAMPLE_STRATEGY],
    });
    render(withClient(<StrategyPage />));
    await waitFor(() =>
      expect(screen.getByTestId("strategy-card")).toBeInTheDocument(),
    );
    // Review-required banner
    expect(screen.getByTestId("strategy-review-required")).toBeInTheDocument();
    // Current posture renders
    expect(screen.getByTestId("strategy-current-posture")).toBeInTheDocument();
    // Forum sequence renders
    expect(screen.getByTestId("strategy-forum-sequence")).toBeInTheDocument();
    expect(screen.getByText(/Quashing petition/)).toBeInTheDocument();
    expect(screen.getByText(/SLP if HC declines/)).toBeInTheDocument();
    // Recommended draft buttons render — available draft has a link,
    // unavailable draft has the reason.
    expect(
      screen.getByTestId("strategy-draft-button-quashing_petition"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("strategy-draft-unavailable-special_leave_petition"),
    ).toBeInTheDocument();
    // Limitation flags + missing facts + risks render
    expect(screen.getByTestId("strategy-limitation-flags")).toBeInTheDocument();
    expect(screen.getByTestId("strategy-missing-facts")).toBeInTheDocument();
    expect(screen.getByTestId("strategy-risks")).toBeInTheDocument();
    // Disclaimer renders
    expect(screen.getByTestId("strategy-disclaimer")).toBeInTheDocument();
  });

  it("links the available recommended draft to the drafts/new flow with the right type", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [SAMPLE_STRATEGY],
    });
    render(withClient(<StrategyPage />));
    const link = await screen.findByTestId(
      "strategy-draft-button-quashing_petition",
    );
    // Button renders as an anchor when given href.
    expect(link.tagName).toBe("A");
    expect((link as HTMLAnchorElement).getAttribute("href")).toBe(
      "/app/matters/m-1/drafts/new?type=quashing_petition",
    );
  });

  it("surfaces the persistent error banner when generation fails", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [],
    });
    generateRecommendationMock.mockRejectedValue(
      new Error(
        "No grounding authorities were verified for this strategy.",
      ),
    );
    render(withClient(<StrategyPage />));
    fireEvent.click(await screen.findByTestId("strategy-generate"));
    await waitFor(() =>
      expect(screen.getByTestId("strategy-last-error")).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/No grounding authorities were verified/),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("strategy-retry-from-banner"),
    ).toBeInTheDocument();
  });

  it("shows a loading skeleton while the query is pending", () => {
    listRecommendationsMock.mockReturnValue(
      // never-resolving promise → query stays pending
      new Promise(() => {}),
    );
    render(withClient(<StrategyPage />));
    expect(screen.getByTestId("strategy-loading")).toBeInTheDocument();
  });

  it("does not render strategy cards for non-strategy recommendation types", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [
        {
          ...SAMPLE_STRATEGY,
          type: "authority",
          strategy_payload: null,
        },
      ],
    });
    render(withClient(<StrategyPage />));
    await waitFor(() =>
      expect(screen.getByTestId("strategy-generate")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("strategy-card")).not.toBeInTheDocument();
  });

  it("structural test: the strategy fixture contains no forbidden outcome-promising language", () => {
    // Self-check on the test fixture so any future regression in the
    // sample payload (someone editing the fixture and adding a
    // disallowed phrase) gets caught HERE, not in production.
    const haystack = JSON.stringify(SAMPLE_STRATEGY).toLowerCase();
    for (const phrase of FORBIDDEN_PHRASES) {
      expect(haystack).not.toContain(phrase);
    }
  });
});
