import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  enableIpWorkspaceMock,
  fetchIpCoreRecordsMock,
  fetchIpDocketsMock,
  fetchIpProsecutionWorkspaceMock,
  fetchIpWorkspaceReadinessMock,
  previewIpDocketEventMock,
  previewIpDocketLifecycleMock,
  runIpWorkspaceTestMock,
  saveIpWorkspaceConfigurationMock,
  appendIpDocketEventMock,
  transitionIpDocketLifecycleMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  enableIpWorkspaceMock: vi.fn(),
  fetchIpCoreRecordsMock: vi.fn(),
  fetchIpDocketsMock: vi.fn(),
  fetchIpProsecutionWorkspaceMock: vi.fn(),
  fetchIpWorkspaceReadinessMock: vi.fn(),
  previewIpDocketEventMock: vi.fn(),
  previewIpDocketLifecycleMock: vi.fn(),
  runIpWorkspaceTestMock: vi.fn(),
  saveIpWorkspaceConfigurationMock: vi.fn(),
  appendIpDocketEventMock: vi.fn(),
  transitionIpDocketLifecycleMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchIpDockets: fetchIpDocketsMock,
  fetchIpCoreRecords: fetchIpCoreRecordsMock,
  fetchIpProsecutionWorkspace: fetchIpProsecutionWorkspaceMock,
  fetchIpWorkspaceReadiness: fetchIpWorkspaceReadinessMock,
  enableIpWorkspace: enableIpWorkspaceMock,
  runIpWorkspaceTest: runIpWorkspaceTestMock,
  saveIpWorkspaceConfiguration: saveIpWorkspaceConfigurationMock,
  createIpDocket: vi.fn(),
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
    fetchIpCoreRecordsMock.mockReset();
    fetchIpProsecutionWorkspaceMock.mockReset();
    fetchIpWorkspaceReadinessMock.mockReset();
    previewIpDocketEventMock.mockReset();
    previewIpDocketLifecycleMock.mockReset();
    appendIpDocketEventMock.mockReset();
    transitionIpDocketLifecycleMock.mockReset();
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
    fetchIpCoreRecordsMock.mockResolvedValue({ assets: [], applications: [], proceedings: [], identifiers: [] });
    fetchIpProsecutionWorkspaceMock.mockResolvedValue({
      docket_id: "ip-1", lifecycle_status: "active", lifecycle_version: 0,
      current_phase: "draft", registry_freshness: "not_configured",
      data_quality_gaps: [], unconfirmed_deadline_refs: [], conflicting_event_ids: [],
      events: [], operational_completion_count: 0, filing_evidence_count: 0,
      registry_acceptance_count: 0, final_disposition_count: 0,
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
        is_active: true, lifecycle_version: 0, lifecycle_effective_at: null,
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

    render(withClient(<IpDocketPage />));

    expect(await screen.findByRole("button", { name: "Discover Matter evidence" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Accept and link" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reject" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Transfer covered deadlines" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Add recordal obligation" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reconcile with Matter billing" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Preview prosecution event" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Record prosecution event" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Preview lifecycle impact" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Apply lifecycle transition" })).toBeVisible();
  });

  it("requires a current preview before recording an event or acknowledged lifecycle impact", async () => {
    fetchIpDocketsMock.mockResolvedValue({
      dockets: [{
        id: "ip-1", company_id: "company-1", matter_id: "matter-1", record_type: "trademark",
        title: "CASEOPS", primary_identifier: "TM-1", status: "active", is_active: true,
        lifecycle_version: 0, lifecycle_effective_at: null, lifecycle_reason: null,
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
});
