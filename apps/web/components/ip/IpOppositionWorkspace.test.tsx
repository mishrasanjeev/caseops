import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  createMock,
  fetchCoreMock,
  fetchWorkspaceMock,
  saveMock,
  transitionMock,
} = vi.hoisted(() => ({
  createMock: vi.fn(),
  fetchCoreMock: vi.fn(),
  fetchWorkspaceMock: vi.fn(),
  saveMock: vi.fn(),
  transitionMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createIpOppositionProceeding: createMock,
  fetchIpCoreRecords: fetchCoreMock,
  fetchIpOppositionWorkspace: fetchWorkspaceMock,
  saveIpOppositionWorkspace: saveMock,
  transitionIpOppositionStage: transitionMock,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock("@/components/ip/IpOppositionApplicantWorkflow", () => ({
  IpOppositionApplicantWorkflow: () => <div data-testid="applicant-workflow-stub" />,
}));

vi.mock("@/components/ip/IpOppositionOpponentWorkflow", () => ({
  IpOppositionOpponentWorkflow: () => <div data-testid="opponent-workflow-stub" />,
}));

vi.mock("@/components/ip/IpOppositionSharedWorkflow", () => ({
  IpOppositionSharedWorkflow: () => <div data-testid="shared-workflow-stub" />,
}));
vi.mock("@/components/ip/IpOppositionSpecializedPaths", () => ({
  IpOppositionSpecializedPaths: () => <div data-testid="specialized-paths-stub" />,
}));

vi.mock("@/components/ip/IpPleadingWorkspace", () => ({
  IpPleadingWorkspace: () => <div data-testid="pleading-workspace-stub" />,
}));

import { IpOppositionWorkspace } from "@/components/ip/IpOppositionWorkspace";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const docket = {
  id: "docket-1",
  company_id: "company-1",
  matter_id: "matter-1",
  record_type: "trademark",
  title: "ASTER",
  primary_identifier: "TM-APP-100",
  status: "active",
  is_active: true,
  lifecycle_version: 3,
  lifecycle_effective_at: null,
  lifecycle_reason: null,
  lifecycle_outcome: null,
  lifecycle_source: null,
  lifecycle_evidence_ref: null,
  successor_docket_id: null,
  restricted: false,
  access_policy_version: 0,
  current_version: 1,
  current_particulars: {
    id: "particulars-1",
    docket_id: "docket-1",
    version: 1,
    form_key: "TM-A",
    form_version: "2026.1",
    mark_kind: "word",
    representation_json: { text: "ASTER" },
    classes_json: [{ class_number: 9, specification: "Software" }],
    use_priority_json: null,
    parties_json: [],
    agent_json: null,
    filing_manifest_json: [],
    readiness_status: "ready",
    readiness_errors_json: [],
    finalized_at: null,
    created_at: "2026-08-23T00:00:00Z",
  },
  notice_links: [],
  evidence_candidates: [],
  deadline_coverages: [],
  deadline_incidents: [],
  title_interests: [],
  related_right_obligations: [],
  cost_items: [],
  created_at: "2026-08-23T00:00:00Z",
  updated_at: "2026-08-23T00:00:00Z",
};

const proceeding = {
  id: "opposition-1",
  docket_id: "docket-1",
  application_id: "application-1",
  proceeding_kind: "opposition",
  side: "applicant",
  office: "Trade Marks Registry Delhi",
  jurisdiction: "IN",
  stage: "draft",
  origin_kind: "registry_event",
  stage_template_version: "opposition-applicant-v1",
  source_pending_identifier_allocation: false,
  version: 2,
  created_at: "2026-08-23T00:00:00Z",
  updated_at: "2026-08-23T00:00:00Z",
};

const identifierBase = {
  id: "identifier-1",
  docket_id: "docket-1",
  normalized_value: "TMAPP100",
  office: "Trade Marks Registry Delhi",
  jurisdiction: "IN",
  source: "registry",
  effective_from: "2026-08-20",
  effective_until: null,
  is_primary: true,
  reconciliation_status: "confirmed",
  supersedes_identifier_id: null,
  superseded_by_identifier_id: null,
  correction_reason: null,
  created_at: "2026-08-20T00:00:00Z",
};

const event = {
  id: "profile-event-2",
  company_id: "company-1",
  docket_id: "docket-1",
  sequence: 2,
  application_id: null,
  proceeding_id: "opposition-1",
  event_kind: "opposition_profile",
  source: "manual",
  source_reference: "https://registry.example/opposition/200",
  effective_at: "2026-08-23T08:00:00Z",
  entered_at: "2026-08-23T08:00:00Z",
  responsible_membership_id: "membership-1",
  entered_by_membership_id: "membership-1",
  reason: "Lawyer confirmed the profile.",
  evidence_refs_json: ["evidence:notice"],
  document_refs_json: ["document:notice"],
  resulting_stage: null,
  resulting_deadline_refs_json: [],
  before_phase: "draft",
  after_phase: null,
  candidate_status: "confirmed",
  supersedes_event_id: "profile-event-1",
  correction_reason: "Corrected source facts.",
  reconciles_event_id: null,
  reconciliation_decision: null,
  payload_json: { opposition_profile_revision: true },
  created_at: "2026-08-23T08:00:00Z",
};

const workspace = {
  proceeding,
  profile: {
    applicable_rule_version: "trade-marks-rules-2017@2026-08-23",
    forum: "Trade Marks Registry Delhi",
    client_instruction_state: "not_required",
    client_instruction_reference: null,
    limitation_date: null,
    source_notice_reference: "notice:200",
    source_notice_document_ref: "document:notice",
    grounds: [{
      category: "bad_faith",
      lawyer_detail: "Counsel confirmed the pleaded bad-faith ground.",
      classification_source: "ai_assisted",
    }],
    challenged_scope: [{ class_number: 9, goods_services_segment: "Computer software" }],
    relied_on_rights: [],
    service: {
      method: "registry email",
      destination: "applicant@example.com",
      served_on: "2026-08-20",
      acknowledgement: null,
      defect: null,
      reservice_on: null,
      starts_response_period: true,
      evidence_refs: ["evidence:service"],
    },
    lawyer_confirmed_by_membership_id: "membership-1",
  },
  profile_event: event,
  profile_revision_count: 2,
  parties: [
    { id: "party-1", role: "applicant", party_name: "Applicant Ltd", source: "notice", effective_from: "2026-08-20", effective_until: null },
    { id: "party-2", role: "opponent", party_name: "Opponent LLP", source: "notice", effective_from: "2026-08-20", effective_until: null },
  ],
  application_identifiers: [{ ...identifierBase, application_id: "application-1", proceeding_id: null, identifier_kind: "application", raw_value: "TM-APP-100" }],
  opposition_identifiers: [{ ...identifierBase, id: "identifier-2", application_id: null, proceeding_id: "opposition-1", identifier_kind: "opposition", raw_value: "OPP-200" }],
  linked_matter_id: "matter-1",
  stage_events: [],
  ready_for_stage_progression: true,
  readiness_gaps: [],
};

describe("IpOppositionWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchCoreMock.mockResolvedValue({
      assets: [],
      applications: [{
        id: "application-1",
        docket_id: "docket-1",
        asset_id: "asset-1",
        office: "Trade Marks Registry Delhi",
        jurisdiction: "IN",
        filing_phase: "filed",
        is_active: true,
        lifecycle_version: 1,
        source_pending_identifier_allocation: false,
        version: 1,
        created_at: "2026-08-20T00:00:00Z",
        updated_at: "2026-08-20T00:00:00Z",
      }],
      proceedings: [proceeding],
      identifiers: workspace.application_identifiers,
    });
    fetchWorkspaceMock.mockResolvedValue(workspace);
    saveMock.mockResolvedValue(workspace);
    transitionMock.mockResolvedValue({ proceeding, event });
  });

  it("shows distinct registry identifiers and saves every optimistic fence", async () => {
    render(withClient(
      <IpOppositionWorkspace
        docket={docket}
        canWrite
        canReview
        currentMembershipId="membership-1"
      />,
    ));

    expect(await screen.findByText("TM-APP-100")).toBeVisible();
    expect(screen.getByText("OPP-200")).toBeVisible();
    expect(screen.getByRole("link", { name: "Open profile source" })).toHaveAttribute(
      "href",
      "https://registry.example/opposition/200",
    );
    expect(screen.getByDisplayValue("Counsel confirmed the pleaded bad-faith ground.")).toBeVisible();
    expect(screen.getByLabelText("Ground 1 classification source")).toHaveValue("ai_assisted");
    expect(screen.getByRole("button", { name: "Applicant" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Opponent" })).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(screen.getByRole("button", { name: "Save profile revision" }));
    await waitFor(() => expect(saveMock).toHaveBeenCalledOnce());
    expect(saveMock).toHaveBeenCalledWith(
      expect.objectContaining({
        docketId: "docket-1",
        proceedingId: "opposition-1",
        lifecycleVersion: 3,
        proceedingVersion: 2,
        expectedProfileEventId: "profile-event-2",
        responsibleMembershipId: "membership-1",
        grounds: [expect.objectContaining({ classification_source: "ai_assisted" })],
        challengedScope: [{ class_number: 9, goods_services_segment: "Computer software" }],
      }),
      expect.any(Object),
    );
  });

  it("keeps stage progression disabled when readiness is incomplete", async () => {
    fetchWorkspaceMock.mockResolvedValue({
      ...workspace,
      ready_for_stage_progression: false,
      readiness_gaps: ["confirmed_opposition_identifier_required", "service_fact_required"],
      opposition_identifiers: [],
    });
    render(withClient(
      <IpOppositionWorkspace
        docket={docket}
        canWrite
        canReview
        currentMembershipId="membership-1"
      />,
    ));

    expect(await screen.findByText("confirmed opposition identifier required")).toBeVisible();
    expect(screen.getByText("service fact required")).toBeVisible();
    expect(screen.getByRole("button", { name: "Apply stage" })).toBeDisabled();
  });

  it("refreshes both represented-side workflows after a stage transition", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const invalidate = vi.spyOn(client, "invalidateQueries");
    render(
      <QueryClientProvider client={client}>
        <IpOppositionWorkspace
          docket={docket}
          canWrite
          canReview
          currentMembershipId="membership-1"
        />
      </QueryClientProvider>,
    );

    fireEvent.change(await screen.findByLabelText("Reason"), {
      target: { value: "Counsel approved the next opposition stage." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Apply stage" }));
    await waitFor(() => expect(transitionMock).toHaveBeenCalledOnce());
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["ip", "opposition-opponent-workflow", "docket-1", "opposition-1"],
    }));
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ["ip", "opposition-applicant-workflow", "docket-1", "opposition-1"],
    });
  });
});
