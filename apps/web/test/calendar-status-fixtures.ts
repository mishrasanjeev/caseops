import type { components } from "@/lib/api/openapi-types";

type SyncStatus = components["schemas"]["CalendarEventSyncRecord"]["sync_status"];

const syncStates = {
  pending: true, synced: true, failed: true, retry_scheduled: true,
  dead_letter: true, deleted: true, delete_pending: true,
} satisfies Record<SyncStatus, true>;

export const canonicalCalendarSyncStates = Object.keys(syncStates) as SyncStatus[];
type BulkStatus = components["schemas"]["OutlookBulkSyncItem"]["sync_status"];
const bulkStates = { ...syncStates, skipped: true } satisfies Record<BulkStatus, true>;
export const canonicalBulkCalendarSyncStates = Object.keys(bulkStates) as BulkStatus[];

export function calendarStatusFixture(
  statuses: SyncStatus[] = ["delete_pending"],
): components["schemas"]["CalendarSyncStatusResponse"] {
  return {
    provider_available: true,
    durable_automation: "blocked_pending_provider_approval",
    notification_delivery: "wtd_5_3_foundation_available",
    capabilities: {
      sync_mode: "manual_bounded", manual_sync_available: true,
      durable_automation: "blocked_pending_provider_approval",
      notification_delivery: "wtd_5_3_foundation_available",
      email_invitation_candidates: "review_queue_available",
    },
    provider_config: [
      { provider: "outlook", configured: false, missing_config_names: ["OUTLOOK_CLIENT_ID"] },
      { provider: "google_calendar", configured: true, missing_config_names: [] },
    ],
    conflict_summary: {
      has_conflicts: false, candidate_count: 0, duplicate_provider_event_count: 0,
      changed_event_candidate_count: 0, changed_event_detection: "unsupported_no_provider_snapshot",
    },
    conflict_candidates: [],
    connections: [{
      id: "synthetic-calendar-connection", company_id: "synthetic-company",
      membership_id: "synthetic-member", provider: "google_calendar",
      provider_account_id: null, display_email: null, status: "revoked", scopes: [],
      connected_at: "2026-10-01T00:00:00Z", last_sync_at: null,
      created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-02T00:00:00Z",
    }],
    syncs: statuses.map((sync_status, index) => ({
      id: `synthetic-sync-${index}`, company_id: "synthetic-company",
      calendar_connection_id: "synthetic-calendar-connection", source_type: "matter_hearing",
      source_id: `synthetic-hearing-${index}`, provider_event_id: `synthetic-event-${index}`,
      sync_status, last_error: null, last_synced_at: null, attempts: 0, max_attempts: 3,
      next_attempt_at: null, dead_letter_reason: null,
      created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-02T00:00:00Z",
    })),
  };
}
