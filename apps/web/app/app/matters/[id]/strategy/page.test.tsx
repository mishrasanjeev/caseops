import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  listRecommendationsMock,
  generateRecommendationMock,
  recordDecisionMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  listRecommendationsMock: vi.fn(),
  generateRecommendationMock: vi.fn(),
  recordDecisionMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  listRecommendations: listRecommendationsMock,
  generateRecommendation: generateRecommendationMock,
  recordRecommendationDecision: recordDecisionMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
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
      supporting_citations: ["Sushila Aggarwal v. State of NCT (2020)"],
      unverified: false,
    },
    {
      forum_level: "supreme_court" as const,
      stage_label: "SLP if HC declines",
      forum_name: "Supreme Court of India",
      rationale: "Article 136 SLP grounds.",
      statutory_basis: ["Constitution Article 136"],
      expected_filings: ["special_leave_petition", "synopsis_list_of_dates"],
      supporting_citations: ["Sushila Aggarwal v. State of NCT (2020)"],
      unverified: false,
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
      supporting_citations: ["Sushila Aggarwal v. State of NCT (2020)"],
      unverified: false,
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
      supporting_citations: [],
      unverified: false,
    },
  ],
  next_best_actions: [
    {
      action: "Wait for HC listing",
      supporting_citations: [],
      unverified: false,
    },
    {
      action: "Prepare SLP within 60 days",
      supporting_citations: ["Sushila Aggarwal v. State of NCT (2020)"],
      unverified: false,
    },
  ],
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
    recordDecisionMock.mockReset();
    // Default: assume the signed-in user has approval capability.
    // Specific tests override this for the no-cap case.
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation(() => true);
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

  it("BUG-031: quota exhaustion keeps actionable provider guidance instead of calling it grounding", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [],
    });
    generateRecommendationMock.mockRejectedValue({
      name: "ApiError",
      status: 503,
      problemType: "llm_quota_exhausted",
      detail:
        "Could not generate the strategy: the configured AI provider quota is exhausted. Restore or top up provider credits, then retry. No output was saved.",
      data: {},
    });

    render(withClient(<StrategyPage />));
    fireEvent.click(await screen.findByTestId("strategy-generate"));

    await waitFor(() =>
      expect(screen.getByTestId("strategy-last-error")).toBeInTheDocument(),
    );
    expect(
      screen.getByText(/Strategy generation is temporarily unavailable/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/needs more grounding/)).not.toBeInTheDocument();
    expect(
      screen.getByText(/provider quota is exhausted/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/No output was saved/i),
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

  // ---------------------------------------------------------------
  // Round-2 P1 #3: partner-review approval controls.
  // ---------------------------------------------------------------

  it("renders the Approve / Request changes bar when the user has the strategy:approve capability", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [SAMPLE_STRATEGY],
    });
    render(withClient(<StrategyPage />));
    await waitFor(() =>
      expect(screen.getByTestId("strategy-card")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("strategy-approval-bar")).toBeInTheDocument();
    expect(screen.getByTestId("strategy-approve")).toBeInTheDocument();
    expect(
      screen.getByTestId("strategy-request-changes"),
    ).toBeInTheDocument();
  });

  it("hides the Approve / Request changes bar when the user lacks strategy:approve", async () => {
    // Round-2 P2 #7. Two distinct caps now gate the page —
    // strategy:generate (Generate button) and strategy:approve
    // (approval bar). For this test we permit Generate so the page
    // renders normally but withhold Approve.
    useCapabilityMock.mockImplementation(
      (cap: string) => cap !== "strategy:approve",
    );
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [SAMPLE_STRATEGY],
    });
    render(withClient(<StrategyPage />));
    await waitFor(() =>
      expect(screen.getByTestId("strategy-card")).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("strategy-approval-bar"),
    ).not.toBeInTheDocument();
    expect(screen.queryByTestId("strategy-approve")).not.toBeInTheDocument();
    // Review banner stays visible even though approval controls are hidden —
    // a non-approver can still see that review is required.
    expect(screen.getByTestId("strategy-review-required")).toBeInTheDocument();
    // Generate button stays visible because canGenerate is still true.
    expect(screen.getByTestId("strategy-generate")).toBeInTheDocument();
  });

  it("hides the Generate button when the user lacks strategy:generate", async () => {
    // Round-2 P2 #7. With strategy:generate denied the empty state
    // still renders (so the page is still informative) but the
    // Generate button is hidden.
    useCapabilityMock.mockImplementation(
      (cap: string) => cap !== "strategy:generate",
    );
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [],
    });
    render(withClient(<StrategyPage />));
    await waitFor(() =>
      expect(screen.getByText(/No strategy yet/i)).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("strategy-generate")).not.toBeInTheDocument();
  });

  it("clicking Approve calls recordRecommendationDecision and refreshes the list", async () => {
    listRecommendationsMock
      .mockResolvedValueOnce({
        matter_id: "m-1",
        recommendations: [SAMPLE_STRATEGY],
      })
      // After invalidate the page re-fetches; this time the strategy
      // is already approved.
      .mockResolvedValueOnce({
        matter_id: "m-1",
        recommendations: [
          {
            ...SAMPLE_STRATEGY,
            review_required: false,
            status: "accepted" as const,
            decisions: [
              {
                id: "d-1",
                actor_membership_id: "mem-1",
                decision: "accepted" as const,
                selected_option_index: 0,
                notes: null,
                created_at: "2026-05-03T11:00:00Z",
              },
            ],
          },
        ],
      });
    recordDecisionMock.mockResolvedValue(SAMPLE_STRATEGY);
    render(withClient(<StrategyPage />));
    const approveBtn = await screen.findByTestId("strategy-approve");
    fireEvent.click(approveBtn);
    await waitFor(() =>
      expect(recordDecisionMock).toHaveBeenCalledWith({
        recommendationId: "rec-1",
        decision: "accepted",
        selectedOptionIndex: 0,
      }),
    );
    // After re-fetch the partner-review banner should be gone and the
    // approved badge should appear.
    await waitFor(() =>
      expect(screen.getByTestId("strategy-approved-badge")).toBeInTheDocument(),
    );
    expect(
      screen.queryByTestId("strategy-review-required"),
    ).not.toBeInTheDocument();
    // The approval bar disappears once review is no longer required.
    expect(
      screen.queryByTestId("strategy-approval-bar"),
    ).not.toBeInTheDocument();
  });

  it("shows the loading state on the Approve button while the decision is in-flight", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [SAMPLE_STRATEGY],
    });
    // Never-resolving mutation → stays pending so we can assert the
    // spinner copy.
    recordDecisionMock.mockReturnValue(new Promise(() => {}));
    render(withClient(<StrategyPage />));
    const approveBtn = await screen.findByTestId("strategy-approve");
    fireEvent.click(approveBtn);
    await waitFor(() =>
      expect(screen.getByText(/Approving…/)).toBeInTheDocument(),
    );
    expect(screen.getByTestId("strategy-approve")).toBeDisabled();
    // Request-changes button should also be disabled while the
    // approve mutation is pending — defensive against double-submit.
    expect(screen.getByTestId("strategy-request-changes")).toBeDisabled();
  });

  it("Request changes calls recordRecommendationDecision with edited and keeps review_required true", async () => {
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [SAMPLE_STRATEGY],
    });
    recordDecisionMock.mockResolvedValue(SAMPLE_STRATEGY);
    render(withClient(<StrategyPage />));
    const requestChangesBtn = await screen.findByTestId(
      "strategy-request-changes",
    );
    fireEvent.click(requestChangesBtn);
    await waitFor(() =>
      expect(recordDecisionMock).toHaveBeenCalledWith({
        recommendationId: "rec-1",
        decision: "edited",
        selectedOptionIndex: 0,
      }),
    );
    // Banner stays — Request changes is not an approval.
    expect(screen.getByTestId("strategy-review-required")).toBeInTheDocument();
  });

  // ---------------------------------------------------------------
  // Round-2 P1 #4: surface unverified flags on items that did not
  // pass per-item citation verification.
  // ---------------------------------------------------------------

  it("renders an Unverified badge on a forum step / limitation flag / next-best action whose citation did not verify", async () => {
    const unverifiedStrategy = {
      ...SAMPLE_STRATEGY,
      strategy_payload: {
        ...SAMPLE_PAYLOAD,
        forum_sequence: [
          {
            ...SAMPLE_PAYLOAD.forum_sequence[0],
            supporting_citations: [],
            unverified: true,
          },
        ],
        limitation_flags: [
          {
            ...SAMPLE_PAYLOAD.limitation_flags[0],
            supporting_citations: [],
            unverified: true,
          },
        ],
        next_best_actions: [
          {
            action: "File the application",
            supporting_citations: [],
            unverified: true,
          },
        ],
      },
    };
    listRecommendationsMock.mockResolvedValue({
      matter_id: "m-1",
      recommendations: [unverifiedStrategy],
    });
    render(withClient(<StrategyPage />));
    await waitFor(() =>
      expect(screen.getByTestId("strategy-card")).toBeInTheDocument(),
    );
    expect(
      screen.getByTestId("strategy-forum-step-unverified-0"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("strategy-limitation-flag-unverified"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("strategy-nba-unverified")).toBeInTheDocument();
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
