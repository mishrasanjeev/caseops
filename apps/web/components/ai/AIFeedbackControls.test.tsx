import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  submitProductGuideFeedback: vi.fn(),
  submitWorkspaceAssistantFeedback: vi.fn(),
}));

vi.mock("@/lib/api/ai-feedback", () => api);

import { AIFeedbackControls } from "@/components/ai/AIFeedbackControls";

describe("AIFeedbackControls", () => {
  beforeEach(() => {
    api.submitProductGuideFeedback.mockReset().mockResolvedValue({ id: "feedback-1" });
    api.submitWorkspaceAssistantFeedback.mockReset().mockResolvedValue({ id: "feedback-2" });
  });

  it("submits one rating and one independently idempotent typed report", async () => {
    const user = userEvent.setup();
    render(
      <AIFeedbackControls
        target={{
          surface: "product_guide",
          targetType: "product_guide_command",
          targetId: "deadline-control",
          catalogFingerprint: "f".repeat(64),
        }}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Mark as helpful" }));
    await waitFor(() => expect(api.submitProductGuideFeedback).toHaveBeenCalledTimes(1));
    expect(api.submitProductGuideFeedback).toHaveBeenLastCalledWith(
      expect.objectContaining({
        target_id: "deadline-control",
        catalog_fingerprint: "f".repeat(64),
      }),
      { feedback_type: "rating", rating: "helpful" },
    );
    expect(screen.getByRole("button", { name: "Mark as not helpful" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Report an issue" }));
    await user.selectOptions(screen.getByLabelText("Issue"), "unsafe_citation");
    await user.type(screen.getByLabelText("Note"), "Source link did not match the result.");
    await user.click(screen.getByRole("button", { name: "Submit report" }));

    await waitFor(() => expect(api.submitProductGuideFeedback).toHaveBeenCalledTimes(2));
    expect(api.submitProductGuideFeedback).toHaveBeenLastCalledWith(
      expect.objectContaining({ target_type: "product_guide_command" }),
      {
        feedback_type: "report",
        category: "unsafe_citation",
        comment: "Source link did not match the result.",
      },
    );
  });

  it("reuses the submission key when a failed assistant rating is retried", async () => {
    const user = userEvent.setup();
    api.submitWorkspaceAssistantFeedback
      .mockRejectedValueOnce(new Error("temporary"))
      .mockResolvedValueOnce({ id: "feedback-2" });
    render(
      <AIFeedbackControls
        target={{ surface: "workspace_assistant", sessionId: "session-1", turnId: "turn-2" }}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Mark as not helpful" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("temporary");
    await user.click(screen.getByRole("button", { name: "Mark as not helpful" }));
    await waitFor(() => expect(api.submitWorkspaceAssistantFeedback).toHaveBeenCalledTimes(2));

    const firstTarget = api.submitWorkspaceAssistantFeedback.mock.calls[0][0];
    const retriedTarget = api.submitWorkspaceAssistantFeedback.mock.calls[1][0];
    expect(firstTarget.submission_key).toBe(retriedTarget.submission_key);
    expect(retriedTarget).toMatchObject({ session_id: "session-1", turn_id: "turn-2" });
  });
});
