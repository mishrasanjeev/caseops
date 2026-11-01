import { defaultScheduler, notifyManager, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { IpWorkspaceConfiguration, IpWorkspaceReadiness } from "@/lib/api/endpoints";
import { providerAdapterContractRecord } from "@/lib/api/schemas";

const routerReplaceMock = vi.hoisted(() => vi.fn());

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
  useRouter: () => ({ replace: routerReplaceMock }),
  usePathname: () => "/app/ip",
}));

vi.mock("@/components/app/InAppNotificationCenter", () => ({
  InAppNotificationCenter: () => <section aria-label="Your in-app alerts" />,
}));

const {
  addIpCostItemMock,
  fetchMatterWorkspaceMock,
  fetchIpNiceClassesMock,
  listMattersMock,
  enableIpWorkspaceMock,
  fetchIpDeadlineDependenciesMock,
  fetchIpDeadlineWorkspaceMock,
  fetchIpCoreRecordsMock,
  fetchIpDocketMock,
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
  updateIpSharedHearingMock,
  createManualTrademarkApplicationMock,
  correctIpIdentifierMock,
  correctIpCostItemMock,
  fetchIpAccessPanelMock,
  listCompanyUsersMock,
  listTeamsMock,
  previewIpAccessChangeMock,
  applyIpAccessChangeMock,
  fetchIpCoverageTransfersAwaitingMeMock,
  decideIpCoverageTransferMock,
  createIpDeadlineIncidentMock,
  recordIpDeadlineIncidentActionMock,
  recordIpDeadlineIncidentImpactMock,
  decideIpDeadlineIncidentNotificationMock,
  resolveIpDeadlineIncidentMock,
  releaseIpIncidentKillSwitchMock,
  previewIpIdentifierDuplicatesMock,
  resolveIpIdentifierDuplicateMock,
  updateTrademarkApplicationPhaseMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  addIpCostItemMock: vi.fn(),
  fetchMatterWorkspaceMock: vi.fn(),
  fetchIpNiceClassesMock: vi.fn(),
  listMattersMock: vi.fn(),
  enableIpWorkspaceMock: vi.fn(),
  fetchIpDeadlineDependenciesMock: vi.fn(),
  fetchIpDeadlineWorkspaceMock: vi.fn(),
  fetchIpCoreRecordsMock: vi.fn(),
  fetchIpDocketMock: vi.fn(),
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
  updateIpSharedHearingMock: vi.fn(),
  createManualTrademarkApplicationMock: vi.fn(),
  correctIpIdentifierMock: vi.fn(),
  correctIpCostItemMock: vi.fn(),
  fetchIpAccessPanelMock: vi.fn(),
  listCompanyUsersMock: vi.fn(),
  listTeamsMock: vi.fn(),
  previewIpAccessChangeMock: vi.fn(),
  applyIpAccessChangeMock: vi.fn(),
  fetchIpCoverageTransfersAwaitingMeMock: vi.fn(),
  decideIpCoverageTransferMock: vi.fn(),
  createIpDeadlineIncidentMock: vi.fn(),
  recordIpDeadlineIncidentActionMock: vi.fn(),
  recordIpDeadlineIncidentImpactMock: vi.fn(),
  decideIpDeadlineIncidentNotificationMock: vi.fn(),
  resolveIpDeadlineIncidentMock: vi.fn(),
  releaseIpIncidentKillSwitchMock: vi.fn(),
  previewIpIdentifierDuplicatesMock: vi.fn(),
  resolveIpIdentifierDuplicateMock: vi.fn(),
  updateTrademarkApplicationPhaseMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  TRADEMARK_MARK_KINDS: ["word", "device", "composite", "label", "colour", "shape", "sound", "other"],
  fetchMatterWorkspace: fetchMatterWorkspaceMock,
  fetchIpNiceClasses: fetchIpNiceClassesMock,
  listMatters: listMattersMock,
  fetchIpDocket: fetchIpDocketMock,
  fetchIpDockets: fetchIpDocketsMock,
  fetchIpDocuments: fetchIpDocumentsMock,
  fetchIpDocumentTaxonomy: fetchIpDocumentTaxonomyMock,
  seedIpDocumentTaxonomy: vi.fn(),
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
  fetchIpDeadlineDependencies: fetchIpDeadlineDependenciesMock,
  fetchIpCoreRecords: fetchIpCoreRecordsMock,
  createIpOppositionProceeding: vi.fn(),
  fetchIpOppositionWorkspace: vi.fn(),
  fetchIpOppositionSharedWorkflow: vi.fn(),
  recordIpOppositionSharedAction: vi.fn(),
  saveIpOppositionWorkspace: vi.fn(),
  transitionIpOppositionStage: vi.fn(),
  createIpPostRegistrationProceeding: vi.fn(),
  fetchIpPostRegistrationWorkspace: vi.fn(),
  recordIpPostRegistrationAction: vi.fn(),
  saveIpPostRegistrationWorkspace: vi.fn(),
  fetchIpProsecutionWorkspace: fetchIpProsecutionWorkspaceMock,
  fetchIpSharedHearings: fetchIpSharedHearingsMock,
  fetchIpWorkspaceReadiness: fetchIpWorkspaceReadinessMock,
  enableIpWorkspace: enableIpWorkspaceMock,
  runIpWorkspaceTest: runIpWorkspaceTestMock,
  saveIpWorkspaceConfiguration: saveIpWorkspaceConfigurationMock,
  createManualTrademarkApplication: createManualTrademarkApplicationMock,
  correctIpIdentifier: correctIpIdentifierMock,
  createIpDeadlineIncident: createIpDeadlineIncidentMock,
  recordIpDeadlineIncidentAction: recordIpDeadlineIncidentActionMock,
  recordIpDeadlineIncidentImpact: recordIpDeadlineIncidentImpactMock,
  decideIpDeadlineIncidentNotification: decideIpDeadlineIncidentNotificationMock,
  resolveIpDeadlineIncident: resolveIpDeadlineIncidentMock,
  releaseIpIncidentKillSwitch: releaseIpIncidentKillSwitchMock,
  createIpSharedHearing: createIpSharedHearingMock,
  updateIpSharedHearing: updateIpSharedHearingMock,
  listCalendarConnections: listCalendarConnectionsMock,
  syncHearingToOutlook: vi.fn(),
  syncHearingToGoogleCalendar: vi.fn(),
  addIpTitleInterest: vi.fn(),
  addIpCostItem: addIpCostItemMock,
  correctIpCostItem: correctIpCostItemMock,
  discoverIpEvidence: vi.fn(),
  reviewIpEvidenceCandidate: vi.fn(),
  bulkReassignIpCoverage: vi.fn(),
  addIpRelatedRightObligation: vi.fn(),
  completeIpRelatedRightObligation: vi.fn(),
  reconcileIpCosts: vi.fn(),
  previewIpDocketEvent: previewIpDocketEventMock,
  appendIpDocketEvent: appendIpDocketEventMock,
  previewIpDocketLifecycle: previewIpDocketLifecycleMock,
  previewIpIdentifierDuplicates: previewIpIdentifierDuplicatesMock,
  resolveIpIdentifierDuplicate: resolveIpIdentifierDuplicateMock,
  transitionIpDocketLifecycle: transitionIpDocketLifecycleMock,
  proposeIpLegalDeadline: proposeIpLegalDeadlineMock,
  confirmIpLegalDeadline: confirmIpLegalDeadlineMock,
  fetchIpDeadlineImpact: vi.fn(),
  overrideIpLegalDeadline: vi.fn(),
  recalculateIpLegalDeadline: vi.fn(),
  completeIpLegalDeadline: vi.fn(),
  proposeIpWorkingCalendar: vi.fn(),
  fetchIpRulePolicies: vi.fn().mockResolvedValue([]),
  selectIpRulePolicy: vi.fn(),
  activateIpWorkingCalendar: vi.fn(),
  proposeIpDeadlineRule: vi.fn(),
  fetchIpDeadlineRuleImpact: vi.fn(),
  activateIpDeadlineRule: vi.fn(),
  transitionIpDeadlineRule: vi.fn(),
  fetchIpAccessPanel: fetchIpAccessPanelMock,
  listCompanyUsers: listCompanyUsersMock,
  listTeams: listTeamsMock,
  previewIpAccessChange: previewIpAccessChangeMock,
  applyIpAccessChange: applyIpAccessChangeMock,
  updateTrademarkApplicationPhase: updateTrademarkApplicationPhaseMock,
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
import { availableGovernance } from "@/test/ip-governance-fixtures";

const NICE_HEADINGS: Record<number, string> = {
  9: "Scientific, research, navigation, surveying apparatus; computer software.",
  35: "Advertising; business management, organization and administration; office functions.",
};

function niceCatalogue() {
  return {
    edition: "NCL 13-2026",
    in_force_from: "2026-01-01",
    source_url: "https://nclpub.wipo.int/enfr/?version=20260101",
    source_data_url: "https://www.wipo.int/classifications/data/nice/20260101.zip",
    retrieved_on: "2026-10-31",
    headings_sha256: "a".repeat(64),
    attribution: "Nice Classification, 13th edition, version 2026 (NCL 13-2026). Copyright World Intellectual Property Organization (WIPO).",
    classes: Array.from({ length: 45 }, (_, index) => {
      const number = index + 1;
      return {
        number,
        kind: number <= 34 ? "goods" : "services",
        heading: NICE_HEADINGS[number] ?? `Class ${number} heading.`,
        note: null,
      };
    }),
  };
}

// Production readiness for test-legal on 2026-10-31 (triage readiness.json):
// manual docketing available, eight automations missing from the plan.
function productionShapedReadiness() {
  const feature = (featureId: string, available: boolean, blocked: string[]) => ({
    feature_id: featureId,
    available,
    reason: blocked[0] ?? "available",
    blocked_reasons: blocked,
    owner: "product-ip",
    required_capabilities: [],
    missing_capabilities: blocked.includes("missing_capability") ? ["ip:rules_propose"] : [],
    entitlement_key: `ip_${featureId}`,
    entitled: !blocked.includes("missing_entitlement"),
    rollout_flag: `ip_${featureId}_enabled`,
    rollout_enabled: !blocked.includes("rollout_disabled"),
    rollout_expires_at: null,
    manual_fallback_feature_id: available ? null : "manual_docketing",
  });
  return {
    timezone: "Asia/Kolkata",
    workspace_available: true,
    manual_docketing_available: true,
    features: [
      feature("workspace_core", true, []),
      feature("manual_docketing", true, []),
      feature("taxonomy_admin", true, []),
      feature("registry_sync", false, ["missing_entitlement", "rollout_disabled"]),
      feature("deadline_automation", false, ["missing_entitlement", "tenant_disabled"]),
      feature("notification_automation", false, ["missing_entitlement"]),
      feature("filing_prepare", false, ["missing_entitlement"]),
      feature("filing_confirm", false, ["missing_entitlement"]),
      feature("watch_operations", false, ["missing_entitlement"]),
      feature("cost_operations", false, ["missing_entitlement"]),
      feature("rule_governance", false, ["missing_capability", "missing_entitlement"]),
    ],
  };
}

async function chooseNiceClass(user: ReturnType<typeof userEvent.setup>, name: string, query: string, option: RegExp) {
  const input = screen.getByRole("combobox", { name });
  await waitFor(() => expect(input).toBeEnabled());
  await user.click(input);
  await user.type(input, query);
  await user.click(within(screen.getByRole("listbox")).getByRole("option", { name: option }));
}

async function fillRequiredTrademarkFields(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Docket title"), "Aster filing");
  await user.type(screen.getByLabelText("Word mark"), "ASTER");
  await user.type(screen.getByLabelText("Applicant"), "Aster Applicant LLP");
  await user.type(screen.getByLabelText("Representation evidence reference"), "attachment:aster");
}

function withClient(children: ReactNode, companyUsers?: unknown) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  if (companyUsers) {
    client.setQueryDefaults(["company-users"], { staleTime: Infinity });
    client.setQueryData(["company-users"], companyUsers);
  }
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function activeDocket() {
  return {
    id: "ip-1", company_id: "company-1", matter_id: "matter-1", record_type: "trademark",
    title: "CASEOPS", primary_identifier: "TM-1", status: "active", is_active: true,
    lifecycle_version: 0, access_policy_version: 0, lifecycle_effective_at: null,
    lifecycle_reason: null, lifecycle_outcome: null, lifecycle_source: null,
    lifecycle_evidence_ref: null, successor_docket_id: null, restricted: false,
    current_version: 1, created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    current_particulars: {
      form_key: "TM-A", form_version: "2026.1", readiness_status: "ready",
      classes_json: [{ class_number: 9, specification: "Software" }],
    },
    notice_links: [], evidence_candidates: [], deadline_coverages: [],
    deadline_incidents: [], title_interests: [], related_right_obligations: [], cost_items: [],
  };
}

function prosecutionEvent(overrides: Record<string, unknown> = {}) {
  return {
    id: "event-1", company_id: "company-1", docket_id: "ip-1", sequence: 1,
    application_id: "application-1", proceeding_id: null, event_kind: "formalities",
    source: "manual", source_reference: null, effective_at: "2026-08-10T09:00:00Z",
    entered_at: "2026-08-10T09:05:00Z", responsible_membership_id: "membership-1",
    entered_by_membership_id: "membership-1", reason: "Formalities reviewed.",
    evidence_refs_json: ["attachment:evidence-1"], document_refs_json: [],
    resulting_stage: "formalities", resulting_deadline_refs_json: [], before_phase: "draft",
    after_phase: "formalities", candidate_status: "confirmed", supersedes_event_id: null,
    correction_reason: null, reconciles_event_id: null, reconciliation_decision: null,
    payload_json: {}, created_at: "2026-08-10T09:05:00Z", ...overrides,
  };
}

function renewalConfiguration(overrides: Partial<IpWorkspaceConfiguration> = {}): IpWorkspaceConfiguration {
  return {
    id: "config-1", version: 4, enabled_asset_types_json: ["trademark"],
    jurisdictions_json: ["IN"], offices_json: ["IP India"], timezone: "Europe/London",
    holiday_calendar_key: "reviewed-calendar", working_day_policy_json: { working_weekdays: [0, 1, 2, 3, 4] },
    document_taxonomy_version: "ip-taxonomy-2026.1", event_catalog_version: "ip-events-v1",
    deadline_rule_versions_json: { IN: "2026.1" }, notification_channels_json: ["in_app"],
    critical_event_policy_json: { escalation_after_minutes: 30 },
    renewal_reminder_cadence_days: 7, renewal_reminder_delivery_time: "14:45",
    escalation_owner_membership_id: "membership-1", provider_keys_json: ["ipindia-registry"],
    provider_terms_version: "2026.1", provider_terms_accepted_by_membership_id: "membership-1",
    provider_terms_accepted_at: "2026-08-07T00:00:00Z", enabled_automations_json: [], workspace_enabled: false,
    updated_by_membership_id: "membership-1", created_at: "2026-08-07T00:00:00Z", updated_at: "2026-08-07T00:00:00Z",
    ...overrides,
  };
}

function setupReadiness(configuration: IpWorkspaceConfiguration | null = null): IpWorkspaceReadiness {
  return {
    timezone: configuration?.timezone ?? "Asia/Kolkata", workspace_available: false,
    manual_docketing_available: false, features: [],
    configuration_status: { configuration, tests: [], ready_for_manual_docketing: true,
      enablement_blockers: [], provider_adapters: [providerAdapterContractRecord.parse({
        provider: "ipindia-registry", display_name: "IP India registry", domain: "ip_office_registry",
        adapter_status: "blocked_pending_provider_contract", commercial_terms_status: "not_approved",
        attribution_label: "Synthetic registry contract, not activated", operations_path: "/api/admin/provider-operations/jobs",
      })] },
  };
}

function unknownTimeHearing() {
  const reminder = (
    id: string,
    generation: number,
    status: "queued" | "cancelled",
    replacementGeneration: number | null,
  ) => ({
    id,
    recipient_membership_id: "membership-1",
    channel: "in_app" as const,
    scheduled_for: generation === 1
      ? "2026-12-13T12:30:00Z"
      : "2026-12-14T09:00:00Z",
    schedule_generation: generation,
    is_superseded: replacementGeneration !== null,
    replacement_generation: replacementGeneration,
    status,
    provider: null,
    provider_message_id: null,
    last_error: null,
    attempts: 0,
    sent_at: null,
    delivered_at: null,
    created_at: "2026-08-22T00:00:00Z",
  });
  return {
    id: "hearing-1",
    company_id: "company-1",
    target_type: "ip_docket" as const,
    target_id: "ip-1",
    ip_docket_id: "ip-1",
    hearing_on: "2026-12-15",
    time_status: "time_not_published" as const,
    hearing_time: null,
    session_label: null,
    timezone: "Asia/Kolkata",
    hearing_mode: "unknown" as const,
    location_text: null,
    meeting_url: null,
    attendee_membership_ids: ["membership-1"],
    source: "registry_notice",
    source_ref_type: "document",
    source_ref_id: "document-1",
    responsible_membership_id: "membership-1",
    forum_name: "Trade Marks Registry",
    judge_name: null,
    purpose: "Opposition hearing",
    status: "scheduled" as const,
    outcome_note: null,
    reminder_policy: { offsets_hours: [48], channels: ["in_app" as const] },
    time_confirmation_required: true,
    current_schedule_generation: 2,
    reminders: [
      reminder("reminder-1", 1, "cancelled", 2),
      reminder("reminder-2", 2, "queued", null),
    ],
    created_at: "2026-08-22T00:00:00Z",
  };
}

describe("IpDocketPage", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/app/ip");
    fetchIpDocketMock.mockReset();
    fetchIpDocketsMock.mockReset();
    fetchIpDocumentsMock.mockReset();
    fetchIpDocumentTaxonomyMock.mockReset();
    fetchIpDeadlineWorkspaceMock.mockReset();
    fetchIpDeadlineDependenciesMock.mockReset();
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
    updateIpSharedHearingMock.mockReset();
    createManualTrademarkApplicationMock.mockReset();
    correctIpIdentifierMock.mockReset();
    correctIpCostItemMock.mockReset();
    fetchIpAccessPanelMock.mockReset();
    listCompanyUsersMock.mockReset();
    listTeamsMock.mockReset();
    previewIpAccessChangeMock.mockReset();
    applyIpAccessChangeMock.mockReset();
    fetchIpCoverageTransfersAwaitingMeMock.mockReset();
    decideIpCoverageTransferMock.mockReset();
    createIpDeadlineIncidentMock.mockReset();
    recordIpDeadlineIncidentActionMock.mockReset();
    recordIpDeadlineIncidentImpactMock.mockReset();
    decideIpDeadlineIncidentNotificationMock.mockReset();
    resolveIpDeadlineIncidentMock.mockReset();
    releaseIpIncidentKillSwitchMock.mockReset();
    previewIpIdentifierDuplicatesMock.mockReset();
    resolveIpIdentifierDuplicateMock.mockReset();
    updateTrademarkApplicationPhaseMock.mockReset();
    fetchIpCoverageTransfersAwaitingMeMock.mockResolvedValue({ transfers: [] });
    decideIpCoverageTransferMock.mockResolvedValue({});
    correctIpCostItemMock.mockResolvedValue({});
    enableIpWorkspaceMock.mockReset();
    runIpWorkspaceTestMock.mockReset();
    saveIpWorkspaceConfigurationMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    routerReplaceMock.mockReset();
    fetchIpNiceClassesMock.mockReset();
    fetchIpNiceClassesMock.mockResolvedValue(niceCatalogue());
    listMattersMock.mockReset();
    listMattersMock.mockResolvedValue({ matters: [], next_cursor: null });
    addIpCostItemMock.mockReset();
    addIpCostItemMock.mockResolvedValue({});
    fetchMatterWorkspaceMock.mockReset();
    fetchMatterWorkspaceMock.mockResolvedValue({ invoices: [], time_entries: [] });
    fetchIpWorkspaceReadinessMock.mockResolvedValue({
      timezone: "Asia/Calcutta",
      workspace_available: true,
      manual_docketing_available: true,
      features: [],
    });
    fetchIpDocketsMock.mockResolvedValue({ dockets: [], count: 0 });
    fetchIpDocketMock.mockResolvedValue(activeDocket());
    fetchIpDocumentsMock.mockResolvedValue({ items: [], total: 0 });
    fetchIpDocumentTaxonomyMock.mockResolvedValue({
      taxonomy_version: "ip-document-taxonomy-v1",
      entries: [{ key: "evidence", label: "Evidence", is_active: true, version: 1 }],
    });
    fetchIpDeadlineWorkspaceMock.mockResolvedValue({
      docket_id: "ip-1",
      eligible_rule_version_ids: ["rule-1"],
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
      deadlines: [], exceptions: [], automation_state: "explicit_confirmation_only", governance: availableGovernance(),
    });
    fetchIpDeadlineDependenciesMock.mockResolvedValue({
      deadline_id: "legal-deadline-1", docket_id: "ip-1", state: "candidate",
      result_on: "2026-08-18", certainty: "certain", is_critical: true,
      engine_version: "caseops-ip-deadline-v1", source_version: "source-v1",
      rule_citation: "Trade Marks Rules",
      explanation: "One business day after the verified source date.",
      nodes: [
        { kind: "trigger_event", reference_id: null, label: "Manual base date", detail: "2026-08-14", available: true },
        { kind: "rule_version", reference_id: "rule-1", label: "in-tm-response v1", detail: "active", available: true },
        { kind: "calendar_version", reference_id: "calendar-1", label: "calendar v1", detail: "1 holiday", available: true },
      ],
      calculation_trace: [], unavailable_inputs: [], superseded_chain: [],
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
    listCompanyUsersMock.mockResolvedValue({
      company_id: "company-1",
      company_slug: "firm",
      users: [
        {
          membership_id: "member-1",
          full_name: "Priya Raghavan",
          email: "priya@example.com",
          role: "partner",
          membership_active: true,
          user_id: "user-1",
          user_active: true,
          created_at: "2026-08-16T00:00:00Z",
        },
        {
          membership_id: "member-2",
          full_name: "Anand Rao",
          email: "anand@example.com",
          role: "member",
          membership_active: true,
          user_id: "user-2",
          user_active: true,
          created_at: "2026-08-16T00:00:00Z",
        },
      ],
    });
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
    updateTrademarkApplicationPhaseMock.mockResolvedValue({});
  });

  it("renders the authorized empty state and working create form", async () => {
    expect(vi.isFakeTimers()).toBe(false);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const notifications: Array<() => void> = [];
    notifyManager.setScheduler((callback) => {
      expect(notifications.length).toBeLessThan(8);
      notifications.push(callback);
    });
    let view: Pick<ReturnType<typeof render>, "unmount"> | undefined;
    try {
      view = render(<QueryClientProvider client={client}><IpDocketPage /></QueryClientProvider>);
      expect(fetchIpWorkspaceReadinessMock).toHaveBeenCalledTimes(1);
      await act(async () => { await fetchIpWorkspaceReadinessMock.mock.results[0].value; });
      expect(client.getQueryState(["ip", "readiness"])?.status).toBe("success");
      expect(screen.getByText("Checking IP workspace readiness…")).toBeVisible();
      expect(fetchIpDocketsMock).not.toHaveBeenCalled();
      expect(notifications).toHaveLength(1);
      await act(async () => { notifications.splice(0).forEach((callback) => callback()); });
      expect(fetchIpDocketsMock).toHaveBeenCalledTimes(1);
      await act(async () => { await fetchIpDocketsMock.mock.results[0].value; });
      expect(client.getQueryState(["ip", "dockets"])?.status).toBe("success");
      expect(screen.getByText("Loading IP docket…")).toBeVisible();
      expect(notifications).toHaveLength(1);
      console.info("IP_EMPTY_QUERY_DELIVERY_CONTROL", {
        fakeTimers: vi.isFakeTimers(), readinessStatus: client.getQueryState(["ip", "readiness"])?.status,
        docketStatus: client.getQueryState(["ip", "dockets"])?.status,
        queuedNotifications: notifications.length, readinessCalls: fetchIpWorkspaceReadinessMock.mock.calls.length,
        docketCalls: fetchIpDocketsMock.mock.calls.length,
      });
      // Settled fixtures are not delivered observer updates; flush that boundary in act.
      await act(async () => { notifications.splice(0).forEach((callback) => callback()); });
      expect(notifications).toHaveLength(0);

      expect(await screen.findByText("No IP records yet")).toBeInTheDocument();
      const create = screen.getByRole("button", { name: "New trademark" });
      expect(create).toBeVisible();
      fireEvent.click(create);
      expect(screen.getByRole("heading", { name: "New trademark application" })).toBeVisible();
      expect(screen.getByLabelText("Word mark")).toBeVisible();
      expect(screen.getByRole("button", { name: "Create application" })).toBeDisabled();
    } finally {
      try { view?.unmount(); } finally {
        try { client.clear(); } finally {
          notifications.length = 0;
          notifyManager.setScheduler(defaultScheduler);
        }
      }
    }
    expect(client.getQueryCache().getAll()).toHaveLength(0);
  });

  it("keeps a deep-linked docket focused instead of starting the full portfolio request", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=ip-1&view=access");

    render(withClient(<IpDocketPage />));

    expect(await screen.findByTestId("ip-access-workspace")).toBeVisible();
    expect(fetchIpDocketMock).toHaveBeenCalledWith("ip-1");
    expect(fetchIpDocketsMock).not.toHaveBeenCalled();
    expect(screen.getByText("Showing the record selected by this link.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open full portfolio" })).toHaveAttribute(
      "href",
      "/app/ip/portfolio",
    );
  });

  it("prioritizes a deep-linked docket before portfolio and document requests", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=ip-1&view=access");
    fetchIpDocketMock.mockReturnValue(new Promise(() => {}));

    render(withClient(<IpDocketPage />));

    const workspace = await screen.findByTestId("ip-access-workspace-loading");
    expect(
      within(workspace).getByRole("heading", {
        name: "Internal access and ethical walls",
      }),
    ).toBeVisible();
    expect(workspace).toHaveTextContent(/Linked Matter permissions are never copied/i);
    expect(workspace).toHaveTextContent(/Loading the selected docket/i);
    expect(fetchIpDocketMock).toHaveBeenCalledWith("ip-1");
    expect(fetchIpDocketsMock).not.toHaveBeenCalled();
    expect(fetchIpDocumentsMock).not.toHaveBeenCalled();
    expect(fetchIpDocumentTaxonomyMock).not.toHaveBeenCalled();
  });

  it("fails a missing deep-linked docket explicitly without falling back to a portfolio scan", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=missing-ip-record&view=proceedings");
    fetchIpDocketMock.mockRejectedValue(new Error("Linked IP docket not found."));

    render(withClient(<IpDocketPage />));

    expect(await screen.findByText("Could not load the linked IP docket")).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry linked docket" })).toBeVisible();
    expect(fetchIpDocketsMock).not.toHaveBeenCalled();
  });

  it("BUG-012 links a national trademark docket to its registry reconciliation", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=ip-1");

    render(withClient(<IpDocketPage />));

    expect(await screen.findByRole("link", { name: "Reconcile with registry" })).toHaveAttribute(
      "href",
      "/app/ip/registry?docket=ip-1",
    );
  });

  it("opens ordinary docket links on overview and honors an explicit schedule view", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=ip-1");

    const { unmount } = render(withClient(<IpDocketPage />));

    expect(await screen.findByRole("tab", { name: "Overview" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByTestId("ip-access-workspace")).not.toBeInTheDocument();
    unmount();

    window.history.replaceState(null, "", "/app/ip?docket=ip-1&view=schedule");
    render(withClient(<IpDocketPage />));

    expect(
      await screen.findByRole("tab", { name: "Hearings and deadlines" }),
    ).toHaveAttribute("aria-selected", "true");
    expect(
      await screen.findByRole("heading", {
        name: "Hearings, reminders, and calendar copies",
      }),
    ).toBeVisible();
  });

  it("BUG-015 opens the Documents tab from a documents deep link", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=ip-1&tab=documents");
    render(withClient(<IpDocketPage />));

    expect(await screen.findByRole("tab", { name: "Documents" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Docket" })).toHaveAttribute("aria-selected", "false");
  });

  it("B2-BUG-001/002 explains absent active calendar and rule prerequisites without enabling calculation", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=ip-1&view=schedule");
    fetchIpDeadlineWorkspaceMock.mockResolvedValue({
      docket_id: "ip-1", rules: [], calendars: [], deadlines: [], exceptions: [],
      eligible_rule_version_ids: [],
      automation_state: "explicit_confirmation_only", governance: availableGovernance(),
    });
    render(withClient(<IpDocketPage />));

    const workspace = await screen.findByTestId("ip-deadline-workspace");
    expect(await within(workspace).findByText("No active working calendar")).toBeInTheDocument();
    expect(within(workspace).getByText("No eligible active deadline rule")).toBeInTheDocument();
    expect(workspace.querySelectorAll("label label")).toHaveLength(0);
    expect(within(workspace).getByRole("combobox", { name: "Active working calendar" })).toBeDisabled();
    expect(within(workspace).getByRole("combobox", { name: "Active rule version" })).toBeDisabled();
    expect(within(workspace).getByLabelText("Active working calendar")).toBeDisabled();
    expect(within(workspace).getByLabelText("Active rule version")).toBeDisabled();
    expect(within(workspace).getByRole("button", { name: "Calculate deadline proposal" })).toBeDisabled();
    expect(within(workspace).getByText(/independent approval/i)).toBeVisible();
    expect(proposeIpLegalDeadlineMock).not.toHaveBeenCalled();
  });

  it("B2-BUG-001/002 distinguishes pending workspace data from an empty eligible inventory", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=ip-1&view=schedule");
    fetchIpDeadlineWorkspaceMock.mockImplementation(() => new Promise(() => {}));
    render(withClient(<IpDocketPage />));

    const workspace = await screen.findByTestId("ip-deadline-workspace");
    expect(within(workspace).getByLabelText("Active working calendar")).toBeDisabled();
    expect(within(workspace).getByLabelText("Active rule version")).toBeDisabled();
    expect(within(workspace).getByText("Loading working calendars…")).toBeInTheDocument();
    expect(within(workspace).queryByText("No active working calendar")).not.toBeInTheDocument();
    expect(proposeIpLegalDeadlineMock).not.toHaveBeenCalled();
  });

  it("B2-BUG-001/002 retries a workspace failure without presenting it as missing legal data", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=ip-1&view=schedule");
    fetchIpDeadlineWorkspaceMock.mockRejectedValue(new Error("Bounded workspace read failed"));
    render(withClient(<IpDocketPage />));

    const workspace = await screen.findByTestId("ip-deadline-workspace");
    await within(workspace).findByRole("button", { name: "Retry deadline workspace" });
    expect(within(workspace).getByLabelText("Active working calendar")).toBeDisabled();
    expect(within(workspace).getByText("Working calendars unavailable")).toBeInTheDocument();
    expect(within(workspace).queryByText("No active working calendar")).not.toBeInTheDocument();
    const callsBefore = fetchIpDeadlineWorkspaceMock.mock.calls.length;
    fetchIpDeadlineWorkspaceMock.mockResolvedValue({
      docket_id: "ip-1", rules: [], calendars: [], deadlines: [], exceptions: [],
      eligible_rule_version_ids: [],
      automation_state: "explicit_confirmation_only", governance: availableGovernance(),
    });
    await userEvent.click(within(workspace).getByRole("button", { name: "Retry deadline workspace" }));
    await within(workspace).findByText("No active working calendar");
    expect(fetchIpDeadlineWorkspaceMock.mock.calls.length).toBeGreaterThan(callsBefore);
    expect(proposeIpLegalDeadlineMock).not.toHaveBeenCalled();
  });

  it("B2-BUG-001/002 selects active deadline data and drops selections removed by a fresh response", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=ip-1&view=schedule");
    const rule = {
      id: "rule-1", rule_set_id: "set-1", key: "in-tm-response", version: 1,
      status: "active", rule_kind: "deadline", jurisdiction: "IN", office: "IP India",
    };
    const calendar = {
      id: "calendar-1", name: "IP India working calendar", version: 1,
      status: "active", jurisdiction: "IN", timezone: "Asia/Kolkata",
    };
    const data = {
      docket_id: "ip-1", eligible_rule_version_ids: ["rule-1", "rule-2"],
      rules: [rule, { ...rule, id: "rule-2", rule_set_id: "set-2", key: "in-tm-alternate", version: 2 },
        { ...rule, id: "unselected-active", rule_set_id: "set-unselected", key: "unselected-rule" },
        { ...rule, id: "candidate-rule", status: "candidate" },
        { ...rule, id: "fee-rule", rule_kind: "fee" }],
      calendars: [calendar, { ...calendar, id: "calendar-2", version: 2 },
        { ...calendar, id: "candidate-calendar", status: "candidate" }],
      deadlines: [], exceptions: [], automation_state: "explicit_confirmation_only", governance: availableGovernance(),
    };
    fetchIpDeadlineWorkspaceMock.mockResolvedValue(data);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><IpDocketPage /></QueryClientProvider>);
    const workspace = await screen.findByTestId("ip-deadline-workspace");
    const rules = within(workspace).getByLabelText("Active rule version");
    const calendars = within(workspace).getByLabelText("Active working calendar");
    await waitFor(() => expect(rules).toBeEnabled());
    expect(within(rules).getAllByRole("option").map(option => (option as HTMLOptionElement).value))
      .toEqual(["rule-1", "rule-2"]);
    expect(within(calendars).getAllByRole("option").map(option => (option as HTMLOptionElement).value))
      .toEqual(["calendar-1", "calendar-2"]);
    await userEvent.selectOptions(rules, "rule-2");
    await userEvent.selectOptions(calendars, "calendar-2");
    expect(rules).toHaveValue("rule-2");
    expect(calendars).toHaveValue("calendar-2");
    const ruleDetail = document.getElementById(rules.getAttribute("aria-describedby") ?? "");
    const calendarDetail = document.getElementById(calendars.getAttribute("aria-describedby") ?? "");
    expect(ruleDetail).toBeVisible();
    expect(ruleDetail).toHaveAttribute("data-selected-option-value", "rule-2");
    expect(ruleDetail?.textContent).toBe("in-tm-alternate · version 2 · IN · IP India · active");
    expect(calendarDetail).toBeVisible();
    expect(calendarDetail).toHaveAttribute("data-selected-option-value", "calendar-2");
    expect(calendarDetail?.textContent).toBe("IP India working calendar · version 2 · IN · Asia/Kolkata · active");
    expect((rules as HTMLSelectElement).selectedOptions[0].textContent).toBe(ruleDetail?.textContent);
    expect((calendars as HTMLSelectElement).selectedOptions[0].textContent).toBe(calendarDetail?.textContent);
    expect(within(workspace).getByRole("button", { name: "Calculate deadline proposal" })).toBeEnabled();

    await act(async () => client.setQueryData(["ip", "deadline-workspace", "ip-1"], {
      ...data, eligible_rule_version_ids: ["rule-1"],
    }));
    await waitFor(() => expect(rules).toHaveValue("rule-1"));
    expect(within(rules).queryByRole("option", { name: /in-tm-alternate/ })).not.toBeInTheDocument();
    expect(calendars).toHaveValue("calendar-2");
    expect(proposeIpLegalDeadlineMock).not.toHaveBeenCalled();

    await act(async () => client.setQueryData(["ip", "deadline-workspace", "ip-1"], {
      ...data, rules: [], calendars: [],
    }));
    await waitFor(() => expect(rules).toBeDisabled());
    expect(rules).toHaveValue("");
    expect(calendars).toHaveValue("");
    expect(document.getElementById("ip-active-rule-detail")).toBeNull();
    expect(document.getElementById("ip-active-calendar-detail")).toBeNull();
    expect(rules).toHaveAttribute("aria-describedby", "ip-deadline-prerequisites");
    expect(calendars).toHaveAttribute("aria-describedby", "ip-deadline-prerequisites");
    expect(within(workspace).getByRole("button", { name: "Calculate deadline proposal" })).toBeDisabled();
    expect(proposeIpLegalDeadlineMock).not.toHaveBeenCalled();
  });

  it("B2-BUG-001/002 keeps complete long rule and calendar captions linked to exact selected IDs", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=ip-1&view=schedule");
    const rule = {
      id: "rule-one", rule_set_id: "set-one", key: `rule-${"longkey".repeat(30)}`,
      version: 7, status: "active", rule_kind: "deadline", jurisdiction: "IN",
      office: "Intellectual Property Office",
    };
    const calendar = {
      id: "calendar-one", name: `Working calendar ${"longname".repeat(30)}`,
      version: 8, status: "active", jurisdiction: "IN", office: "Calendar Office",
      timezone: "Asia/Kolkata",
    };
    const data = {
      docket_id: "ip-1", eligible_rule_version_ids: ["rule-one", "rule-two"],
      rules: [rule, { ...rule, id: "rule-two", rule_set_id: "set-two" }],
      calendars: [calendar, { ...calendar, id: "calendar-two" }],
      deadlines: [], exceptions: [], automation_state: "explicit_confirmation_only", governance: availableGovernance(),
    };
    fetchIpDeadlineWorkspaceMock.mockResolvedValue(data);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><IpDocketPage /></QueryClientProvider>);
    const workspace = await screen.findByTestId("ip-deadline-workspace");
    const rules = within(workspace).getByLabelText("Active rule version") as HTMLSelectElement;
    const calendars = within(workspace).getByLabelText("Active working calendar") as HTMLSelectElement;
    await waitFor(() => expect(rules).toBeEnabled());

    const assertDetail = (select: HTMLSelectElement, expectedId: string, caption: string) => {
      expect(select).toHaveValue(expectedId);
      const detail = document.getElementById(select.getAttribute("aria-describedby") ?? "");
      expect(detail?.tagName).toBe("P");
      expect(detail).toBeVisible();
      expect(detail).toHaveAttribute("data-selected-option-value", expectedId);
      expect(detail?.textContent).toBe(caption);
      expect(select.selectedOptions[0].textContent).toBe(caption);
      expect(detail).toHaveClass("min-w-0", "whitespace-normal", "break-all");
      expect(detail?.className).not.toMatch(/truncate|line-clamp|overflow-hidden|sr-only/);
    };
    const ruleCaption = `${rule.key} · version 7 · IN · Intellectual Property Office · active`;
    const calendarCaption = `${calendar.name} · version 8 · IN · Calendar Office · Asia/Kolkata · active`;
    assertDetail(rules, "rule-one", ruleCaption);
    assertDetail(calendars, "calendar-one", calendarCaption);
    await userEvent.selectOptions(rules, "rule-two");
    await userEvent.selectOptions(calendars, "calendar-two");
    assertDetail(rules, "rule-two", ruleCaption);
    assertDetail(calendars, "calendar-two", calendarCaption);

    await act(async () => client.setQueryData(["ip", "deadline-workspace", "ip-1"], {
      ...data, rules: [rule], calendars: [calendar],
    }));
    await waitFor(() => expect(rules).toHaveValue("rule-one"));
    assertDetail(rules, "rule-one", ruleCaption);
    assertDetail(calendars, "calendar-one", calendarCaption);
    expect(proposeIpLegalDeadlineMock).not.toHaveBeenCalled();
  });

  it.each([{ label: "empty", ids: [] }, { label: "absent", ids: undefined }])(
    "B2-BUG-002 rejects active rules when server-owned eligibility is $label", async ({ ids }) => {
    window.history.replaceState(null, "", "/app/ip?docket=ip-1&view=schedule");
    fetchIpDeadlineWorkspaceMock.mockResolvedValue({
      docket_id: "ip-1", eligible_rule_version_ids: ids,
      rules: [{ id: "unselected-active", key: "unselected-rule", version: 1,
        status: "active", rule_kind: "deadline", jurisdiction: "IN", office: "IP India" }],
      calendars: [{ id: "calendar-1", name: "Approved calendar", version: 1,
        status: "active", timezone: "Asia/Kolkata" }],
      deadlines: [], exceptions: [], automation_state: "explicit_confirmation_only", governance: availableGovernance(),
    });
    render(withClient(<IpDocketPage />));
    const workspace = await screen.findByTestId("ip-deadline-workspace");
    await waitFor(() => expect(within(workspace).getByLabelText("Active working calendar")).toBeEnabled());
    const rules = within(workspace).getByLabelText("Active rule version");
    expect(rules).toBeDisabled();
    expect(within(rules).queryByRole("option", { name: /unselected-rule/ })).not.toBeInTheDocument();
    expect(within(workspace).getByRole("button", { name: "Calculate deadline proposal" })).toBeDisabled();
    expect(proposeIpLegalDeadlineMock).not.toHaveBeenCalled();
  });

  it("BUG-002 creates a two-class application with the catalogue edition on every row", async () => {
    const user = userEvent.setup();
    createManualTrademarkApplicationMock.mockResolvedValue({
      docket: activeDocket(),
      asset: { id: "asset-created" },
      application: { id: "application-created" },
      identifier: null,
      duplicate_candidates: [],
    });
    render(withClient(<IpDocketPage />));

    await user.click(await screen.findByRole("button", { name: "New trademark" }));
    await fillRequiredTrademarkFields(user);
    const submit = screen.getByRole("button", { name: "Create application" });
    expect(submit).toBeDisabled();
    expect(screen.getByText(/a Nice class for every class row/)).toBeVisible();

    await chooseNiceClass(user, "Nice class, row 1", "advertising", /^Class 35, services:/);
    await user.type(screen.getByLabelText("Goods and services, row 1"), "Advertising services");
    await user.click(screen.getByRole("button", { name: "Add class row" }));
    // The class chosen in row 1 cannot be chosen again in row 2.
    const second = screen.getByRole("combobox", { name: "Nice class, row 2" });
    await user.click(second);
    await user.type(second, "35");
    expect(within(screen.getByRole("listbox")).getByRole("option", { name: /^Class 35, services: .*Already listed in another row\.$/ }))
      .toHaveAttribute("aria-disabled", "true");
    await user.clear(second);
    await user.type(second, "9");
    await user.click(within(screen.getByRole("listbox")).getByRole("option", { name: /^Class 9, goods:/ }));
    await user.type(screen.getByLabelText("Goods and services, row 2"), "Downloadable software");
    await waitFor(() => expect(submit).toBeEnabled());
    await user.click(submit);

    await waitFor(() => expect(createManualTrademarkApplicationMock).toHaveBeenCalledTimes(1));
    expect(createManualTrademarkApplicationMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Aster filing",
        assetTitle: "ASTER",
        filingPhase: "pre_filing",
        applicationNumber: null,
        sourcePendingIdentifierAllocation: false,
        matterId: null,
        niceEdition: "NCL 13-2026",
        classes: [
          { classNumber: 35, specification: "Advertising services" },
          { classNumber: 9, specification: "Downloadable software" },
        ],
      }),
    );
    expect(screen.queryByRole("region", { name: "New trademark application" })).not.toBeInTheDocument();
  });

  it("BUG-002 anchors a refused class row to that row's field", async () => {
    const user = userEvent.setup();
    const { ApiError } = await import("@/lib/api/config");
    createManualTrademarkApplicationMock.mockRejectedValue(new ApiError(422,
      "Particulars › Classes › Specification: Class row 2: describe the goods or services for Nice class 9 (at least 3 characters).",
      { errors: [{ loc: ["body", "particulars", "classes", 1, "specification"], type: "nice_class",
        msg: "Class row 2: describe the goods or services for Nice class 9 (at least 3 characters)." }] }));
    render(withClient(<IpDocketPage />));

    await user.click(await screen.findByRole("button", { name: "New trademark" }));
    await fillRequiredTrademarkFields(user);
    await chooseNiceClass(user, "Nice class, row 1", "35", /^Class 35, services:/);
    await user.type(screen.getByLabelText("Goods and services, row 1"), "Advertising services");
    await user.click(screen.getByRole("button", { name: "Add class row" }));
    await chooseNiceClass(user, "Nice class, row 2", "9", /^Class 9, goods:/);
    await user.type(screen.getByLabelText("Goods and services, row 2"), "Apps");
    await user.click(screen.getByRole("button", { name: "Create application" }));

    const field = screen.getByLabelText("Goods and services, row 2");
    await waitFor(() => expect(field).toHaveAttribute("aria-invalid", "true"));
    const errorId = field.getAttribute("aria-describedby")!;
    expect(document.getElementById(errorId)).toHaveTextContent(
      "Class row 2: describe the goods or services for Nice class 9 (at least 3 characters).",
    );
    expect(screen.getByLabelText("Goods and services, row 1")).not.toHaveAttribute("aria-invalid");
  });

  it("BUG-002 keeps submit disabled with a reason while the Nice catalogue cannot load", async () => {
    const user = userEvent.setup();
    fetchIpNiceClassesMock.mockRejectedValue(new Error("offline"));
    render(withClient(<IpDocketPage />));

    await user.click(await screen.findByRole("button", { name: "New trademark" }));
    await fillRequiredTrademarkFields(user);
    expect(await screen.findByText(/The Nice class list could not load/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Create application" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add class row" })).toBeDisabled();
    expect(createManualTrademarkApplicationMock).not.toHaveBeenCalled();
  });

  it("BUG-001 opens the form above the readiness summary, scrolls it into view and focuses it", async () => {
    const user = userEvent.setup();
    fetchIpWorkspaceReadinessMock.mockResolvedValue(productionShapedReadiness());
    const scrolled: Element[] = [];
    const original = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = function scrollIntoView(this: Element) { scrolled.push(this); };
    try {
      render(withClient(<IpDocketPage />));
      const toggle = await screen.findByRole("button", { name: "New trademark" });
      expect(toggle).toHaveAttribute("type", "button");
      expect(toggle).toHaveAttribute("aria-expanded", "false");

      await user.click(toggle);

      const panel = screen.getByRole("region", { name: "New trademark application" });
      expect(toggle).toHaveAttribute("aria-expanded", "true");
      expect(toggle).toHaveAttribute("aria-controls", panel.id);
      expect(scrolled).toContain(panel);
      expect(screen.getByLabelText("Docket title")).toHaveFocus();
      const summary = screen.getByTestId("ip-automation-summary");
      expect(panel.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
      expect(summary).toHaveTextContent(
        "Manual docketing is available. 8 IP features are unavailable: 1 paused by CaseOps, 8 not in your plan, 1 needs setup, 1 your role cannot use.",
      );
      expect(screen.queryByText(/owner /)).not.toBeInTheDocument();
      expect(screen.queryByTestId("ip-automation-registry_sync")).not.toBeInTheDocument();

      await user.click(screen.getByRole("button", { name: "Cancel" }));
      expect(screen.queryByRole("region", { name: "New trademark application" })).not.toBeInTheDocument();
      await waitFor(() => expect(toggle).toHaveFocus());
      expect(toggle).toHaveAttribute("aria-expanded", "false");
    } finally {
      Element.prototype.scrollIntoView = original;
    }
  });

  it("BUG-001 picks a transfer's successor docket by name and never offers the docket itself", async () => {
    const successor = { ...activeDocket(), id: "ip-2", title: "BIRCH", primary_identifier: "TM-2" };
    fetchIpDocketsMock.mockResolvedValue({ dockets: [activeDocket(), successor], count: 2 });
    render(withClient(<IpDocketPage />));

    const lifecycle = await screen.findByTestId("ip-lifecycle-workflow");
    fireEvent.change(within(lifecycle).getByLabelText("Transition"), { target: { value: "transferred" } });
    expect(within(lifecycle).queryByLabelText("Successor docket ID")).toBeNull();
    const picker = within(lifecycle).getByRole<HTMLSelectElement>("combobox", { name: "Successor docket" });
    await waitFor(() => expect(picker).toBeEnabled());
    expect(Array.from(picker.options, (option) => option.value)).toEqual(["", "ip-2"]);
    const preview = within(lifecycle).getByRole("button", { name: "Preview lifecycle impact" });
    fireEvent.change(within(lifecycle).getByLabelText("Reason"), { target: { value: "Assigned to the successor owner." } });
    fireEvent.change(within(lifecycle).getByLabelText("Outcome"), { target: { value: "transferred" } });
    fireEvent.change(within(lifecycle).getByLabelText("Evidence reference"), { target: { value: "attachment:assignment-1" } });
    expect(preview).toBeDisabled();
    fireEvent.change(picker, { target: { value: "ip-2" } });
    expect(preview).toBeEnabled();
    fireEvent.click(preview);
    await waitFor(() => expect(previewIpDocketLifecycleMock).toHaveBeenCalledTimes(1));
    expect(previewIpDocketLifecycleMock).toHaveBeenCalledWith(
      "ip-1",
      expect.objectContaining({ toStatus: "transferred", successorDocketId: "ip-2" }),
    );
  });

  it("BUG-002 posts the chosen cost category and a Matter billing record chosen by name", async () => {
    fetchIpDocketsMock.mockResolvedValue({ dockets: [activeDocket()], count: 1 });
    fetchMatterWorkspaceMock.mockResolvedValue({
      invoices: [{ id: "invoice-1", invoice_number: "INV-2026-001", status: "issued", total_amount_minor: 900000,
        balance_due_minor: 0, amount_received_minor: 0, currency: "INR", line_items: [] }],
      time_entries: [],
    });
    render(withClient(<IpDocketPage />));

    const costs = await screen.findByTestId("ip-cost-workspace");
    fireEvent.change(within(costs).getByLabelText("Category"), { target: { value: "professional_fee" } });
    fireEvent.change(within(costs).getByLabelText("Description"), { target: { value: "Counsel fee for the search" } });
    fireEvent.change(within(costs).getByLabelText("Amount (INR)"), { target: { value: "9000" } });
    fireEvent.change(within(costs).getByLabelText("Evidence reference"), { target: { value: "receipt:counsel-1" } });
    fireEvent.change(within(costs).getByLabelText("Matter billing link type"), { target: { value: "invoice" } });
    expect(within(costs).queryByLabelText("Matter billing record ID")).toBeNull();
    const record = within(costs).getByRole<HTMLSelectElement>("combobox", { name: "Matter billing record" });
    await waitFor(() => expect(record).toBeEnabled());
    expect(fetchMatterWorkspaceMock).toHaveBeenCalledWith("matter-1", expect.anything());
    const add = within(costs).getByRole("button", { name: "Add cost evidence" });
    expect(add).toBeDisabled();
    fireEvent.change(record, { target: { value: "invoice-1" } });
    expect(record).toHaveAccessibleDescription("INV-2026-001 · issued · INR 9000.00");
    fireEvent.click(add);
    await waitFor(() => expect(addIpCostItemMock).toHaveBeenCalledTimes(1));
    expect(addIpCostItemMock).toHaveBeenCalledWith(
      "ip-1",
      expect.objectContaining({
        category: "professional_fee",
        amountMinor: 900000,
        billingLinkType: "invoice",
        billingLinkId: "invoice-1",
      }),
    );
  });

  it("BUG-001 explains each unavailable automation by who can change it", async () => {
    const user = userEvent.setup();
    fetchIpWorkspaceReadinessMock.mockResolvedValue(productionShapedReadiness());
    render(withClient(<IpDocketPage />));

    await user.click(await screen.findByRole("button", { name: "Show details" }));
    const registry = screen.getByTestId("ip-automation-registry_sync");
    expect(within(registry).getByText(/^Not in your plan\./)).toBeVisible();
    expect(within(registry).getByText(/^Paused by CaseOps\./)).toBeVisible();
    const deadlines = screen.getByTestId("ip-automation-deadline_automation");
    expect(within(deadlines).getByText(/^Needs setup\./)).toBeVisible();
    const rules = screen.getByTestId("ip-automation-rule_governance");
    expect(within(rules).getByText(/^Your role cannot use it\./)).toBeVisible();
    // Lawyers read what the role is missing, never a capability id.
    expect(rules).toHaveTextContent("It needs permission to propose deadline rules.");
    expect(rules).not.toHaveTextContent("ip:rules_propose");
    expect(registry.querySelector('[data-reason="missing_entitlement"]')).toHaveTextContent("ask CaseOps to add it to the plan");
    expect(screen.queryByRole("link", { name: /workspace plan/i })).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Hide details" });
    expect(toggle).toHaveAttribute("aria-controls", "ip-automation-readiness-detail");
    expect(document.getElementById("ip-automation-readiness-detail")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open workspace configuration" }));
    expect(screen.getByTestId("ip-workspace-configuration-panel")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Hide details" }));
    // A collapsed toggle points at nothing: the detail is not in the document.
    expect(screen.getByRole("button", { name: "Show details" })).not.toHaveAttribute("aria-controls");
  });

  it("opens the tab named by ?tab= and writes the tab back to the URL", async () => {
    const user = userEvent.setup();
    window.history.replaceState(null, "", "/app/ip?tab=documents");
    try {
      render(withClient(<IpDocketPage />));
      expect(await screen.findByRole("tab", { name: "Documents" })).toHaveAttribute("aria-selected", "true");
      await user.click(screen.getByRole("tab", { name: "Domain availability" }));
      expect(routerReplaceMock).toHaveBeenLastCalledWith("/app/ip?tab=availability", { scroll: false });
      await user.click(screen.getByRole("tab", { name: "Docket" }));
      expect(routerReplaceMock).toHaveBeenLastCalledWith("/app/ip", { scroll: false });
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });

  it("falls back to the docket tab for an unknown ?tab= value", async () => {
    window.history.replaceState(null, "", "/app/ip?tab=nonsense");
    try {
      render(withClient(<IpDocketPage />));
      expect(await screen.findByRole("tab", { name: "Docket" })).toHaveAttribute("aria-selected", "true");
    } finally {
      window.history.replaceState(null, "", "/");
    }
  });

  it("shows saved hearing source and complete reminder policy without treating queued as delivered", async () => {
    const colleagues = { users: [{ membership_id: "membership-1", full_name: "Current reminder owner",
      email: "reminder-owner@example.com", membership_active: true, user_active: true }] };
    const hearing = {
      ...unknownTimeHearing(),
      reminder_policy: { offsets_hours: [48, 24], channels: ["in_app"],
        recipient_membership_ids: ["membership-1"], date_reminder_local_time: "18:00:00" },
    };
    fetchIpDocketsMock.mockResolvedValue({ dockets: [activeDocket()], count: 1 });
    fetchIpSharedHearingsMock.mockResolvedValue({ docket_id: "ip-1", hearings: [hearing] });
    render(withClient(<IpDocketPage />, colleagues));
    await userEvent.click(await screen.findByRole("tab", { name: "Hearings and deadlines" }));
    const saved = await screen.findByTestId("ip-hearing-hearing-1");
    expect(within(saved).getByText("Source: registry_notice")).toBeVisible();
    expect(within(saved).getByText("Reminder offsets: 48, 24 hours")).toBeVisible();
    expect(within(saved).getByText("Channels: in_app")).toBeVisible();
    expect(within(saved).getByText("Date-based delivery: 18:00:00 · Asia/Kolkata")).toBeVisible();
    expect(within(saved).getByTestId("ip-hearing-policy-recipients")).toHaveAttribute(
      "data-recipient-membership-ids", "membership-1",
    );
    expect(within(saved).getByText("Recipients: 1")).toBeVisible();
    expect(within(saved).getByRole("list", { name: "Saved reminder recipients" })).toHaveTextContent(
      "Current reminder owner — reminder-owner@example.com",
    );
    expect(listCompanyUsersMock).not.toHaveBeenCalled();
    expect(within(saved).getByRole("group", { name: "Reminder delivery for Opposition hearing" })).toHaveTextContent("queued");
    expect(within(saved).queryByText(/confirmed delivery/i)).not.toBeInTheDocument();
  });

  it("resolves saved recipients from a cold directory for a read-only hearing viewer", async () => {
    useCapabilityMock.mockImplementation((capability: string) => capability === "ip:read");
    const hearing = { ...unknownTimeHearing(), reminder_policy: {
      ...unknownTimeHearing().reminder_policy, recipient_membership_ids: ["member-1"],
    } };
    fetchIpDocketsMock.mockResolvedValue({ dockets: [activeDocket()], count: 1 });
    fetchIpSharedHearingsMock.mockResolvedValue({ docket_id: "ip-1", hearings: [hearing] });
    render(withClient(<IpDocketPage />));
    await userEvent.click(await screen.findByRole("tab", { name: "Hearings and deadlines" }));
    const saved = await screen.findByTestId("ip-hearing-hearing-1");
    await waitFor(() => expect(within(saved).getByRole("list", { name: "Saved reminder recipients" }))
      .toHaveTextContent("Priya Raghavan — priya@example.com"));
    expect(listCompanyUsersMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Preview recipients and policy" })).not.toBeInTheDocument();
  });

  it("retries a failed saved-recipient directory without changing retained assignments", async () => {
    useCapabilityMock.mockImplementation((capability: string) => capability === "ip:read");
    listCompanyUsersMock.mockRejectedValueOnce(new Error("Directory unavailable"));
    const hearing = { ...unknownTimeHearing(), reminder_policy: {
      ...unknownTimeHearing().reminder_policy, recipient_membership_ids: ["member-1"],
    } };
    fetchIpDocketsMock.mockResolvedValue({ dockets: [activeDocket()], count: 1 });
    fetchIpSharedHearingsMock.mockResolvedValue({ docket_id: "ip-1", hearings: [hearing] });
    render(withClient(<IpDocketPage />));
    await userEvent.click(await screen.findByRole("tab", { name: "Hearings and deadlines" }));
    const error = await screen.findByTestId("ip-hearing-recipient-error");
    expect(error).toHaveTextContent("Could not load saved reminder recipients");
    const saved = await screen.findByTestId("ip-hearing-hearing-1");
    expect(within(saved).getByTestId("ip-hearing-policy-recipients"))
      .toHaveAttribute("data-recipient-membership-ids", "member-1");
    await userEvent.click(within(error).getByRole("button", { name: /^Try again$/ }));
    await waitFor(() => expect(within(saved).getByRole("list", { name: "Saved reminder recipients" }))
      .toHaveTextContent("Priya Raghavan — priya@example.com"));
    expect(listCompanyUsersMock).toHaveBeenCalledTimes(2);
    expect(updateIpSharedHearingMock).not.toHaveBeenCalled();
  });

  it("preserves unavailable and inactive saved reminder recipients without adding assignment options", async () => {
    const hearing = { ...unknownTimeHearing(), reminder_policy: {
      ...unknownTimeHearing().reminder_policy, recipient_membership_ids: ["inactive-member", "missing-member"],
    } };
    listCompanyUsersMock.mockResolvedValue({ users: [{ membership_id: "inactive-member", full_name: "Former colleague",
      email: "former@example.com", membership_active: false, user_active: true }] });
    fetchIpDocketsMock.mockResolvedValue({ dockets: [activeDocket()], count: 1 });
    fetchIpSharedHearingsMock.mockResolvedValue({ docket_id: "ip-1", hearings: [hearing] });
    render(withClient(<IpDocketPage />));
    await userEvent.click(await screen.findByRole("tab", { name: "Hearings and deadlines" }));
    const saved = await screen.findByTestId("ip-hearing-hearing-1");
    const recipients = within(saved).getByRole("list", { name: "Saved reminder recipients" });
    expect(recipients).toHaveTextContent("Former colleague — former@example.com (inactive; retained assignment)");
    expect(recipients).toHaveTextContent("Recipient details unavailable (retained assignment)");
    expect(recipients.querySelector('[data-membership-id="missing-member"]')).toBeVisible();
    expect(within(saved).queryByRole("option", { name: /Former colleague/ })).not.toBeInTheDocument();
  });

  it("confirms an unpublished hearing time and shows the reminder replacement chain", async () => {
    const hearing = unknownTimeHearing();
    const rescheduledDate = "2026-12-16";
    const exactRescheduledDate = "2026-12-17";
    const confirmed = {
      ...hearing,
      hearing_on: rescheduledDate,
      time_status: "exact",
      hearing_time: "14:30:00",
      time_confirmation_required: false,
    };
    fetchIpDocketsMock.mockResolvedValue({ dockets: [activeDocket()], count: 1 });
    fetchIpSharedHearingsMock.mockResolvedValue({ docket_id: "ip-1", hearings: [hearing] });
    updateIpSharedHearingMock
      .mockResolvedValueOnce({ ...hearing, hearing_on: rescheduledDate })
      .mockResolvedValueOnce(confirmed)
      .mockResolvedValueOnce({ ...confirmed, hearing_on: exactRescheduledDate });

    render(withClient(<IpDocketPage />));

    expect(fetchIpSharedHearingsMock).not.toHaveBeenCalled();
    await userEvent.click(
      await screen.findByRole("tab", { name: "Hearings and deadlines" }),
    );
    const workflow = await screen.findByTestId("ip-hearing-workflow");
    expect(await within(workflow).findByText(/Time confirmation pending/)).toBeVisible();
    expect(within(workflow).getByText("Superseded by generation 2")).toBeVisible();
    expect(within(workflow).getByText("Current schedule")).toBeVisible();
    const rescheduleDate = within(workflow).getByLabelText("Reschedule Opposition hearing");
    const publishedTime = within(workflow).getByLabelText("Published time for Opposition hearing");
    for (const input of [rescheduleDate, publishedTime]) {
      expect(input).toHaveClass("w-full", "min-w-0", "max-w-full", "sm:w-52", "sm:shrink-0");
      expect(input).not.toHaveClass("sm:w-auto");
    }
    expect(rescheduleDate).toHaveAttribute("type", "date");
    expect(rescheduleDate).toHaveValue(hearing.hearing_on);
    expect(publishedTime).toHaveAttribute("type", "time");
    expect(publishedTime).toHaveValue("");

    const confirm = within(workflow).getByRole("button", {
      name: "Confirm published time",
    });
    expect(confirm).toBeDisabled();
    fireEvent.change(rescheduleDate, { target: { value: rescheduledDate } });
    expect(rescheduleDate).toHaveValue(rescheduledDate);
    fireEvent.click(within(workflow).getByRole("button", { name: "Reschedule" }));
    await waitFor(() => expect(updateIpSharedHearingMock).toHaveBeenNthCalledWith(1, {
      docketId: "ip-1", hearingId: "hearing-1", hearingOn: rescheduledDate,
    }));
    const savedHearing = within(workflow).getByTestId("ip-hearing-hearing-1");
    await waitFor(() => expect(savedHearing).toHaveTextContent(`${rescheduledDate} · Time not published · Asia/Kolkata`));
    expect(within(workflow).getByText(/Time confirmation pending/)).toBeVisible();
    expect(confirm).toBeDisabled();
    expect(publishedTime).toHaveValue("");
    fireEvent.change(publishedTime, {
      target: { value: "14:30" },
    });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);

    await waitFor(() =>
      expect(updateIpSharedHearingMock).toHaveBeenCalledWith({
        docketId: "ip-1",
        hearingId: "hearing-1",
        timeStatus: "exact",
        hearingTime: "14:30",
        sessionLabel: null,
      }),
    );
    await waitFor(() =>
      expect(within(workflow).queryByText(/Time confirmation pending/)).not.toBeInTheDocument(),
    );
    expect(savedHearing).toHaveTextContent(`${rescheduledDate} · 14:30:00 · Asia/Kolkata`);
    expect(within(workflow).queryByLabelText("Published time for Opposition hearing")).toBeNull();
    fireEvent.change(rescheduleDate, { target: { value: exactRescheduledDate } });
    expect(rescheduleDate).toHaveValue(exactRescheduledDate);
    fireEvent.click(within(workflow).getByRole("button", { name: "Reschedule" }));
    await waitFor(() => expect(updateIpSharedHearingMock).toHaveBeenNthCalledWith(3, {
      docketId: "ip-1", hearingId: "hearing-1", hearingOn: exactRescheduledDate,
    }));
    await waitFor(() => expect(savedHearing).toHaveTextContent(`${exactRescheduledDate} · 14:30:00 · Asia/Kolkata`));
    expect(updateIpSharedHearingMock).toHaveBeenCalledTimes(3);
    expect(fetchIpSharedHearingsMock).toHaveBeenCalledTimes(1);
  });

  it("links to the complete portfolio when the bounded docket list has more records", async () => {
    fetchIpDocketsMock.mockResolvedValue({
      dockets: [activeDocket()],
      count: 1,
      has_more: true,
    });

    render(withClient(<IpDocketPage />));

    expect(await screen.findByText("Showing the 100 most recently updated records.")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open full portfolio" })).toHaveAttribute(
      "href",
      "/app/ip/portfolio",
    );
  });

  it("renders created reminder delivery from the mutation without a list refetch", async () => {
    const returned = unknownTimeHearing();
    const currentReminder = returned.reminders[1];
    const created = {
      ...returned,
      purpose: "Hearing",
      reminders: [
        { ...currentReminder, id: "reminder-email", channel: "email" as const },
        { ...currentReminder, id: "reminder-in-app", channel: "in_app" as const },
      ],
    };
    fetchIpDocketsMock.mockResolvedValue({ dockets: [activeDocket()], count: 1 });
    createIpSharedHearingMock.mockResolvedValue(created);

    render(withClient(<IpDocketPage />));

    expect(fetchIpSharedHearingsMock).not.toHaveBeenCalled();
    await userEvent.click(
      await screen.findByRole("tab", { name: "Hearings and deadlines" }),
    );
    const workflow = await screen.findByTestId("ip-hearing-workflow");
    await waitFor(() => expect(fetchIpSharedHearingsMock).toHaveBeenCalledTimes(1));
    fireEvent.click(within(workflow).getByRole("button", {
      name: "Preview recipients and policy",
    }));
    fireEvent.click(within(workflow).getByRole("button", {
      name: "Confirm hearing and reminders",
    }));

    await waitFor(() => expect(createIpSharedHearingMock).toHaveBeenCalledTimes(1));
    const delivery = await within(workflow).findByLabelText("Reminder delivery for Hearing");
    expect(within(delivery).getByText("email").parentElement).toHaveTextContent(
      "email · queued",
    );
    expect(within(delivery).getByText("in_app").parentElement).toHaveTextContent(
      "in_app · queued",
    );
    expect(fetchIpSharedHearingsMock).toHaveBeenCalledTimes(1);
  });

  it("keeps 48h reminder offsets instead of silently dropping them (B4-ADJ-19)", async () => {
    fetchIpDocketsMock.mockResolvedValue({ dockets: [activeDocket()], count: 1 });
    createIpSharedHearingMock.mockResolvedValue(unknownTimeHearing());
    render(withClient(<IpDocketPage />));
    await userEvent.click(await screen.findByRole("tab", { name: "Hearings and deadlines" }));
    const workflow = await screen.findByTestId("ip-hearing-workflow");
    const offsets = within(workflow).getByLabelText("Reminder offsets");
    const preview = within(workflow).getByRole("button", { name: "Preview recipients and policy" });

    fireEvent.change(offsets, { target: { value: "48h, soon" } });
    expect(offsets).toHaveAttribute("aria-invalid", "true");
    expect(within(workflow).getByRole("alert")).toHaveTextContent('"soon" is not a reminder offset.');
    expect(preview).toBeDisabled();

    fireEvent.change(offsets, { target: { value: "48h, 1d" } });
    expect(offsets).not.toHaveAttribute("aria-invalid");
    expect(within(workflow).getByText(/Before the hearing: 48, 24 hours\./)).toBeVisible();
    fireEvent.click(preview);
    fireEvent.click(within(workflow).getByRole("button", { name: "Confirm hearing and reminders" }));
    await waitFor(() => expect(createIpSharedHearingMock).toHaveBeenCalledTimes(1));
    expect(createIpSharedHearingMock.mock.calls[0][0].reminderOffsetsHours).toEqual([48, 24]);
  });

  it("keeps typed numbers separate and resolves duplicates on narrow mobile", async () => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: 360 });
    fetchIpDocketsMock.mockResolvedValue({
      dockets: [{
        id: "ip-1", company_id: "company-1", matter_id: "matter-1",
        record_type: "trademark", title: "ASTER", primary_identifier: null,
        status: "ready", restricted: false, is_active: true, lifecycle_version: 0,
        access_policy_version: 0, lifecycle_effective_at: null, lifecycle_reason: null,
        lifecycle_outcome: null, lifecycle_source: null, lifecycle_evidence_ref: null,
        successor_docket_id: null, current_version: 1,
        created_at: "2026-08-21T00:00:00Z", updated_at: "2026-08-21T00:00:00Z",
        current_particulars: {
          form_key: "TM-A", form_version: "2026.1", readiness_status: "ready",
          classes_json: [{ class_number: 9, specification: "Software" }],
        },
        notice_links: [], evidence_candidates: [], deadline_coverages: [],
        deadline_incidents: [], title_interests: [], related_right_obligations: [],
        cost_items: [],
      }],
      count: 1,
    });
    const application = {
      id: "application-1", docket_id: "ip-1", asset_id: "asset-1",
      office: "IP India", jurisdiction: "IN", filing_phase: "draft", is_active: true,
      lifecycle_version: 0, source_pending_identifier_allocation: false, version: 1,
      created_at: "2026-08-21T00:00:00Z", updated_at: "2026-08-21T00:00:00Z",
    };
    const baseIdentifier = {
      docket_id: "ip-1", office: "IP India", jurisdiction: "IN", source: "manual",
      normalized_value: "tm202600421", effective_from: "2026-08-21",
      effective_until: null, is_primary: true, supersedes_identifier_id: null,
      superseded_by_identifier_id: null, correction_reason: null,
      created_at: "2026-08-21T00:00:00Z",
    };
    fetchIpCoreRecordsMock.mockResolvedValue({
      assets: [], applications: [application], proceedings: [],
      identifiers: [
        {
          ...baseIdentifier, id: "identifier-1", application_id: "application-1",
          proceeding_id: null, identifier_kind: "application", raw_value: "TM / 2026 / 00421",
          reconciliation_status: "needs_review",
        },
        {
          ...baseIdentifier, id: "identifier-2", application_id: null,
          proceeding_id: "opposition-1", identifier_kind: "opposition", raw_value: "OPP 17/2026",
          normalized_value: "opp172026", reconciliation_status: "confirmed",
        },
      ],
    });
    previewIpIdentifierDuplicatesMock.mockResolvedValue({
      identifier_id: "identifier-1",
      identifier: {
        identifier_id: "identifier-1", docket_id: "ip-1", application_id: "application-1",
        proceeding_id: null, matter_id: "matter-1", raw_value: "TM / 2026 / 00421",
        normalized_value: "tm202600421", source: "manual", is_primary: true,
        reconciliation_status: "needs_review", docket_title: "ASTER", docket_status: "ready",
        docket_restricted: false, docket_is_active: true,
      },
      candidates: [{
        identifier_id: "identifier-existing", docket_id: "ip-existing",
        application_id: "application-existing", proceeding_id: null, matter_id: "matter-1",
        raw_value: "TM-2026-00421", normalized_value: "tm202600421", source: "registry",
        is_primary: true, reconciliation_status: "confirmed", docket_title: "ASTER EXISTING",
        docket_status: "ready", docket_restricted: false, docket_is_active: true,
      }],
      decision_token: "current-preview-token", automatic_merge_blocked: false,
      blocking_reasons: [], allowed_decisions: ["distinct", "supersede"],
    });
    resolveIpIdentifierDuplicateMock.mockResolvedValue({
      identifier: { id: "identifier-1", reconciliation_status: "confirmed" },
      decision: "distinct", resolved_candidate_ids: ["identifier-existing"],
    });

    render(withClient(<IpDocketPage />));

    const identity = await screen.findByTestId("ip-identity-workspace");
    expect(await within(identity).findByText("Application no.")).toBeVisible();
    expect(within(identity).getByText("TM / 2026 / 00421")).toBeVisible();
    expect(within(identity).getByText("Opposition no.")).toBeVisible();
    expect(within(identity).getByText("OPP 17/2026")).toBeVisible();
    expect(await within(identity).findByText("ASTER EXISTING")).toBeVisible();
    fireEvent.change(within(identity).getByLabelText("Decision reason"), {
      target: { value: "Registry evidence confirms a separate filing." },
    });
    fireEvent.click(within(identity).getByRole("button", { name: "Confirm separate filing" }));
    await waitFor(() => expect(resolveIpIdentifierDuplicateMock).toHaveBeenCalledWith({
      docketId: "ip-1", identifierId: "identifier-1", decision: "distinct",
      decisionToken: "current-preview-token",
      reason: "Registry evidence confirms a separate filing.",
      supersededByIdentifierId: null,
    }));
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
    expect(screen.getByText("Not in your plan. Your workspace plan does not include it. A workspace admin can ask CaseOps to add it to the plan.")).toBeVisible();
    expect(screen.getByText("Paused by CaseOps. CaseOps has not switched this feature on yet. Nothing in your workspace needs to change.")).toBeVisible();
    expect(screen.queryByText(/owner (product-ip|integrations)/)).not.toBeInTheDocument();
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
    expect(screen.getByTestId("ip-automation-summary")).toHaveTextContent(
      "Manual docketing is available. 1 IP feature is unavailable: 1 paused by CaseOps.",
    );
    fireEvent.click(screen.getByRole("button", { name: "Show details" }));
    expect(screen.getByText("Registry sync")).toBeVisible();
    expect(screen.getByText("Until then, use manual docketing.")).toBeVisible();
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
          renewal_reminder_cadence_days: 1,
          renewal_reminder_delivery_time: "09:00",
          escalation_owner_membership_id: "membership-1",
          provider_keys_json: ["ipindia-registry"],
          provider_terms_version: "2026.1",
          provider_terms_accepted_by_membership_id: "membership-1",
          provider_terms_accepted_at: "2026-08-07T00:00:00Z",
          enabled_automations_json: [],
          workspace_enabled: false,
          updated_by_membership_id: "membership-1",
          created_at: "2026-08-07T00:00:00Z",
          updated_at: "2026-08-07T00:00:00Z",
        },
        tests: [],
        ready_for_manual_docketing: true,
        enablement_blockers: [],
        provider_adapters: [{
          provider: "ipindia-registry",
          display_name: "IP India registry",
          domain: "ip_office_registry",
          adapter_status: "blocked_pending_provider_contract",
          commercial_terms_status: "not_approved",
          required_capabilities: ["search", "record_fetch", "document_fetch"],
          implemented_capabilities: [],
          attribution_label: "IP India registry source (not activated)",
          cost_categories: ["registry_search"],
          health_path: null,
          support_matrix_path: null,
          operations_path: "/api/admin/provider-operations/jobs",
          endpoint_paths: [],
          legal_coverage: [{
            jurisdiction: "IN",
            office: "IP India",
            asset_types: ["trademark"],
            identifier_types: [],
            register_fields: [],
            document_types: [],
            coverage_status: "unverified",
            evidence_ref: null,
          }],
          activation_blockers: ["provider_contract_not_approved"],
          limitations: ["Manual sourced docketing remains available."],
        }],
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
    expect(screen.getByLabelText("Permitted registry provider")).toHaveValue(
      "ipindia-registry",
    );
    expect(screen.getByTestId("ip-provider-contract")).toHaveTextContent(
      "blocked pending provider contract",
    );
    expect(screen.getByText(/unverified legal coverage/i)).toBeVisible();
    expect(screen.getByLabelText("registry sync")).toBeDisabled();
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

  it("preserves configured renewal policy and provider consent during an unrelated configuration save", async () => {
    const readiness = setupReadiness(renewalConfiguration());
    fetchIpWorkspaceReadinessMock.mockResolvedValue(readiness);
    saveIpWorkspaceConfigurationMock.mockResolvedValue(readiness.configuration_status);
    render(withClient(<IpDocketPage />));
    const card = await screen.findByTestId("ip-workspace-configuration");
    expect(within(card).getByLabelText("Renewal reminder cadence (days)")).toHaveValue(7);
    expect(within(card).getByLabelText("Renewal reminder local time")).toHaveValue("14:45");
    expect(within(card).getByLabelText("Renewal reminder local time")).toHaveAccessibleName("Renewal reminder local time");
    expect(within(card).getByLabelText("Renewal reminder local time")).toHaveAccessibleDescription("Europe/London");
    expect(within(card).getByLabelText("IANA timezone")).toHaveValue("Europe/London");
    const consent = within(card).getByLabelText(/Accept provider attribution and cost terms/);
    expect(consent).toBeChecked();
    fireEvent.change(within(card).getByLabelText("Office"), { target: { value: "Reviewed office" } });
    await userEvent.click(within(card).getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(saveIpWorkspaceConfigurationMock).toHaveBeenCalledExactlyOnceWith({
      currentConfiguration: readiness.configuration_status?.configuration ?? undefined,
      expectedVersion: 4, jurisdiction: "IN", office: "Reviewed office", timezone: "Europe/London",
      holidayCalendarKey: "reviewed-calendar", escalationOwnerMembershipId: "membership-1",
      providerKey: "ipindia-registry", acceptProviderTerms: true,
      renewalReminderCadenceDays: 7, renewalReminderDeliveryTime: "14:45",
    }));
    expect(consent).toBeChecked();
    expect(enableIpWorkspaceMock).not.toHaveBeenCalled();
    expect(runIpWorkspaceTestMock).not.toHaveBeenCalled();
  });

  it("opens active workspace configuration and requires explicit manual re-enable after saving policy", async () => {
    const configuration = renewalConfiguration({ workspace_enabled: true });
    let readiness = { ...setupReadiness(configuration), workspace_available: true, manual_docketing_available: true };
    fetchIpWorkspaceReadinessMock.mockImplementation(async () => readiness);
    saveIpWorkspaceConfigurationMock.mockImplementation(async () => {
      readiness = setupReadiness(renewalConfiguration({ version: 5,
        renewal_reminder_cadence_days: 2, renewal_reminder_delivery_time: "10:15" }));
      return readiness.configuration_status;
    });
    enableIpWorkspaceMock.mockImplementation(async () => {
      readiness = { ...setupReadiness(renewalConfiguration({ version: 5, workspace_enabled: true,
        renewal_reminder_cadence_days: 2, renewal_reminder_delivery_time: "10:15" })),
        workspace_available: true, manual_docketing_available: true };
      return readiness.configuration_status;
    });
    render(withClient(<IpDocketPage />));
    const action = await screen.findByRole("button", { name: "Workspace configuration" });
    expect(action).toHaveAttribute("title", "Workspace configuration");
    expect(action).toHaveAttribute("aria-expanded", "false");
    expect(action).toHaveAttribute("aria-controls", "ip-workspace-configuration-panel");
    expect(screen.queryByTestId("ip-workspace-configuration")).not.toBeInTheDocument();
    await userEvent.click(action);
    const region = await screen.findByRole("region", { name: "Workspace configuration" });
    expect(region).toHaveAttribute("data-testid", "ip-workspace-configuration-panel");
    expect(action).toHaveAttribute("aria-expanded", "true");
    fireEvent.change(within(region).getByLabelText("Renewal reminder cadence (days)"), { target: { value: "2" } });
    fireEvent.change(within(region).getByLabelText("Renewal reminder local time"), { target: { value: "10:15" } });
    await userEvent.click(within(region).getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Workspace configuration" })).not.toBeInTheDocument());
    expect(saveIpWorkspaceConfigurationMock).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({
      currentConfiguration: configuration, expectedVersion: 4, renewalReminderCadenceDays: 2, renewalReminderDeliveryTime: "10:15",
    }));
    expect(enableIpWorkspaceMock).not.toHaveBeenCalled();
    const blockedCard = await screen.findByTestId("ip-workspace-configuration");
    await userEvent.click(within(blockedCard).getByRole("button", { name: "Enable manual workspace" }));
    await screen.findByRole("heading", { name: "Trademark docket" });
    expect(enableIpWorkspaceMock).toHaveBeenCalledExactlyOnceWith({ version: 5, enabledAutomations: [] });
    const restored = await screen.findByRole("region", { name: "Workspace configuration" });
    expect(within(restored).getByLabelText("Renewal reminder cadence (days)")).toHaveValue(2);
    expect(within(restored).getByLabelText("Renewal reminder local time")).toHaveValue("10:15");
    await userEvent.click(screen.getByRole("button", { name: "Workspace configuration" }));
    expect(screen.queryByRole("region", { name: "Workspace configuration" })).not.toBeInTheDocument();
  });

  it("does not expose active workspace configuration without its existing configuration capability", async () => {
    useCapabilityMock.mockImplementation((capability: string) => capability !== "ip:taxonomy_admin");
    fetchIpWorkspaceReadinessMock.mockResolvedValue({ ...setupReadiness(renewalConfiguration({ workspace_enabled: true })),
      workspace_available: true, manual_docketing_available: true });
    render(withClient(<IpDocketPage />));
    await screen.findByRole("heading", { name: "Trademark docket" });
    expect(screen.queryByRole("button", { name: "Workspace configuration" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Workspace configuration" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("ip-workspace-configuration")).not.toBeInTheDocument();
  });

  it.each([1, 31])("saves the explicit renewal cadence boundary %i with local time and no new provider consent", async (cadence) => {
    const readiness = setupReadiness();
    fetchIpWorkspaceReadinessMock.mockResolvedValue(readiness);
    saveIpWorkspaceConfigurationMock.mockResolvedValue(readiness.configuration_status);
    render(withClient(<IpDocketPage />));
    const card = await screen.findByTestId("ip-workspace-configuration");
    const days = within(card).getByLabelText("Renewal reminder cadence (days)");
    const time = within(card).getByLabelText("Renewal reminder local time");
    expect(days).toHaveValue(1);
    expect(time).toHaveValue("09:00");
    expect(days).toHaveAttribute("min", "1");
    expect(days).toHaveAttribute("max", "31");
    expect(days).toHaveAttribute("step", "1");
    const calendar = within(card).getByLabelText("Holiday calendar");
    await userEvent.clear(calendar);
    await userEvent.type(calendar, "IN-TEST");
    expect(calendar).toHaveValue("IN-TEST");
    fireEvent.change(days, { target: { value: String(cadence) } });
    fireEvent.change(time, { target: { value: "23:59" } });
    await userEvent.click(within(card).getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(saveIpWorkspaceConfigurationMock).toHaveBeenCalledExactlyOnceWith({
      currentConfiguration: undefined,
      expectedVersion: null, jurisdiction: "IN", office: "IP India", timezone: "Asia/Kolkata",
      holidayCalendarKey: "IN-TEST", escalationOwnerMembershipId: "membership-1",
      providerKey: "", acceptProviderTerms: false,
      renewalReminderCadenceDays: cadence, renewalReminderDeliveryTime: "23:59",
    }));
  });

  it.each([
    { name: "missing cadence", cadence: "", time: "09:00" },
    { name: "zero cadence", cadence: "0", time: "09:00" },
    { name: "oversized cadence", cadence: "32", time: "09:00" },
    { name: "fractional cadence", cadence: "1.5", time: "09:00" },
    { name: "missing time", cadence: "1", time: "" },
    { name: "invalid time", cadence: "1", time: "24:00" },
  ])("does not save a renewal policy with $name", async ({ cadence, time }) => {
    fetchIpWorkspaceReadinessMock.mockResolvedValue(setupReadiness());
    render(withClient(<IpDocketPage />));
    const card = await screen.findByTestId("ip-workspace-configuration");
    fireEvent.change(within(card).getByLabelText("Renewal reminder cadence (days)"), { target: { value: cadence } });
    fireEvent.change(within(card).getByLabelText("Renewal reminder local time"), { target: { value: time } });
    expect(within(card).getByRole("button", { name: "Save configuration" })).toBeDisabled();
    expect(saveIpWorkspaceConfigurationMock).not.toHaveBeenCalled();
  });

  it("hydrates a new configuration version without resetting current-version renewal edits or other fields", async () => {
    const configuration = renewalConfiguration();
    fetchIpWorkspaceReadinessMock.mockResolvedValue(setupReadiness(configuration));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><IpDocketPage /></QueryClientProvider>);
    const card = await screen.findByTestId("ip-workspace-configuration");
    const days = within(card).getByLabelText("Renewal reminder cadence (days)");
    const time = within(card).getByLabelText("Renewal reminder local time");
    fireEvent.change(days, { target: { value: "3" } });
    fireEvent.change(time, { target: { value: "15:30" } });
    fireEvent.change(within(card).getByLabelText("Office"), { target: { value: "Reviewed office" } });
    await act(async () => client.setQueryData(["ip", "readiness"], setupReadiness({ ...configuration })));
    expect(days).toHaveValue(3);
    expect(time).toHaveValue("15:30");
    const refreshed = setupReadiness(renewalConfiguration({ version: 5,
      renewal_reminder_cadence_days: 5, renewal_reminder_delivery_time: "16:00" }));
    await act(async () => client.setQueryData(["ip", "readiness"], refreshed));
    await waitFor(() => expect(days).toHaveValue(5));
    expect(time).toHaveValue("16:00");
    expect(within(card).getByLabelText("Office")).toHaveValue("Reviewed office");
    expect(within(card).getByLabelText(/Accept provider attribution and cost terms/)).toBeChecked();
  });

  it("does not silently default an existing configuration whose renewal policy is absent", async () => {
    const configuration: Partial<IpWorkspaceConfiguration> = renewalConfiguration();
    delete configuration.renewal_reminder_cadence_days;
    delete configuration.renewal_reminder_delivery_time;
    fetchIpWorkspaceReadinessMock.mockResolvedValue({ ...setupReadiness(),
      configuration_status: { ...setupReadiness().configuration_status, configuration } });
    render(withClient(<IpDocketPage />));
    const card = await screen.findByTestId("ip-workspace-configuration");
    expect(within(card).getByLabelText("Renewal reminder cadence (days)")).toHaveValue(null);
    expect(within(card).getByLabelText("Renewal reminder local time")).toHaveValue("");
    expect(within(card).getByRole("button", { name: "Save configuration" })).toBeDisabled();
    expect(saveIpWorkspaceConfigurationMock).not.toHaveBeenCalled();
  });

  it("passes the complete nondefault current configuration when editing only renewal cadence", async () => {
    const configuration = renewalConfiguration({ enabled_asset_types_json: ["trademark", "patent"],
      jurisdictions_json: ["GB", "IN"], offices_json: ["UK IPO", "IP India"],
      working_day_policy_json: { working_weekdays: [0, 2, 4], region: "reviewed" },
      document_taxonomy_version: "reviewed-taxonomy", event_catalog_version: "reviewed-events",
      deadline_rule_versions_json: { GB: "reviewed-gb", IN: "reviewed-in" },
      notification_channels_json: ["email", "in_app"], critical_event_policy_json: { escalation_after_minutes: 75 },
      provider_keys_json: ["ipindia-registry", "reviewed-secondary"], provider_terms_version: "reviewed-terms" });
    const before = structuredClone(configuration);
    const readiness = setupReadiness(configuration);
    fetchIpWorkspaceReadinessMock.mockResolvedValue(readiness);
    saveIpWorkspaceConfigurationMock.mockResolvedValue(readiness.configuration_status);
    render(withClient(<IpDocketPage />));
    const card = await screen.findByTestId("ip-workspace-configuration");
    expect(within(card).getByLabelText("Enabled asset type")).toHaveValue("Trademark, Patent");
    expect(within(card).queryByText(/Monday–Friday working policy/)).not.toBeInTheDocument();
    expect(within(card).getByLabelText(/Accept provider attribution and cost terms version reviewed-terms/)).toBeChecked();
    fireEvent.change(within(card).getByLabelText("Renewal reminder cadence (days)"), { target: { value: "2" } });
    await userEvent.click(within(card).getByRole("button", { name: "Save configuration" }));
    await waitFor(() => expect(saveIpWorkspaceConfigurationMock).toHaveBeenCalledExactlyOnceWith({
      currentConfiguration: configuration, expectedVersion: 4, jurisdiction: "GB", office: "UK IPO",
      timezone: "Europe/London", holidayCalendarKey: "reviewed-calendar", escalationOwnerMembershipId: "membership-1",
      providerKey: "ipindia-registry", acceptProviderTerms: true,
      renewalReminderCadenceDays: 2, renewalReminderDeliveryTime: "14:45",
    }));
    expect(configuration).toEqual(before);
    expect(enableIpWorkspaceMock).not.toHaveBeenCalled();
    expect(runIpWorkspaceTestMock).not.toHaveBeenCalled();
  });

  it("hydrates untouched configuration fields and consent when current configuration arrives asynchronously", async () => {
    fetchIpWorkspaceReadinessMock.mockResolvedValue(setupReadiness());
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><IpDocketPage /></QueryClientProvider>);
    const card = await screen.findByTestId("ip-workspace-configuration");
    expect(within(card).getByLabelText("Office")).toHaveValue("IP India");
    const configuration = renewalConfiguration({ jurisdictions_json: ["GB", "IN"], offices_json: ["UK IPO", "IP India"] });
    await act(async () => client.setQueryData(["ip", "readiness"], setupReadiness(configuration)));
    await waitFor(() => expect(within(card).getByLabelText("Jurisdiction")).toHaveValue("GB"));
    expect(within(card).getByLabelText("Office")).toHaveValue("UK IPO");
    expect(within(card).getByLabelText("IANA timezone")).toHaveValue("Europe/London");
    expect(within(card).getByLabelText("Holiday calendar")).toHaveValue("reviewed-calendar");
    expect(within(card).getByLabelText("Permitted registry provider")).toHaveValue("ipindia-registry");
    expect(within(card).getByLabelText(/Accept provider attribution and cost terms/)).toBeChecked();
    expect(within(card).getByLabelText("Renewal reminder cadence (days)")).toHaveValue(7);
    expect(within(card).getByLabelText("Renewal reminder local time")).toHaveValue("14:45");
  });

  it("requires explicit consent after provider identity changes, even when returning to the previously accepted provider", async () => {
    const readiness = setupReadiness(renewalConfiguration());
    fetchIpWorkspaceReadinessMock.mockResolvedValue(readiness);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><IpDocketPage /></QueryClientProvider>);
    const card = await screen.findByTestId("ip-workspace-configuration");
    const provider = within(card).getByLabelText("Permitted registry provider");
    const consent = within(card).getByLabelText(/Accept provider attribution and cost terms/);
    expect(provider).toHaveValue("ipindia-registry");
    expect(consent).toBeChecked();
    await userEvent.selectOptions(provider, "");
    expect(consent).not.toBeChecked();
    expect(consent).toBeDisabled();
    await userEvent.selectOptions(provider, "ipindia-registry");
    await act(async () => client.setQueryData(["ip", "readiness"], { ...readiness }));
    expect(consent).not.toBeChecked();
    expect(consent).toBeEnabled();
    expect(within(card).getByRole("button", { name: "Save configuration" })).toBeDisabled();
    expect(saveIpWorkspaceConfigurationMock).not.toHaveBeenCalled();
  });

  it("does not infer acceptance for an existing provider without a recorded terms version", async () => {
    fetchIpWorkspaceReadinessMock.mockResolvedValue(setupReadiness(renewalConfiguration({ provider_terms_version: null })));
    render(withClient(<IpDocketPage />));
    const card = await screen.findByTestId("ip-workspace-configuration");
    expect(within(card).getByLabelText(/Accept provider attribution and cost terms version not configured/)).not.toBeChecked();
    expect(within(card).getByRole("button", { name: "Save configuration" })).toBeDisabled();
    expect(saveIpWorkspaceConfigurationMock).not.toHaveBeenCalled();
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

    const continuityHeading = await screen.findByRole("heading", {
      name: "Deadline continuity",
    });
    const continuityCard = continuityHeading.parentElement?.parentElement;
    expect(continuityCard).not.toBeNull();
    expect(
      await within(continuityCard!).findByText((_content, element) =>
        Boolean(
          element?.classList.contains("font-semibold") &&
            element.textContent ===
              "Responsible: Priya Raghavan — priya@example.com",
        ),
      ),
    ).toBeVisible();
    expect(await screen.findByRole("button", { name: "Discover Matter evidence" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Accept and link" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reject" })).toBeVisible();
    // 2026-08-15: a routine transfer is a proposal, so the control offers the
    // work rather than claiming it moved.
    expect(screen.getByRole("button", { name: "Offer covered deadlines" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Add recordal obligation" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reconcile with Matter billing" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Open incident" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Preview lifecycle impact" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Apply lifecycle transition" })).toBeVisible();

    await userEvent.click(screen.getByRole("tab", { name: "Proceedings" }));
    expect(screen.getByRole("button", { name: "Preview prosecution event" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Record prosecution event" })).toBeVisible();

    await userEvent.click(
      screen.getByRole("tab", { name: "Hearings and deadlines" }),
    );
    expect(screen.getByRole("button", { name: "Calculate deadline proposal" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Propose calendar version" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Propose rule and fixture" })).toBeVisible();
    const hearingWorkflow = screen.getByTestId("ip-hearing-workflow");
    expect(within(hearingWorkflow).getByLabelText("Hearing date")).toBeVisible();
    expect(within(hearingWorkflow).getByLabelText("Time precision")).toBeVisible();
    expect(within(hearingWorkflow).getByLabelText("Virtual hearing link")).toBeVisible();
    expect(within(hearingWorkflow).getByLabelText("Reminder offsets")).toBeVisible();
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

    await userEvent.click(screen.getByRole("tab", { name: "Documents" }));
    const documentWorkspace = await screen.findByTestId("ip-document-workspace");
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

  // IPLF-039F / UJ-52-EXC-01, EXC-04, EXC-05. The cost card used to replace its
  // whole form with "Cost items require a linked Matter" whenever the record had
  // no billing owner, so the surface that is supposed to preserve an already-paid
  // official fee offered no way to record one. It must now offer the nonbillable
  // capture, and it must not render a withheld rate as an amount.
  it("offers nonbillable capture on a record with no Matter and withholds confidential rates", async () => {
    fetchIpDocketsMock.mockResolvedValue({
      dockets: [{
        id: "ip-1", company_id: "company-1", matter_id: null, record_type: "trademark",
        title: "CASEOPS", primary_identifier: "TM-1", status: "active", restricted: false,
        is_active: true, lifecycle_version: 0, access_policy_version: 0, lifecycle_effective_at: null,
        lifecycle_reason: null, lifecycle_outcome: null, lifecycle_source: null,
        lifecycle_evidence_ref: null, successor_docket_id: null,
        current_version: 1, created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
        current_particulars: { form_key: "TM-A", form_version: "2026.1", readiness_status: "ready", classes_json: [{ class_number: 9, specification: "Software" }] },
        notice_links: [], deadline_incidents: [], title_interests: [], related_right_obligations: [],
        evidence_candidates: [], deadline_coverages: [],
        cost_items: [
          {
            id: "cost-1", matter_id: null, category: "official_fee",
            description: "Official filing fee paid before a billing Matter existed.",
            amount_minor: 900000, currency: "INR", billable: false, cost_nature: "actual",
            rate_confidential: false, amount_withheld: false,
            fx_rate: null, fx_rate_source: null, fx_converted_at: null,
            base_amount_minor: null, base_currency: null,
            evidence_reference: "receipt:registry-fee-unbilled-2026",
            billing_link_type: null, billing_link_id: null,
            reconciliation_status: "nonbillable" as const,
            canonical_amount_minor: null, reconciliation_difference_minor: null, reconciled_at: null,
            lineage_status: "active" as const, corrects_cost_item_id: null,
            replacement_cost_item_id: null, correction_reason: null,
            correction_evidence_reference: null,
          },
          {
            id: "cost-2", matter_id: null, category: "associate_fee",
            description: "Negotiated associate rate.",
            amount_minor: null, currency: "USD", billable: false, cost_nature: "estimate",
            rate_confidential: true, amount_withheld: true,
            fx_rate: null, fx_rate_source: null, fx_converted_at: null,
            base_amount_minor: null, base_currency: null,
            evidence_reference: "attachment:confidential-fee-agreement-2026",
            billing_link_type: null, billing_link_id: null,
            reconciliation_status: "nonbillable" as const,
            canonical_amount_minor: null, reconciliation_difference_minor: null, reconciled_at: null,
            lineage_status: "active" as const, corrects_cost_item_id: null,
            replacement_cost_item_id: null, correction_reason: null,
            correction_evidence_reference: null,
          },
        ],
      }],
      count: 1,
    });
    fetchIpDocumentsMock.mockResolvedValue({ items: [], total: 0 });

    render(withClient(<IpDocketPage />));

    // The capture the old surface refused is now the offered action.
    expect(
      await screen.findByRole("button", { name: "Add nonbillable cost evidence" }),
    ).toBeVisible();
    expect(
      screen.getByText(/captured as\s+nonbillable evidence/i),
    ).toBeVisible();
    expect(
      screen.getByText(/cannot create an invoice, invoice line, payment\s+attempt, or collection/i),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Verify nonbillable evidence" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Reconcile with Matter billing" }),
    ).toBeNull();
    expect(screen.queryByLabelText("Matter billing link type")).toBeNull();
    expect(screen.queryByLabelText("Matter billing record ID")).toBeNull();

    // A withheld rate reads as withheld. Rendering 0.00 would be undetectable.
    expect(
      screen.getByText(/Amount withheld — requires fee-management access/),
    ).toBeVisible();
    expect(screen.queryByText("USD 0.00")).toBeNull();

    // Status and nature are words, not colour alone.
    expect(
      within(screen.getByTestId("ip-cost-item-cost-2")).getByText(
        /Nonbillable · Provider estimate/,
      ),
    ).toBeVisible();
    expect(
      within(screen.getByTestId("ip-cost-item-cost-1")).getByText("Nonbillable", {
        exact: true,
      }),
    ).toBeVisible();
    // The non-confidential cost on the same record is unaffected.
    expect(screen.getByText("INR 9000.00")).toBeVisible();
    expect(screen.getByText(/Evidence: receipt:registry-fee-unbilled-2026/)).toBeVisible();

    // Corrections are a real append-only action, not an instruction to edit a
    // supposedly immutable row elsewhere. The full replacement is sent with
    // the source identity and independent correction evidence.
    const officialFee = screen.getByTestId("ip-cost-item-cost-1");
    fireEvent.click(within(officialFee).getByRole("button", { name: "Correct or void" }));
    expect(within(officialFee).getByText(/original cost and evidence never change/i)).toBeVisible();
    expect(within(officialFee).getByText(/rather than copied silently/i)).toBeVisible();
    fireEvent.change(within(officialFee).getByLabelText("Corrected category"), {
      target: { value: "disbursement" },
    });
    fireEvent.change(within(officialFee).getByLabelText("Correction reason"), {
      target: { value: "Registry receipt corrected the transposed amount." },
    });
    fireEvent.change(within(officialFee).getByLabelText("Correction evidence reference"), {
      target: { value: "registry-correction:2026-08-30" },
    });
    fireEvent.change(within(officialFee).getByLabelText("Corrected amount (INR)"), {
      target: { value: "8500.00" },
    });
    fireEvent.change(within(officialFee).getByLabelText("Corrected currency"), {
      target: { value: "USD" },
    });
    fireEvent.change(within(officialFee).getByLabelText("Corrected cost nature"), {
      target: { value: "estimate" },
    });
    fireEvent.click(within(officialFee).getByLabelText("Corrected rate is confidential"));
    expect(
      within(officialFee).getByLabelText("Replacement includes an exchange conversion"),
    ).toBeVisible();
    fireEvent.change(within(officialFee).getByLabelText("Replacement evidence reference"), {
      target: { value: "receipt:registry-fee-corrected-2026" },
    });
    fireEvent.click(within(officialFee).getByRole("button", { name: "Append corrected cost" }));
    await waitFor(() => expect(correctIpCostItemMock).toHaveBeenCalledTimes(1));
    expect(correctIpCostItemMock).toHaveBeenCalledWith("ip-1", "cost-1", {
      action: "supersede",
      reason: "Registry receipt corrected the transposed amount.",
      correctionEvidenceReference: "registry-correction:2026-08-30",
      replacement: expect.objectContaining({
        description: "Official filing fee paid before a billing Matter existed.",
        amountMinor: 850000,
        category: "disbursement",
        currency: "USD",
        billable: false,
        costNature: "estimate",
        rateConfidential: true,
        billingLinkType: null,
        billingLinkId: null,
        evidenceReference: "receipt:registry-fee-corrected-2026",
      }),
    });
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
      eligible_rule_version_ids: ["rule-1", "rule-2"],
      eligible_responsible_membership_ids: ["member-1", "member-2"],
      rules: [
        { id: "rule-1", key: "in-tm-response", version: 1, status: "active", source_reference: "https://official.example/ip-india/tm-rules" },
        { id: "rule-2", key: "in-tm-alternate", version: 2, status: "active", source_reference: "https://official.example/ip-india/tm-rules-alternate" },
      ],
      calendars: [{ id: "calendar-1", key: "ip-india", name: "IP India calendar", version: 1, status: "active", source_reference: "https://official.example/ip-india/calendar/2026", timezone: "Asia/Kolkata", weekend_days: [5, 6], holidays: [], exceptional_working_days: [], source_hash: "a".repeat(64) }],
      deadlines: [{
        id: "legal-deadline-1", docket_id: "ip-1", trigger_event_id: null,
        rule_version_id: "rule-1", calendar_version_id: "calendar-1", matter_deadline_id: null,
        supersedes_deadline_id: null, deadline_kind: "legal_deadline", title: "Respond to examination report",
        trigger_kind: "examination_report_received", base_date: "2026-08-14", date_precision: "date",
        certainty: "conflicting", result_on: null, calculation_inputs: {}, calculation_trace: [],
        explanation: "One business day after the verified source date; confirmation remains required.",
        rule_citation: "Trade Marks Rules", engine_version: "caseops-ip-deadline-v1",
        source_version: "source-v1", is_critical: true, state: "candidate", version: 1,
        confirmed_at: null, override_reason: null, override_evidence_ref: null,
        completed_evidence_ref: null, created_at: "2026-08-09T00:00:00Z",
        updated_at: "2026-08-09T00:00:00Z", responsibilities: [],
      }],
      exceptions: [{ deadline_id: "legal-deadline-1", docket_id: "ip-1", exception_kinds: ["unowned", "unacknowledged"], critical: true, result_on: "2026-08-18", visible: true }],
      automation_state: "explicit_confirmation_only", governance: availableGovernance(),
    });

    render(withClient(<IpDocketPage />));

    expect(fetchIpDeadlineWorkspaceMock).not.toHaveBeenCalled();
    await userEvent.click(
      await screen.findByRole("tab", { name: "Hearings and deadlines" }),
    );
    const deadlineWorkspace = await screen.findByTestId("ip-deadline-workspace");
    expect(await within(deadlineWorkspace).findByText("Exception queue")).toBeVisible();
    // Readable labels and the deadline's title, never raw codes or ids.
    expect(within(deadlineWorkspace).getByText("No responsible lawyer · Owner has not accepted")).toBeVisible();
    expect(within(deadlineWorkspace).getByText(/Respond to examination report · 2026-08-18/)).toBeVisible();
    expect(within(deadlineWorkspace).queryByText(/deadline legal-deadline-1/)).not.toBeInTheDocument();
    // 2026-08-16: these were free-text boxes demanding a membership UUID. They
    // are now pickers, so the assertion is that a lawyer can name a colleague.
    const primary = within(deadlineWorkspace).getByLabelText("Responsible lawyer");
    expect(primary).toBeVisible();
    expect(within(primary).getByRole("option", { name: /Priya Raghavan/ })).toBeInTheDocument();
    expect(within(deadlineWorkspace).getByLabelText("Backup")).toBeVisible();
    expect(within(deadlineWorkspace).getByLabelText("Evidence reference")).toBeVisible();
    const confirm = within(deadlineWorkspace).getByRole("button", { name: "Confirm legal deadline" });
    expect(confirm).toBeVisible();
    expect(confirm).toBeDisabled();
    expect(within(deadlineWorkspace).getByRole("button", { name: "Calculate deadline proposal" })).toBeVisible();
    expect(within(deadlineWorkspace).getByRole("link", { name: /Open verified rule source/ })).toHaveAttribute(
      "href",
      "https://official.example/ip-india/tm-rules",
    );
    fireEvent.click(within(deadlineWorkspace).getByRole("button", { name: "View calculation provenance" }));
    const provenance = await within(deadlineWorkspace).findByTestId("ip-deadline-provenance-legal-deadline-1");
    expect(await within(provenance).findByText(/Manual base date/)).toBeVisible();
    expect(within(provenance).getByText(/extension application alone does not move the legal date/i)).toBeVisible();
    const conflict = within(deadlineWorkspace).getByTestId(
      "ip-deadline-rule-conflict-legal-deadline-1",
    );
    expect(within(conflict).getByText(/blocks confirmation/)).toBeVisible();
    expect(within(conflict).getByText(/in-tm-response v1/)).toBeVisible();
    expect(within(conflict).getByText(/in-tm-alternate v2/)).toBeVisible();

    fireEvent.change(within(deadlineWorkspace).getByLabelText("Backup"), {
      target: { value: "member-2" },
    });
    fireEvent.change(within(deadlineWorkspace).getByLabelText("Corrected / override date"), {
      target: { value: "2026-08-18" },
    });
    fireEvent.change(within(deadlineWorkspace).getByLabelText("Action reason"), {
      target: { value: "Independent review resolved competing official sources." },
    });
    fireEvent.change(within(deadlineWorkspace).getByLabelText("Evidence reference"), {
      target: { value: "attachment:source-conflict-resolution" },
    });
    expect(confirm).toBeEnabled();
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

    await userEvent.click(await screen.findByRole("tab", { name: "Proceedings" }));
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

    await userEvent.click(screen.getByRole("tab", { name: "Overview" }));
    const lifecycle = await screen.findByTestId("ip-lifecycle-workflow");
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

  it("keeps a prosecution application's complete caption outside its accessible field name", async () => {
    fetchIpDocketsMock.mockResolvedValue({ dockets: [activeDocket()], count: 1 });
    const office = `Registry ${"long-source-".repeat(15)}`;
    fetchIpCoreRecordsMock.mockResolvedValue({ assets: [], proceedings: [], identifiers: [], applications: [
      { id: "application-1", version: 1, jurisdiction: "IN", office, filing_phase: "response_filed" },
      { id: "application-2", version: 1, jurisdiction: "IN", office, filing_phase: "response_filed" },
    ] });
    render(withClient(<IpDocketPage />));
    await userEvent.click(await screen.findByRole("tab", { name: "Proceedings" }));
    const prosecution = await screen.findByTestId("ip-prosecution-workspace");
    const select = await within(prosecution).findByRole<HTMLSelectElement>("combobox", { name: "Application" });
    expect(select).toHaveValue("application-1");
    expect(select).toHaveAccessibleName("Application");
    expect(select).toHaveAccessibleDescription(`IN · ${office} · response_filed`);
    fireEvent.change(select, { target: { value: "application-2" } });
    expect(select.selectedOptions[0].value).toBe("application-2");
    const detail = document.getElementById(select.getAttribute("aria-describedby")!);
    expect(detail).toHaveAttribute("data-selected-option-value", "application-2");
    expect(detail?.textContent).toBe(select.selectedOptions[0].textContent);
    expect(detail?.closest("label")).toBeNull();
    expect(appendIpDocketEventMock).not.toHaveBeenCalled();
  });

  it("requires backdated acknowledgement before committing a correction", async () => {
    fetchIpDocketsMock.mockResolvedValue({ dockets: [activeDocket()], count: 1 });
    fetchIpCoreRecordsMock.mockResolvedValue({
      assets: [], proceedings: [], identifiers: [],
      applications: [{
        id: "application-1", version: 4, jurisdiction: "IN",
        office: "Trade Marks Registry Mumbai", filing_phase: "response_filed",
      }],
    });
    fetchIpProsecutionWorkspaceMock.mockResolvedValue({
      docket_id: "ip-1", lifecycle_status: "active", lifecycle_version: 0,
      current_phase: "response_filed", registry_freshness: "current",
      data_quality_gaps: [], unconfirmed_deadline_refs: [], conflicting_event_ids: [],
      events: [prosecutionEvent()], operational_completion_count: 1,
      filing_evidence_count: 0, registry_acceptance_count: 0, final_disposition_count: 0,
    });
    previewIpDocketEventMock.mockResolvedValue({
      docket_id: "ip-1", lifecycle_version: 0, current_phase: "response_filed",
      proposed_phase: "formalities", backdated: true, recalculation_required: true,
      duplicate_candidate_ids: [], checklist: [],
      unresolved_exception_codes: ["backdated_recalculation_review_required"],
      operational_effects_are_proposals: true, filing_claimed: false,
    });

    render(withClient(<IpDocketPage />));
    await userEvent.click(await screen.findByRole("tab", { name: "Proceedings" }));
    const prosecution = await screen.findByTestId("ip-prosecution-workspace");
    fireEvent.click(await within(prosecution).findByRole("button", { name: "Correct event" }));
    fireEvent.change(within(prosecution).getByLabelText("Correction reason"), {
      target: { value: "The official record corrects the event classification." },
    });
    fireEvent.click(within(prosecution).getByRole("button", { name: "Preview prosecution event" }));
    await waitFor(() =>
      expect(previewIpDocketEventMock).toHaveBeenCalledWith(
        "ip-1",
        expect.objectContaining({ supersedesEventId: "event-1" }),
      ),
    );
    const record = within(prosecution).getByRole("button", { name: "Record prosecution event" });
    expect(record).toBeDisabled();
    fireEvent.click(within(prosecution).getByRole("checkbox", { name: /reviewed the recalculation preview/i }));
    expect(record).toBeEnabled();
    fireEvent.click(record);
    await waitFor(() =>
      expect(appendIpDocketEventMock).toHaveBeenCalledWith(
        "ip-1",
        expect.objectContaining({
          supersedesEventId: "event-1",
          acknowledgedExceptionCodes: ["backdated_recalculation_review_required"],
        }),
      ),
    );
  });

  it("previews and commits an explicit registry-candidate reconciliation", async () => {
    fetchIpDocketsMock.mockResolvedValue({ dockets: [activeDocket()], count: 1 });
    fetchIpCoreRecordsMock.mockResolvedValue({
      assets: [], proceedings: [], identifiers: [],
      applications: [{
        id: "application-1", version: 4, jurisdiction: "IN",
        office: "Trade Marks Registry Mumbai", filing_phase: "formalities",
      }],
    });
    fetchIpProsecutionWorkspaceMock.mockResolvedValue({
      docket_id: "ip-1", lifecycle_status: "active", lifecycle_version: 0,
      current_phase: "formalities", registry_freshness: "candidate_pending",
      data_quality_gaps: [], unconfirmed_deadline_refs: [], conflicting_event_ids: [],
      events: [prosecutionEvent({
        id: "candidate-1", source: "registry", source_reference: "ipindia:snapshot-1",
        candidate_status: "candidate", reason: null,
      })], operational_completion_count: 0, filing_evidence_count: 0,
      registry_acceptance_count: 0, final_disposition_count: 0,
    });

    render(withClient(<IpDocketPage />));
    await userEvent.click(await screen.findByRole("tab", { name: "Proceedings" }));
    const prosecution = await screen.findByTestId("ip-prosecution-workspace");
    fireEvent.click(await within(prosecution).findByRole("button", { name: "Reconcile candidate" }));
    fireEvent.click(within(prosecution).getByRole("button", { name: "Preview prosecution event" }));
    await waitFor(() =>
      expect(previewIpDocketEventMock).toHaveBeenCalledWith(
        "ip-1",
        expect.objectContaining({
          source: "registry",
          sourceReference: "ipindia:snapshot-1",
          reconcilesEventId: "candidate-1",
          reconciliationDecision: "same_fact",
        }),
      ),
    );
    fireEvent.click(within(prosecution).getByRole("button", { name: "Record prosecution event" }));
    await waitFor(() =>
      expect(appendIpDocketEventMock).toHaveBeenCalledWith(
        "ip-1",
        expect.objectContaining({ reconcilesEventId: "candidate-1" }),
      ),
    );
  });

  it("maps the complete restricted incident review journey", async () => {
    fetchIpDocketsMock.mockResolvedValue({
      dockets: [{
        id: "ip-1", company_id: "company-1", matter_id: "matter-1", record_type: "trademark",
        title: "CASEOPS", primary_identifier: "TM-1", status: "active", restricted: true,
        is_active: true, lifecycle_version: 0, access_policy_version: 0, lifecycle_effective_at: null,
        lifecycle_reason: null, lifecycle_outcome: null, lifecycle_source: null,
        lifecycle_evidence_ref: null, successor_docket_id: null, current_version: 1,
        created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z",
        current_particulars: { form_key: "TM-A", form_version: "2026.1", readiness_status: "ready", classes_json: [] },
        notice_links: [], title_interests: [], cost_items: [], related_right_obligations: [],
        evidence_candidates: [], deadline_coverages: [],
        deadline_incidents: [{
          id: "incident-1", matter_deadline_id: null, severity: "critical",
          summary: "Shared deadline rule may be defective", impact_json: {},
          evidence_snapshot_json: { rule_version_refs: ["rule:v7"] },
          preservation_manifest_sha256: "a".repeat(64), defect_scope: "platform_wide",
          defect_fingerprint_sha256: "b".repeat(64), containment: "Automation paused",
          correction_deadline_id: null, status: "impact_assessed",
          impact_scan_completed_at: "2026-08-21T00:00:00Z", corrective_action: null,
          root_cause: null, preventive_action: null, prevention_verified_at: null,
          resolution_evidence_reference: null, resolved_at: null, verified_at: null,
          version: 3, created_at: "2026-08-21T00:00:00Z",
          impacts: [{ id: "impact-1", record_type: "trademark_application", record_reference_sha256: "c".repeat(64), relationship: "same rule", assessment: "affected", scan_method: "fingerprint", evidence_reference: "scan:1", assessed_by_membership_id: "membership-1", assessed_at: "2026-08-21T00:00:00Z" }],
          actions: [{ id: "action-1", action_type: "containment", action_status: "completed", action_reference: "task:1", details: "Automation paused", evidence_reference: "action:1", recorded_by_membership_id: "membership-1", recorded_at: "2026-08-21T00:00:00Z" }],
          notification_decisions: [{ id: "decision-1", recipient_type: "client", recipient_reference_sha256: "d".repeat(64), decision: "pending", decision_version: 1, rationale: "Partner review pending", approval_evidence_reference: "approval:1", communication_reference: null, decided_by_membership_id: "membership-1", decided_at: "2026-08-21T00:00:00Z" }],
          kill_switches: [{ id: "switch-1", feature_id: "deadline_automation", status: "active", reason: "Shared defect", activation_evidence_reference: "stop:1", release_reason: null, release_evidence_reference: null, version: 1 }],
        }],
      }],
      count: 1,
    });

    render(withClient(<IpDocketPage />));

    const workspace = await screen.findByTestId("ip-incident-workspace");
    expect(within(workspace).getByRole("option", { name: /Shared deadline rule may be defective/ })).toBeInTheDocument();
    expect(within(workspace).getByText("Affected records")).toBeVisible();
    expect(within(workspace).getByRole("button", { name: "Actions" })).toBeVisible();
    expect(within(workspace).getByRole("button", { name: "Impact" })).toBeVisible();
    expect(within(workspace).getByRole("button", { name: "Recipients" })).toBeVisible();
    expect(within(workspace).getByRole("button", { name: "Resolution" })).toBeVisible();
    expect(within(workspace).getByRole("button", { name: "Record action" })).toBeDisabled();

    fireEvent.click(within(workspace).getByRole("button", { name: "Impact" }));
    expect(within(workspace).getByLabelText("Record reference")).toBeVisible();
    expect(within(workspace).getByRole("button", { name: "Record impact" })).toBeDisabled();
    fireEvent.click(within(workspace).getByRole("button", { name: "Recipients" }));
    expect(within(workspace).getByLabelText("Private recipient reference")).toBeVisible();
    expect(within(workspace).getByRole("button", { name: "Record recipient decision" })).toBeDisabled();
    fireEvent.click(within(workspace).getByRole("button", { name: "Resolution" }));
    expect(within(workspace).getByLabelText("Root cause")).toBeVisible();
    expect(within(workspace).getByRole("button", { name: "Resolve incident" })).toBeDisabled();
    expect(within(workspace).getByRole("button", { name: "Release deadline automation" })).toBeDisabled();

    fireEvent.click(within(workspace).getByRole("button", { name: "Open another incident" }));
    expect(within(workspace).getByLabelText("Defect scope")).toBeVisible();
    expect(within(workspace).getByRole("button", { name: "Open incident" })).toBeDisabled();
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
    await waitFor(() =>
      expect(screen.queryByTestId("ip-coverage-decisions")).toBeNull(),
    );
  });

  it("keeps a deep-linked decision surface visible while the query is loading", async () => {
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    const scrollIntoView = vi.fn();
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    window.history.replaceState(null, "", "/app/ip#coverage-decisions");
    fetchIpDocketsMock.mockResolvedValue({ dockets: [AWAITING_DOCKET], count: 1 });
    fetchIpCoverageTransfersAwaitingMeMock.mockReturnValue(new Promise(() => {}));

    try {
      render(withClient(<IpDocketPage />));

      const card = await screen.findByTestId("ip-coverage-decisions");
      expect(card).toHaveAttribute("id", "coverage-decisions");
      const loader = within(card).getByTestId("ip-coverage-decisions-loading");
      expect(loader).toHaveAttribute("role", "status");
      expect(loader).toHaveAttribute("aria-busy", "true");
      expect(within(loader).getByText("Loading coverage decisions.")).toHaveClass("sr-only");
      await waitFor(() =>
        expect(scrollIntoView).toHaveBeenCalledWith({ block: "start" }),
      );
    } finally {
      if (originalScrollIntoView) {
        HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
      } else {
        delete (HTMLElement.prototype as { scrollIntoView?: unknown }).scrollIntoView;
      }
    }
  });

  it("shows a retryable decision error instead of a false empty band", async () => {
    fetchIpDocketsMock.mockResolvedValue({ dockets: [AWAITING_DOCKET], count: 1 });
    fetchIpCoverageTransfersAwaitingMeMock.mockRejectedValue(
      new Error("Coverage decisions unavailable"),
    );

    render(withClient(<IpDocketPage />));

    const card = await screen.findByTestId("ip-coverage-decisions");
    expect(await within(card).findByText("Could not load coverage decisions")).toBeVisible();
    const retry = within(card).getByRole("button", { name: "Try again" });
    expect(retry).toBeVisible();
    fireEvent.click(retry);
    await waitFor(() =>
      expect(fetchIpCoverageTransfersAwaitingMeMock).toHaveBeenCalledTimes(2),
    );
  });

  it("lets the named replacement accept a proposed transfer without writing prose", async () => {
    fetchIpDocketsMock.mockResolvedValue({ dockets: [AWAITING_DOCKET], count: 1 });
    fetchIpCoverageTransfersAwaitingMeMock.mockResolvedValue({ transfers: [PROPOSED_TRANSFER] });

    render(withClient(<IpDocketPage />));

    const band = await screen.findByTestId("ip-coverage-decisions");
    expect(band).toHaveAttribute("id", "coverage-decisions");
    // Enough to answer "can I hold this date?" without opening the record.
    expect(await within(band).findByText("ACME WORDMARK")).toBeVisible();
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

  it("scrolls to an asynchronously loaded coverage decision deep link", async () => {
    const originalScrollIntoView = HTMLElement.prototype.scrollIntoView;
    const scrollIntoView = vi.fn();
    HTMLElement.prototype.scrollIntoView = scrollIntoView;
    window.history.replaceState(null, "", "/app/ip#coverage-decisions");
    fetchIpDocketsMock.mockResolvedValue({ dockets: [AWAITING_DOCKET], count: 1 });
    fetchIpCoverageTransfersAwaitingMeMock.mockResolvedValue({
      transfers: [PROPOSED_TRANSFER],
    });

    try {
      render(withClient(<IpDocketPage />));

      await screen.findByTestId("ip-coverage-decisions");
      await waitFor(() =>
        expect(scrollIntoView).toHaveBeenCalledWith({ block: "start" }),
      );
    } finally {
      if (originalScrollIntoView) {
        HTMLElement.prototype.scrollIntoView = originalScrollIntoView;
      } else {
        delete (HTMLElement.prototype as { scrollIntoView?: unknown })
          .scrollIntoView;
      }
    }
  });

  it("requires a written reason before a decline is sent", async () => {
    fetchIpDocketsMock.mockResolvedValue({ dockets: [AWAITING_DOCKET], count: 1 });
    fetchIpCoverageTransfersAwaitingMeMock.mockResolvedValue({ transfers: [PROPOSED_TRANSFER] });

    render(withClient(<IpDocketPage />));

    const band = await screen.findByTestId("ip-coverage-decisions");
    fireEvent.click(await within(band).findByRole("button", { name: "Decline" }));

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
      await within(band).findByText(
        /You already hold this deadline\. Declining moves it to Anand Rao\./,
      ),
    ).toBeVisible();
  });
});
