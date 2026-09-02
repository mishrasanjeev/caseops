import { describe, expect, it } from "vitest";

import {
  googleWorkspaceReadinessTestResponse,
  googleWorkspaceTenantConfigurationResponse,
  outlookReadinessTestResponse,
  outlookTenantConfigurationResponse,
  outsideCounselAssignmentStatus,
  outsideCounselSpendStatus,
  panelStatus,
  providerAdapterContractRecord,
  providerCostProfileRecord,
  providerOperationRecord,
} from "@/lib/api/schemas";

describe("connector readiness mixed-revision compatibility", () => {
  it("accepts an older Outlook API response but forces machine readiness blocked", () => {
    const parsed = outlookTenantConfigurationResponse.parse({
      provider: "outlook",
      configured: true,
      config_source: "tenant_admin",
      enabled: true,
      required_config: [],
      required_approvals: [],
      approved_scopes: [],
      missing_config_names: [],
      missing_approval_keys: [],
      connection_count: 1,
      connected_account_count: 1,
      last_test_status: "passed",
      last_tested_at: "2026-08-30T00:00:00Z",
      last_error_redacted: null,
      adp20_readiness: "ready_for_adp20_implementation",
    });

    expect(parsed.machine_control_version).toBe("legacy-api-unversioned");
    expect(parsed.missing_machine_control_keys).toEqual([
      "machine_controls_unavailable",
    ]);
    expect(parsed.machine_controls[0]?.status).toBe("blocked");
    expect(parsed.last_test_status).toBe("blocked");
    expect(parsed.adp20_readiness).toBe("blocked_pending_admin_configuration");
  });

  it("accepts older Google and probe responses without allowing an always-green gate", () => {
    const configuration = googleWorkspaceTenantConfigurationResponse.parse({
      provider: "google_workspace",
      configured: true,
      config_source: "tenant_admin",
      enabled: true,
      calendar_enabled: true,
      gmail_enabled: true,
      drive_enabled: true,
      required_config: [],
      required_approvals: [],
      approved_scopes: [],
      missing_config_names: [],
      missing_approval_keys: [],
      connection_counts: {
        calendar_connection_count: 0,
        gmail_connection_count: 0,
        drive_connection_count: 0,
        connected_calendar_account_count: 0,
        connected_gmail_account_count: 0,
        connected_drive_account_count: 0,
      },
      last_test_status: "passed",
      last_tested_at: "2026-08-30T00:00:00Z",
      last_error_redacted: null,
      readiness: "ready_for_user_connections",
    });
    const googleProbe = googleWorkspaceReadinessTestResponse.parse({
      provider: "google_workspace",
      status: "passed",
      checks: [],
      readiness: "ready_for_user_connections",
      tested_at: "2026-08-30T00:00:00Z",
    });
    const outlookProbe = outlookReadinessTestResponse.parse({
      provider: "outlook",
      status: "passed",
      checks: [],
      adp20_readiness: "ready_for_adp20_implementation",
      tested_at: "2026-08-30T00:00:00Z",
    });

    expect(configuration.readiness).toBe("blocked_pending_admin_configuration");
    expect(configuration.machine_controls[0]?.status).toBe("blocked");
    expect(googleProbe.status).toBe("blocked");
    expect(googleProbe.readiness).toBe("blocked_pending_admin_configuration");
    expect(outlookProbe.status).toBe("blocked");
    expect(outlookProbe.adp20_readiness).toBe(
      "blocked_pending_admin_configuration",
    );
  });
});

// All three enums below MUST match
// apps/api/src/caseops_api/db/models.py (OutsideCounselPanelStatus,
// OutsideCounselAssignmentStatus, OutsideCounselSpendStatus). The
// 2026-04-22 audit found three independent drifts that each broke
// the Outside Counsel module by failing Zod parse on real backend
// rows. These tests pin every canonical value as accepted and every
// previously-incorrect value as rejected, so the drift cannot
// silently recur even one enum at a time.

describe("panelStatus", () => {
  it.each([["active"], ["preferred"], ["inactive"]])(
    "accepts the canonical backend value %s",
    (value) => {
      expect(panelStatus.parse(value)).toBe(value);
    },
  );

  it.each([
    ["approved"], ["trial"], ["blocked"], ["archived"], ["on_hold"],
  ])(
    "rejects the previously-incorrect value %s so the drift cannot recur",
    (value) => {
      expect(() => panelStatus.parse(value)).toThrow();
    },
  );
});

describe("outsideCounselAssignmentStatus", () => {
  it.each([["proposed"], ["approved"], ["active"], ["closed"]])(
    "accepts the canonical backend value %s",
    (value) => {
      expect(outsideCounselAssignmentStatus.parse(value)).toBe(value);
    },
  );

  it.each([["declined"], ["completed"]])(
    "rejects the previously-incorrect value %s",
    (value) => {
      expect(() => outsideCounselAssignmentStatus.parse(value)).toThrow();
    },
  );
});

describe("outsideCounselSpendStatus", () => {
  it.each([
    ["submitted"], ["approved"], ["partially_approved"],
    ["disputed"], ["paid"],
  ])(
    "accepts the canonical backend value %s",
    (value) => {
      expect(outsideCounselSpendStatus.parse(value)).toBe(value);
    },
  );

  it("accepts partially_approved (the value missing from the prior enum)", () => {
    expect(outsideCounselSpendStatus.parse("partially_approved")).toBe(
      "partially_approved",
    );
  });

  it.each([["rejected"], ["cancelled"]])(
    "rejects the previously-incorrect value %s",
    (value) => {
      expect(() => outsideCounselSpendStatus.parse(value)).toThrow();
    },
  );
});

describe("providerAdapterContractRecord", () => {
  it("accepts a licensed legal-research adapter that is implemented default-off", () => {
    const parsed = providerAdapterContractRecord.parse({
      provider: "indian-kanoon",
      display_name: "Indian Kanoon licensed API",
      domain: "legal_research",
      adapter_status: "implemented_default_off",
      commercial_terms_status: "runtime_metadata_governed",
      required_capabilities: ["search", "document"],
      implemented_capabilities: ["search", "document"],
      attribution_label: "Powered by Indian Kanoon",
      cost_categories: ["legal_source_search"],
      health_path: "/api/authorities/providers/indian-kanoon/health",
      support_matrix_path: "/api/authorities/providers/indian-kanoon/readiness",
      operations_path: "/api/admin/provider-operations/jobs",
      endpoint_paths: ["/api/authorities/providers/indian-kanoon/search"],
      legal_coverage: [],
      activation_blockers: ["provider disabled"],
      limitations: ["No public HTML scraping."],
    });

    expect(parsed.domain).toBe("legal_research");
    expect(parsed.adapter_status).toBe("implemented_default_off");
  });
});

describe("providerCostProfileRecord", () => {
  it.each([
    ["legal_source_search", 50],
    ["legal_source_document", 20],
    ["legal_source_original_document", 50],
    ["legal_source_fragment", 5],
    ["legal_source_metadata", 2],
  ])("accepts the Indian Kanoon cost category %s", (category, amount) => {
    const parsed = providerCostProfileRecord.parse({
      id: `indian-kanoon-${category}`,
      category,
      provider: "indian-kanoon",
      currency: "INR",
      unit_amount_minor: amount,
      unit_amount_bps: null,
      unit_label: "request",
      effective_from: "2026-09-02T00:00:00Z",
      effective_until: null,
      status: "active",
      source: "https://api.indiankanoon.org/pricing/",
      tax_fee_notes: null,
      cost_basis: "actual",
      confidence_level: "high",
      evidence_ref: "Indian Kanoon API pricing checked 2026-09-02",
      founder_approval_status: "pending",
      approved_at: null,
      approved_by_platform_admin_id: null,
      notes: null,
      created_by_platform_admin_id: "platform-1",
      created_at: "2026-09-02T00:00:00Z",
      updated_at: "2026-09-02T00:00:00Z",
    });

    expect(parsed.category).toBe(category);
    expect(parsed.unit_amount_minor).toBe(amount);
  });
});

describe("providerOperationRecord", () => {
  it.each([
    ["ip_registry_sync", "provider_outage"],
    ["ip_journal_ingestion", "rate_limit"],
    ["source_link_health", "changed_content"],
  ])("accepts the IPLF-056 operation kind %s", (jobKind, responseClass) => {
    const parsed = providerOperationRecord.parse({
      id: `${jobKind}:operation-1`,
      job_kind: jobKind,
      provider: "ipindia-registry",
      company_id: "company-1",
      matter_id: null,
      source_type: "ip_registry_link",
      source_ref: "id:abc123",
      provider_item_ref: null,
      status: "failed",
      operator_state: "open",
      error_redacted: "Provider operation failed.",
      dead_letter_reason: null,
      attempts: 1,
      max_attempts: 1,
      next_attempt_at: null,
      created_at: "2026-08-25T00:00:00Z",
      updated_at: "2026-08-25T00:00:00Z",
      correlation_ref: null,
      response_class: responseClass,
      last_attempted_at: "2026-08-25T00:00:00Z",
      last_successful_at: null,
      last_good_at: null,
      next_scheduled_at: null,
      freshness_state: "stale",
      records_affected: null,
      estimated_cost_minor: 0,
      estimated_cost_currency: "INR",
      estimated_cost_basis: "recorded_provider_attempt",
      retryable: false,
      quarantined: false,
      replay_available: false,
      ignore_available: false,
      mark_resolved_available: false,
      notes: [],
    });

    expect(parsed.job_kind).toBe(jobKind);
    expect(parsed.response_class).toBe(responseClass);
  });
});
