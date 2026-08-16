import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  enableIpWorkspaceMock,
  fetchIpDeadlineWorkspaceMock,
  fetchIpCoreRecordsMock,
  fetchIpDocketsMock,
  fetchIpDocumentsMock,
  fetchIpDocumentTaxonomyMock,
  fetchIpProsecutionWorkspaceMock,
  fetchIpSharedHearingsMock,
  fetchIpWorkspaceReadinessMock,
  listCalendarConnectionsMock,
  previewIpDocketEventMock,
  previewIpDocketLifecycleMock,
  runIpWorkspaceTestMock,
  saveIpWorkspaceConfigurationMock,
  appendIpDocketEventMock,
  transitionIpDocketLifecycleMock,
  confirmIpLegalDeadlineMock,
  proposeIpLegalDeadlineMock,
  createIpSharedHearingMock,
  fetchIpAccessPanelMock,
  listEmployeesMock,
  listTeamsMock,
  previewIpAccessChangeMock,
  applyIpAccessChangeMock,
  fetchIpCoverageTransfersAwaitingMeMock,
  decideIpCoverageTransferMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  enableIpWorkspaceMock: vi.fn(),
  fetchIpDeadlineWorkspaceMock: vi.fn(),
  fetchIpCoreRecordsMock: vi.fn(),
  fetchIpDocketsMock: vi.fn(),
  fetchIpDocumentsMock: vi.fn(),
  fetchIpDocumentTaxonomyMock: vi.fn(),
  fetchIpProsecutionWorkspaceMock: vi.fn(),
  fetchIpSharedHearingsMock: vi.fn(),
  fetchIpWorkspaceReadinessMock: vi.fn(),
  listCalendarConnectionsMock: vi.fn(),
  previewIpDocketEventMock: vi.fn(),
  previewIpDocketLifecycleMock: vi.fn(),
  runIpWorkspaceTestMock: vi.fn(),
  saveIpWorkspaceConfigurationMock: vi.fn(),
  appendIpDocketEventMock: vi.fn(),
  transitionIpDocketLifecycleMock: vi.fn(),
  confirmIpLegalDeadlineMock: vi.fn(),
  proposeIpLegalDeadlineMock: vi.fn(),
  createIpSharedHearingMock: vi.fn(),
  fetchIpAccessPanelMock: vi.fn(),
  listEmployeesMock: vi.fn(),
  listTeamsMock: vi.fn(),
  previewIpAccessChangeMock: vi.fn(),
  applyIpAccessChangeMock: vi.fn(),
  fetchIpCoverageTransfersAwaitingMeMock: vi.fn(),
  decideIpCoverageTransferMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchIpDockets: fetchIpDocketsMock,
  fetchIpDocuments: fetchIpDocumentsMock,
  fetchIpDocumentTaxonomy: fetchIpDocumentTaxonomyMock,
  previewIpDocumentName: vi.fn(),
  importIpDocumentAliases: vi.fn(),
  downloadApiFile: vi.fn(),
  uploadIpDocument: vi.fn(),
  uploadIpDocumentVersion: vi.fn(),
  addIpDocumentLinks: vi.fn(),
  transitionIpDocument: vi.fn(),
  previewIpDocumentBulk: vi.fn(),
  applyIpDocumentBulk: vi.fn(),
  fetchIpDeadlineWorkspace: fetchIpDeadlineWorkspaceMock,
  fetchIpCoreRecords: fetchIpCoreRecordsMock,
  fetchIpProsecutionWorkspace: fetchIpProsecutionWorkspaceMock,
  fetchIpSharedHearings: fetchIpSharedHearingsMock,
  fetchIpWorkspaceReadiness: fetchIpWorkspaceReadinessMock,
  enableIpWorkspace: enableIpWorkspaceMock,
  runIpWorkspaceTest: runIpWorkspaceTestMock,
  saveIpWorkspaceConfiguration: saveIpWorkspaceConfigurationMock,
  createIpDocket: vi.fn(),
  createIpSharedHearing: createIpSharedHearingMock,
  updateIpSharedHearing: vi.fn(),
  listCalendarConnections: listCalendarConnectionsMock,
  syncHearingToOutlook: vi.fn(),
  syncHearingToGoogleCalendar: vi.fn(),
  addIpTitleInterest: vi.fn(),
  addIpCostItem: vi.fn(),
  discoverIpEvidence: vi.fn(),
  reviewIpEvidenceCandidate: vi.fn(),
  bulkReassignIpCoverage: vi.fn(),
  addIpRelatedRightObligation: vi.fn(),
  completeIpRelatedRightObligation: vi.fn(),
  reconcileIpCosts: vi.fn(),
  previewIpDocketEvent: previewIpDocketEventMock,
  appendIpDocketEvent: appendIpDocketEventMock,
  previewIpDocketLifecycle: previewIpDocketLifecycleMock,
  transitionIpDocketLifecycle: transitionIpDocketLifecycleMock,
  proposeIpLegalDeadline: proposeIpLegalDeadlineMock,
  confirmIpLegalDeadline: confirmIpLegalDeadlineMock,
  fetchIpDeadlineImpact: vi.fn(),
  overrideIpLegalDeadline: vi.fn(),
  recalculateIpLegalDeadline: vi.fn(),
  completeIpLegalDeadline: vi.fn(),
  proposeIpWorkingCalendar: vi.fn(),
  activateIpWorkingCalendar: vi.fn(),
  proposeIpDeadlineRule: vi.fn(),
  fetchIpDeadlineRuleImpact: vi.fn(),
  activateIpDeadlineRule: vi.fn(),
  transitionIpDeadlineRule: vi.fn(),
  fetchIpAccessPanel: fetchIpAccessPanelMock,
  listEmployees: listEmployeesMock,
  listTeams: listTeamsMock,
  previewIpAccessChange: previewIpAccessChangeMock,
  applyIpAccessChange: applyIpAccessChangeMock,
  fetchIpCoverageTransfersAwaitingMe: fetchIpCoverageTransfersAwaitingMeMock,
  decideIpCoverageTransfer: decideIpCoverageTransferMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/lib/use-session", () => ({
  useSession: () => ({ context: { membership: { id: "membership-1" } } }),
}));

import IpDocketPage from "@/app/app/ip/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("IpDocketPage", () => {
  beforeEach(() => {
    fetchIpDocketsMock.mockReset();
    fetchIpDocumentsMock.mockReset();
    fetchIpDocumentTaxonomyMock.mockReset();
    fetchIpDeadlineWorkspaceMock.mockReset();
    fetchIpCoreRecordsMock.mockReset();
    fetchIpProsecutionWorkspaceMock.mockReset();
    fetchIpSharedHearingsMock.mockReset();
    fetchIpWorkspaceReadinessMock.mockReset();
    listCalendarConnectionsMock.mockReset();
    previewIpDocketEventMock.mockReset();
    previewIpDocketLifecycleMock.mockReset();
    appendIpDocketEventMock.mockReset();
    transitionIpDocketLifecycleMock.mockReset();
    confirmIpLegalDeadlineMock.mockReset();
    proposeIpLegalDeadlineMock.mockReset();
    createIpSharedHearingMock.mockReset();
    fetchIpAccessPanelMock.mockReset();
    listEmployeesMock.mockReset();
    listTeamsMock.mockReset();
    previewIpAccessChangeMock.mockReset();
    applyIpAccessChangeMock.mockReset();
    fetchIpCoverageTransfersAwaitingMeMock.mockReset();
    decideIpCoverageTransferMock.mockReset();
    fetchIpCoverageTransfersAwaitingMeMock.mockResolvedValue({ transfers: [] });
    decideIpCoverageTransferMock.mockResolvedValue({});
    enableIpWorkspaceMock.mockReset();
    runIpWorkspaceTestMock.mockReset();
    saveIpWorkspaceConfigurationMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    fetchIpWorkspaceReadinessMock.mockResolvedValue({
      timezone: "Asia/Calcutta",
      workspace_available: true,
      manual_docketing_available: true,
      features: [],
    });
    fetchIpDocketsMock.mockResolvedValue({ dockets: [], count: 0 });
    fetchIpDocumentsMock.mockResolvedValue({ items: [], total: 0 });
    fetchIpDocumentTaxonomyMock.mockResolvedValue({
      taxonomy_version: "ip-document-taxonomy-v1",
      entries: [{ key: "evidence", label: "Evidence", is_active: true, version: 1 }],
    });
    fetchIpDeadlineWorkspaceMock.mockResolvedValue({
      docket_id: "ip-1",
      rules: [{
        id: "rule-1", key: "in-tm-response", version: 1, status: "active",
        source_reference: "official:rule", rule_set_id: "set-1", rule_kind: "deadline",
      }],
      calendars: [{
        id: "calendar-1", calendar_id: "calendar-set-1", key: "ip-india",
        name: "IP India calendar", version: 1, status: "active", timezone: "Asia/Kolkata",
        weekend_days: [5, 6], holidays: [], exceptional_working_days: [],
        source_reference: "official:calendar", source_hash: "a".repeat(64),
      }],
      deadlines: [], exceptions: [], automation_state: "explicit_confirmation_only",
    });
    fetchIpCoreRecordsMock.mockResolvedValue({ assets: [], applications: [], proceedings: [], identifiers: [] });
    fetchIpProsecutionWorkspaceMock.mockResolvedValue({
      docket_id: "ip-1", lifecycle_status: "active", lifecycle_version: 0,
      current_phase: "draft", registry_freshness: "not_configured",
      data_quality_gaps: [], unconfirmed_deadline_refs: [], conflicting_event_ids: [],
      events: [], operational_completion_count: 0, filing_evidence_count: 0,
      registry_acceptance_count: 0, final_disposition_count: 0,
    });
    fetchIpSharedHearingsMock.mockResolvedValue({ docket_id: "ip-1", hearings: [] });
    listCalendarConnectionsMock.mockResolvedValue({ connections: [] });
    listEmployeesMock.mockResolvedValue({ employees: [], total: 0 });
    listTeamsMock.mockResolvedValue({ teams: [], total: 0 });
    fetchIpAccessPanelMock.mockResolvedValue({
      docket_id: "ip-1",
      restricted: false,
      access_policy_version: 0,
      active_internal_membership_count: 1,
      grants: [],
      walls: [],
      linked_matter_id: "matter-1",
      linked_matter_mismatch_count: 0,
      persistence_contract: {
        canonical_owner: "matter_access_grants_and_ethical_walls",
        excluded: ["portal_access", "access_reviews", "emergency_access"],
      },
    });
    previewIpDocketEventMock.mockResolvedValue({
      docket_id: "ip-1", lifecycle_version: 0, current_phase: "draft",
      proposed_phase: "formalities", backdated: false, recalculation_required: false,
      duplicate_candidate_ids: [], checklist: [{ category: "document", key: "document_evidence", label: "Supporting document", required: true, satisfied: true, evidence_refs: ["attachment:document-1"] }],
      unresolved_exception_codes: [], operational_effects_are_proposals: true, filing_claimed: false,
    });
    appendIpDocketEventMock.mockResolvedValue({ id: "event-1" });
    previewIpDocketLifecycleMock.mockResolvedValue({
      docket_id: "ip-1", from_status: "active", to_status: "closed",
      expected_lifecycle_version: 0,
      impacts: [{ impact_kind: "incident", record_id: "incident-1", current_state: "open", proposed_outcome: "retain_restricted_history", blocking: true, blocker_code: "open_deadline_incident:incident-1" }],
      blocker_codes: ["open_deadline_incident:incident-1"],
      requires_exception_acknowledgement: true, reopen_without_child_resurrection: false,
    });
    transitionIpDocketLifecycleMock.mockResolvedValue({ status: "closed" });
    proposeIpLegalDeadlineMock.mockResolvedValue({ id: "deadline-proposal-1" });
    confirmIpLegalDeadlineMock.mockResolvedValue({ id: "deadline-confirmed-1" });
  });

  it("renders the authorized empty state and working create form", async () => {
    render(withClient(<IpDocketPage />));

    expect(await screen.findByText("No IP records yet")).toBeInTheDocument();
    const create = screen.getByRole("button", { name: "New trademark" });
    expect(create).toBeVisible();
    fireEvent.click(create);
    expect(screen.getByRole("heading", { name: "New trademark particulars" })).toBeVisible();
    expect(screen.getByLabelText("Word mark")).toBeVisible();
    expect(screen.getByRole("button", { name: "Validate and create" })).toBeDisabled();
  });

  it("fails closed when the role cannot view IP records", () => {
    useCapabilityMock.mockReturnValue(false);
    render(withClient(<IpDocketPage />));
    expect(screen.getByText("IP docket access required")).toBeInTheDocument();
    expect(fetchIpDocketsMock).not.toHaveBeenCalled();
  });

  it("hides operational records and explains each failed readiness gate on narrow mobile", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 360 });
    fetchIpWorkspaceReadinessMock.mockResolvedValue({
      timezone: "Asia/Kolkata",
      workspace_available: false,
      manual_docketing_available: false,
      features: [
        {
          feature_id: "workspace_core",
          available: false,
          reason: "missing_entitlement",
          owner: "product-ip",
          required_capabilities: ["ip:read"],
          missing_capabilities: [],
          entitlement_key: "ip_workspace",
          entitled: false,
          rollout_flag: "ip_workspace_enabled",
          rollout_enabled: false,
          rollout_expires_at: null,
          manual_fallback_feature_id: null,
        },
        {
          feature_id: "registry_sync",
          available: false,
          reason: "rollout_disabled",
          owner: "integrations",
          required_capabilities: ["ip:registry_sync"],
          missing_capabilities: [],
          entitlement_key: "ip_registry_sync",
          entitled: true,
          rollout_flag: "ip_registry_sync_enabled",
          rollout_enabled: false,
          rollout_expires_at: null,
          manual_fallback_feature_id: "manual_docketing",
        },
      ],
    });

    render(withClient(<IpDocketPage />));

    expect(await screen.findByRole("heading", { name: "IP workspace setup" })).toBeVisible();
    expect(screen.getByText("The workspace plan does not include this feature · owner product-ip")).toBeVisible();
    expect(screen.getByText("The safety rollout has not been enabled · owner integrations")).toBeVisible();
    expect(screen.getByText("Manual fallback: manual docketing")).toBeVisible();
    expect(fetchIpDocketsMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "New trademark" })).not.toBeInTheDocument();
  });

  it("keeps manual docketing available while a provider automation is disabled", async () => {
    fetchIpWorkspaceReadinessMock.mockResolvedValue({
      timezone: "Asia/Kolkata",
      workspace_available: true,
      manual_docketing_available: true,
      features: [
        {
          feature_id: "workspace_core",
          available: true,
          reason: "available",
          owner: "product-ip",
          required_capabilities: ["ip:read"],
          missing_capabilities: [],
          entitlement_key: "ip_workspace",
          entitled: true,
          rollout_flag: "ip_workspace_enabled",
          rollout_enabled: true,
          rollout_expires_at: null,
          manual_fallback_feature_id: null,
        },
        {
          feature_id: "registry_sync",
          available: false,
          reason: "rollout_disabled",
          owner: "integrations",
          required_capabilities: ["ip:registry_sync"],
          missing_capabilities: [],
          entitlement_key: "ip_registry_sync",
          entitled: true,
          rollout_flag: "ip_registry_sync_enabled",
          rollout_enabled: false,
          rollout_expires_at: null,
          manual_fallback_feature_id: "manual_docketing",
        },
      ],
    });

    render(withClient(<IpDocketPage />));

    expect(await screen.findByText("No IP records yet")).toBeVisible();
    expect(screen.getByRole("button", { name: "New trademark" })).toBeVisible();
    expect(screen.getByText("registry sync")).toBeVisible();
    expect(screen.getByText("Manual fallback remains manual docketing.")).toBeVisible();
  });

  it("renders the complete setup and isolated-automation actions on narrow mobile", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 360 });
    fetchIpWorkspaceReadinessMock.mockResolvedValue({
      timezone: "Asia/Kolkata",
      workspace_available: false,
      manual_docketing_available: false,
      configuration_status: {
        configuration: {
          id: "config-1",
          version: 1,
          enabled_asset_types_json: ["trademark"],
          jurisdictions_json: ["IN"],
          offices_json: ["IP India"],
          timezone: "Asia/Kolkata",
          holiday_calendar_key: "test-calendar",
          working_day_policy_json: { working_weekdays: [0, 1, 2, 3, 4] },
          document_taxonomy_version: "ip-taxonomy-2026.1",
          event_catalog_version: "ip-events-v1",
          deadline_rule_versions_json: { IN: "2026.1" },
          notification_channels_json: ["in_app"],
          critical_event_policy_json: { escalation_after_minutes: 30 },
          escalation_owner_membership_id: "membership-1",
          provider_keys_json: [],
          provider_terms_version: null,
          provider_terms_accepted_by_membership_id: null,
          provider_terms_accepted_at: null,
          enabled_automations_json: [],
          workspace_enabled: false,
          updated_by_membership_id: "membership-1",
          created_at: "2026-08-07T00:00:00Z",
          updated_at: "2026-08-07T00:00:00Z",
        },
        tests: [],
        ready_for_manual_docketing: true,
        enablement_blockers: [],
      },
      features: [{
        feature_id: "workspace_core",
        available: false,
        reason: "tenant_disabled",
        owner: "product-ip",
        required_capabilities: ["ip:read"],
        missing_capabilities: [],
        entitlement_key: "ip_workspace",
        entitled: true,
        rollout_flag: "ip_workspace_enabled",
        rollout_enabled: true,
        rollout_expires_at: null,
        manual_fallback_feature_id: null,
      }],
    });

    render(withClient(<IpDocketPage />));

    expect(await screen.findByRole("heading", { name: "Configure pilot workspace" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Save configuration" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Map IP roles" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Configure pilot teams" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Configure provider secrets" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Test provider connection" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Test source open" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Test notification (dry run)" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Test sample deadline" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Enable manual workspace" })).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Enable selected tested automations" }),
    ).toBeVisible();
    expect(fetchIpDocketsMock).not.toHaveBeenCalled();
  });

  it("renders every grouped operational action at a narrow viewport", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 360 });
    fetchIpDocketsMock.mockResolvedValue({
      dockets: [{
        id: "ip-1", company_id: "company-1", matter_id: "matter-1", record_type: "trademark",
        title: "CASEOPS", primary_identifier: "TM-1", status: "active", restricted: false,
        is_active: true, lifecycle_version: 0, access_policy_version: 0, lifecycle_effective_at: null,
        lifecycle_reason: null, lifecycle_outcome: null, lifecycle_source: null,
        lifecycle_evidence_ref: null, successor_docket_id: null,
        current_version: 1, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
        current_particulars: { form_key: "TM-A", form_version: "2026.1", readiness_status: "ready", classes_json: [{ class_number: 9, specification: "Software" }] },
        notice_links: [], deadline_incidents: [], title_interests: [], cost_items: [], related_right_obligations: [],
        evidence_candidates: [{ id: "candidate-1", source_type: "communication", source_id: "mail-1", source_fingerprint: "abc", evidence_kind: "correspondence", suggested_link_kind: "instruction", status: "needs_review", accepted_effect: null, duplicate_of_candidate_id: null, metadata_json: { label: "Client instruction" }, reviewed_at: null, created_at: "2026-08-01T00:00:00Z" }],
        deadline_coverages: [{ id: "coverage-1", matter_deadline_id: "deadline-1", responsible_membership_id: "member-1", backup_membership_id: null, coverage_status: "accepted", calendar_projection_status: "queued", reassignment_version: 1, updated_at: "2026-08-01T00:00:00Z" }],
      }],
      count: 1,
    });
    fetchIpDocumentsMock.mockResolvedValue({
      items: [{
        id: "document-1", taxonomy_key: "evidence", taxonomy_label: "Evidence",
        title: "Evidence affidavit", confidentiality: "restricted", is_privileged: true,
        current_version: 1, created_by_membership_id: "membership-1",
        created_at: "2026-08-09T00:00:00Z", updated_at: "2026-08-09T00:00:00Z",
        links: [{ id: "link-1", version_id: null, target_type: "docket", target_id: "ip-1", created_by_membership_id: "membership-1", created_at: "2026-08-09T00:00:00Z" }],
        versions: [{
          id: "version-1", version: 1, original_filename: "original evidence.pdf",
          display_name: "ACME_Trademark_Evidence_2026-08-09_1.pdf",
          content_type: "application/pdf", size_bytes: 200, sha256_hex: "a".repeat(64),
          processing_status: "indexed", extracted_char_count: 12, extraction_error: null,
          ocr_quality_score: 0.4, low_ocr_quality: true, ai_eligible: false, state: "draft",
          uploaded_by_membership_id: "membership-1", locked_by_membership_id: null,
          locked_at: null, created_at: "2026-08-09T00:00:00Z",
        }],
      }],
      total: 1,
    });

    render(withClient(<IpDocketPage />));

    expect(await screen.findByRole("button", { name: "Discover Matter evidence" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Accept and link" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reject" })).toBeVisible();
    // 2026-08-15: a routine transfer is a proposal, so the control offers the
    // work rather than claiming it moved.
    expect(screen.getByRole("button", { name: "Offer covered deadlines" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Add recordal obligation" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reconcile with Matter billing" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Preview prosecution event" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Record prosecution event" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Preview lifecycle impact" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Apply lifecycle transition" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Calculate deadline proposal" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Propose calendar version" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Propose rule and fixture" })).toBeVisible();
    const hearingWorkflow = screen.getByTestId("ip-hearing-workflow");
    expect(within(hearingWorkflow).getByLabelText("Hearing date")).toBeVisible();
    expect(within(hearingWorkflow).getByLabelText("Time precision")).toBeVisible();
    expect(within(hearingWorkflow).getByLabelText("Virtual hearing link")).toBeVisible();
    expect(within(hearingWorkflow).getByLabelText("Reminder offsets (hours)")).toBeVisible();
    const previewReminders = within(hearingWorkflow).getByRole("button", {
      name: "Preview recipients and policy",
    });
    expect(previewReminders).toBeVisible();
    fireEvent.click(previewReminders);
    expect(within(hearingWorkflow).getByTestId("ip-hearing-preview")).toBeVisible();
    expect(
      within(hearingWorkflow).getByRole("button", {
        name: "Confirm hearing and reminders",
      }),
    ).toBeVisible();
    expect(within(hearingWorkflow).getByRole("button", { name: "Edit details" })).toBeVisible();
    const documentWorkspace = screen.getByTestId("ip-document-workspace");
    expect(within(documentWorkspace).getByLabelText("Original file")).toBeVisible();
    expect(within(documentWorkspace).getByRole("button", { name: "Preview controlled name" })).toBeVisible();
    expect(within(documentWorkspace).getByRole("button", { name: "Upload reviewed document" })).toBeVisible();
    expect(within(documentWorkspace).getByRole("button", { name: "Download original" })).toBeVisible();
    expect(within(documentWorkspace).getByLabelText("Supplied document names")).toBeVisible();
    expect(within(documentWorkspace).getByRole("button", { name: "Preview alias import" })).toBeVisible();
    expect(within(documentWorkspace).getByRole("button", { name: "Move to review" })).toBeVisible();
    expect(within(documentWorkspace).getByText(/AI\/search legal conclusions are disabled/i)).toBeVisible();
    expect(within(documentWorkspace).getByLabelText(/New version for ACME_Trademark/i)).toBeVisible();
  });

  it("surfaces deadline exceptions and keeps every confirmation control visible on mobile", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 360 });
    fetchIpDocketsMock.mockResolvedValue({
      dockets: [{
        id: "ip-1", company_id: "company-1", matter_id: "matter-1", record_type: "trademark",
        title: "CASEOPS", primary_identifier: "TM-1", status: "active", restricted: false,
        is_active: true, lifecycle_version: 0, access_policy_version: 0, lifecycle_effective_at: null,
        lifecycle_reason: null, lifecycle_outcome: null, lifecycle_source: null,
        lifecycle_evidence_ref: null, successor_docket_id: null, current_version: 1,
        created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
        current_particulars: { form_key: "TM-A", form_version: "2026.1", readiness_status: "ready", classes_json: [{ class_number: 9, specification: "Software" }] },
        notice_links: [], deadline_incidents: [], title_interests: [], cost_items: [],
        related_right_obligations: [], evidence_candidates: [], deadline_coverages: [],
      }],
      count: 1,
    });
    fetchIpDeadlineWorkspaceMock.mockResolvedValue({
      docket_id: "ip-1",
      rules: [{ id: "rule-1", key: "in-tm-response", version: 1, status: "active", source_reference: "official:rule" }],
      calendars: [{ id: "calendar-1", key: "ip-india", name: "IP India calendar", version: 1, status: "active", source_reference: "official:calendar", timezone: "Asia/Kolkata", weekend_days: [5, 6], holidays: [], exceptional_working_days: [], source_hash: "a".repeat(64) }],
      deadlines: [{
        id: "legal-deadline-1", docket_id: "ip-1", trigger_event_id: null,
        rule_version_id: "rule-1", calendar_version_id: "calendar-1", matter_deadline_id: null,
        supersedes_deadline_id: null, deadline_kind: "legal_deadline", title: "Respond to examination report",
        trigger_kind: "examination_report_received", base_date: "2026-08-14", date_precision: "date",
        certainty: "certain", result_on: "2026-08-18", calculation_inputs: {}, calculation_trace: [],
        explanation: "One business day after the verified source date; confirmation remains required.",
        rule_citation: "Trade Marks Rules", engine_version: "caseops-ip-deadline-v1",
        source_version: "source-v1", is_critical: true, state: "candidate", version: 1,
        confirmed_at: null, override_reason: null, override_evidence_ref: null,
        completed_evidence_ref: null, created_at: "2026-08-09T00:00:00Z",
        updated_at: "2026-08-09T00:00:00Z", responsibilities: [],
      }],
      exceptions: [{ deadline_id: "legal-deadline-1", docket_id: "ip-1", exception_kinds: ["unowned", "unacknowledged"], critical: true, result_on: "2026-08-18", visible: true }],
      automation_state: "explicit_confirmation_only",
    });

    render(withClient(<IpDocketPage />));

    const deadlineWorkspace = await screen.findByTestId("ip-deadline-workspace");
    expect(await within(deadlineWorkspace).findByText("Exception queue")).toBeVisible();
    expect(within(deadlineWorkspace).getByText("unowned Â· unacknowledged")).toBeVisible();
    expect(within(deadlineWorkspace).getByLabelText("Primary membership ID")).toBeVisible();
    expect(within(deadlineWorkspace).getByLabelText("Backup membership ID")).toBeVisible();
    expect(within(deadlineWorkspace).getByLabelText("Evidence reference")).toBeVisible();
    expect(within(deadlineWorkspace).getByRole("button", { name: "Confirm legal deadline" })).toBeVisible();
    expect(within(deadlineWorkspace).getByRole("button", { name: "Calculate deadline proposal" })).toBeVisible();
  });

  it("requires a current preview before recording an event or acknowledged lifecycle impact", async () => {
    fetchIpDocketsMock.mockResolvedValue({
      dockets: [{
        id: "ip-1", company_id: "company-1", matter_id: "matter-1", record_type: "trademark",
        title: "CASEOPS", primary_identifier: "TM-1", status: "active", is_active: true,
        lifecycle_version: 0, access_policy_version: 0, lifecycle_effective_at: null, lifecycle_reason: null,
        lifecycle_outcome: null, lifecycle_source: null, lifecycle_evidence_ref: null,
        successor_docket_id: null, restricted: false, current_version: 1,
        created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
        current_particulars: { form_key: "TM-A", form_version: "2026.1", readiness_status: "ready", classes_json: [{ class_number: 9, specification: "Software" }] },
        notice_links: [], evidence_candidates: [], deadline_coverages: [], deadline_incidents: [],
        title_interests: [], related_right_obligations: [], cost_items: [],
      }],
      count: 1,
    });

    render(withClient(<IpDocketPage />));

    const prosecution = await screen.findByTestId("ip-prosecution-workspace");
    const record = within(prosecution).getByRole("button", { name: "Record prosecution event" });
    expect(record).toBeDisabled();
    fireEvent.change(within(prosecution).getByLabelText("Reason"), { target: { value: "Reviewed official event evidence." } });
    fireEvent.change(within(prosecution).getByLabelText("Evidence reference"), { target: { value: "attachment:evidence-1" } });
    fireEvent.change(within(prosecution).getByLabelText("Document reference"), { target: { value: "attachment:document-1" } });
    fireEvent.click(within(prosecution).getByRole("button", { name: "Preview prosecution event" }));
    expect(await within(prosecution).findByTestId("ip-event-preview")).toHaveTextContent("Preview only");
    expect(record).toBeEnabled();
    fireEvent.click(record);
    await waitFor(() => expect(appendIpDocketEventMock).toHaveBeenCalledTimes(1));

    const lifecycle = screen.getByTestId("ip-lifecycle-workflow");
    const apply = within(lifecycle).getByRole("button", { name: "Apply lifecycle transition" });
    fireEvent.change(within(lifecycle).getByLabelText("Reason"), { target: { value: "Client instructed closure." } });
    fireEvent.change(within(lifecycle).getByLabelText("Outcome"), { target: { value: "closed" } });
    fireEvent.change(within(lifecycle).getByLabelText("Evidence reference"), { target: { value: "attachment:closure-1" } });
    fireEvent.click(within(lifecycle).getByRole("button", { name: "Preview lifecycle impact" }));
    expect(await within(lifecycle).findByTestId("ip-lifecycle-preview")).toHaveTextContent("acknowledgement required");
    expect(apply).toBeDisabled();
    fireEvent.click(within(lifecycle).getByRole("checkbox", { name: /reviewed and acknowledge/i }));
    expect(apply).toBeEnabled();
    fireEvent.click(apply);
    await waitFor(() => expect(transitionIpDocketLifecycleMock).toHaveBeenCalledTimes(1));
  });

  const AWAITING_DOCKET = {
    id: "ip-1", company_id: "company-1", matter_id: "matter-1", record_type: "trademark",
    title: "CASEOPS", primary_identifier: "TM-1", status: "active", restricted: false,
    is_active: true, lifecycle_version: 0, access_policy_version: 0, lifecycle_effective_at: null,
    lifecycle_reason: null, lifecycle_outcome: null, lifecycle_source: null,
    lifecycle_evidence_ref: null, successor_docket_id: null,
    current_version: 1, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
    current_particulars: { form_key: "TM-A", form_version: "2026.1", readiness_status: "ready", classes_json: [] },
    notice_links: [], deadline_incidents: [], title_interests: [], cost_items: [],
    related_right_obligations: [], evidence_candidates: [], deadline_coverages: [],
  };

  const PROPOSED_TRANSFER = {
    coverage_id: "coverage-9", docket_id: "ip-1", docket_title: "ACME WORDMARK",
    docket_identifier: "TM 4412330", deadline_title: "Opposition reply",
    due_on: "2026-10-12", days_until_due: 58, critical: true,
    transfer_kind: "proposed" as const, responsible_membership_id: "member-2",
    responsible_label: "Priya Raghavan", escalation_membership_id: null,
    escalation_label: null, reason: "Covering the Delhi hearing block.",
    reassignment_version: 3,
  };

  it("does not render the decision band when nothing is awaiting the member", async () => {
    fetchIpDocketsMock.mockResolvedValue({ dockets: [AWAITING_DOCKET], count: 1 });

    render(withClient(<IpDocketPage />));

    expect(await screen.findByText("Portfolio")).toBeVisible();
    // An always-present empty band trains people to ignore the space.
    expect(screen.queryByTestId("ip-coverage-decisions")).toBeNull();
  });

  it("lets the named replacement accept a proposed transfer without writing prose", async () => {
    fetchIpDocketsMock.mockResolvedValue({ dockets: [AWAITING_DOCKET], count: 1 });
    fetchIpCoverageTransfersAwaitingMeMock.mockResolvedValue({ transfers: [PROPOSED_TRANSFER] });

    render(withClient(<IpDocketPage />));

    const band = await screen.findByTestId("ip-coverage-decisions");
    // Enough to answer "can I hold this date?" without opening the record.
    expect(within(band).getByText("ACME WORDMARK")).toBeVisible();
    expect(within(band).getByText("TM 4412330")).toBeVisible();
    expect(within(band).getByText(/Opposition reply/)).toHaveTextContent("in 58 days");
    expect(within(band).getByText("Critical")).toBeVisible();
    // The consequence of not acting is stated, not implied.
    expect(within(band).getByText(/Priya Raghavan remains responsible until you accept/)).toBeVisible();
    expect(within(band).getByText(/Covering the Delhi hearing block/)).toBeVisible();

    fireEvent.click(within(band).getByRole("button", { name: "Accept responsibility" }));
    await waitFor(() => expect(decideIpCoverageTransferMock).toHaveBeenCalledTimes(1));
    expect(decideIpCoverageTransferMock).toHaveBeenCalledWith("coverage-9", {
      decision: "accepted",
      reason: undefined,
    });
  });

  it("requires a written reason before a decline is sent", async () => {
    fetchIpDocketsMock.mockResolvedValue({ dockets: [AWAITING_DOCKET], count: 1 });
    fetchIpCoverageTransfersAwaitingMeMock.mockResolvedValue({ transfers: [PROPOSED_TRANSFER] });

    render(withClient(<IpDocketPage />));

    const band = await screen.findByTestId("ip-coverage-decisions");
    fireEvent.click(within(band).getByRole("button", { name: "Decline" }));

    const confirm = within(band).getByRole("button", { name: "Confirm decline" });
    expect(confirm).toBeDisabled();
    expect(decideIpCoverageTransferMock).not.toHaveBeenCalled();

    fireEvent.change(within(band).getByLabelText("Why are you declining?"), {
      target: { value: "I am in trial that fortnight." },
    });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);

    await waitFor(() => expect(decideIpCoverageTransferMock).toHaveBeenCalledTimes(1));
    expect(decideIpCoverageTransferMock).toHaveBeenCalledWith("coverage-9", {
      decision: "rejected",
      reason: "I am in trial that fortnight.",
    });
  });

  it("tells a member holding an immediate transfer where declining sends it", async () => {
    fetchIpDocketsMock.mockResolvedValue({ dockets: [AWAITING_DOCKET], count: 1 });
    fetchIpCoverageTransfersAwaitingMeMock.mockResolvedValue({
      transfers: [{
        ...PROPOSED_TRANSFER,
        transfer_kind: "immediate" as const,
        responsible_membership_id: "membership-1",
        responsible_label: "You",
        escalation_membership_id: "member-3",
        escalation_label: "Anand Rao",
      }],
    });

    render(withClient(<IpDocketPage />));

    const band = await screen.findByTestId("ip-coverage-decisions");
    // Declining an immediate transfer escalates; saying "remains responsible
    // until you accept" here would be false.
    expect(
      within(band).getByText(/You already hold this deadline\. Declining moves it to Anand Rao\./),
    ).toBeVisible();
  });
});
