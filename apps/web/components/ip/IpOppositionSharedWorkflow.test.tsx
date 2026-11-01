import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { createHearingMock, fetchWorkflowMock, recordActionMock, deadlineWorkspaceMock, listMattersMock, fetchMatterMock } = vi.hoisted(() => ({
  createHearingMock: vi.fn(),
  fetchWorkflowMock: vi.fn(),
  recordActionMock: vi.fn(),
  deadlineWorkspaceMock: vi.fn(),
  listMattersMock: vi.fn(),
  fetchMatterMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createIpSharedHearing: createHearingMock,
  fetchIpDeadlineWorkspace: deadlineWorkspaceMock,
  fetchIpOppositionSharedWorkflow: fetchWorkflowMock,
  recordIpOppositionSharedAction: recordActionMock,
  listMatters: listMattersMock,
  fetchMatter: fetchMatterMock,
  listCompanyUsers: vi.fn().mockResolvedValue({ users: [] }),
}));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { IpOppositionSharedWorkflow } from "@/components/ip/IpOppositionSharedWorkflow";

const docket = { id: "docket-43", lifecycle_version: 6 };
const workspace = {
  proceeding: {
    id: "opposition-43",
    application_id: "application-43",
    side: "applicant",
    stage: "applicant_evidence_due",
    office: "Trade Marks Registry Delhi",
    version: 8,
  },
  profile: { forum: "Trade Marks Registry Delhi" },
};

const baseWorkflow = {
  proceeding_id: "opposition-43",
  represented_side: "applicant",
  current_stage: "applicant_evidence_due",
  shared_actions: [],
  active_deadlines: [],
  shared_hearings: [],
  next_required_action: "record_evidence_package",
};

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderWorkflow() {
  return render(withClient(
    <IpOppositionSharedWorkflow
      docket={docket as never}
      workspace={workspace as never}
      canReview
      currentMembershipId="membership-43"
    />,
  ));
}

describe("IpOppositionSharedWorkflow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchWorkflowMock.mockResolvedValue(baseWorkflow);
    deadlineWorkspaceMock.mockResolvedValue({ eligible_responsible_membership_ids: [] });
    recordActionMock.mockResolvedValue(baseWorkflow);
    createHearingMock.mockResolvedValue({ id: "hearing-43" });
    listMattersMock.mockResolvedValue({
      matters: [{ id: "matter-appeal", matter_code: "APL-43", title: "Aster appeal", client_name: "Aster Holdings", status: "active" }],
      next_cursor: null,
    });
  });

  function fillCommon() {
    fireEvent.change(screen.getByLabelText("Source reference"), { target: { value: "registry:shared:43" } });
    fireEvent.change(screen.getByLabelText("Lawyer confirmation"), { target: { value: "Approved by responsible IP counsel" } });
    fireEvent.change(screen.getByLabelText("Evidence references"), { target: { value: "registry-pdf:43" } });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Counsel verified the shared opposition record." } });
  }

  it("B4-ADJ-22 never pre-selects a deadline, hearing or order and explains empty choices", async () => {
    fetchWorkflowMock.mockResolvedValue({
      ...baseWorkflow,
      current_stage: "hearing_scheduled",
      next_required_action: "record_hearing_preparation",
      shared_hearings: [
        { id: "hearing-done", hearing_on: "2026-10-01", forum_name: "Registry Delhi", status: "completed", purpose: "Hearing", time_status: "session" },
        { id: "hearing-next", hearing_on: "2026-10-20", forum_name: "Registry Delhi", status: "scheduled", purpose: "Hearing", time_status: "session" },
      ],
    });
    renderWorkflow();
    const hearing = await screen.findByLabelText<HTMLSelectElement>("Shared hearing");
    expect(hearing).toHaveValue("");
    // Preparation needs an active hearing: the completed one is listed but cannot be chosen.
    expect(Array.from(hearing.options).find((option) => option.value === "hearing-done")?.disabled).toBe(true);
    expect(Array.from(hearing.options).find((option) => option.value === "hearing-next")?.disabled).toBe(false);

    fireEvent.change(screen.getByLabelText("Record type"), { target: { value: "deadline_extended" } });
    const deadline = screen.getByLabelText<HTMLSelectElement>("Active deadline");
    expect(deadline).toBeDisabled();
    expect(screen.getByText(/This opposition has no confirmed deadline to extend/)).toBeVisible();

    fireEvent.change(screen.getByLabelText("Record type"), { target: { value: "appeal_linked" } });
    expect(screen.getByLabelText("Opposition order event")).toBeDisabled();
    expect(screen.getByText(/No opposition order is recorded yet/)).toBeVisible();
    expect(screen.queryByLabelText(/record ID/i)).toBeNull();
  });

  it("B4-ADJ-02 links an appeal to a Matter chosen by name, never a typed record ID", async () => {
    fetchWorkflowMock.mockResolvedValue({
      ...baseWorkflow,
      current_stage: "appeal_pending",
      next_required_action: "link_appeal",
      shared_actions: [{ id: "order-43", event_kind: "opposition_shared_action", source_reference: "registry-order:43", effective_at: "2026-10-25T07:00:00Z", reason: "Order", payload_json: { action_kind: "order_recorded" } }],
      appeal_proceedings: [{ id: "appeal-unnumbered", office: "High Court of Delhi", stage: "filed", appeal_identifiers: [] }],
    });
    renderWorkflow();
    const kind = await screen.findByLabelText<HTMLSelectElement>("Appeal target");
    expect(kind).toHaveValue("");
    // The only appeal proceeding has no appeal number, so that route is listed with its reason.
    const proceedingOption = Array.from(kind.options).find((option) => option.value === "appeal_proceeding");
    expect(proceedingOption?.disabled).toBe(true);
    expect(proceedingOption?.textContent).toContain("no appeal number recorded yet");
    fireEvent.change(kind, { target: { value: "matter" } });
    const matter = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Appeal Matter" });
    await waitFor(() => expect(matter).toBeEnabled());
    fireEvent.change(matter, { target: { value: "matter-appeal" } });
    fireEvent.change(screen.getByLabelText("Appeal number"), { target: { value: "C.A.(COMM.IPD-TM) 43/2026" } });
    const order = screen.getByLabelText<HTMLSelectElement>("Opposition order event");
    expect(order).toHaveValue("");
    fireEvent.change(order, { target: { value: "order-43" } });
    fillCommon();
    fireEvent.click(screen.getByRole("button", { name: "Record appeal link" }));
    await waitFor(() => expect(recordActionMock).toHaveBeenCalledOnce());
    expect(recordActionMock).toHaveBeenCalledWith(expect.objectContaining({
      actionKind: "appeal_linked",
      appealLink: { target_kind: "matter", target_id: "matter-appeal", appeal_identifier: "C.A.(COMM.IPD-TM) 43/2026", order_event_id: "order-43" },
    }));
  });

  it("B4-ADJ-02 offers numbered appeal proceedings and their numbers from the validator", async () => {
    fetchWorkflowMock.mockResolvedValue({
      ...baseWorkflow,
      current_stage: "appeal_pending",
      next_required_action: "link_appeal",
      shared_actions: [{ id: "order-43", event_kind: "opposition_shared_action", source_reference: "registry-order:43", effective_at: "2026-10-25T07:00:00Z", reason: "Order", payload_json: { action_kind: "order_recorded" } }],
      appeal_proceedings: [{ id: "appeal-43", office: "High Court of Delhi", stage: "filed", appeal_identifiers: ["C.A.(COMM.IPD-TM) 43/2026"] }],
    });
    renderWorkflow();
    fireEvent.change(await screen.findByLabelText("Appeal target"), { target: { value: "appeal_proceeding" } });
    const proceeding = screen.getByLabelText<HTMLSelectElement>("Appeal proceeding");
    expect(proceeding).toHaveValue("");
    expect(screen.getByLabelText("Appeal number")).toBeDisabled();
    fireEvent.change(proceeding, { target: { value: "appeal-43" } });
    const number = screen.getByLabelText<HTMLSelectElement>("Appeal number");
    expect(number).toHaveValue("");
    fireEvent.change(number, { target: { value: "C.A.(COMM.IPD-TM) 43/2026" } });
    fireEvent.change(screen.getByLabelText("Opposition order event"), { target: { value: "order-43" } });
    fillCommon();
    fireEvent.click(screen.getByRole("button", { name: "Record appeal link" }));
    await waitFor(() => expect(recordActionMock).toHaveBeenCalledOnce());
    expect(recordActionMock).toHaveBeenCalledWith(expect.objectContaining({
      appealLink: { target_kind: "appeal_proceeding", target_id: "appeal-43", appeal_identifier: "C.A.(COMM.IPD-TM) 43/2026", order_event_id: "order-43" },
    }));
  });

  it("records a complete Rule 46 evidence package", async () => {
    renderWorkflow();

    const values: Record<string, string> = {
      "Affidavit deponent": "Evidence Deponent",
      "Affidavit document": "document:affidavit:43",
      "Exhibit documents": "document:exhibit-a:43, document:exhibit-b:43",
      "Evidence index": "document:index:43",
      "Relied-on documents": "document:prior-use:43",
      "Filing reference": "registry-filing:rule-46:43",
      Signatory: "Authorized IP Counsel",
      Authority: "Signed client authority",
      Place: "New Delhi",
      "Verified paragraphs": "1-12, verification",
      "Knowledge basis": "Client records and registry documents",
      "Signed affidavit reference": "document:signed-affidavit:43",
      "Service method": "Registry portal and email",
      "Service destination": "Opposing counsel",
      "Service evidence": "service-receipt:43",
      "Source reference": "registry:rule-46:43",
      "Lawyer confirmation": "Approved by responsible IP counsel",
      "Evidence references": "filing-receipt:43",
      "Document references": "document:evidence-set:43",
      Reason: "Counsel verified the complete Rule 46 evidence package.",
    };
    for (const [label, value] of Object.entries(values)) {
      fireEvent.change(await screen.findByLabelText(label), { target: { value } });
    }
    fireEvent.change(screen.getByLabelText("Filed and verified on"), {
      target: { value: "2026-08-23" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Record evidence package" }));

    await waitFor(() => expect(recordActionMock).toHaveBeenCalledOnce());
    expect(recordActionMock).toHaveBeenCalledWith(expect.objectContaining({
      docketId: "docket-43",
      proceedingId: "opposition-43",
      lifecycleVersion: 6,
      proceedingVersion: 8,
      actionKind: "evidence_package_recorded",
      evidenceRefs: ["filing-receipt:43"],
      documentRefs: ["document:evidence-set:43"],
      evidencePackage: expect.objectContaining({
        package_kind: "rule_46",
        package_version: 1,
        exhibit_document_refs: ["document:exhibit-a:43", "document:exhibit-b:43"],
        verification: expect.objectContaining({
          signed_document_ref: "document:signed-affidavit:43",
        }),
        service: expect.objectContaining({ evidence_refs: ["service-receipt:43"] }),
      }),
    }));
  });

  it("schedules the canonical shared hearing with durable reminders", async () => {
    fetchWorkflowMock.mockResolvedValue({
      ...baseWorkflow,
      current_stage: "hearing_pending",
      next_required_action: "schedule_hearing",
    });
    renderWorkflow();

    fireEvent.change(await screen.findByLabelText("Hearing date"), {
      target: { value: "2026-10-20" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Schedule hearing" }));

    await waitFor(() => expect(createHearingMock).toHaveBeenCalledOnce());
    expect(createHearingMock).toHaveBeenCalledWith(expect.objectContaining({
      docketId: "docket-43",
      hearingOn: "2026-10-20",
      forumName: "Trade Marks Registry Delhi",
      attendeeMembershipIds: ["membership-43"],
      reminderOffsetsHours: [168, 24],
      reminderChannels: ["in_app", "email"],
      reminderRecipientMembershipIds: ["membership-43"],
    }));
  });
});
