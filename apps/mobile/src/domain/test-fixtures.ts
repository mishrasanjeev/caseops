// Synthetic decoder fixtures only. Never imported by the application.
export function matterFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "matter-test",
    matter_code: "SYNTHETIC-TEST",
    title: "Synthetic test matter",
    status: "active",
    lifecycle_version: 4,
    updated_at: "2026-10-24T12:00:00Z",
    created_at: "2026-01-01T12:00:00Z",
    next_hearing_on: "2026-10-25",
    next_hearing_source: "manual",
    ...overrides,
  };
}
export function noteFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "note-test",
    matter_id: "matter-test",
    body: "Synthetic note for test",
    created_at: "2026-10-24T12:00:01Z",
    author_name: "Synthetic author",
    author_membership_id: "member-test",
    author_role: "member",
    ...overrides,
  };
}
export function workspaceFixture(overrides: Record<string, unknown> = {}) {
  return {
    matter: matterFixture(),
    notes: [],
    tasks: [],
    attachments: [],
    activity: [],
    ...overrides,
  };
}
export function todayFixture(overrides: Record<string, unknown> = {}) {
  return {
    today: "2026-10-24",
    horizon_days: 7,
    hearings_next_7d: [],
    tasks_due_or_overdue: [],
    drafts_in_review: [],
    deadlines_next_7d: [],
    overdue_invoices: [],
    ...overrides,
  };
}
export function draftFixture(overrides: Record<string, unknown> = {}) {
  return {
    id: "draft-test",
    matter_id: "matter-test",
    ip_docket_id: null,
    title: "Synthetic draft",
    status: "in_review",
    current_version_id: "version-current",
    versions: [
      {
        id: "version-current",
        draft_id: "draft-test",
        revision: 2,
        body: "Current synthetic version",
        citations: ["Synthetic citation"],
        verified_citation_count: 0,
      },
      {
        id: "version-later-in-array",
        draft_id: "draft-test",
        revision: 1,
        body: "Historical synthetic version",
        citations: [],
        verified_citation_count: 0,
      },
    ],
    ...overrides,
  };
}
