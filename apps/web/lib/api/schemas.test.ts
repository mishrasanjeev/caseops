import { describe, expect, it } from "vitest";

import {
  outsideCounselAssignmentStatus,
  outsideCounselSpendStatus,
  panelStatus,
  providerAdapterContractRecord,
  providerOperationRecord,
} from "@/lib/api/schemas";

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
      commercial_terms_status: "not_approved",
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
