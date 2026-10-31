import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { actionMock, createMock, fetchCoreMock, fetchIpNiceClassesMock, fetchWorkspaceMock, saveMock } =
  vi.hoisted(() => ({
    actionMock: vi.fn(),
    createMock: vi.fn(),
    fetchCoreMock: vi.fn(),
    fetchIpNiceClassesMock: vi.fn(),
    fetchWorkspaceMock: vi.fn(),
    saveMock: vi.fn(),
  }));

vi.mock("@/lib/api/endpoints", () => ({
  createIpPostRegistrationProceeding: createMock,
  fetchIpCoreRecords: fetchCoreMock,
  fetchIpNiceClasses: fetchIpNiceClassesMock,
  fetchIpPostRegistrationWorkspace: fetchWorkspaceMock,
  recordIpPostRegistrationAction: actionMock,
  saveIpPostRegistrationWorkspace: saveMock,
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { IpPostRegistrationWorkspace } from "@/components/ip/IpPostRegistrationWorkspace";

function niceCatalogue() {
  return {
    edition: "NCL 13-2026",
    in_force_from: "2026-01-01",
    source_url: "https://nclpub.wipo.int/enfr/?version=20260101",
    source_data_url: "https://www.wipo.int/classifications/data/nice/20260101.zip",
    retrieved_on: "2026-10-31",
    headings_sha256: "a".repeat(64),
    attribution: "Nice Classification, 13th edition, version 2026 (NCL 13-2026). Copyright World Intellectual Property Organization (WIPO).",
    classes: Array.from({ length: 45 }, (_, index) => ({
      number: index + 1,
      kind: index + 1 <= 34 ? "goods" : "services",
      heading: `Class ${index + 1} heading.`,
      note: null,
    })),
  };
}

async function chooseNiceClass(user: ReturnType<typeof userEvent.setup>, name: string, number: number) {
  const input = screen.getByRole("combobox", { name });
  await waitFor(() => expect(input).toBeEnabled());
  await user.click(input);
  await user.type(input, String(number));
  await user.click(within(screen.getByRole("listbox")).getByRole("option", { name: new RegExp(`^Class ${number}, `) }));
}

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
    fetchIpNiceClassesMock.mockResolvedValue(niceCatalogue());
    saveMock.mockResolvedValue(workspace);
    actionMock.mockResolvedValue(workspace);
    createMock.mockResolvedValue(proceeding);
  });

  it("describes current application/proceeding identities and keeps parallel self-exclusion", async () => {
    const core = await fetchCoreMock.getMockImplementation()!();
    fetchCoreMock.mockResolvedValue({ ...core, proceedings: [proceeding,
      { ...proceeding, id: "parallel-1", proceeding_kind: "opposition", stage: "hearing_pending" }],
    });
    render(withClient(<IpPostRegistrationWorkspace docket={docket} canWrite canReview currentMembershipId="membership-1" />));
    const application = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Target application" });
    await waitFor(() => expect(application).toHaveValue("application-1"));
    expect(application).toHaveAccessibleDescription("Trade Marks Registry Delhi · filed");
    const selected = screen.getByRole<HTMLSelectElement>("combobox", { name: "Selected proceeding" });
    expect(selected).toHaveValue(proceeding.id);
    expect(selected).toHaveAccessibleDescription("Rectification · draft");
    expect(document.getElementById(selected.getAttribute("aria-describedby")!))
      .toHaveAttribute("data-selected-option-value", proceeding.id);
    fireEvent.change(await screen.findByLabelText("Action"), { target: { value: "parallel_proceeding_link" } });
    const parallel = screen.getByRole<HTMLSelectElement>("combobox", { name: "Parallel proceeding" });
    expect(Array.from(parallel.options, option => option.value)).toEqual(["", "parallel-1"]);
    fireEvent.change(parallel, { target: { value: "parallel-1" } });
    expect(parallel.selectedOptions[0].value).toBe("parallel-1");
    expect(parallel).toHaveAccessibleDescription("Opposition · hearing_pending");
    fireEvent.change(parallel, { target: { value: "" } });
    expect(parallel.value).toBe("");
    expect(Array.from(parallel.selectedOptions, option => option.value)).toEqual([""]);
    expect(parallel).not.toHaveAttribute("aria-describedby");
    expect(actionMock).not.toHaveBeenCalled();
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

  it("BUG-002 needs a Nice class chosen from the catalogue before the profile can be confirmed", async () => {
    const user = userEvent.setup();
    fetchWorkspaceMock.mockResolvedValue({ ...workspace, profile: null, profile_event: null });
    render(withClient(<IpPostRegistrationWorkspace docket={docket} canWrite canReview currentMembershipId="membership-1" />));

    expect(await screen.findByText("RECT-100")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Record source"), { target: { value: "registry:rectification:100" } });
    fireEvent.change(screen.getAllByLabelText("Source documents")[0], { target: { value: "document:petition" } });
    const confirm = screen.getByRole("button", { name: "Confirm profile" });
    // No class is preselected, and an empty class is never sent as 0.
    expect(screen.getByRole("combobox", { name: "Class" })).toHaveValue("");
    expect(confirm).toBeDisabled();
    expect(screen.getByText("Choose the Nice class of the challenged goods or services.")).toBeVisible();

    await chooseNiceClass(user, "Class", 9);
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);
    await waitFor(() => expect(saveMock).toHaveBeenCalledOnce());
    expect(saveMock.mock.calls[0][0].profile.challenged_scope[0].class_number).toBe(9);
  });

  it("BUG-002 anchors a refused challenged class to the class field", async () => {
    const { ApiError } = await import("@/lib/api/config");
    saveMock.mockRejectedValue(new ApiError(422, "Profile › Challenged scope › Class number: Class 9 is not registered.", {
      errors: [{ loc: ["body", "profile", "challenged_scope", 0, "class_number"], type: "value_error",
        msg: "Class 9 is not registered." }],
    }));
    render(withClient(<IpPostRegistrationWorkspace docket={docket} canWrite canReview currentMembershipId="membership-1" />));

    expect(await screen.findByText("RECT-100")).toBeVisible();
    fireEvent.change(screen.getByLabelText("Record source"), { target: { value: "registry:rectification:100" } });
    fireEvent.change(screen.getAllByLabelText("Source documents")[0], { target: { value: "document:petition" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm profile" }));
    const field = screen.getByRole("combobox", { name: "Class" });
    await waitFor(() => expect(field).toHaveAttribute("aria-invalid", "true"));
    const described = (field.getAttribute("aria-describedby") ?? "").split(" ").map((id) => document.getElementById(id)?.textContent);
    expect(described).toContain("Class 9 is not registered.");
  });
});
