import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

const {
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
  fetchIpDocket: fetchIpDocketMock,
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

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
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
    fetchIpDocketMock.mockResolvedValue(activeDocket());
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
    render(withClient(<IpDocketPage />));

    expect(await screen.findByText("No IP records yet")).toBeInTheDocument();
    const create = screen.getByRole("button", { name: "New trademark" });
    expect(create).toBeVisible();
    fireEvent.click(create);
    expect(screen.getByRole("heading", { name: "New trademark application" })).toBeVisible();
    expect(screen.getByLabelText("Word mark")).toBeVisible();
    expect(screen.getByRole("button", { name: "Create application" })).toBeDisabled();
  });

  it("renders a deep-linked docket without waiting for the full portfolio", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=ip-1");
    fetchIpDocketsMock.mockReturnValue(new Promise(() => {}));

    render(withClient(<IpDocketPage />));

    expect(await screen.findByTestId("ip-access-workspace")).toBeVisible();
    expect(fetchIpDocketMock).toHaveBeenCalledWith("ip-1");
    expect(
      await screen.findByText("Loading the rest of the portfolio…"),
    ).toBeVisible();
  });

  it("prioritizes a deep-linked docket before portfolio and document requests", async () => {
    window.history.replaceState(null, "", "/app/ip?docket=ip-1");
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

  it("creates a pre-filing application through one canonical command", async () => {
    createManualTrademarkApplicationMock.mockResolvedValue({
      docket: { id: "ip-created" },
      asset: { id: "asset-created" },
      application: { id: "application-created" },
      identifier: null,
      duplicate_candidates: [],
    });
    render(withClient(<IpDocketPage />));

    fireEvent.click(await screen.findByRole("button", { name: "New trademark" }));
    fireEvent.change(screen.getByLabelText("Docket title"), {
      target: { value: "Aster filing" },
    });
    fireEvent.change(screen.getByLabelText("Word mark"), {
      target: { value: "ASTER" },
    });
    fireEvent.change(screen.getByLabelText("Goods / services specification"), {
      target: { value: "Downloadable software" },
    });
    fireEvent.change(screen.getByLabelText("Applicant"), {
      target: { value: "Aster Applicant LLP" },
    });
    fireEvent.change(screen.getByLabelText("Representation evidence reference"), {
      target: { value: "attachment:aster" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create application" }));

    await waitFor(() =>
      expect(createManualTrademarkApplicationMock).toHaveBeenCalledTimes(1),
    );
    expect(createManualTrademarkApplicationMock).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Aster filing",
        assetTitle: "ASTER",
        filingPhase: "pre_filing",
        applicationNumber: null,
        sourcePendingIdentifierAllocation: false,
      }),
    );
  });

  it("confirms an unpublished hearing time and shows the reminder replacement chain", async () => {
    const hearing = unknownTimeHearing();
    fetchIpDocketsMock.mockResolvedValue({ dockets: [activeDocket()], count: 1 });
    fetchIpSharedHearingsMock.mockResolvedValue({ docket_id: "ip-1", hearings: [hearing] });
    updateIpSharedHearingMock.mockResolvedValue({
      ...hearing,
      time_status: "exact",
      hearing_time: "14:30:00",
      time_confirmation_required: false,
    });

    render(withClient(<IpDocketPage />));

    const workflow = await screen.findByTestId("ip-hearing-workflow");
    expect(await within(workflow).findByText(/Time confirmation pending/)).toBeVisible();
    expect(within(workflow).getByText("Superseded by generation 2")).toBeVisible();
    expect(within(workflow).getByText("Current schedule")).toBeVisible();

    const confirm = within(workflow).getByRole("button", {
      name: "Confirm published time",
    });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(workflow).getByLabelText("Published time for Opposition hearing"), {
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
    expect(fetchIpSharedHearingsMock).toHaveBeenCalledTimes(1);
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
            reconciliation_status: "estimate" as const,
            canonical_amount_minor: null, reconciliation_difference_minor: null, reconciled_at: null,
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

    // A withheld rate reads as withheld. Rendering 0.00 would be undetectable.
    expect(
      screen.getByText(/Amount withheld — requires fee-management access/),
    ).toBeVisible();
    expect(screen.queryByText("USD 0.00")).toBeNull();

    // Status and nature are words, not colour alone.
    expect(screen.getByText(/Estimate — not an expense/)).toBeVisible();
    expect(screen.getByText(/Nonbillable/)).toBeVisible();
    // The non-confidential cost on the same record is unaffected.
    expect(screen.getByText("INR 9000.00")).toBeVisible();
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
      automation_state: "explicit_confirmation_only",
    });

    render(withClient(<IpDocketPage />));

    const deadlineWorkspace = await screen.findByTestId("ip-deadline-workspace");
    expect(await within(deadlineWorkspace).findByText("Exception queue")).toBeVisible();
    expect(within(deadlineWorkspace).getByText("unowned Â· unacknowledged")).toBeVisible();
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
