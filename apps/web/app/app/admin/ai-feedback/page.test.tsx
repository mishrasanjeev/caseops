import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listAIFeedback: vi.fn(),
  reviewAIFeedback: vi.fn(),
  useCapability: vi.fn(),
}));

vi.mock("@/lib/api/ai-feedback", () => ({
  listAIFeedback: mocks.listAIFeedback,
  reviewAIFeedback: mocks.reviewAIFeedback,
}));
vi.mock("@/lib/capabilities", () => ({ useCapability: mocks.useCapability }));

import AIFeedbackPage from "@/app/app/admin/ai-feedback/page";

const ITEM = {
  id: "feedback-1",
  submitted_by_membership_id: "membership-1",
  reviewed_by_membership_id: null,
  surface: "workspace_assistant" as const,
  target_type: "assistant_turn",
  target_id: "turn-2",
  parent_target_id: "session-1",
  target_version: "a".repeat(64),
  target_href: null,
  feedback_type: "report" as const,
  rating: null,
  category: "unsafe_citation" as const,
  priority: "high" as const,
  comment: "The source did not support this sentence.",
  status: "open" as const,
  review_notes: null,
  reviewed_at: null,
  created_at: "2026-08-30T10:00:00Z",
  updated_at: "2026-08-30T10:00:00Z",
};

describe("AIFeedbackPage", () => {
  beforeEach(() => {
    mocks.listAIFeedback.mockReset().mockResolvedValue({
      items: [ITEM],
      limit: 50,
      has_more: false,
    });
    mocks.reviewAIFeedback.mockReset().mockResolvedValue({
      ...ITEM,
      status: "in_review",
      reviewed_by_membership_id: "admin-1",
      reviewed_at: "2026-08-30T10:05:00Z",
      updated_at: "2026-08-30T10:05:00Z",
    });
    mocks.useCapability.mockReset().mockReturnValue(true);
  });

  it("loads a bounded filtered queue and applies an optimistic review", async () => {
    const user = userEvent.setup();
    render(<AIFeedbackPage />);

    expect(await screen.findByText("The source did not support this sentence.")).toBeVisible();
    expect(mocks.listAIFeedback).toHaveBeenCalledWith({ status: "open", limit: 50 });
    expect(screen.getByText("High priority")).toBeVisible();
    await user.type(screen.getByRole("textbox", { name: "Review notes" }), "Check citation provenance.");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mocks.reviewAIFeedback).toHaveBeenCalledWith("feedback-1", {
        expected_updated_at: "2026-08-30T10:00:00Z",
        status: "in_review",
        review_notes: "Check citation provenance.",
      }),
    );
  });

  it("does not call the queue when workspace admin capability is absent", () => {
    mocks.useCapability.mockReturnValue(false);
    render(<AIFeedbackPage />);
    expect(screen.getByText("Workspace administrator access is required.")).toBeVisible();
    expect(mocks.listAIFeedback).not.toHaveBeenCalled();
  });
});
