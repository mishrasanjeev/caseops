import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  confirmMock,
  createNumberMock,
  fetchDeadlineMock,
  fetchWorkflowMock,
  listUsersMock,
  proposeMock,
  recordActionMock,
} = vi.hoisted(() => ({
  listUsersMock: vi.fn(),
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
  listCompanyUsers: listUsersMock,
  proposeIpOppositionOpponentDeadline: proposeMock,
  recordIpOppositionOpponentAction: recordActionMock,
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { IpOppositionOpponentWorkflow } from "@/components/ip/IpOppositionOpponentWorkflow";
import type { IpDeadlineWorkspace } from "@/lib/api/endpoints";
import {
  availableGovernance,
  governedRule,
  rolloutPausedGovernance,
  workingCalendar,
} from "@/test/ip-governance-fixtures";

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
const deadlineWorkspace: IpDeadlineWorkspace = {
  docket_id: "docket-1",
  rules: [
    governedRule({ id: "wrong-rule", key: "applicant-rule", version: 1, role: "applicant" }),
    governedRule({ id: "notice-rule", key: "opponent-notice", version: 3 }),
    // Active and exact, but company policy does not select it: the validator refuses it.
    governedRule({ id: "unselected-rule", key: "opponent-unselected", version: 5 }),
    governedRule({ id: "evidence-rule", key: "opponent-evidence", version: 4, stage: "opponent_evidence_due" }),
  ],
  eligible_rule_version_ids: ["wrong-rule", "notice-rule", "evidence-rule"],
  calendars: [workingCalendar({ id: "calendar-1", name: "India registry calendar", version: 2 })],
  deadlines: [],
  exceptions: [],
  automation_state: "explicit_confirmation_only",
  governance: availableGovernance(),
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
    listUsersMock.mockResolvedValue({
      users: [
        { membership_id: "membership-primary", full_name: "Ram Gupta", email: "ram@example.com", role: "owner", membership_active: true, user_active: true },
        { membership_id: "membership-backup", full_name: "Asha Rao", email: "asha@example.com", role: "partner", membership_active: true, user_active: true },
      ],
    });
    createNumberMock.mockResolvedValue({ identifier: {}, duplicate_candidates: [] });
    proposeMock.mockResolvedValue({ workflow_stage: "notice_filing_due", deadline });
    confirmMock.mockResolvedValue({ ...deadline, state: "confirmed" });
    recordActionMock.mockResolvedValue({});
  });

  it("uses only the exact active opponent rule and profile trigger", async () => {
    fetchWorkflowMock.mockResolvedValue(workflow("propose_notice_filing_deadline"));
    renderWorkflow();

    expect(await screen.findByRole("option", { name: /^opponent-notice v3 · Opposition, opponent · notice of opposition due/ })).toBeVisible();
    expect(screen.queryByRole("option", { name: /^applicant-rule v1/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /^opponent-unselected v5/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: /^opponent-evidence v4/ })).not.toBeInTheDocument();
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

    await waitFor(() => expect(screen.getByLabelText("Trigger date")).toHaveValue("2026-09-03"));
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

    const backup = await screen.findByLabelText("Opponent backup lawyer");
    await screen.findAllByRole("option", { name: "Asha Rao — asha@example.com" });
    expect(screen.queryByRole("textbox", { name: /membership/i })).not.toBeInTheDocument();
    fireEvent.change(backup, { target: { value: "membership-backup" } });
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

  it("BUG-003/004 empty catalogue: disabled pickers name the missing rule and calendar and link to governance", async () => {
    fetchWorkflowMock.mockResolvedValue(workflow("propose_notice_filing_deadline"));
    fetchDeadlineMock.mockResolvedValue({
      ...deadlineWorkspace,
      rules: [],
      eligible_rule_version_ids: [],
      calendars: [],
      governance: rolloutPausedGovernance(),
    });
    renderWorkflow();

    const rule = await screen.findByLabelText("Governed rule");
    await waitFor(() => expect(rule).toBeDisabled());
    const calendar = screen.getByLabelText("Working calendar");
    expect(calendar).toBeDisabled();
    expect(rule).toHaveDisplayValue("No eligible rule for Opposition, opponent · notice of opposition due");
    const ruleStatus = document.getElementById(rule.getAttribute("aria-describedby") ?? "");
    expect(ruleStatus).toHaveTextContent("No active governed rule exists for Opposition, opponent · notice of opposition due.");
    expect(ruleStatus).toHaveTextContent("Paused by CaseOps: Rule publication is paused by CaseOps");
    const calendarStatus = document.getElementById(calendar.getAttribute("aria-describedby") ?? "");
    expect(calendarStatus).toHaveTextContent("No active working calendar exists for this workspace.");
    expect(calendarStatus).toHaveTextContent("Propose one in Rule and calendar governance");
    expect(screen.getByRole("link", { name: "Open rule and calendar governance" })).toHaveAttribute(
      "href",
      "/app/ip?docket=docket-1&view=schedule&tab=schedule&rule_scope=opponent_notice#ip-deadline-governance",
    );
    expect(screen.getByRole("button", { name: "Propose deadline" })).toBeDisabled();
    expect(screen.queryByText(/notice_filing_due/)).not.toBeInTheDocument();
  });

  it("BUG-004 names a candidate calendar awaiting another approver", async () => {
    fetchWorkflowMock.mockResolvedValue(workflow("propose_notice_filing_deadline"));
    fetchDeadlineMock.mockResolvedValue({
      ...deadlineWorkspace,
      calendars: [workingCalendar({ id: "calendar-2", name: "Delhi registry calendar", status: "candidate" })],
    });
    renderWorkflow();

    const calendar = await screen.findByLabelText("Working calendar");
    await waitFor(() => expect(calendar).toBeDisabled());
    expect(document.getElementById(calendar.getAttribute("aria-describedby") ?? "")).toHaveTextContent(
      "Delhi registry calendar v1 is awaiting activation by an approver other than its proposer.",
    );
  });

  it("BUG-003 keeps the workflow usable while governed rules load and offers retry on failure", async () => {
    fetchWorkflowMock.mockResolvedValue(workflow("propose_notice_filing_deadline"));
    fetchDeadlineMock.mockRejectedValueOnce(new Error("Deadline workspace unavailable"));
    renderWorkflow();

    expect(await screen.findByText("Deadline workspace unavailable")).toBeVisible();
    expect(screen.getByLabelText("Governed rule")).toBeDisabled();
    expect(screen.getByLabelText("Governed rule")).toHaveDisplayValue("Unavailable — retry below");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("option", { name: /^opponent-notice v3/ })).toBeVisible();
    expect(screen.getByLabelText("Governed rule")).toBeEnabled();
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
