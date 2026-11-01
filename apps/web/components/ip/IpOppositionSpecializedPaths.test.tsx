import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchWorkflowMock, recordActionMock } = vi.hoisted(() => ({
  fetchWorkflowMock: vi.fn(),
  recordActionMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchIpOppositionSharedWorkflow: fetchWorkflowMock,
  recordIpOppositionSharedAction: recordActionMock,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { IpOppositionSpecializedPaths } from "@/components/ip/IpOppositionSpecializedPaths";

const docket = { id: "docket-48", lifecycle_version: 4 };
const workspace = {
  proceeding: {
    id: "opposition-48",
    application_id: "application-48",
    side: "opponent",
    stage: "hearing_scheduled",
    office: "Trade Marks Registry Delhi",
    version: 11,
  },
  stage_events: [{ id: "outcome-event-48", event_kind: "opposition_stage_transition", resulting_stage: "withdrawn", source_reference: "registry-order:48" }],
};
// The API's hearing_statuses_by_action (services/ip_opposition_shared.py
// HEARING_STATUSES_BY_ACTION); the form reads it, it keeps no copy.
const HEARING_TABLE = {
  hearing_preparation_recorded: ["adjourned", "scheduled"],
  post_hearing_note_recorded: ["completed"],
  hearing_notice_recorded: ["adjourned", "scheduled"],
  adjournment_recorded: ["adjourned", "scheduled"],
  written_arguments_recorded: ["adjourned", "completed", "scheduled"],
  attendance_recorded: ["completed"],
};

const workflow = {
  proceeding_id: "opposition-48",
  represented_side: "opponent",
  current_stage: "hearing_scheduled",
  shared_actions: [],
  active_deadlines: [],
  shared_hearings: [{ id: "hearing-48", hearing_on: "2026-10-20", forum_name: "Trade Marks Registry Delhi", status: "scheduled", purpose: "Opposition", time_status: "session" }],
  application_scopes: [
    { id: "scope-9", class_number: 9, specification: "Downloadable software", effective_from: "2026-08-23", source: "registry" },
    { id: "scope-42", class_number: 42, specification: "Legal technology services", effective_from: "2026-08-23", source: "registry" },
  ],
  hearing_statuses_by_action: HEARING_TABLE,
  next_required_action: "await_hearing",
};

function withClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderPaths() {
  return render(withClient(<IpOppositionSpecializedPaths docket={docket as never} workspace={workspace as never} canReview currentMembershipId="membership-48" />));
}

async function fillCommon() {
  fireEvent.change(await screen.findByLabelText("Source reference"), { target: { value: "registry-scope:48" } });
  fireEvent.change(screen.getByLabelText("Lawyer confirmation"), { target: { value: "Approved by responsible counsel" } });
  fireEvent.change(screen.getByLabelText("Evidence references"), { target: { value: "registry-pdf:48" } });
  fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Counsel verified the specialized opposition record." } });
}

describe("IpOppositionSpecializedPaths", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchWorkflowMock.mockResolvedValue(workflow);
    recordActionMock.mockResolvedValue(workflow);
  });

  it("B4-ADJ-22 offers exactly the hearings the served status table accepts", async () => {
    fetchWorkflowMock.mockResolvedValue({
      ...workflow,
      shared_hearings: [
        workflow.shared_hearings[0],
        { id: "hearing-adjourned", hearing_on: "2026-10-27", forum_name: "Trade Marks Registry Delhi", status: "adjourned", purpose: "Opposition", time_status: "session" },
      ],
      // A narrower server rule must be followed, not a copy in the form.
      hearing_statuses_by_action: { ...HEARING_TABLE, hearing_notice_recorded: ["adjourned"] },
    });
    renderPaths();
    fireEvent.change(await screen.findByTestId("ip-opposition-specialized-action"), { target: { value: "hearing_notice_recorded" } });
    const hearing = screen.getByTestId<HTMLSelectElement>("ip-opposition-specialized-hearing");
    expect(hearing).toHaveValue("");
    const option = (id: string) => Array.from(hearing.options).find((row) => row.value === id)!;
    expect(option("hearing-48").disabled).toBe(true);
    expect(option("hearing-48").textContent).toContain("not available for a scheduled hearing");
    expect(option("hearing-adjourned").disabled).toBe(false);
  });

  it("records a partial multi-class scope review without changing unlisted scope", async () => {
    renderPaths();
    await fillCommon();
    fireEvent.change(screen.getByLabelText("Registry scope certainty"), { target: { value: "partial" } });
    fireEvent.change(screen.getByLabelText("Source confirmation"), { target: { value: "registry-source-pdf:48" } });
    fireEvent.change(screen.getByLabelText("Class 9 decision"), { target: { value: "withdrawn" } });
    fireEvent.change(screen.getByLabelText("Class 42 decision"), { target: { value: "continuing" } });
    fireEvent.click(screen.getByTestId("ip-opposition-specialized-submit"));

    await waitFor(() => expect(recordActionMock).toHaveBeenCalledOnce());
    expect(recordActionMock).toHaveBeenCalledWith(expect.objectContaining({
      actionKind: "scope_review_recorded",
      scopeReview: expect.objectContaining({
        source_scope_certainty: "partial",
        source_confirmation_reference: "registry-source-pdf:48",
        preserve_unlisted_scopes: true,
        decisions: [
          expect.objectContaining({ application_scope_id: "scope-9", status: "withdrawn" }),
          expect.objectContaining({ application_scope_id: "scope-42", status: "continuing" }),
        ],
      }),
    }));
  });

  it("exposes every specialized procedural path and canonical hearing", async () => {
    renderPaths();
    const selector = await screen.findByTestId("ip-opposition-specialized-action");
    expect(Array.from((selector as HTMLSelectElement).options).map((option) => option.value)).toEqual([
      "scope_review_recorded",
      "translation_recorded",
      "hearing_notice_recorded",
      "adjournment_recorded",
      "written_arguments_recorded",
      "attendance_recorded",
      "security_for_costs_recorded",
      "disposition_review_recorded",
      "madrid_designation_link_recorded",
    ]);
    fireEvent.change(selector, { target: { value: "adjournment_recorded" } });
    // B4-ADJ-22: the hearing is never chosen for the user.
    const hearing = screen.getByLabelText<HTMLSelectElement>("Canonical hearing");
    expect(hearing).toHaveValue("");
    expect(hearing).toBeEnabled();
    fireEvent.change(hearing, { target: { value: "hearing-48" } });
    expect(hearing).toHaveValue("hearing-48");
    expect(screen.getByLabelText("Allowed-count candidate")).toBeInTheDocument();
    fireEvent.change(selector, { target: { value: "attendance_recorded" } });
    fireEvent.change(screen.getByLabelText("Appearance"), { target: { value: "nonappearance" } });
    expect(screen.getByLabelText("Consequence candidate")).toBeInTheDocument();
  });

  it("offers only hearings the record accepts and explains a dead end instead of an empty select", async () => {
    renderPaths();
    const selector = await screen.findByTestId("ip-opposition-specialized-action");
    // Attendance needs a completed hearing; the only hearing is scheduled.
    fireEvent.change(selector, { target: { value: "attendance_recorded" } });
    const hearing = screen.getByLabelText<HTMLSelectElement>("Canonical hearing");
    expect(hearing).toBeDisabled();
    const option = Array.from(hearing.options).find((row) => row.value === "hearing-48");
    expect(option?.disabled).toBe(true);
    expect(option?.textContent).toContain("mark the hearing completed first");
    expect(screen.getByText(/No hearing is completed yet. Mark the hearing completed on the Hearings and deadlines tab first./)).toBeVisible();
  });

  it("takes disposition triggers and affected classes from the validator, never typed ids", async () => {
    fetchWorkflowMock.mockResolvedValue({
      ...workflow,
      disposition_trigger_events: [{ id: "order-48", event_kind: "opposition_shared_action", resulting_stage: null, source_reference: "registry-order:48", effective_at: "2026-10-21T07:00:00Z", payload_json: { action_kind: "order_recorded" } }],
    });
    renderPaths();
    await fillCommon();
    fireEvent.change(screen.getByTestId("ip-opposition-specialized-action"), { target: { value: "disposition_review_recorded" } });
    const trigger = screen.getByLabelText<HTMLSelectElement>("Trigger event");
    // The withdrawn stage event in workspace.stage_events is not the validator's list.
    expect(Array.from(trigger.options).map((row) => row.value)).toEqual(["", "order-48"]);
    expect(trigger).toHaveValue("");
    expect(screen.queryByLabelText(/scope IDs/i)).toBeNull();
    fireEvent.change(trigger, { target: { value: "order-48" } });
    fireEvent.click(screen.getByLabelText("Class 9: Downloadable software"));
    fireEvent.change(screen.getByLabelText("Recommended application disposition"), { target: { value: "Review class 9 only." } });
    fireEvent.change(screen.getByLabelText("Review reference"), { target: { value: "counsel-review:48" } });
    fireEvent.click(screen.getByTestId("ip-opposition-specialized-submit"));
    await waitFor(() => expect(recordActionMock).toHaveBeenCalledOnce());
    expect(recordActionMock).toHaveBeenCalledWith(expect.objectContaining({
      dispositionReview: expect.objectContaining({ trigger_event_id: "order-48", affected_application_scope_ids: ["scope-9"] }),
    }));
  });

  it("disables the trigger select with the path to an outcome when none exists", async () => {
    renderPaths();
    fireEvent.change(await screen.findByTestId("ip-opposition-specialized-action"), { target: { value: "disposition_review_recorded" } });
    expect(screen.getByLabelText("Trigger event")).toBeDisabled();
    expect(screen.getByText(/This opposition has no order or outcome yet/)).toBeVisible();
  });

  it("offers related applications from this record only, and says so when there are none", async () => {
    renderPaths();
    const related = await screen.findByLabelText<HTMLSelectElement>("Related application");
    expect(related).toBeDisabled();
    expect(screen.getByText(/No other application is recorded on this IP record/)).toBeVisible();
    expect(screen.queryByLabelText(/application ID/i)).toBeNull();
  });

  it("lists this record's other applications by number", async () => {
    fetchWorkflowMock.mockResolvedValue({
      ...workflow,
      related_applications: [{ id: "application-div", application_number: "TM-DIV-48", office: "IP India", filing_phase: "filed" }],
    });
    renderPaths();
    const related = await screen.findByLabelText<HTMLSelectElement>("Related application");
    expect(related).toBeEnabled();
    expect(Array.from(related.options).map((row) => row.textContent)).toEqual([
      "No related application",
      "Application TM-DIV-48 · IP India · Filed",
    ]);
  });

  it("starts the applicable rules from the opposition profile", async () => {
    render(withClient(<IpOppositionSpecializedPaths docket={docket as never} workspace={{ ...workspace, profile: { applicable_rule_version: "Trade Marks Rules, 2017" } } as never} canReview currentMembershipId="membership-48" />));
    fireEvent.change(await screen.findByTestId("ip-opposition-specialized-action"), { target: { value: "hearing_notice_recorded" } });
    expect(screen.getByLabelText("Applicable rules")).toHaveValue("Trade Marks Rules, 2017");
  });
});
