import { describe, expect, it } from "vitest";

import { activityFixture } from "./activity-fixture.test-data";
import { activityReport } from "./activity-schema";

describe("complete canonical ActivityReportResponse adapter", () => {
  it("retains every category, period, snapshot, engagement and account-scope field", () => {
    const payload = activityFixture();
    expect(activityReport.parse(JSON.parse(JSON.stringify(payload)))).toEqual(payload);
    expect(Object.keys(payload.segments.solo_lawyers.accounts[0].current)).toHaveLength(11);
    expect(Object.keys(payload.segments.solo_lawyers.accounts[0].periods.day)).toHaveLength(16);
  });
  it.each(["law_firms", "general_counsels", "solo_lawyers", "other"] as const)("requires the complete %s account snapshot", (name) => {
    const payload = activityFixture();
    const raw = payload as unknown as { segments: Record<string, { accounts: { current: Record<string, unknown> }[] }> };
    delete raw.segments[name].accounts[0].current.documents_total;
    expect(activityReport.safeParse(raw).success).toBe(false);
  });
  it("rejects omitted accounts hidden behind a matching-looking summary", () => {
    const payload = activityFixture(); payload.segments.solo_lawyers.accounts = [];
    expect(activityReport.safeParse(payload).success).toBe(false);
  });
  it("rejects a duplicated account across categories", () => {
    const payload = activityFixture(); payload.segments.other.accounts[0].company_id = payload.segments.law_firms.accounts[0].company_id;
    expect(activityReport.safeParse(payload).success).toBe(false);
  });
  it("rejects unknown classifications instead of silently treating them as inactive", () => {
    const payload = activityFixture();
    expect(activityReport.safeParse({ ...payload, activity_window: { ...payload.activity_window, basis: "last_row_updated" } }).success).toBe(false);
    expect(activityReport.safeParse({ ...payload, account_scope: "unknown_scope" }).success).toBe(false);
  });
  it("rejects an extra raw tenant payload nested in a canonical account", () => {
    const payload = activityFixture();
    const row = payload.segments.law_firms.accounts[0];
    Object.assign(row, { raw_audit_events: [{ private_body: "not-admitted" }] });
    expect(activityReport.safeParse(payload).success).toBe(false);
  });
  it.each(["recent", "inactive"] as const)("requires timestamp evidence for %s", (status) => {
    const payload = activityFixture();
    payload.segments.general_counsels.accounts[0].usage_status = status;
    expect(activityReport.safeParse(payload).success).toBe(false);
  });
  it("keeps null evidence unknown but rejects future timestamps for every classification", () => {
    const payload = activityFixture();
    expect(activityReport.safeParse(payload).success).toBe(true);
    for (const status of ["unknown", "recent", "inactive"] as const) {
      payload.segments.other.accounts[0].usage_status = status;
      payload.segments.other.accounts[0].last_meaningful_activity_at = "2026-10-21T07:00:00+05:30";
      expect(activityReport.safeParse(payload).success).toBe(false);
    }
  });
  it("requires the engagement window to end at report generation", () => {
    const payload = activityFixture(); payload.generated_at = "2026-10-20T08:30:00+05:30";
    expect(activityReport.safeParse(payload).success).toBe(false);
  });
  it("cannot exclude accounts while claiming all-registered scope", () => {
    const payload = activityFixture(); payload.excluded_account_count = 1;
    expect(activityReport.safeParse(payload).success).toBe(false);
    payload.account_scope = "operational_email";
    expect(activityReport.safeParse(payload).success).toBe(true);
  });
  it("rejects a reversed metric period and a non-30-day engagement window", () => {
    const payload = activityFixture();
    payload.reporting_periods.month.start_date = "2026-10-01";
    expect(activityReport.safeParse(payload).success).toBe(false);
    const other = activityFixture(); other.activity_window.cutoff = "2026-09-21T07:30:00+05:30";
    expect(activityReport.safeParse(other).success).toBe(false);
  });
});
