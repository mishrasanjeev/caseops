// Synthetic source-unit DTOs. Actual API/native acceptance uses independently
// persisted records and complete populated canonical HTTP responses.
export const readScopeFixture = () => ({
  company_id: "co",
  matter_id: "matter",
  matter_status: "active",
  matter_is_active: true,
  matter_lifecycle_version: 2,
});
export const readMetadataFixture = () => ({
  type: "authority",
  title: "Stored recommendation",
  confidence: "medium",
  review_required: true,
  status: "proposed",
});
export const readSummaryFixture = (id = "rec") => ({
  id,
  read_state: "available",
  record: readMetadataFixture(),
  created_at: "2026-10-28T00:00:00.000001+00:00",
  updated_at: "2026-10-28T01:00:00.000002+00:00",
});
export const readRecommendationFixture = () => ({
  ...readSummaryFixture(),
  scope: readScopeFixture(),
  record: {
    ...readMetadataFixture(),
    rationale: "Recorded reasoning",
    primary_option_index: 0,
    assumptions: ["Recorded assumption"],
    missing_facts: [],
    next_action: null,
    retrieved_authorities: ["Recorded citation"],
    strategy_payload: null,
    analysis: null,
  },
});
export const readOptionFixture = (id = "option", rank = 0) => ({
  id,
  rank,
  read_state: "available",
  record: {
    label: "Stored option",
    rationale: "Stored rationale",
    confidence: "low",
    supporting_citations: ["Recorded citation"],
    risk_notes: null,
  },
});
export const readDecisionFixture = () => ({
  id: "decision",
  read_state: "available",
  record: {
    actor_membership_id: null,
    decision: "deferred",
    selected_option_index: null,
    notes: null,
  },
  created_at: "2026-10-28T02:00:00.000001+00:00",
});
export const readPackFixture = () => ({
  id: "pack",
  scope: readScopeFixture(),
  hearing_id: "hearing",
  generated_at: "2026-10-28T03:00:00.000001+00:00",
  reviewed_at: null,
  read_state: "available",
  record: {
    generated_by_membership_id: null,
    reviewed_by_membership_id: null,
    model_run_id: null,
    status: "draft",
    summary: "Saved pack summary",
    review_required: true,
  },
});
export const readPackItemFixture = (id = "item", rank = 0) => ({
  id,
  rank,
  created_at: "2026-10-28T03:00:00.000002+00:00",
  read_state: "available",
  record: {
    item_type: "authority_card",
    title: "Stored authority card",
    body: "Exact retained content",
    source_ref: "https://untrusted.example.test/not-an-open-command",
  },
});
export const readPageFixture = (
  kind = "recommendations",
  items: unknown[] = [readSummaryFixture()],
  next: string | null = null,
) => ({
  scope: readScopeFixture(),
  kind,
  order: ["recommendation_options", "hearing_pack_items"].includes(kind)
    ? "rank_asc_id_asc"
    : "created_at_desc_id_desc",
  parent_id:
    kind === "recommendations"
      ? null
      : kind === "hearing_pack_items"
        ? "pack"
        : "rec",
  limit: 25,
  items,
  next_cursor: next,
});
