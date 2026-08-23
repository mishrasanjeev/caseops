import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { createHearingMock, fetchWorkflowMock, recordActionMock } = vi.hoisted(() => ({
  createHearingMock: vi.fn(),
  fetchWorkflowMock: vi.fn(),
  recordActionMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  createIpSharedHearing: createHearingMock,
  fetchIpOppositionSharedWorkflow: fetchWorkflowMock,
  recordIpOppositionSharedAction: recordActionMock,
}));

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
    recordActionMock.mockResolvedValue(baseWorkflow);
    createHearingMock.mockResolvedValue({ id: "hearing-43" });
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
