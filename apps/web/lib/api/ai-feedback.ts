import { apiRequest } from "@/lib/api/client";

export type AIFeedbackCategory =
  | "answer_quality"
  | "wrong_navigation"
  | "missing_permission_explanation"
  | "unsafe_citation"
  | "outdated_guidance"
  | "missing_guidance"
  | "other";

export type AIFeedbackStatus = "open" | "in_review" | "resolved" | "dismissed";

export type AIFeedbackRecord = {
  id: string;
  submitted_by_membership_id: string;
  reviewed_by_membership_id: string | null;
  surface: "product_guide" | "workspace_assistant";
  target_type: string;
  target_id: string;
  parent_target_id: string | null;
  target_version: string | null;
  target_href: string | null;
  feedback_type: "rating" | "report";
  rating: "helpful" | "not_helpful" | null;
  category: AIFeedbackCategory | null;
  priority: "normal" | "high";
  comment: string | null;
  status: AIFeedbackStatus;
  review_notes: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
};

type FeedbackDetail =
  | { feedback_type: "rating"; rating: "helpful" | "not_helpful" }
  | { feedback_type: "report"; category: AIFeedbackCategory; comment?: string };

export function submitProductGuideFeedback(
  target: {
    submission_key: string;
    target_type:
      | "product_guide_command"
      | "product_guide_section"
      | "product_guide_permission"
      | "product_guide_no_match";
    target_id: string;
    catalog_fingerprint: string;
  },
  detail: FeedbackDetail,
) {
  return apiRequest<AIFeedbackRecord>("/api/ai-feedback/product-guide", {
    method: "POST",
    body: { ...target, ...detail },
  });
}

export function submitWorkspaceAssistantFeedback(
  target: { submission_key: string; session_id: string; turn_id: string },
  detail: FeedbackDetail,
) {
  return apiRequest<AIFeedbackRecord>("/api/ai-feedback/workspace-assistant", {
    method: "POST",
    body: { ...target, ...detail },
  });
}

export function listAIFeedback(filters: {
  status?: AIFeedbackStatus;
  surface?: "product_guide" | "workspace_assistant";
  category?: AIFeedbackCategory;
  limit?: number;
}) {
  const params = new URLSearchParams({ limit: String(filters.limit ?? 50) });
  if (filters.status) params.set("status", filters.status);
  if (filters.surface) params.set("surface", filters.surface);
  if (filters.category) params.set("category", filters.category);
  return apiRequest<{ items: AIFeedbackRecord[]; limit: number; has_more: boolean }>(
    `/api/admin/ai-feedback?${params}`,
  );
}

export function reviewAIFeedback(
  feedbackId: string,
  input: {
    expected_updated_at: string;
    status: Exclude<AIFeedbackStatus, "open">;
    review_notes?: string;
  },
) {
  return apiRequest<AIFeedbackRecord>(`/api/admin/ai-feedback/${feedbackId}`, {
    method: "PATCH",
    body: input,
  });
}
