import { apiRequest } from "@/lib/api/client";
import type { SourceActionContract } from "@/components/app/SourceAction";

export type IntelligentReviewState =
  | "queued"
  | "running"
  | "ready"
  | "abstained"
  | "failed"
  | "finalized"
  | "published";

export type IntelligentReviewFactInput = {
  label: string;
  value: string;
  source_ref?: string | null;
};

export type IntelligentReviewAssertion = {
  text: string;
  authority_document_ids: string[];
};

export type IntelligentReviewAuthority = {
  authority_document_id: string;
  disposition: "supporting" | "contrary";
  title: string;
  citation: string;
  court: string;
  decision_date: string | null;
  source_url: string | null;
  source_action: SourceActionContract;
  passage: string;
  relevance: string;
  treatment: string | null;
  access_state: string;
  content_hash: string | null;
  source_version: string | null;
  retrieved_at: string | null;
  selected: boolean;
};

export type IntelligentReviewCompleteness = {
  selected_authority_count: number;
  supporting_authority_count: number;
  contrary_authority_count: number;
  cited_assertion_count: number;
  unsupported_assertion_count: number;
  complete: boolean;
  reasons: string[];
};

export type IntelligentReview = {
  id: string;
  company_id: string;
  matter_id: string | null;
  ip_docket_id: string | null;
  ip_proceeding_id: string | null;
  source_research_report_id: string;
  state: IntelligentReviewState;
  progress: number;
  error_code: string | null;
  issue: string;
  relevant_facts: string[];
  applicable_provisions: IntelligentReviewAssertion[];
  supporting_authorities: IntelligentReviewAuthority[];
  contrary_authorities: IntelligentReviewAuthority[];
  factual_analogies: IntelligentReviewAssertion[];
  gaps: string[];
  lawyer_checks: string[];
  unresolved_contradictions: string[];
  abstention_reason: string | null;
  stale_warning: string | null;
  source_freshness_at: string | null;
  non_exhaustive_disclaimer: string;
  lawyer_notes: string | null;
  completeness: IntelligentReviewCompleteness;
  review_template_version: string | null;
  prompt_policy_version: string | null;
  model_run_id: string | null;
  output_hash: string | null;
  finalized_by_membership_id: string | null;
  finalized_at: string | null;
  published_draft_id: string | null;
  created_at: string;
  updated_at: string;
};

export type IntelligentReviewCreateInput = {
  issue: string;
  sourceResearchReportId: string;
  matterId?: string | null;
  ipDocketId?: string | null;
  ipProceedingId?: string | null;
  facts: IntelligentReviewFactInput[];
  documentRefs: string[];
  includedAuthorityIds: string[];
};

export function createIntelligentReview(input: IntelligentReviewCreateInput) {
  return apiRequest<IntelligentReview>("/api/research/reviews", {
    method: "POST",
    body: {
      issue: input.issue,
      source_research_report_id: input.sourceResearchReportId,
      matter_id: input.matterId ?? null,
      ip_docket_id: input.ipDocketId ?? null,
      ip_proceeding_id: input.ipProceedingId ?? null,
      facts: input.facts,
      document_refs: input.documentRefs,
      included_authority_ids: input.includedAuthorityIds,
    },
  });
}

export function listIntelligentReviews(input?: {
  matterId?: string | null;
  ipDocketId?: string | null;
  limit?: number;
}) {
  const params = new URLSearchParams({ limit: String(input?.limit ?? 50) });
  if (input?.matterId) params.set("matter_id", input.matterId);
  if (input?.ipDocketId) params.set("ip_docket_id", input.ipDocketId);
  return apiRequest<{ reviews: IntelligentReview[] }>(
    `/api/research/reviews?${params.toString()}`,
  );
}

export function getIntelligentReview(reviewId: string) {
  return apiRequest<IntelligentReview>(
    `/api/research/reviews/${encodeURIComponent(reviewId)}`,
  );
}

export function updateIntelligentReviewAuthorities(input: {
  reviewId: string;
  includedAuthorityIds: string[];
  lawyerNotes?: string | null;
}) {
  return apiRequest<IntelligentReview>(
    `/api/research/reviews/${encodeURIComponent(input.reviewId)}/authorities`,
    {
      method: "PATCH",
      body: {
        included_authority_ids: input.includedAuthorityIds,
        lawyer_notes: input.lawyerNotes ?? null,
      },
    },
  );
}

export function finalizeIntelligentReview(input: {
  reviewId: string;
  lawyerNotes?: string | null;
}) {
  return apiRequest<IntelligentReview>(
    `/api/research/reviews/${encodeURIComponent(input.reviewId)}/finalize`,
    {
      method: "POST",
      body: { lawyer_notes: input.lawyerNotes ?? null },
    },
  );
}

export function publishIntelligentReview(input: {
  reviewId: string;
  title?: string | null;
}) {
  return apiRequest<{
    review: IntelligentReview;
    draft_id: string;
    draft_version_id: string;
  }>(`/api/research/reviews/${encodeURIComponent(input.reviewId)}/publish`, {
    method: "POST",
    body: { title: input.title ?? null },
  });
}
