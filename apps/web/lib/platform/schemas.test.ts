import { describe, expect, it } from "vitest";

import { consoleAdminRecord, consoleAuthState, consoleEnrollmentResponse, consoleOverview, consoleReportPage } from "./schemas";

describe("platform nested response contracts", () => {
  const admin = { id: "admin", email: "viewer@example.invalid", full_name: "Viewer", role: "viewer" };
  const state = { state: "authenticated", admin, expires_at: "2099-01-01T00:00:00Z", recovery_codes: null };
  it("retains the exact platform role and nullable first-verification codes", () => {
    expect(consoleAuthState.parse(state)).toEqual(state);
  });
  it.each(["owner", "platform:admin", "founder"])("does not promote tenant/founder role %s", (role) => {
    expect(consoleAuthState.safeParse({ ...state, admin: { ...admin, role } }).success).toBe(false);
  });
  it("rejects unexpected credentials in the top-level or nested identity", () => {
    expect(consoleAuthState.safeParse({ ...state, access_token: "not-allowed" }).success).toBe(false);
    expect(consoleAuthState.safeParse({ ...state, admin: { ...admin, company_id: "not-allowed" } }).success).toBe(false);
  });
  it("requires a fully verified identity for authenticated state", () => {
    expect(consoleAuthState.safeParse({ ...state, admin: null }).success).toBe(false);
  });
  it("mirrors the current enrollment DTO without inventing a QR field", () => {
    const enrollment = { secret: "TESTONLYSETUPKEY", otpauth_url: "otpauth://totp/CaseOps:fixture?secret=TESTONLYSETUPKEY" };
    expect(consoleEnrollmentResponse.parse(enrollment)).toEqual(enrollment);
    expect(consoleEnrollmentResponse.safeParse({ ...enrollment, qr_svg: "<svg />" }).success).toBe(false);
  });
  it("does not fabricate creation time or admin status", () => {
    expect(consoleAdminRecord.safeParse(admin).success).toBe(false);
  });
  it("keeps all report-page pagination and coverage fields", () => {
    const report = { items: [{ company_id: "company", feature_key: "document_read", quantity: 2, credits: 0, estimated_internal_cost_minor: 0 }], generated_at: "2026-10-20T10:00:00+05:30", next_cursor: null, has_more: false, coverage: "recorded_usage" };
    expect(consoleReportPage.parse(report)).toEqual(report);
    expect(consoleReportPage.safeParse({ ...report, items: [{ company_id: "company", quantity: 2 }] }).success).toBe(false);
  });
  const warning = {
    type: "case_refresh_cost_guardrail", severity: "warning", category: "case_refresh", provider: "case_tracking",
    unit_amount_minor: 37, message: "Actual tracked-case refresh cost is INR 0.10 or more. Pause public high-volume fixed-price bundles or require founder quote review.",
  };
  const overview = {
    generated_at: "2026-10-20T10:00:00+05:30", coverage: "recorded_rollups", rollup_count: 2,
    mrr_minor: 1234500, arr_minor: 14814000, active_subscriptions: 4, trial_count: 1, failed_payments: 0,
    gross_revenue_minor: 10000, recognized_revenue_minor: 10000, total_variable_cost_minor: 13000,
    gross_profit_minor: -3000, gross_margin_bps: -3000,
    margin_alerts: [{ company_id: "company", gross_margin_bps: null, gross_profit_minor: -3000 }, warning],
    margin_alerts_has_more: true,
  };
  it("retains both complete canonical overview alert variants without fabricating company margins for a warning", () => {
    expect(consoleOverview.parse(overview)).toEqual(overview);
  });
  it.each([
    { ...warning, type: "unreviewed_guardrail" },
    { ...warning, severity: "critical" },
    { ...warning, unit_amount_minor: "37" },
    { ...warning, message: undefined },
    { ...warning, company_id: "forged-margin-row" },
    { company_id: "company", gross_margin_bps: null, gross_profit_minor: -3000, type: "unreviewed" },
  ])("rejects unknown, incomplete or mixed overview alert shapes %#", (alert) => {
    expect(consoleOverview.safeParse({ ...overview, margin_alerts: [alert] }).success).toBe(false);
  });
});
