import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchPredictiveIntelligenceMock } = vi.hoisted(() => ({
  fetchPredictiveIntelligenceMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchPredictiveIntelligence: fetchPredictiveIntelligenceMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
}));

import PredictiveIntelligencePage from "@/app/app/matters/[id]/predictive-intelligence/page";
import { predictiveIntelligenceResponse } from "@/lib/api/schemas";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const SUPPORTED_RESPONSE = {
  matter_id: "m-1",
  mode: "predictive" as const,
  tenant_policy_enabled: true,
  generated_at: "2026-05-11T06:30:00Z",
  run_id: "run-1",
  bench_summary: {
    matter_id: "m-1",
    bench_judge_ids: ["j-1"],
    evidence_quality: "thin",
    disclaimer:
      "Predictive intelligence is statistical decision support based on indexed sources only, not legal advice.",
    signals: [
      {
        signal_type: "interim_relief_likelihood",
        label: "Interim relief likelihood",
        status: "supported" as const,
        estimate_label: "higher historical positive source-label band",
        sample_size: 7,
        confidence: {
          label: "low" as const,
          sample_size: 7,
          confidence_band_low: 0.17,
          confidence_band_high: 0.64,
          method: "classified_source_outcome_frequency_wilson_95",
          limitations: ["Source-frequency band only."],
        },
        evidence: [
          {
            id: "e-1",
            source_type: "authority_document",
            source_id: "auth-1",
            title: "Alpha v Beta",
            source_reference: "2026 TEST 1",
            excerpt: "The court granted interim relief on source-backed grounds.",
            source_date: "2026-01-03",
            weight: 1,
          },
          {
            id: "e-2",
            source_type: "matter_court_order",
            source_id: "order-1",
            title: "Interim order",
            source_reference: "fixture:order",
            excerpt: "Interim order recorded from the matter file.",
            source_date: "2026-01-04",
            weight: 1,
          },
        ],
        features: [
          {
            feature_key: "classified_outcome_distribution",
            label: "Classified outcome distribution",
            direction: "supports" as const,
            weight: 1,
            explanation:
              "Stored classifications were grouped by source-backed outcome labels.",
            evidence_ids: ["e-1"],
          },
        ],
        missing_data: [],
        limitation_note:
          "This signal reflects only the indexed source sample available to CaseOps.",
        human_review_required: true,
        decision_support_label: "decision support, not legal advice",
        disclaimer:
          "Predictive intelligence is decision support based on indexed sources only, not legal advice.",
      },
      {
        signal_type: "stay_likelihood",
        label: "Stay likelihood",
        status: "insufficient_evidence" as const,
        estimate_label: null,
        sample_size: 2,
        confidence: {
          label: "insufficient" as const,
          sample_size: 2,
          confidence_band_low: null,
          confidence_band_high: null,
          method: "insufficient_source_sample",
          limitations: ["Minimum sample size is 5."],
        },
        evidence: [],
        features: [],
        missing_data: ["At least five source-linked stay classifications."],
        limitation_note:
          "This signal reflects only the indexed source sample available to CaseOps.",
        human_review_required: true,
        decision_support_label: "decision support, not legal advice",
        disclaimer:
          "Predictive intelligence is decision support based on indexed sources only, not legal advice.",
      },
    ],
  },
  bench_context: {
    matter_id: "m-1",
    status: "supported" as const,
    scope: {
      court_name: "High Court of Delhi",
      forum_level: "high_court",
      bench_name: "Justice Source",
      judge_ids: ["j-1"],
      judge_names: ["Justice Source"],
      matter_type: "Commercial",
      year_start: 2024,
      year_end: 2026,
    },
    sample_size: 7,
    evidence_quality: "thin",
    confidence: {
      label: "low" as const,
      sample_size: 7,
      confidence_band_low: 0.17,
      confidence_band_high: 0.64,
      method: "classified_source_outcome_frequency_wilson_95",
      limitations: ["Source-frequency band only."],
    },
    observed_distribution: [
      {
        signal_type: "bench_party_side_tendency",
        label: "Bench/party-side tendency",
        sample_size: 7,
        positive_count: 4,
        negative_count: 2,
        neutral_count: 1,
        year_start: 2024,
        year_end: 2026,
      },
    ],
    evidence: [
      {
        id: "bench-e-1",
        source_type: "authority_document",
        source_id: "auth-1",
        title: "Alpha v Beta",
        source_reference: "2026 TEST 1",
        excerpt: "Bench context is traceable to indexed source evidence.",
        source_date: "2026-01-03",
        weight: 1,
      },
    ],
    missing_data: [],
    limitation_note:
      "Bench context is derived from indexed source classifications and cited judgments/orders.",
    human_review_required: true,
    decision_support_label: "decision support, not legal advice",
    disclaimer:
      "Predictive intelligence is decision support based on indexed sources only, not legal advice.",
  },
  calibrated_signals: [
    {
      signal_type: "interim_relief_likelihood",
      label: "Interim relief likelihood",
      status: "supported" as const,
      scope: {
        scope_type: "judge",
        scope_key: "judge:j-1|signal:interim_relief_likelihood",
        court_name: "High Court of Delhi",
        forum_level: "high_court",
        judge_id: "j-1",
        matter_type: "Commercial",
        party_side: null,
        year_start: 2024,
        year_end: 2026,
      },
      sample_size: 7,
      observed_rate: 0.57,
      positive_count: 4,
      negative_count: 2,
      neutral_count: 1,
      confidence: {
        label: "low" as const,
        sample_size: 7,
        confidence_band_low: 0.17,
        confidence_band_high: 0.64,
        method: "calibrated_classified_source_frequency_wilson_95",
        limitations: ["Observed rates are historical indexed-source distributions only."],
      },
      calibration_level: "low" as const,
      evidence_quality: "thin",
      evidence: [
        {
          id: "cal-e-1",
          source_type: "authority_document",
          source_id: "auth-1",
          title: "Alpha v Beta",
          source_reference: "2026 TEST 1",
          excerpt: "The court granted interim relief on source-backed grounds.",
          source_date: "2026-01-03",
          weight: 1,
        },
      ],
      missing_data: [],
      limitation_note:
        "Calibrated signal is an observed historical pattern for source-backed decision support, not legal advice.",
      aggregate_snapshot_id: "snap-1",
      generated_at: "2026-05-11T06:00:00Z",
      human_review_required: true,
      decision_support_label: "decision support, not legal advice",
      disclaimer:
        "Predictive intelligence is decision support based on indexed sources only, not legal advice.",
    },
  ],
  matter_risk_summary: {
    matter_id: "m-1",
    status: "supported" as const,
    risk_band: "mixed source-context band",
    confidence: {
      label: "low" as const,
      sample_size: 7,
      confidence_band_low: 0.17,
      confidence_band_high: 0.64,
      method: "classified_source_outcome_frequency_wilson_95",
      limitations: [],
    },
    signals: [],
    features: [
      {
        feature_key: "classified_outcome_distribution",
        label: "Classified outcome distribution",
        direction: "neutral" as const,
        weight: 1,
        explanation: "The supporting and weakening labels are mixed.",
        evidence_ids: ["e-1"],
      },
    ],
    evidence: [
      {
        id: "risk-e-1",
        source_type: "authority_document",
        source_id: "auth-1",
        title: "Alpha v Beta",
        source_reference: "2026 TEST 1",
        excerpt: "Risk context is traceable to the source sample.",
        source_date: "2026-01-03",
        weight: 1,
      },
    ],
    missing_data: [],
    limitation_note:
      "This risk context reflects only the indexed source sample available to CaseOps.",
    human_review_required: true,
    decision_support_label: "decision support, not legal advice",
    disclaimer:
      "Predictive intelligence is decision support based on indexed sources only, not legal advice.",
  },
  hearing_prep_scorecard: {
    matter_id: "m-1",
    status: "insufficient_evidence" as const,
    overall_band: null,
    confidence: {
      label: "insufficient" as const,
      sample_size: 0,
      confidence_band_low: null,
      confidence_band_high: null,
      method: "insufficient_source_sample",
      limitations: [],
    },
    observable_metrics: [
      {
        feature_key: "response_consistency",
        label: "Response consistency",
        direction: "unknown" as const,
        weight: 0,
        explanation: "Requires transcript turns to compare repeated answers.",
        evidence_ids: [],
      },
      {
        feature_key: "source_support_rate",
        label: "Source support rate",
        direction: "unknown" as const,
        weight: 0,
        explanation: "Requires answers linked to source material.",
        evidence_ids: [],
      },
    ],
    evidence: [],
    missing_data: ["No source-linked mock-hearing transcript turns are available."],
    prohibited_inferences: [
      "medical_or_mental_health_diagnosis",
      "personality_assessment",
    ],
    limitation_note: "Observable answer consistency only.",
    human_review_required: true,
    decision_support_label: "decision support, not legal advice",
    disclaimer:
      "Predictive intelligence is decision support based on indexed sources only, not legal advice.",
  },
  disclaimer:
    "Predictive intelligence is statistical decision support based on indexed sources only, not legal advice.",
};

const INSUFFICIENT_RESPONSE = {
  ...SUPPORTED_RESPONSE,
  bench_summary: {
    ...SUPPORTED_RESPONSE.bench_summary,
    evidence_quality: "insufficient",
    bench_judge_ids: [],
    signals: SUPPORTED_RESPONSE.bench_summary.signals.map((signal) => ({
      ...signal,
      status: "insufficient_evidence" as const,
      sample_size: 0,
      estimate_label: null,
      confidence: {
        label: "insufficient" as const,
        sample_size: 0,
        confidence_band_low: null,
        confidence_band_high: null,
        method: "insufficient_source_sample",
        limitations: ["Minimum sample size is 5."],
      },
      evidence: [],
      features: [],
      missing_data: ["Stored LI-S7B aggregate snapshots with source evidence."],
    })),
  },
  bench_context: {
    ...SUPPORTED_RESPONSE.bench_context,
    status: "insufficient_evidence" as const,
    scope: {
      ...SUPPORTED_RESPONSE.bench_context.scope,
      judge_ids: [],
      judge_names: [],
      bench_name: null,
      year_start: null,
      year_end: null,
    },
    sample_size: 0,
    evidence_quality: "insufficient",
    confidence: {
      label: "insufficient" as const,
      sample_size: 0,
      confidence_band_low: null,
      confidence_band_high: null,
      method: "insufficient_source_sample",
      limitations: ["Minimum sample size is 5."],
    },
    observed_distribution: [],
    evidence: [],
    missing_data: ["Resolved bench or judge IDs for this matter."],
    limitation_note:
      "Bench context cannot be generated until source-linked bench history is available.",
  },
  calibrated_signals: SUPPORTED_RESPONSE.calibrated_signals.map((signal) => ({
    ...signal,
    status: "insufficient_evidence" as const,
    sample_size: 0,
    observed_rate: null,
    positive_count: 0,
    negative_count: 0,
    neutral_count: 0,
    confidence: {
      label: "insufficient" as const,
      sample_size: 0,
      confidence_band_low: null,
      confidence_band_high: null,
      method: "insufficient_source_sample",
      limitations: ["Minimum sample size is 5."],
    },
    calibration_level: "insufficient" as const,
    evidence_quality: "insufficient",
    evidence: [],
    missing_data: ["Stored LI-S7B aggregate snapshot for this signal and matter scope."],
    aggregate_snapshot_id: null,
  })),
  matter_risk_summary: {
    ...SUPPORTED_RESPONSE.matter_risk_summary,
    status: "insufficient_evidence" as const,
    risk_band: null,
    evidence: [],
    features: [],
    missing_data: ["A supported adverse-order signal is required."],
  },
};

const FORBIDDEN_COPY = [
  "guaranteed",
  "will win",
  "will lose",
  "win probability",
  "loss probability",
  "win/loss",
  "judge likes",
  "judge dislikes",
  "favorable judge",
  "judge reputation",
  "emotional instability",
  "psychological",
  "mental state",
  "biometric",
  "voice stress",
  "this is legal advice",
];

describe("PredictiveIntelligencePage", () => {
  beforeEach(() => {
    fetchPredictiveIntelligenceMock.mockReset();
  });

  it("renders supported signals with confidence, sample size, and disclaimer", async () => {
    fetchPredictiveIntelligenceMock.mockResolvedValue(SUPPORTED_RESPONSE);

    render(withClient(<PredictiveIntelligencePage />));

    expect(await screen.findByText("Source-backed litigation signals")).toBeInTheDocument();
    expect(screen.getAllByText("Interim relief likelihood").length).toBeGreaterThan(0);
    expect(screen.getAllByText("17-64%")[0]).toBeInTheDocument();
    expect(screen.getAllByText("7")[0]).toBeInTheDocument();
    expect(screen.getByTestId("predictive-disclaimer")).toHaveTextContent(
      /not legal advice/i,
    );
    expect(screen.getByTestId("predictive-matter-risk")).toHaveTextContent(
      /evidence-backed factors only/i,
    );
  });

  it("renders source-backed bench context with distribution and source links", async () => {
    fetchPredictiveIntelligenceMock.mockResolvedValue(SUPPORTED_RESPONSE);

    render(withClient(<PredictiveIntelligencePage />));

    const panel = await screen.findByTestId("predictive-bench-context");
    expect(panel).toHaveTextContent("Bench and judge context");
    expect(panel).toHaveTextContent("Justice Source");
    expect(panel).toHaveTextContent("Bench/party-side tendency");
    expect(panel).toHaveTextContent("4");
    expect(panel).toHaveTextContent("2");
    expect(panel).toHaveTextContent("2024-2026");
    expect(panel).toHaveTextContent(/not legal advice/i);
  });

  it("renders calibrated source-backed signals safely", async () => {
    fetchPredictiveIntelligenceMock.mockResolvedValue(SUPPORTED_RESPONSE);

    render(withClient(<PredictiveIntelligencePage />));

    const panel = await screen.findByTestId("predictive-calibrated-signals");
    expect(panel).toHaveTextContent("Observed historical patterns");
    expect(panel).toHaveTextContent("Interim relief likelihood");
    expect(panel).toHaveTextContent("57%");
    expect(panel).toHaveTextContent("17-64%");
    expect(panel).toHaveTextContent("4/2/1");
    expect(panel).toHaveTextContent("Judge aggregate");
    expect(panel).toHaveTextContent("Snapshot snap-1");
    expect(panel).toHaveTextContent(/not legal advice/i);
  });

  it("renders insufficient evidence state without inventing a signal", async () => {
    fetchPredictiveIntelligenceMock.mockResolvedValue(INSUFFICIENT_RESPONSE);

    render(withClient(<PredictiveIntelligencePage />));

    expect(await screen.findByTestId("predictive-insufficient-banner")).toHaveTextContent(
      /No predictive signal crossed the source threshold/i,
    );
    expect(screen.getAllByText("Insufficient evidence").length).toBeGreaterThan(0);
    expect(screen.getAllByTestId("predictive-missing-data").length).toBeGreaterThan(0);
    expect(
      screen.getByTestId("predictive-calibrated-signal-interim_relief_likelihood"),
    ).toHaveTextContent("No rate");
  });

  it("renders tenant policy disabled state for 403 responses", async () => {
    fetchPredictiveIntelligenceMock.mockRejectedValue({
      name: "ApiError",
      status: 403,
      detail: "Predictive intelligence is disabled by tenant AI policy.",
      problemType: null,
      data: {},
    });

    render(withClient(<PredictiveIntelligencePage />));

    expect(await screen.findByTestId("predictive-policy-disabled")).toHaveTextContent(
      /disabled by tenant AI policy/i,
    );
    expect(screen.getByRole("link", { name: "Open admin settings" })).toHaveAttribute(
      "href",
      "/app/admin",
    );
  });

  it("renders source links for authority documents and matter orders", async () => {
    fetchPredictiveIntelligenceMock.mockResolvedValue(SUPPORTED_RESPONSE);

    render(withClient(<PredictiveIntelligencePage />));

    await screen.findAllByText("Alpha v Beta");
    const sourceLinks = screen.getAllByRole("link", { name: "View source" });
    expect(sourceLinks.map((link) => link.getAttribute("href"))).toContain(
      "/app/research?q=2026+TEST+1",
    );
    expect(sourceLinks.map((link) => link.getAttribute("href"))).toContain(
      "/app/matters/m-1/timeline",
    );
  });

  it("rejects unknown evidence source types at the schema boundary", () => {
    const payload = JSON.parse(JSON.stringify(SUPPORTED_RESPONSE));
    payload.bench_summary.signals[0].evidence[0].source_type = "manual_upload";

    expect(predictiveIntelligenceResponse.safeParse(payload).success).toBe(false);
  });

  it("does not render prohibited predictive or hearing-prep copy", async () => {
    fetchPredictiveIntelligenceMock.mockResolvedValue(SUPPORTED_RESPONSE);

    const { container } = render(withClient(<PredictiveIntelligencePage />));

    await screen.findByText("Hearing prep scorecard");
    const rendered = container.textContent?.toLowerCase() ?? "";
    for (const phrase of FORBIDDEN_COPY) {
      expect(rendered).not.toContain(phrase);
    }
    expect(rendered).toContain("not legal advice");
    expect(rendered).toContain("observable preparation metrics only");
  });

  it("renders loading state", () => {
    fetchPredictiveIntelligenceMock.mockReturnValue(new Promise(() => {}));
    render(withClient(<PredictiveIntelligencePage />));

    expect(screen.getByTestId("predictive-loading")).toBeInTheDocument();
  });

  it("renders generic error state", async () => {
    fetchPredictiveIntelligenceMock.mockRejectedValue(new Error("network failed"));
    render(withClient(<PredictiveIntelligencePage />));

    await waitFor(() =>
      expect(
        screen.getByText("Could not load predictive intelligence"),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/network failed/i)).toBeInTheDocument();
  });
});
