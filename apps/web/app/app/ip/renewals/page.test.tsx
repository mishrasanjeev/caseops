import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  acknowledgeMock,
  createInstructionMock,
  fetchPortfolioMock,
  referencesMock,
  scheduleMock,
  transitionMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  acknowledgeMock: vi.fn(),
  createInstructionMock: vi.fn(),
  fetchPortfolioMock: vi.fn(),
  referencesMock: vi.fn(),
  scheduleMock: vi.fn(),
  transitionMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  acknowledgeIpRenewalInstruction: acknowledgeMock,
  createIpRenewalInstruction: createInstructionMock,
  fetchIpRenewalPortfolio: fetchPortfolioMock,
  fetchIpRenewalTransitionReferences: referencesMock,
  scheduleIpRenewalReminders: scheduleMock,
  transitionIpRenewalTerm: transitionMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (capability: string) => useCapabilityMock(capability),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import IpRenewalsPage from "@/app/app/ip/renewals/page";

const TERM = {
  id: "term-1",
  docket_id: "docket-1",
  term_sequence: 1,
  registration_event_id: "event-registration",
  renewal_deadline_id: "deadline-renewal",
  grace_deadline_id: "deadline-grace",
  fee_cost_item_id: null,
  filing_initiated_reference: null,
  filing_event_id: null,
  acceptance_event_id: null,
  certificate_document_id: null,
  next_term_deadline_id: null,
  state: "due" as const,
  version: 1,
  completed_at: null,
  created_at: "2026-08-22T04:00:00Z",
  updated_at: "2026-08-22T04:00:00Z",
  instructions: [],
};

const RESPONSE = {
  generated_at: "2026-08-22T05:00:00Z",
  counts: {
    total: 1,
    due: 1,
    instructed: 0,
    filing_in_progress: 0,
    filed: 0,
    accepted: 0,
    grace: 0,
    overdue: 0,
    completed: 0,
    cancelled: 0,
    action_required: 1,
  },
  items: [
    {
      docket_id: "docket-1",
      docket_title: "ASTER device mark",
      primary_identifier: "TM-421",
      record_type: "trademark",
      term: TERM,
      renewal_deadline: {
        id: "deadline-renewal",
        title: "Renewal due",
        deadline_kind: "renewal",
        result_on: "2026-09-30",
        result_at: null,
        state: "confirmed",
        certainty: "verified",
        rule_citation: "Trade Marks Act and applicable rules",
        source_version: "registry-rules-2026-v1",
        explanation: "Ten years from verified registration date",
      },
      grace_deadline: {
        id: "deadline-grace",
        title: "Grace period ends",
        deadline_kind: "renewal_grace",
        result_on: "2027-03-31",
        result_at: null,
        state: "confirmed",
        certainty: "verified",
        rule_citation: "Trade Marks Rules",
        source_version: "registry-rules-2026-v1",
        explanation: "Verified grace period",
      },
      fee: {
        id: "fee-1",
        category: "official_fee",
        description: "Renewal official fee quote",
        cost_nature: "estimate",
        billable: false,
        evidence_reference: "registry://fees/renewal-v1",
        billing_link_type: null,
        billing_link_id: null,
        reconciliation_status: "unlinked",
        reconciled_at: null,
      },
      reporting_state: "due" as const,
      calendar_phase: "due" as const,
      action_required: "request_instruction" as const,
      days_until_renewal: 39,
      days_until_grace_end: 221,
      state_reconciliation_required: false,
      reminders: {
        total: 0,
        queued: 0,
        sent_or_delivered: 0,
        cancelled: 0,
        blocked_or_failed: 0,
        next_scheduled_for: null,
        last_delivered_at: null,
      },
    },
  ],
};

const REFERENCES = {
  term_id: "term-1",
  filing_events: [{ id: "event-filing", event_kind: "renewal_filing", effective_at: "2026-09-01T00:00:00Z", source_reference: "registry://filing/1", reason: null }],
  acceptance_events: [{ id: "event-acceptance", event_kind: "renewal_acceptance", effective_at: "2026-09-20T00:00:00Z", source_reference: "registry://acceptance/1", reason: null }],
  certificate_documents: [{ id: "document-certificate", title: "Renewal certificate", current_version: 1 }],
  next_term_deadlines: [
    { id: "deadline-renewal", title: "Renewal due", result_on: "2026-09-30", state: "confirmed", trigger_event_id: "event-registration" },
    { id: "deadline-next", title: "Next renewal due", result_on: "2036-09-30", state: "confirmed", trigger_event_id: "event-acceptance" },
  ],
};

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("IpRenewalsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useCapabilityMock.mockReturnValue(true);
    fetchPortfolioMock.mockResolvedValue(RESPONSE);
    scheduleMock.mockResolvedValue({ created_count: 4, existing_count: 0, intents: [] });
    createInstructionMock.mockResolvedValue(TERM);
    acknowledgeMock.mockResolvedValue({ ...TERM, state: "instructed" });
    transitionMock.mockResolvedValue({ ...TERM, state: "filing_in_progress" });
    referencesMock.mockResolvedValue(REFERENCES);
  });

  it("BUG-015 completes a renewal by choosing validator-backed evidence, never typing record IDs", async () => {
    const user = userEvent.setup();
    const accepted = { ...TERM, state: "accepted" as const, filing_event_id: "event-filing", acceptance_event_id: "event-acceptance" };
    fetchPortfolioMock.mockResolvedValue({ ...RESPONSE, items: [{ ...RESPONSE.items[0], term: accepted }] });
    transitionMock.mockResolvedValue({ ...accepted, state: "completed" });
    render(withClient(<IpRenewalsPage />));
    await screen.findByText("ASTER device mark");
    expect(screen.queryByLabelText(/ID$/)).not.toBeInTheDocument();
    // Recorded evidence is shown locked: the validator refuses to replace it.
    const filing = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Confirmed filing event" });
    expect(filing).toBeDisabled();
    expect(filing).toHaveAccessibleDescription(/renewal evidence cannot be replaced/);
    const certificate = screen.getByRole<HTMLSelectElement>("combobox", { name: "Accepted certificate" });
    await waitFor(() => expect(certificate).toBeEnabled());
    expect(Array.from(certificate.options, (option) => option.value)).toEqual(["", "document-certificate"]);
    // Only a deadline calculated from this term's acceptance event is offered.
    const nextTerm = screen.getByRole<HTMLSelectElement>("combobox", { name: "Next-term renewal deadline" });
    expect(Array.from(nextTerm.options, (option) => option.value)).toEqual(["", "deadline-next"]);
    await user.selectOptions(certificate, "document-certificate");
    await user.selectOptions(nextTerm, "deadline-next");
    await user.type(screen.getByLabelText("Reason"), "Certificate and next term verified");
    await user.click(screen.getByRole("button", { name: "Record transition" }));
    await waitFor(() => expect(transitionMock).toHaveBeenCalledWith(expect.objectContaining({
      targetState: "completed",
      filingEventId: "event-filing",
      acceptanceEventId: "event-acceptance",
      certificateDocumentId: "document-certificate",
      nextTermDeadlineId: "deadline-next",
    })));
    expect(referencesMock).toHaveBeenCalledWith({ docketId: "docket-1", termId: "term-1" });
  });

  it("BUG-015 disables a renewal evidence choice the docket cannot supply and says where to add it", async () => {
    const user = userEvent.setup();
    referencesMock.mockResolvedValue({ ...REFERENCES, filing_events: [] });
    render(withClient(<IpRenewalsPage />));
    await screen.findByText("ASTER device mark");
    await user.selectOptions(screen.getByLabelText("Next state"), "filed");
    const filing = screen.getByRole<HTMLSelectElement>("combobox", { name: "Confirmed filing event" });
    await waitFor(() => expect(filing.options[0]).toHaveTextContent("None on this docket"));
    expect(filing).toBeDisabled();
    expect(filing).toHaveAccessibleDescription(/No confirmed renewal filing event is on this docket/);
    expect(screen.getByRole("link", { name: "Record and confirm it on the docket" })).toHaveAttribute("href", "/app/ip?docket=docket-1");
    await user.type(screen.getByLabelText("Reason"), "Registry filing acknowledged");
    expect(screen.getByRole("button", { name: "Record transition" })).toBeDisabled();
    expect(transitionMock).not.toHaveBeenCalled();
  });

  it("BUG-015 shows a renewal evidence load failure with a retry", async () => {
    const user = userEvent.setup();
    referencesMock.mockRejectedValueOnce(new Error("References unavailable."));
    render(withClient(<IpRenewalsPage />));
    await screen.findByText("ASTER device mark");
    await user.selectOptions(screen.getByLabelText("Next state"), "filed");
    const filing = screen.getByRole<HTMLSelectElement>("combobox", { name: "Confirmed filing event" });
    await waitFor(() => expect(filing).toHaveAccessibleDescription(/References unavailable\./));
    await user.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(filing).toBeEnabled());
    expect(Array.from(filing.options, (option) => option.value)).toEqual(["", "event-filing"]);
  });

  it("shows renewal totals, legal provenance, and date-derived work", async () => {
    render(withClient(<IpRenewalsPage />));

    expect(await screen.findByRole("heading", { name: "Trademark renewals" })).toBeInTheDocument();
    expect((await screen.findAllByText("ASTER device mark")).length).toBeGreaterThan(0);
    expect(await screen.findByText("Trade Marks Act and applicable rules")).toBeInTheDocument();
    expect(screen.getByText("registry-rules-2026-v1")).toBeInTheDocument();
    expect(screen.getByText(/Renewal official fee quote/)).toBeInTheDocument();
    expect(screen.getByText("Reconciliation: unlinked")).toBeInTheDocument();
    expect(screen.getByText("Request client instruction")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open IP docket" })).toHaveAttribute(
      "href",
      "/app/ip?docket=docket-1",
    );
  });

  it("schedules idempotent instruction notifications from the selected term", async () => {
    const user = userEvent.setup();
    render(withClient(<IpRenewalsPage />));

    await user.click(await screen.findByRole("button", { name: "Schedule instruction notifications" }));
    await waitFor(() =>
      expect(scheduleMock).toHaveBeenCalledWith({ docketId: "docket-1", term: TERM }),
    );
  });

  it("records a source-backed client instruction", async () => {
    const user = userEvent.setup();
    render(withClient(<IpRenewalsPage />));
    await screen.findByText("ASTER device mark");

    await user.type(screen.getByLabelText("Authority name"), "Authorized client contact");
    await user.type(screen.getByLabelText("Authority reference"), "BOARD-2026-08");
    await user.type(screen.getByLabelText("Evidence reference"), "portal://instruction/1");
    await user.click(screen.getByRole("button", { name: "Record instruction" }));

    await waitFor(() =>
      expect(createInstructionMock).toHaveBeenCalledWith(
        expect.objectContaining({
          docketId: "docket-1",
          termId: "term-1",
          decision: "renew",
          authorityName: "Authorized client contact",
          evidenceRefs: ["portal://instruction/1"],
        }),
      ),
    );
  });

  it("requires filing-initiation evidence before submitting that transition", async () => {
    const user = userEvent.setup();
    render(withClient(<IpRenewalsPage />));
    await screen.findByText("ASTER device mark");

    await user.selectOptions(screen.getByLabelText("Next state"), "filing_in_progress");
    await user.type(screen.getByLabelText("Reason"), "Provider filing has started");
    expect(screen.getByRole("button", { name: "Record transition" })).toBeDisabled();
    await user.type(screen.getByLabelText("Filing initiation reference"), "PROVIDER-ACK-1");
    await user.click(screen.getByRole("button", { name: "Record transition" }));

    await waitFor(() =>
      expect(transitionMock).toHaveBeenCalledWith(
        expect.objectContaining({
          targetState: "filing_in_progress",
          filingInitiatedReference: "PROVIDER-ACK-1",
          acceptanceEventId: null,
        }),
      ),
    );
  });

  it("accepts a pending renew instruction and does not confuse it with filing", async () => {
    fetchPortfolioMock.mockResolvedValue({
      ...RESPONSE,
      items: [
        {
          ...RESPONSE.items[0],
          action_required: "review_instruction",
          term: {
            ...TERM,
            instructions: [
              {
                id: "instruction-1",
                instruction_version: 1,
                row_version: 1,
                decision: "renew",
                status: "pending",
                scope_json: { description: "All classes" },
                options_json: [],
                instruction_deadline_at: null,
                source_channel: "client_portal",
                authority_name: "Authorized client contact",
                authority_reference: "BOARD-2026-08",
                evidence_refs_json: ["portal://instruction/1"],
                received_at: "2026-08-22T04:30:00Z",
                acknowledgement_reason: null,
                updated_at: "2026-08-22T04:30:00Z",
              },
            ],
          },
        },
      ],
    });
    const user = userEvent.setup();
    render(withClient(<IpRenewalsPage />));
    await screen.findByText("Authorized client contact");

    fireEvent.change(screen.getByLabelText("Review reason"), {
      target: { value: "Authority and scope verified" },
    });
    await user.click(screen.getByRole("button", { name: "Accept" }));

    await waitFor(() =>
      expect(acknowledgeMock).toHaveBeenCalledWith(
        expect.objectContaining({ status: "accepted", reason: "Authority and scope verified" }),
      ),
    );
    expect(transitionMock).not.toHaveBeenCalled();
  });

  it("records a versioned revision without replacing the current instruction in place", async () => {
    const acceptedInstruction = {
      id: "instruction-1",
      instruction_version: 1,
      row_version: 2,
      decision: "renew" as const,
      status: "accepted" as const,
      scope_json: { description: "All classes" },
      options_json: [],
      instruction_deadline_at: null,
      source_channel: "client_portal",
      authority_name: "Authorized client contact",
      authority_reference: "BOARD-2026-08",
      evidence_refs_json: ["portal://instruction/1"],
      received_at: "2026-08-22T04:30:00Z",
      acknowledgement_reason: "Authority verified",
      updated_at: "2026-08-22T04:35:00Z",
    };
    fetchPortfolioMock.mockResolvedValue({
      ...RESPONSE,
      items: [
        {
          ...RESPONSE.items[0],
          term: { ...TERM, state: "instructed", version: 2, instructions: [acceptedInstruction] },
        },
      ],
    });
    const user = userEvent.setup();
    render(withClient(<IpRenewalsPage />));
    await user.click(await screen.findByRole("button", { name: "Record revised instruction" }));
    await user.type(screen.getByLabelText("Revised authority name"), "Revised authority");
    await user.type(screen.getByLabelText("Revised evidence reference"), "portal://instruction/2");
    await user.click(screen.getByRole("button", { name: "Record revision" }));

    await waitFor(() =>
      expect(createInstructionMock).toHaveBeenCalledWith(
        expect.objectContaining({ currentInstruction: acceptedInstruction }),
      ),
    );
  });

  it("fails closed when the member lacks IP read access", () => {
    useCapabilityMock.mockImplementation((capability: string) => capability !== "ip:read");
    render(withClient(<IpRenewalsPage />));

    expect(screen.getByText("IP access required")).toBeInTheDocument();
    expect(fetchPortfolioMock).not.toHaveBeenCalled();
  });
});
