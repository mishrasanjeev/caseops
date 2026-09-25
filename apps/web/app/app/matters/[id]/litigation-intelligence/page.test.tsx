import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent, { type UserEvent } from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchLitigationIntelligenceReviewMock,
  mutateLitigationIntelligenceReviewItemMock,
  toastError,
  toastSuccess,
} = vi.hoisted(() => ({
  fetchLitigationIntelligenceReviewMock: vi.fn(),
  mutateLitigationIntelligenceReviewItemMock: vi.fn(),
  toastError: vi.fn(),
  toastSuccess: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchLitigationIntelligenceReview: fetchLitigationIntelligenceReviewMock,
  mutateLitigationIntelligenceReviewItem: mutateLitigationIntelligenceReviewItemMock,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m-1" }),
}));

vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));

import LitigationIntelligenceReviewPage from "@/app/app/matters/[id]/litigation-intelligence/page";
import {
  litigationIntelligenceReviewMutationResponse,
  litigationIntelligenceReviewResponse,
} from "@/lib/api/schemas";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

// Mutation tests query only inside their own render container. If a test ever
// overruns its deadline, cleanup() empties that container and the abandoned
// user flow fails on its next query instead of driving the next test's page.
function renderReviewPage() {
  const view = render(withClient(<LitigationIntelligenceReviewPage />));
  return within(view.container);
}

// One paste per field: the field still receives focus and a real input event,
// but the page re-renders once per field instead of once per character.
// Paste targets whichever element has focus, so require focus first: an
// abandoned flow holding a detached field fails here instead of pasting into
// the next test's focused input.
async function enterText(user: UserEvent, field: HTMLElement, value: string) {
  await user.click(field);
  expect(field).toHaveFocus();
  await user.paste(value);
  expect(field).toHaveDisplayValue(value);
}

const REVIEW_NOTE_POLICY_MESSAGE =
  "Review note contains unsupported prediction, judge-reputation, legal-advice, or biometric/psychological language.";

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
    mutateLitigationIntelligenceReviewItemMock.mockReset();
    toastError.mockReset();
    toastSuccess.mockReset();
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
    expect(
      screen.getByTestId("litigation-review-actions-affidavit-question:q-1"),
    ).toBeInTheDocument();
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
    expect(screen.getByText(/(25 May 2026|May 25, 2026)/i)).toBeInTheDocument();

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

  it("sends closed review mutation actions with reviewer notes", async () => {
    fetchLitigationIntelligenceReviewMock.mockResolvedValue(REVIEW_RESPONSE);
    mutateLitigationIntelligenceReviewItemMock.mockResolvedValue({
      matter_id: "m-1",
      item_id: "affidavit-question:q-1",
      item_type: "affidavit_question",
      source_type: "affidavit_question",
      source_id: "q-1",
      action: "accept",
      status_before: "review_required",
      status_after: "reviewed",
      note: "Approved for hearing prep.",
      audit_event_id: "audit-1",
      applied: true,
      updated_at: "2026-05-12T09:00:00Z",
    });
    const user = userEvent.setup();
    const page = renderReviewPage();

    await page.findByTestId("litigation-review-page");
    await enterText(
      user,
      page.getByTestId("litigation-review-note-input-affidavit-question:q-1"),
      "Approved for hearing prep.",
    );
    await user.click(page.getByTestId("litigation-review-action-accept-affidavit-question:q-1"));

    // Success is announced only after the review refresh settles.
    await waitFor(() => expect(toastSuccess).toHaveBeenCalledWith("Review action saved."));
    expect(toastSuccess).toHaveBeenCalledTimes(1);
    expect(mutateLitigationIntelligenceReviewItemMock).toHaveBeenCalledTimes(1);
    expect(mutateLitigationIntelligenceReviewItemMock.mock.calls[0]).toEqual([
      {
        matterId: "m-1",
        itemId: "affidavit-question:q-1",
        itemType: "affidavit_question",
        action: "accept",
        note: "Approved for hearing prep.",
      },
    ]);
    expect(fetchLitigationIntelligenceReviewMock).toHaveBeenCalledTimes(2);
    expect(toastError).not.toHaveBeenCalled();
  });

  it("blocks unsafe review-note language before mutation", async () => {
    fetchLitigationIntelligenceReviewMock.mockResolvedValue(REVIEW_RESPONSE);
    const user = userEvent.setup();
    const page = renderReviewPage();

    await page.findByTestId("litigation-review-page");
    const noteInput = page.getByTestId("litigation-review-note-input-affidavit-question:q-1");
    const saveNote = page.getByTestId("litigation-review-action-note-affidavit-question:q-1");
    const unsafeNotes = [
      "Guaranteed win because judge likes us.",
      "The witness will lose on this point.",
      "Add a loss probability for the matter.",
      "Add win/loss notes for this witness.",
      "This relies on judge reputation.",
    ];
    for (const [index, note] of unsafeNotes.entries()) {
      await user.clear(noteInput);
      await enterText(user, noteInput, note);
      await user.click(saveNote);
      // Each attempt is refused locally with the policy message.
      expect(toastError).toHaveBeenCalledTimes(index + 1);
      expect(toastError).toHaveBeenLastCalledWith(REVIEW_NOTE_POLICY_MESSAGE);
      expect(saveNote).toBeEnabled();
    }

    expect(mutateLitigationIntelligenceReviewItemMock).not.toHaveBeenCalled();
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(fetchLitigationIntelligenceReviewMock).toHaveBeenCalledTimes(1);
  });

  it("does not render unsafe stored reviewer notes", async () => {
    fetchLitigationIntelligenceReviewMock.mockResolvedValue({
      ...REVIEW_RESPONSE,
      items: [
        {
          ...REVIEW_RESPONSE.items[0],
          review_note:
            "This relies on judge reputation and win/loss prediction with loss probability.",
        },
      ],
    });

    render(withClient(<LitigationIntelligenceReviewPage />));

    await screen.findByTestId("litigation-review-page");
    expect(screen.getByTestId("litigation-review-note-hidden-proceeding:sig-1")).toHaveTextContent(
      "hidden by safety policy",
    );
    const rendered = document.body.textContent?.toLowerCase() ?? "";
    expect(rendered).not.toContain("judge reputation");
    expect(rendered).not.toContain("win/loss");
    expect(rendered).not.toContain("loss probability");
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
    expect(() =>
      litigationIntelligenceReviewMutationResponse.parse({
        matter_id: "m-1",
        item_id: "affidavit-question:q-1",
        item_type: "affidavit_question",
        source_type: "manual_upload",
        source_id: "manual-1",
        action: "accept",
        status_before: "review_required",
        status_after: "accepted",
        note: null,
        audit_event_id: "audit-1",
        applied: true,
        updated_at: "2026-05-12T09:00:00Z",
      }),
    ).toThrow();
  });

  it("accepts canonical source target identity nested in source_action", () => {
    const parsed = litigationIntelligenceReviewResponse.parse({
      ...REVIEW_RESPONSE,
      items: [
        {
          ...REVIEW_RESPONSE.items[0],
          source: {
            ...REVIEW_RESPONSE.items[0].source,
            source_action: {
              state: "available",
              label: "Open source",
              open_url: "/api/source-actions/targets/matter_attachment/a-1/open",
              source_reference: "/api/matters/m-1/attachments/a-1/download",
              reason: null,
              opens_new_tab: true,
              target_type: "matter_attachment",
              target_id: "a-1",
            },
          },
        },
      ],
    });

    expect(parsed.items[0].source.source_action?.target_type).toBe(
      "matter_attachment",
    );
    expect(parsed.items[0].source.source_action?.target_id).toBe("a-1");
  });
});
