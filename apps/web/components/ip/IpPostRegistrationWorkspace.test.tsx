import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { actionMock, createMock, fetchCoreMock, fetchWorkspaceMock, saveMock } =
  vi.hoisted(() => ({
    actionMock: vi.fn(),
    createMock: vi.fn(),
    fetchCoreMock: vi.fn(),
    fetchWorkspaceMock: vi.fn(),
    saveMock: vi.fn(),
  }));

vi.mock("@/lib/api/endpoints", () => ({
  createIpPostRegistrationProceeding: createMock,
  fetchIpCoreRecords: fetchCoreMock,
  fetchIpPostRegistrationWorkspace: fetchWorkspaceMock,
  recordIpPostRegistrationAction: actionMock,
  saveIpPostRegistrationWorkspace: saveMock,
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { IpPostRegistrationWorkspace } from "@/components/ip/IpPostRegistrationWorkspace";

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
    created_at: "2026-08-24T00:00:00Z",
  },
  notice_links: [],
  evidence_candidates: [],
  deadline_coverages: [],
  deadline_incidents: [],
  title_interests: [],
  related_right_obligations: [],
  cost_items: [],
  created_at: "2026-08-24T00:00:00Z",
  updated_at: "2026-08-24T00:00:00Z",
};

const proceeding = {
  id: "rectification-1",
  docket_id: "docket-1",
  application_id: "application-1",
  proceeding_kind: "rectification",
  side: "claimant",
  office: "Trade Marks Registry Delhi",
  jurisdiction: "IN",
  stage: "draft",
  origin_kind: "registry_event",
  stage_template_version: "post-registration-rectification-v1",
  source_pending_identifier_allocation: false,
  version: 2,
  created_at: "2026-08-24T00:00:00Z",
  updated_at: "2026-08-24T00:00:00Z",
};

const profileEvent = {
  id: "profile-1",
  company_id: "company-1",
  docket_id: "docket-1",
  sequence: 1,
  application_id: null,
  proceeding_id: "rectification-1",
  event_kind: "post_registration_profile",
  source: "manual",
  source_reference: "registry:rectification:100",
  effective_at: "2026-08-24T08:00:00Z",
  entered_at: "2026-08-24T08:00:00Z",
  responsible_membership_id: "membership-1",
  entered_by_membership_id: "membership-1",
  reason: "Counsel confirmed the profile.",
  evidence_refs_json: [],
  document_refs_json: ["document:petition"],
  resulting_stage: null,
  resulting_deadline_refs_json: [],
  before_phase: "draft",
  after_phase: null,
  candidate_status: "confirmed",
  supersedes_event_id: null,
  correction_reason: null,
  reconciles_event_id: null,
  reconciliation_decision: null,
  payload_json: {},
  created_at: "2026-08-24T08:00:00Z",
};

const workspace = {
  proceeding,
  profile: {
    proceeding_type: "rectification",
    legal_basis: "Lawyer-confirmed rectification basis.",
    target_right_reference: "registration:100",
    applicant_name: "Claimant Brands Private Limited",
    respondent_name: "Registered Proprietor Limited",
    challenged_scope: [
      { class_number: 9, goods_services_segment: "Computer software" },
    ],
    grounds: ["Entry should be rectified."],
    forum: "Trade Marks Registry Delhi",
    form_key: "TM-O",
    fee_status: "paid",
    fee_reference: "fee:100",
    service_status: "served",
    service_reference: "service:100",
    rule_map: {
      template_key: "post-registration/rectification",
      template_version: "lawyer-reviewed-v1",
      authority_reference: "Trade Marks Act mapping",
      source_reference: "legal-source:100",
      mutatis_mutandis: false,
      mapped_from_rule: null,
      mapped_provisions: [],
      excluded_provisions: [],
      lawyer_confirmation: null,
    },
    lawyer_confirmed_by_membership_id: "membership-1",
  },
  profile_event: profileEvent,
  profile_revision_count: 1,
  identifiers: [
    {
      id: "identifier-1",
      docket_id: "docket-1",
      application_id: null,
      proceeding_id: "rectification-1",
      identifier_kind: "rectification",
      raw_value: "RECT-100",
      normalized_value: "rect100",
      office: "Trade Marks Registry Delhi",
      jurisdiction: "IN",
      source: "registry",
      effective_from: "2026-08-24",
      effective_until: null,
      is_primary: true,
      reconciliation_status: "confirmed",
      supersedes_identifier_id: null,
      superseded_by_identifier_id: null,
      correction_reason: null,
      created_at: "2026-08-24T00:00:00Z",
    },
  ],
  action_events: [],
  active_stay: false,
  ready_for_stage_progression: true,
  readiness_gaps: [],
  registration_disposition_is_automatic: false,
};

describe("IpPostRegistrationWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchCoreMock.mockResolvedValue({
      assets: [],
      applications: [
        {
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
          created_at: "2026-08-24T00:00:00Z",
          updated_at: "2026-08-24T00:00:00Z",
        },
      ],
      proceedings: [proceeding],
      identifiers: [],
    });
    fetchWorkspaceMock.mockResolvedValue(workspace);
    saveMock.mockResolvedValue(workspace);
    actionMock.mockResolvedValue(workspace);
    createMock.mockResolvedValue(proceeding);
  });

  it("saves the typed rule map and immutable profile fence", async () => {
    render(
      withClient(
        <IpPostRegistrationWorkspace
          docket={docket}
          canWrite
          canReview
          currentMembershipId="membership-1"
        />,
      ),
    );

    expect(await screen.findByText("RECT-100")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Record source"), {
      target: { value: "registry:rectification:100" },
    });
    fireEvent.change(screen.getAllByLabelText("Source documents")[0], {
      target: { value: "document:petition" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm profile" }));

    await waitFor(() => expect(saveMock).toHaveBeenCalledOnce());
    expect(saveMock).toHaveBeenCalledWith(
      expect.objectContaining({
        expectedProfileEventId: "profile-1",
        lifecycleVersion: 3,
        proceedingId: "rectification-1",
        proceedingVersion: 2,
        profile: expect.objectContaining({
          proceeding_type: "rectification",
          rule_map: expect.objectContaining({
            template_key: "post-registration/rectification",
          }),
        }),
      }),
      expect.any(Object),
    );
  });

  it("records a sourced interim stay without reusing an opposition action", async () => {
    render(
      withClient(
        <IpPostRegistrationWorkspace
          docket={docket}
          canWrite
          canReview
          currentMembershipId="membership-1"
        />,
      ),
    );

    await screen.findByText("RECT-100");
    fireEvent.change(screen.getByLabelText("Action"), {
      target: { value: "interim_stay" },
    });
    fireEvent.change(screen.getByLabelText("Source reference"), {
      target: { value: "court-order:stay:100" },
    });
    const sourceDocuments = screen.getAllByLabelText("Source documents");
    fireEvent.change(sourceDocuments[sourceDocuments.length - 1], {
      target: { value: "document:stay-order" },
    });
    fireEvent.change(screen.getByLabelText("Authority reference"), {
      target: { value: "Delhi High Court interim order" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Record action" }));

    await waitFor(() => expect(actionMock).toHaveBeenCalledOnce());
    expect(actionMock).toHaveBeenCalledWith(
      expect.objectContaining({
        actionKind: "interim_stay",
        authorityReference: "Delhi High Court interim order",
        documentRefs: ["document:stay-order"],
        proceedingId: "rectification-1",
        proceedingVersion: 2,
      }),
      expect.any(Object),
    );
  });
});
