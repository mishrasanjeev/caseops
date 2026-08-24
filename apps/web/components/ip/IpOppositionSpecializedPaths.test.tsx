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
    expect(screen.getByLabelText("Canonical hearing")).toHaveValue("hearing-48");
    expect(screen.getByLabelText("Allowed-count candidate")).toBeInTheDocument();
    fireEvent.change(selector, { target: { value: "attendance_recorded" } });
    fireEvent.change(screen.getByLabelText("Appearance"), { target: { value: "nonappearance" } });
    expect(screen.getByLabelText("Consequence candidate")).toBeInTheDocument();
  });
});
