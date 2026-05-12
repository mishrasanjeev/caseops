import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchLitigationIntelligenceReviewMock } = vi.hoisted(() => ({
  fetchLitigationIntelligenceReviewMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchLitigationIntelligenceReview: fetchLitigationIntelligenceReviewMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
}));

import LitigationIntelligenceReviewPage from "@/app/app/matters/[id]/litigation-intelligence/page";
import { litigationIntelligenceReviewResponse } from "@/lib/api/schemas";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const REVIEW_RESPONSE = {
  matter_id: "m-1",
  generated_at: "2026-05-12T08:30:00Z",
  disclaimer:
    "Litigation intelligence review is source-backed decision support, not legal advice.",
  summary: {
    total_items: 3,
    review_required_count: 2,
    source_linked_count: 3,
    by_type: {
      proceeding_signal: 1,
      affidavit_question: 1,
      predictive_signal: 1,
    },
    by_status: {
      review_required: 2,
      limited_context: 1,
    },
  },
  items: [
    {
      id: "proceeding:sig-1",
      item_type: "proceeding_signal",
      title: "Reply Affidavit Deadline",
      description: "File reply affidavit",
      status: "auto_promoted",
      priority: "high",
      confidence_label: "high",
      evidence_quality: null,
      sample_size: null,
      limitation_note: "Extracted from raw order text and pending lawyer review.",
      review_reason: "Generated work exists and should be confirmed.",
      source: {
        source_type: "matter_court_order",
        source_id: "order-1",
        label: "Daily order sheet",
        reference: "fixture:order",
        snippet: "file reply within two weeks from the date of this order",
        page_reference: null,
      },
      due_on: "2026-05-25",
      created_at: "2026-05-12T08:00:00Z",
      updated_at: "2026-05-12T08:00:00Z",
    },
    {
      id: "affidavit-question:q-1",
      item_type: "affidavit_question",
      title: "Document Support",
      description: "Which invoice supports the payment statement?",
      status: "review_required",
      priority: "high",
      confidence_label: "low",
      evidence_quality: null,
      sample_size: null,
      limitation_note: "Question remains review required until accepted.",
      review_reason: "The affidavit claims payment but needs source support.",
      source: {
        source_type: "matter_document",
        source_id: "att-1",
        label: "chief-affidavit.txt",
        reference: "chunk 0",
        snippet: "respondent paid Rs. 10,000 under Invoice A",
        page_reference: null,
      },
      due_on: null,
      created_at: "2026-05-12T08:05:00Z",
      updated_at: "2026-05-12T08:05:00Z",
    },
    {
      id: "predictive-signal:p-1",
      item_type: "predictive_signal",
      title: "Interim relief likelihood",
      description: "mixed historical source-label band",
      status: "limited_context",
      priority: "medium",
      confidence_label: "low",
      evidence_quality: "thin",
      sample_size: 3,
      limitation_note: "Low sample size requires review.",
      review_reason: "Predictive item needs lawyer review because the sample is weak.",
      source: {
        source_type: "predictive_signal_run",
        source_id: "run-1",
        label: "Predictive intelligence run",
        reference: "thin",
        snippet: "The indexed source sample remains thin.",
        page_reference: null,
      },
      due_on: null,
      created_at: "2026-05-12T08:10:00Z",
      updated_at: null,
    },
  ],
};

describe("LitigationIntelligenceReviewPage", () => {
  beforeEach(() => {
    fetchLitigationIntelligenceReviewMock.mockReset();
  });

  it("renders grouped review items with source links and safe disclaimer", async () => {
    fetchLitigationIntelligenceReviewMock.mockResolvedValue(REVIEW_RESPONSE);

    render(withClient(<LitigationIntelligenceReviewPage />));

    expect(await screen.findByTestId("litigation-review-page")).toBeInTheDocument();
    expect(screen.getByTestId("litigation-review-disclaimer")).toHaveTextContent(
      "not legal advice",
    );
    expect(screen.getByTestId("litigation-review-group-proceeding_signal")).toBeInTheDocument();
    expect(screen.getByTestId("litigation-review-group-affidavit_question")).toBeInTheDocument();
    expect(screen.getByTestId("litigation-review-group-predictive_signal")).toBeInTheDocument();
    expect(screen.getByText("Which invoice supports the payment statement?")).toBeInTheDocument();
    expect(screen.getByText("Low sample size requires review.")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "View source" })).toHaveLength(3);
    expect(
      screen.getByTestId("litigation-review-source-link-proceeding:sig-1"),
    ).toHaveAttribute("href", "/app/matters/m-1/timeline");
    expect(
      screen.getByTestId("litigation-review-source-link-affidavit-question:q-1"),
    ).toHaveAttribute("href", "/app/matters/m-1/documents");
    expect(
      screen.getByTestId("litigation-review-source-link-predictive-signal:p-1"),
    ).toHaveAttribute("href", "/app/matters/m-1/predictive-intelligence");

    const rendered = document.body.textContent?.toLowerCase() ?? "";
    for (const forbidden of [
      "guaranteed",
      "will win",
      "judge reputation",
      "judge likes",
      "judge dislikes",
      "emotional instability",
      "psychological diagnosis",
      "biometric",
      "voice stress",
    ]) {
      expect(rendered).not.toContain(forbidden);
    }
  });

  it("renders empty, loading, and error states", async () => {
    fetchLitigationIntelligenceReviewMock.mockResolvedValue({
      ...REVIEW_RESPONSE,
      summary: {
        total_items: 0,
        review_required_count: 0,
        source_linked_count: 0,
        by_type: {},
        by_status: {},
      },
      items: [],
    });
    const { unmount } = render(withClient(<LitigationIntelligenceReviewPage />));

    expect(screen.getByTestId("litigation-review-loading")).toBeInTheDocument();
    expect(await screen.findByTestId("litigation-review-empty")).toBeInTheDocument();
    unmount();

    fetchLitigationIntelligenceReviewMock.mockRejectedValue(new Error("blocked"));
    render(withClient(<LitigationIntelligenceReviewPage />));

    await waitFor(() => {
      expect(
        screen.getByText("Could not load litigation intelligence review"),
      ).toBeInTheDocument();
    });
  });

  it("rejects unknown source types before rendering links", () => {
    expect(() =>
      litigationIntelligenceReviewResponse.parse({
        ...REVIEW_RESPONSE,
        items: [
          {
            ...REVIEW_RESPONSE.items[0],
            source: {
              ...REVIEW_RESPONSE.items[0].source,
              source_type: "manual_upload",
            },
          },
        ],
      }),
    ).toThrow();
  });
});
