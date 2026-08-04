import { apiRequest } from "@/lib/api/client";

export type SourceTargetType =
  | "authority_document"
  | "statute_section"
  | "judge_appointment"
  | "matter_attachment";

export type SourceOriginSurface =
  | "research"
  | "saved_research"
  | "judge_profile"
  | "uploaded_case_analysis"
  | "intelligent_review"
  | "statute"
  | "other";

export type SourceIssueType =
  | "broken"
  | "wrong_document"
  | "access_denied"
  | "stale"
  | "other";

export type SourceLinkReportRecord = {
  id: string;
  target_type: SourceTargetType;
  target_id: string;
  origin_surface: SourceOriginSurface;
  issue_type: SourceIssueType;
  status: "queued" | "investigating" | "resolved" | "dismissed";
  source_state: "available" | "missing" | "unverified" | "blocked" | "quarantined";
  destination_class: string;
  created_at: string;
};

export function reportSourceLink(input: {
  targetType: SourceTargetType;
  targetId: string;
  originSurface: SourceOriginSurface;
  issueType: SourceIssueType;
  description?: string;
}): Promise<SourceLinkReportRecord> {
  return apiRequest("/api/source-actions/reports", {
    method: "POST",
    body: {
      target_type: input.targetType,
      target_id: input.targetId,
      origin_surface: input.originSurface,
      issue_type: input.issueType,
      description: input.description?.trim() || null,
    },
  });
}
