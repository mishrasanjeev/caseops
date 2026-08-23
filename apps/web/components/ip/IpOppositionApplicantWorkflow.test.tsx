import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  confirmMock,
  createNumberMock,
  fetchDeadlineMock,
  fetchWorkflowMock,
  proposeMock,
  recordActionMock,
} = vi.hoisted(() => ({
  confirmMock: vi.fn(),
  createNumberMock: vi.fn(),
  fetchDeadlineMock: vi.fn(),
  fetchWorkflowMock: vi.fn(),
  proposeMock: vi.fn(),
  recordActionMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  confirmIpLegalDeadline: confirmMock,
  createIpOppositionIdentifier: createNumberMock,
  fetchIpDeadlineWorkspace: fetchDeadlineMock,
  fetchIpOppositionApplicantWorkflow: fetchWorkflowMock,
  proposeIpOppositionApplicantDeadline: proposeMock,
  recordIpOppositionApplicantAction: recordActionMock,
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { IpOppositionApplicantWorkflow } from "@/components/ip/IpOppositionApplicantWorkflow";

function withClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const profileEvent = {
  id: "profile-event-1",
  event_kind: "opposition_profile",
  payload_json: {},
};
const docket = { id: "docket-1", lifecycle_version: 4 };
const workspace = {
  proceeding: {
    id: "opposition-1",
    side: "applicant",
    stage: "counterstatement_due",
    office: "Trade Marks Registry Delhi",
    jurisdiction: "IN",
    version: 7,
  },
  profile_event: profileEvent,
  stage_events: [],
};
const deadline = {
  id: "deadline-1",
  version: 2,
  state: "candidate",
  result_on: "2026-09-20",
  rule_citation: "Trade Marks Rules, Rule 44",
};
const deadlineWorkspace = {
  rules: [
    { id: "wrong-rule", key: "opponent-rule", version: 1, status: "active", proceeding_kind: "opposition", role: "opponent", stage: "counterstatement_due" },
    { id: "counter-rule", key: "applicant-counter", version: 3, status: "active", proceeding_kind: "opposition", role: "applicant", stage: "counterstatement_due" },
  ],
  calendars: [{ id: "calendar-1", name: "India registry calendar", version: 2, status: "active" }],
  deadlines: [],
};

function renderWorkflow() {
  return render(withClient(
    <IpOppositionApplicantWorkflow
      docket={docket as never}
      workspace={workspace as never}
      canReview
      currentMembershipId="membership-primary"
    />,
  ));
}

describe("IpOppositionApplicantWorkflow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchDeadlineMock.mockResolvedValue(deadlineWorkspace);
    createNumberMock.mockResolvedValue({ identifier: {}, duplicate_candidates: [] });
    proposeMock.mockResolvedValue({ workflow_stage: "counterstatement_due", deadline });
    confirmMock.mockResolvedValue({ ...deadline, state: "confirmed" });
    recordActionMock.mockResolvedValue({});
  });

  it("records a pending registry opposition number with proceeding scope", async () => {
    fetchWorkflowMock.mockResolvedValue({
      proceeding_id: "opposition-1",
      represented_side: "applicant",
      opposition_number_status: "pending_allocation",
      applicant_actions: [],
      deadlines: [],
      next_required_action: "record_opposition_number",
    });
    renderWorkflow();

    fireEvent.change(await screen.findByLabelText("Opposition number"), { target: { value: "OPP / 41 / 2026" } });
    fireEvent.click(screen.getByRole("button", { name: "Record number" }));
    await waitFor(() => expect(createNumberMock).toHaveBeenCalledOnce());
    expect(createNumberMock).toHaveBeenCalledWith(expect.objectContaining({
      docketId: "docket-1",
      proceedingId: "opposition-1",
      rawValue: "OPP / 41 / 2026",
    }));
  });

  it("uses only the exact active applicant rule and confirmed profile trigger", async () => {
    fetchWorkflowMock.mockResolvedValue({
      proceeding_id: "opposition-1",
      represented_side: "applicant",
      opposition_number_status: "confirmed",
      applicant_actions: [],
      deadlines: [],
      next_required_action: "propose_counterstatement_deadline",
    });
    renderWorkflow();

    expect(await screen.findByRole("option", { name: "applicant-counter v3" })).toBeVisible();
    expect(screen.queryByRole("option", { name: "opponent-rule v1" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Propose deadline" }));
    await waitFor(() => expect(proposeMock).toHaveBeenCalledOnce());
    expect(proposeMock).toHaveBeenCalledWith(expect.objectContaining({
      workflowStage: "counterstatement_due",
      triggerEventId: "profile-event-1",
      ruleVersionId: "counter-rule",
      calendarVersionId: "calendar-1",
    }));
  });

  it("confirms dual ownership and records the signed TM-O work product", async () => {
    fetchWorkflowMock.mockResolvedValue({
      proceeding_id: "opposition-1",
      represented_side: "applicant",
      opposition_number_status: "confirmed",
      applicant_actions: [],
      deadlines: [{ workflow_stage: "counterstatement_due", deadline }],
      next_required_action: "file_counterstatement",
    });
    renderWorkflow();

    fireEvent.change(await screen.findByLabelText("Backup membership ID"), { target: { value: "membership-backup" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalledOnce());
    expect(confirmMock.mock.calls[0][0].responsibilities).toEqual([
      expect.objectContaining({ membership_id: "membership-primary", role: "primary" }),
      expect.objectContaining({ membership_id: "membership-backup", role: "backup" }),
    ]);

    const values: Record<string, string> = {
      "TM-O filing reference": "TM-O-ACK-041",
      Signatory: "Authorized Signatory",
      Authority: "Board authority",
      Place: "New Delhi",
      "Verified paragraph ranges": "1-12, verification",
      "Knowledge basis": "Personal knowledge and company records",
      "Source reference": "registry-filing:041",
      "Document references": "document:signed-tmo:041",
      "Evidence references": "filing-receipt:041",
      "Lawyer reason": "Counsel reviewed and approved the signed counterstatement.",
    };
    for (const [label, value] of Object.entries(values)) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
    fireEvent.click(screen.getByRole("button", { name: "Record work product" }));
    await waitFor(() => expect(recordActionMock).toHaveBeenCalledOnce());
    expect(recordActionMock).toHaveBeenCalledWith(expect.objectContaining({
      lifecycleVersion: 4,
      proceedingVersion: 7,
      actionKind: "counterstatement_filed",
      filingReference: "TM-O-ACK-041",
      documentRefs: ["document:signed-tmo:041"],
      evidenceRefs: ["filing-receipt:041"],
      verification: expect.objectContaining({ signed_document_ref: "document:signed-tmo:041" }),
    }));
  });
});
