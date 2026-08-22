import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  acknowledgeMock,
  createInstructionMock,
  fetchPortfolioMock,
  scheduleMock,
  transitionMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  acknowledgeMock: vi.fn(),
  createInstructionMock: vi.fn(),
  fetchPortfolioMock: vi.fn(),
  scheduleMock: vi.fn(),
  transitionMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  acknowledgeIpRenewalInstruction: acknowledgeMock,
  createIpRenewalInstruction: createInstructionMock,
  fetchIpRenewalPortfolio: fetchPortfolioMock,
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
  });

  it("shows renewal totals, legal provenance, and date-derived work", async () => {
    render(withClient(<IpRenewalsPage />));

    expect(await screen.findByRole("heading", { name: "Trademark renewals" })).toBeInTheDocument();
    expect((await screen.findAllByText("ASTER device mark")).length).toBeGreaterThan(0);
    expect(screen.getByText("Trade Marks Act and applicable rules")).toBeInTheDocument();
    expect(screen.getByText("registry-rules-2026-v1")).toBeInTheDocument();
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

  it("fails closed when the member lacks IP read access", () => {
    useCapabilityMock.mockImplementation((capability: string) => capability !== "ip:read");
    render(withClient(<IpRenewalsPage />));

    expect(screen.getByText("IP access required")).toBeInTheDocument();
    expect(fetchPortfolioMock).not.toHaveBeenCalled();
  });
});
