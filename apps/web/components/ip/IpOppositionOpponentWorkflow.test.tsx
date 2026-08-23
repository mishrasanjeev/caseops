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
  fetchIpOppositionOpponentWorkflow: fetchWorkflowMock,
  proposeIpOppositionOpponentDeadline: proposeMock,
  recordIpOppositionOpponentAction: recordActionMock,
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { IpOppositionOpponentWorkflow } from "@/components/ip/IpOppositionOpponentWorkflow";

function withClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const profileEvent = { id: "profile-event-1", event_kind: "opposition_profile", payload_json: {} };
const docket = { id: "docket-1", lifecycle_version: 4 };
const proceeding = {
  id: "opposition-1",
  side: "opponent",
  stage: "draft",
  origin_kind: "registry_event",
  office: "Trade Marks Registry Delhi",
  jurisdiction: "IN",
  version: 7,
};
const workspace = {
  proceeding,
  profile: { limitation_date: "2026-09-20" },
  profile_event: profileEvent,
  stage_events: [],
};
const deadline = {
  id: "deadline-1",
  version: 2,
  state: "candidate",
  result_on: "2026-09-20",
  rule_citation: "Trade Marks Act and Rules",
};
const deadlineWorkspace = {
  rules: [
    { id: "wrong-rule", key: "applicant-rule", version: 1, status: "active", proceeding_kind: "opposition", role: "applicant", stage: "notice_filing_due" },
    { id: "notice-rule", key: "opponent-notice", version: 3, status: "active", proceeding_kind: "opposition", role: "opponent", stage: "notice_filing_due" },
    { id: "evidence-rule", key: "opponent-evidence", version: 4, status: "active", proceeding_kind: "opposition", role: "opponent", stage: "opponent_evidence_due" },
  ],
  calendars: [{ id: "calendar-1", name: "India registry calendar", version: 2, status: "active" }],
  deadlines: [],
};

function renderWorkflow(overrides: Record<string, unknown> = {}) {
  return render(withClient(
    <IpOppositionOpponentWorkflow
      docket={docket as never}
      workspace={{ ...workspace, ...overrides } as never}
      canReview
      currentMembershipId="membership-primary"
    />,
  ));
}

function workflow(next: string, extra: Record<string, unknown> = {}) {
  return {
    proceeding_id: "opposition-1",
    represented_side: "opponent",
    opposition_number_status: "confirmed",
    client_instruction_status: "confirmed",
    opponent_actions: [],
    deadlines: [],
    corrective_task_id: null,
    next_required_action: next,
    ...extra,
  };
}

function fillCommon() {
  fireEvent.change(screen.getByLabelText("Opponent source reference"), { target: { value: "registry:opposition:42" } });
  fireEvent.change(screen.getByLabelText("Opponent evidence references"), { target: { value: "evidence:42" } });
  fireEvent.change(screen.getByLabelText("Opponent lawyer reason"), { target: { value: "Counsel reviewed and approved this opponent action." } });
}

describe("IpOppositionOpponentWorkflow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchDeadlineMock.mockResolvedValue(deadlineWorkspace);
    createNumberMock.mockResolvedValue({ identifier: {}, duplicate_candidates: [] });
    proposeMock.mockResolvedValue({ workflow_stage: "notice_filing_due", deadline });
    confirmMock.mockResolvedValue({ ...deadline, state: "confirmed" });
    recordActionMock.mockResolvedValue({});
  });

  it("uses only the exact active opponent rule and profile trigger", async () => {
    fetchWorkflowMock.mockResolvedValue(workflow("propose_notice_filing_deadline"));
    renderWorkflow();

    expect(await screen.findByRole("option", { name: "opponent-notice v3" })).toBeVisible();
    expect(screen.queryByRole("option", { name: "applicant-rule v1" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Propose deadline" }));
    await waitFor(() => expect(proposeMock).toHaveBeenCalledOnce());
    expect(proposeMock).toHaveBeenCalledWith(expect.objectContaining({
      workflowStage: "notice_filing_due",
      triggerEventId: "profile-event-1",
      ruleVersionId: "notice-rule",
      calendarVersionId: "calendar-1",
    }));
  });

  it("resets the governed base date to the current stage trigger event", async () => {
    fetchWorkflowMock.mockResolvedValue(workflow("propose_opponent_evidence_deadline"));
    renderWorkflow({
      proceeding: { ...proceeding, stage: "opponent_evidence_due" },
      stage_events: [{
        id: "counterstatement-event-1",
        after_phase: "counterstatement_filed",
        resulting_stage: "counterstatement_filed",
        effective_at: "2026-09-03T10:30:00Z",
      }],
    });

    expect(await screen.findByLabelText("Trigger date")).toHaveValue("2026-09-03");
    fireEvent.click(screen.getByRole("button", { name: "Propose deadline" }));
    await waitFor(() => expect(proposeMock).toHaveBeenCalledOnce());
    expect(proposeMock).toHaveBeenCalledWith(expect.objectContaining({
      workflowStage: "opponent_evidence_due",
      triggerEventId: "counterstatement-event-1",
      ruleVersionId: "evidence-rule",
      baseDate: "2026-09-03",
    }));
  });

  it("confirms dual ownership and records a signed TM-O notice", async () => {
    fetchWorkflowMock.mockResolvedValue(workflow("file_notice", {
      deadlines: [{ workflow_stage: "notice_filing_due", deadline }],
    }));
    renderWorkflow();

    fireEvent.change(await screen.findByLabelText("Opponent backup membership ID"), { target: { value: "membership-backup" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
    await waitFor(() => expect(confirmMock).toHaveBeenCalledOnce());
    expect(confirmMock.mock.calls[0][0].responsibilities).toEqual([
      expect.objectContaining({ membership_id: "membership-primary", role: "primary" }),
      expect.objectContaining({ membership_id: "membership-backup", role: "backup" }),
    ]);

    const values: Record<string, string> = {
      "TM-O notice filing reference": "TM-O-ACK-042",
      Signatory: "Authorized Signatory",
      Authority: "Board authority",
      Place: "New Delhi",
      "Verified paragraph ranges": "1-14, verification",
      "Knowledge basis": "Personal knowledge and company records",
      "Opponent source reference": "registry-filing:042",
      "Opponent document references": "document:signed-tmo:042",
      "Opponent evidence references": "filing-receipt:042",
      "Opponent lawyer reason": "Counsel reviewed and approved the signed notice.",
    };
    for (const [label, value] of Object.entries(values)) {
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    }
    fireEvent.click(screen.getByRole("button", { name: "Record opponent work product" }));
    await waitFor(() => expect(recordActionMock).toHaveBeenCalledOnce());
    expect(recordActionMock).toHaveBeenCalledWith(expect.objectContaining({
      lifecycleVersion: 4,
      proceedingVersion: 7,
      actionKind: "notice_filed",
      filingReference: "TM-O-ACK-042",
      documentRefs: ["document:signed-tmo:042"],
      evidenceRefs: ["filing-receipt:042"],
      verification: expect.objectContaining({ signed_document_ref: "document:signed-tmo:042" }),
    }));
  });

  it("opens corrective work for a rejected filing without recording acceptance", async () => {
    fetchWorkflowMock.mockResolvedValue(workflow("file_notice"));
    renderWorkflow();

    fireEvent.change(await screen.findByLabelText("Filing outcome"), { target: { value: "rejected" } });
    fireEvent.change(screen.getByLabelText("Registry rejection reference"), { target: { value: "registry-rejection:42" } });
    fillCommon();
    fireEvent.click(screen.getByRole("button", { name: "Record opponent work product" }));
    await waitFor(() => expect(recordActionMock).toHaveBeenCalledOnce());
    expect(recordActionMock).toHaveBeenCalledWith(expect.objectContaining({
      actionKind: "notice_filing_rejected",
      rejectionReference: "registry-rejection:42",
      filingReference: null,
    }));
  });

  it("records explicit Rule 45 and Rule 47 elections", async () => {
    fetchWorkflowMock.mockResolvedValueOnce(workflow("record_opponent_evidence_decision"));
    const first = renderWorkflow({ proceeding: { ...proceeding, stage: "opponent_evidence_due" } });
    await screen.findByLabelText("Rule 45 election");
    fillCommon();
    fireEvent.click(screen.getByRole("button", { name: "Record opponent work product" }));
    await waitFor(() => expect(recordActionMock).toHaveBeenCalledOnce());
    expect(recordActionMock).toHaveBeenLastCalledWith(expect.objectContaining({
      actionKind: "opponent_evidence_decision",
      evidenceElection: "rely_on_pleaded_facts",
    }));
    first.unmount();

    fetchWorkflowMock.mockResolvedValueOnce(workflow("record_reply_evidence_decision"));
    renderWorkflow({ proceeding: { ...proceeding, stage: "reply_evidence_due" } });
    await screen.findByLabelText("Rule 47 election");
    fillCommon();
    fireEvent.click(screen.getByRole("button", { name: "Record opponent work product" }));
    await waitFor(() => expect(recordActionMock).toHaveBeenCalledTimes(2));
    expect(recordActionMock).toHaveBeenLastCalledWith(expect.objectContaining({
      actionKind: "reply_evidence_decision",
      evidenceElection: "no_reply_evidence",
    }));
  });

  it("closes a watch hit without creating a filed proceeding", async () => {
    fetchWorkflowMock.mockResolvedValue(workflow("propose_notice_filing_deadline"));
    renderWorkflow({ proceeding: { ...proceeding, origin_kind: "watch_hit" } });

    fireEvent.change(await screen.findByLabelText("Watch source reference"), { target: { value: "watch:42" } });
    fireEvent.change(screen.getByLabelText("Watch evidence references"), { target: { value: "watch-evidence:42" } });
    fireEvent.change(screen.getByLabelText("Watch disposition reason"), { target: { value: "Client declined to proceed after counsel review." } });
    fireEvent.click(screen.getByRole("button", { name: "Close without proceeding" }));
    await waitFor(() => expect(recordActionMock).toHaveBeenCalledOnce());
    expect(recordActionMock).toHaveBeenCalledWith(expect.objectContaining({
      actionKind: "watch_hit_closed",
      filingReference: null,
      evidenceRefs: ["watch-evidence:42"],
    }));
  });
});
