import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchIpPortfolio, fetchIpRenewalTracker, saveIpWorkspaceConfiguration, updateIpPortfolioDates, updateIpPortfolioRenewalDate,
  type IpWorkspaceConfiguration } from "./endpoints";

const docketId = "11111111-1111-4111-8111-111111111111";
const reason = "Synthetic source date correction";

describe("Portfolio renewal corrections through the real HTTP client", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.cookie = "caseops_csrf=renewal-fixture-csrf; path=/";
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    document.cookie = "caseops_csrf=; max-age=0; path=/";
    vi.unstubAllGlobals();
  });

  it("IP15 preserves unrelated current workspace policy when only reminder cadence changes", async () => {
    const configuration: IpWorkspaceConfiguration = {
      id: "configuration-1", version: 7, enabled_asset_types_json: ["trademark", "patent"],
      jurisdictions_json: ["IN", "GB"], offices_json: ["IP India", "UK IPO"],
      timezone: "Europe/London", holiday_calendar_key: "reviewed-calendar",
      working_day_policy_json: { working_weekdays: [0, 1, 2, 3], region: "reviewed" },
      document_taxonomy_version: "reviewed-taxonomy", event_catalog_version: "reviewed-events",
      deadline_rule_versions_json: { IN: "reviewed-in", GB: "reviewed-gb" },
      notification_channels_json: ["in_app", "email"], renewal_reminder_cadence_days: 1,
      renewal_reminder_delivery_time: "09:00", critical_event_policy_json: { escalation_after_minutes: 75 },
      escalation_owner_membership_id: "owner-1", provider_keys_json: ["reviewed-provider", "second-provider"],
      provider_terms_version: "reviewed-terms", provider_terms_accepted_by_membership_id: "owner-1",
      provider_terms_accepted_at: "2026-10-01T00:00:00Z", enabled_automations_json: [],
      workspace_enabled: true, updated_by_membership_id: "owner-1", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
    };
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ configuration }), { status: 200 }));
    await saveIpWorkspaceConfiguration({ currentConfiguration: configuration, expectedVersion: 7,
      jurisdiction: "IN", office: "IP India", timezone: "Europe/London", holidayCalendarKey: "reviewed-calendar",
      escalationOwnerMembershipId: "owner-1", providerKey: "reviewed-provider", acceptProviderTerms: true,
      renewalReminderCadenceDays: 2, renewalReminderDeliveryTime: "10:15" });
    expect(fetch).toHaveBeenCalledOnce();
    const payload = JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string);
    expect(payload).toEqual({ expected_version: 7, enabled_asset_types: ["trademark", "patent"],
      jurisdictions: ["IN", "GB"], offices: ["IP India", "UK IPO"], timezone: "Europe/London",
      holiday_calendar_key: "reviewed-calendar", working_day_policy: configuration.working_day_policy_json,
      document_taxonomy_version: "reviewed-taxonomy", event_catalog_version: "reviewed-events",
      deadline_rule_versions: configuration.deadline_rule_versions_json, notification_channels: ["in_app", "email"],
      critical_event_policy: { escalation_after_minutes: 75 }, escalation_owner_membership_id: "owner-1",
      provider_keys: ["reviewed-provider", "second-provider"], provider_terms_version: "reviewed-terms",
      accept_provider_terms: false, renewal_reminder_cadence_days: 2, renewal_reminder_delivery_time: "10:15" });
  });

  it.each([
    ["new-provider", true, true],
    ["new-provider", false, false],
    ["", true, false],
  ] as const)("IP15 sends only explicit new-provider consent (%s, %s)", async (providerKey, accepted, expected) => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ configuration: null, tests: [],
      ready_for_manual_docketing: false, enablement_blockers: [], provider_adapters: [] }), { status: 200 }));
    await saveIpWorkspaceConfiguration({ expectedVersion: null, jurisdiction: "IN", office: "IP India",
      timezone: "Asia/Kolkata", holidayCalendarKey: "reviewed-calendar", escalationOwnerMembershipId: "owner-1",
      providerKey, acceptProviderTerms: accepted, renewalReminderCadenceDays: 1, renewalReminderDeliveryTime: "09:00" });
    expect(fetch).toHaveBeenCalledOnce();
    const payload = JSON.parse(vi.mocked(fetch).mock.calls[0][1]!.body as string);
    expect(payload.accept_provider_terms).toBe(expected);
    expect(payload.provider_keys).toEqual(providerKey ? [providerKey] : []);
    expect(payload.provider_terms_version).toBe(providerKey ? "2026.1" : null);
  });

  it.each(["2029-04-30", null])("serializes correction %s exactly once, including null clearing", async renewalDueDate => {
    const response = { id: docketId, current_version: 8 };
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify(response), {
      status: 200, headers: { "Content-Type": "application/json" },
    }));

    await expect(updateIpPortfolioRenewalDate({ docketId, expectedCurrentVersion: 7,
      renewalDueDate, reason })).resolves.toEqual(response);

    expect(fetch).toHaveBeenCalledTimes(1);
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toBe(`http://localhost:8000/api/ip/dockets/${docketId}/portfolio-renewal-date`);
    expect(init).toMatchObject({ method: "PATCH", credentials: "include", headers: {
      "Content-Type": "application/json", "X-CSRF-Token": "renewal-fixture-csrf",
    } });
    expect(JSON.parse(init!.body as string)).toEqual({ expected_current_version: 7,
      renewal_due_date: renewalDueDate, reason });
  });

  it.each([409, 422, 500])("preserves HTTP %s without retrying a failed correction", async status => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({
      type: "portfolio_correction_rejected", status, detail: "Synthetic correction rejection",
    }), { status, headers: { "Content-Type": "application/problem+json" } }));

    await expect(updateIpPortfolioRenewalDate({ docketId, expectedCurrentVersion: 7,
      renewalDueDate: null, reason })).rejects.toMatchObject({ status,
      problemType: "portfolio_correction_rejected", detail: "Synthetic correction rejection" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("does not retry a transport failure", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Synthetic network failure"));
    await expect(updateIpPortfolioRenewalDate({ docketId, expectedCurrentVersion: 7,
      renewalDueDate: null, reason })).rejects.toMatchObject({ name: "NetworkError" });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it.each([
    { expected_current_version: 7, application_date: "2026-02-01", reason },
    { expected_current_version: 7, renewal_due_date: null, reason },
    { expected_current_version: 7, application_date: null, renewal_due_date: "2028-03-31", reason },
  ])("IP15 preserves independent date fields, null clearing and concurrency through one JSON serialization", async payload => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ docket_id: docketId, current_version: 8 }), { status: 200 }));
    await updateIpPortfolioDates(docketId, payload);
    expect(fetch).toHaveBeenCalledOnce();
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toBe(`http://localhost:8000/api/ip/dockets/${docketId}/portfolio-dates`);
    expect(init).toMatchObject({ method: "PATCH", credentials: "include", headers: {
      "Content-Type": "application/json", "X-CSRF-Token": "renewal-fixture-csrf",
    } });
    expect(JSON.parse(init!.body as string)).toEqual(payload);
  });

  it.each([403, 404, 409, 422, 500])("IP15 never retries a rejected date mutation (%s)", async status => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ status, detail: "Date update rejected" }), { status }));
    await expect(updateIpPortfolioDates(docketId, { expected_current_version: 7, application_date: null, reason }))
      .rejects.toMatchObject({ status });
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("IP15 serializes date ranges and tracker state into portfolio reads", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ rows: [] }), { status: 200 }));
    await fetchIpPortfolio({ application_date_from: "2026-01-01", application_date_to: "2026-12-31",
      renewal_due_from: "2028-01-01", renewal_due_to: "2028-12-31", renewal_tracker_state: ["active", "failed"] });
    const url = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(url.pathname).toBe("/api/ip/portfolio");
    expect(Object.fromEntries(url.searchParams)).toMatchObject({ application_date_from: "2026-01-01",
      application_date_to: "2026-12-31", renewal_due_from: "2028-01-01", renewal_due_to: "2028-12-31" });
    expect(url.searchParams.getAll("renewal_tracker_state")).toEqual(["active", "failed"]);
  });

  it("IP15 sends bounded tracker pagination and the selected category", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ rows: [] }), { status: 200 }));
    await fetchIpRenewalTracker({ category: "missing", limit: 50, cursor: "server-owned-cursor", horizonDays: 90 });
    const url = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(url.pathname).toBe("/api/ip/portfolio/renewal-tracker");
    expect(Object.fromEntries(url.searchParams)).toEqual({ category: "missing", limit: "50", cursor: "server-owned-cursor", horizon_days: "90" });
  });

  it("IP18 keeps all source-date ranges and the opaque continuation in tracker reads", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ rows: [] }), { status: 200 }));
    await fetchIpRenewalTracker({ query: "supplied source", category: "upcoming", limit: 50,
      cursor: "signed-current-scope.cursor", application_date_from: "2020-01-01",
      application_date_to: "2020-12-31", renewal_due_from: "2028-03-01", renewal_due_to: "2028-03-31" });
    expect(fetch).toHaveBeenCalledOnce();
    const url = new URL(String(vi.mocked(fetch).mock.calls[0][0]));
    expect(url.pathname).toBe("/api/ip/portfolio/renewal-tracker");
    expect(Object.fromEntries(url.searchParams)).toEqual({ query: "supplied source", category: "upcoming",
      limit: "50", cursor: "signed-current-scope.cursor", application_date_from: "2020-01-01",
      application_date_to: "2020-12-31", renewal_due_from: "2028-03-01", renewal_due_to: "2028-03-31" });
  });

  it("IP18 forwards tracker query cancellation to the existing transport", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ rows: [] }), { status: 200 }));
    const controller = new AbortController();
    controller.abort();
    await fetchIpRenewalTracker({ query: "supplied source", category: "missing" }, { signal: controller.signal });
    expect(fetch).toHaveBeenCalledOnce();
    expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
  });
});
