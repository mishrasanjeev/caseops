import { describe, expect, it } from "vitest";

import { calendarEventSyncRecord, calendarEventSyncResponse, calendarSyncStatusResponse, outlookBulkSyncItem } from "@/lib/api/schemas";
import { calendarStatusFixture, canonicalBulkCalendarSyncStates, canonicalCalendarSyncStates } from "@/test/calendar-status-fixtures";

describe("complete Calendar sync response contract", () => {
  it.each(canonicalCalendarSyncStates)("retains canonical status %s", (status) => {
    const response = calendarStatusFixture([status]);
    expect(calendarSyncStatusResponse.parse(response)).toEqual(response);
    expect(calendarEventSyncResponse.parse({ sync: response.syncs[0] }).sync).toEqual(response.syncs[0]);
  });

  it.each(canonicalBulkCalendarSyncStates)("accepts shared Google/Outlook bulk status %s", (status) => {
    const item = { source_type: "matter_hearing", source_id: "synthetic-hearing",
      sync_status: status, matter_id: null, matter_title: null };
    expect(outlookBulkSyncItem.parse(item)).toEqual(item);
  });

  it("rejects an unknown bulk state without weakening the shared contract", () => {
    expect(outlookBulkSyncItem.safeParse({ source_type: "matter_hearing", source_id: "synthetic-hearing",
      sync_status: "unrecognized_provider_state", matter_id: null, matter_title: null }).success).toBe(false);
  });

  it("does not drop pending cleanup or broaden the status validator", () => {
    expect(calendarEventSyncRecord.shape.sync_status.options).toEqual(canonicalCalendarSyncStates);
    const response = calendarStatusFixture();
    expect(calendarSyncStatusResponse.safeParse({ ...response,
      syncs: [{ ...response.syncs[0], sync_status: "unrecognized_provider_state" }],
    }).success).toBe(false);
  });
});
