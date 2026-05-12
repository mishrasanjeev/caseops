import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  completeMockHearingMock,
  fetchCalendarSyncStatusMock,
  fetchHearingCoachMock,
  fetchMockHearingsMock,
  fetchProceedingIntelligenceMock,
  generateHearingCoachMock,
  listMatterRemindersMock,
  startMockHearingMock,
  submitMockHearingResponseMock,
  syncHearingToOutlookMock,
  workspaceData,
  useCapabilityMock,
} = vi.hoisted(() => ({
  completeMockHearingMock: vi.fn(),
  fetchCalendarSyncStatusMock: vi.fn(),
  fetchHearingCoachMock: vi.fn(),
  fetchMockHearingsMock: vi.fn(),
  fetchProceedingIntelligenceMock: vi.fn(),
  generateHearingCoachMock: vi.fn(),
  listMatterRemindersMock: vi.fn(),
  startMockHearingMock: vi.fn(),
  submitMockHearingResponseMock: vi.fn(),
  syncHearingToOutlookMock: vi.fn(),
  workspaceData: {
    current: {
      matter: { id: "m1", matter_code: "X", title: "T", status: "active" },
      hearings: [],
      attachments: [],
      invoices: [],
      time_entries: [],
      activity: [],
      tasks: [],
      notes: [],
      court_orders: [],
      cause_list_entries: [],
    } as unknown,
  },
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  completeMockHearing: completeMockHearingMock,
  createMatterHearing: vi.fn(),
  // BUG-032 (Hari 2026-05-09): AddCourtOrderDialog (mounted on the
  // Orders-on-file card) imports these. Mock so the page renders
  // without hitting real fetch; the API-call shape is asserted in
  // the dedicated BUG-032 test below.
  createMatterCourtOrder: vi.fn().mockResolvedValue({ id: "order-new" }),
  uploadMatterAttachment: vi.fn().mockResolvedValue({ id: "att-new" }),
  fetchCalendarSyncStatus: fetchCalendarSyncStatusMock,
  fetchHearingCoach: fetchHearingCoachMock,
  fetchMockHearings: fetchMockHearingsMock,
  fetchProceedingIntelligence: fetchProceedingIntelligenceMock,
  generateHearingCoach: generateHearingCoachMock,
  listMatterReminders: listMatterRemindersMock,
  pullMatterCourtSync: vi.fn(),
  startMockHearing: startMockHearingMock,
  submitMockHearingResponse: submitMockHearingResponseMock,
  syncHearingToOutlook: syncHearingToOutlookMock,
}));

vi.mock("@/lib/use-matter-workspace", () => ({
  useMatterWorkspace: () => ({ data: workspaceData.current }),
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: (cap: string) => useCapabilityMock(cap),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "m1" }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import MatterHearingsPage from "@/app/app/matters/[id]/hearings/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function mockHearingSession(overrides: Record<string, unknown> = {}) {
  return {
    id: "mh1",
    matter_id: "m1",
    source_affidavit_run_id: "run1",
    mode: "client_preparation",
    participant_label: null,
    status: "active",
    review_status: "review_required",
    current_question_id: "mq1",
    disclaimer:
      "Mock hearings are source-backed hearing-preparation decision support, not legal advice.",
    scorecard: {
      total_questions: 1,
      answered_questions: 0,
      responses_recorded: 0,
      answered_question_count: 0,
      unsupported_assertion_count: 0,
      missing_document_reference_count: 0,
      contradiction_count: 0,
      review_required_count: 0,
      average_response_seconds: null,
    },
    created_by_membership_id: "mem1",
    started_at: "2026-05-11T10:00:00Z",
    completed_at: null,
    updated_at: "2026-05-11T10:00:00Z",
    questions: [
      {
        id: "mq1",
        session_id: "mh1",
        matter_id: "m1",
        source_affidavit_run_id: "run1",
        source_affidavit_question_id: "aq1",
        source_affidavit_statement_id: "as1",
        source_attachment_id: "att1",
        turn_index: 0,
        category: "document_support",
        question_text: "Which invoice supports the payment statement?",
        reason: "The affidavit payment statement requires document support.",
        source_quote: "I state that respondent paid Rs. 10,000 under Invoice A.",
        source_chunk_id: "chunk1",
        source_chunk_index: 0,
        page_reference: "page 2",
        difficulty_label: "low",
        status: "pending",
        responses: [],
        created_at: "2026-05-11T10:00:00Z",
        updated_at: "2026-05-11T10:00:00Z",
      },
    ],
    ...overrides,
  };
}

function hearingCoachReport(overrides: Record<string, unknown> = {}) {
  return {
    matter_id: "m1",
    mock_hearing_session_id: "mh1",
    generated_at: "2026-05-12T10:00:00Z",
    status: "supported",
    disclaimer:
      "Hearing coach is a transcript-first training aid for hearing preparation, not legal advice.",
    consent_acknowledged: true,
    metrics: {
      total_responses: 1,
      answered_question_count: 1,
      source_reference_used_count: 1,
      unsupported_assertion_count: 1,
      contradiction_count: 0,
      missing_exhibit_reference_count: 0,
      evasiveness_marker_count: 0,
      overlong_response_count: 0,
      average_clarity_score: 70,
      average_completeness_score: 65,
      review_required_count: 1,
    },
    feedback_items: [
      {
        response_id: "mr1",
        question_id: "mq1",
        mock_hearing_session_id: "mh1",
        source_affidavit_question_id: "aq1",
        source_affidavit_statement_id: "as1",
        source_attachment_id: "att1",
        source_chunk_id: "chunk1",
        source_chunk_index: 0,
        page_reference: "page 2",
        question_text: "Which invoice supports the payment statement?",
        transcript_excerpt: "Invoice A supports it, with a new Pune warehouse detail.",
        source_quote: "I state that respondent paid Rs. 10,000 under Invoice A.",
        answered_question: true,
        source_reference_used: true,
        unsupported_assertion_count: 1,
        contradiction_count: 0,
        clarity_score: 70,
        completeness_score: 65,
        evasiveness_marker: false,
        overlong_response_marker: false,
        missing_exhibit_reference: false,
        review_required: true,
        feedback: ["The answer addresses the question in typed form."],
        improvement_checklist: ["Remove new facts unless a linked record supports them."],
      },
    ],
    limitation_notes: [
      "Uses typed mock-hearing responses and source-backed affidavit question banks only.",
    ],
    ...overrides,
  };
}

describe("MatterHearingsPage", () => {
  beforeEach(() => {
    completeMockHearingMock.mockReset();
    fetchCalendarSyncStatusMock.mockReset();
    fetchHearingCoachMock.mockReset();
    fetchMockHearingsMock.mockReset();
    fetchProceedingIntelligenceMock.mockReset();
    generateHearingCoachMock.mockReset();
    listMatterRemindersMock.mockReset();
    startMockHearingMock.mockReset();
    submitMockHearingResponseMock.mockReset();
    syncHearingToOutlookMock.mockReset();
    listMatterRemindersMock.mockResolvedValue({ matter_id: "m1", reminders: [] });
    fetchMockHearingsMock.mockResolvedValue({
      matter_id: "m1",
      generated_at: "2026-05-11T00:00:00Z",
      disclaimer:
        "Mock hearings are source-backed hearing-preparation decision support, not legal advice.",
      sessions: [],
      latest_session: null,
    });
    fetchHearingCoachMock.mockResolvedValue({
      matter_id: "m1",
      generated_at: "2026-05-12T00:00:00Z",
      status: "no_mock_hearing_responses",
      disclaimer:
        "Hearing coach is a transcript-first training aid for hearing preparation, not legal advice.",
      consent_required: true,
      latest_session_id: null,
      response_count: 0,
      limitation_notes: [
        "Uses typed mock-hearing responses and source-backed affidavit question banks only.",
      ],
    });
    fetchProceedingIntelligenceMock.mockResolvedValue({
      matter_id: "m1",
      generated_at: "2026-05-11T00:00:00Z",
      disclaimer:
        "Proceeding intelligence is source-backed decision support for legal teams. It is not legal advice; counsel must review extracted directions before external use or client-facing communication.",
      orders: [],
      pending_compliance_items: [],
    });
    fetchCalendarSyncStatusMock.mockResolvedValue({
      provider_available: true,
      durable_automation: "blocked_pending_temporal",
      connections: [],
      syncs: [],
    });
    useCapabilityMock.mockReset();
    useCapabilityMock.mockImplementation(() => false);
    workspaceData.current = {
      matter: { id: "m1", matter_code: "X", title: "T", status: "active" },
      hearings: [],
      attachments: [],
      invoices: [],
      time_entries: [],
      activity: [],
      tasks: [],
      notes: [],
      court_orders: [],
      cause_list_entries: [],
    } as unknown;
  });

  it("renders Outlook sync action and per-hearing status for calendar sync users", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "calendar:sync");
    workspaceData.current = {
      ...(workspaceData.current as { matter: unknown }),
      hearings: [
        {
          id: "h-sync",
          hearing_on: "2026-06-10",
          purpose: "Arguments",
          status: "scheduled",
        },
      ],
      court_orders: [],
      cause_list_entries: [],
    } as unknown;
    fetchCalendarSyncStatusMock.mockResolvedValue({
      provider_available: true,
      durable_automation: "blocked_pending_temporal",
      // BUG-044 (Hari 2026-05-11): the page now suppresses the Sync
      // button when connections is empty (it's pre-empting a 409).
      // For the connected path we need at least one connection.
      connections: [
        {
          id: "conn-1",
          company_id: "c1",
          membership_id: "mem-1",
          provider: "outlook",
          provider_account_id: "acct-1",
          display_email: "owner@firm.in",
          status: "connected",
          last_synced_at: "2026-05-07T10:00:00Z",
          created_at: "2026-05-07T09:00:00Z",
          updated_at: "2026-05-07T10:00:00Z",
        },
      ],
      syncs: [
        {
          id: "sync-1",
          company_id: "c1",
          calendar_connection_id: "conn-1",
          source_type: "matter_hearing",
          source_id: "h-sync",
          provider_event_id: "remote-1",
          sync_status: "synced",
          last_error: null,
          last_synced_at: "2026-05-07T10:00:00Z",
          created_at: "2026-05-07T09:00:00Z",
          updated_at: "2026-05-07T10:00:00Z",
        },
      ],
    });

    render(withClient(<MatterHearingsPage />));

    expect(await screen.findByTestId("hearing-outlook-sync-h-sync")).toBeInTheDocument();
    expect(await screen.findByText(/synced/i)).toBeInTheDocument();
  });

  it("BUG-044 (Hari 2026-05-11): renders Connect Outlook link, NOT Sync, when there is no Outlook connection", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "calendar:sync");
    workspaceData.current = {
      ...(workspaceData.current as { matter: unknown }),
      hearings: [
        {
          id: "h-noconn",
          hearing_on: "2026-06-10",
          purpose: "Arguments",
          status: "scheduled",
        },
      ],
      court_orders: [],
      cause_list_entries: [],
    } as unknown;
    // No connections + no syncs — the broken state Hari hit.
    fetchCalendarSyncStatusMock.mockResolvedValue({
      provider_available: true,
      durable_automation: "blocked_pending_temporal",
      connections: [],
      syncs: [],
    });

    render(withClient(<MatterHearingsPage />));

    const connect = await screen.findByTestId("hearing-outlook-connect-h-noconn");
    expect(connect).toBeInTheDocument();
    expect(connect.getAttribute("href")).toBe("/app/calendar");
    expect(screen.queryByTestId("hearing-outlook-sync-h-noconn")).toBeNull();
  });

  it("renders the Scheduled hearings card and the Schedule hearing trigger", () => {
    render(withClient(<MatterHearingsPage />));
    expect(screen.getByText(/Upcoming hearings/i)).toBeInTheDocument();
    expect(screen.getByTestId("schedule-hearing-open")).toBeInTheDocument();
  });

  it("splits completed and upcoming hearings and sorts orders", () => {
    workspaceData.current = {
      ...(workspaceData.current as { matter: unknown }),
      hearings: [
        {
          id: "h-upcoming",
          hearing_on: "2026-06-10",
          purpose: "Arguments",
          status: "scheduled",
        },
        {
          id: "h-completed",
          hearing_on: "2026-05-01",
          purpose: "Interim hearing",
          status: "completed",
          outcome_note: "Stay continued.",
        },
      ],
      court_orders: [
        {
          id: "o-new",
          title: "New stay order",
          order_date: "2026-06-01",
          order_kind: "interim_order",
          is_interim_order: true,
          stay_status: "granted",
          summary: "Stay granted.",
        },
        {
          id: "o-old",
          title: "Old daily order",
          order_date: "2026-05-01",
          order_kind: "daily_order",
          stay_status: "none",
          summary: "Directions issued.",
        },
      ],
      cause_list_entries: [],
    } as unknown;

    render(withClient(<MatterHearingsPage />));

    expect(screen.getByText(/Upcoming hearings/i)).toBeInTheDocument();
    expect(screen.getByText(/Completed hearings/i)).toBeInTheDocument();
    expect(screen.getByText("Arguments")).toBeInTheDocument();
    expect(screen.getByText("Interim hearing")).toBeInTheDocument();
    expect(screen.getByText("Interim order")).toBeInTheDocument();
    expect(screen.getByText("Stay granted")).toBeInTheDocument();
    expect(screen.getAllByText(/New stay order|Old daily order/)[0]).toHaveTextContent(
      "New stay order",
    );

    fireEvent.click(screen.getByRole("button", { name: "Oldest" }));

    expect(screen.getAllByText(/New stay order|Old daily order/)[0]).toHaveTextContent(
      "Old daily order",
    );
  });

  it("renders cause-list bench as clickable judge links when resolved", () => {
    workspaceData.current = {
      ...(workspaceData.current as { matter: unknown }),
      matter: {
        id: "m1",
        matter_code: "X",
        title: "T",
        status: "active",
      },
      hearings: [],
      attachments: [],
      invoices: [],
      time_entries: [],
      activity: [],
      tasks: [],
      notes: [],
      court_orders: [],
      cause_list_entries: [
        {
          id: "cle1",
          listing_date: "2026-05-01",
          bench_name: "Justice Aalia Banerjee & Justice Brijesh Karandikar",
          item_number: "12",
          stage: "for arguments",
          resolved_bench: [
            {
              judge_id: "j-aalia",
              matched_alias: "Justice Aalia Banerjee",
              confidence: "exact",
            },
            {
              judge_id: "j-brijesh",
              matched_alias: "Justice Brijesh Karandikar",
              confidence: "initial_surname",
            },
          ],
        },
      ],
    } as unknown;

    render(withClient(<MatterHearingsPage />));

    expect(screen.getByTestId("cause-list-bench-resolved")).toBeInTheDocument();
    const aaliaLink = screen.getByRole("link", {
      name: /Justice Aalia Banerjee/i,
    });
    expect(aaliaLink).toHaveAttribute("href", "/app/courts/judges/j-aalia");
    const brijeshLink = screen.getByRole("link", {
      name: /Justice Brijesh Karandikar/i,
    });
    expect(brijeshLink).toHaveAttribute(
      "href",
      "/app/courts/judges/j-brijesh",
    );
  });

  it("falls back to free-text bench_name when resolved_bench is null", () => {
    workspaceData.current = {
      ...(workspaceData.current as { matter: unknown }),
      matter: {
        id: "m1",
        matter_code: "X",
        title: "T",
        status: "active",
      },
      hearings: [],
      attachments: [],
      invoices: [],
      time_entries: [],
      activity: [],
      tasks: [],
      notes: [],
      court_orders: [],
      cause_list_entries: [
        {
          id: "cle2",
          listing_date: "2026-05-02",
          bench_name: "Some unresolvable bench string",
          item_number: "13",
          stage: "for arguments",
          resolved_bench: null,
        },
      ],
    } as unknown;
    render(withClient(<MatterHearingsPage />));
    expect(
      screen.getByText(/Some unresolvable bench string/i),
    ).toBeInTheDocument();
    // No clickable judge link when resolved_bench is null.
    expect(screen.queryByTestId("cause-list-bench-resolved")).toBeNull();
  });

  // BUG-032 (Hari 2026-05-09): Orders-on-file card now exposes an
  // explicit Add-order affordance (the previous symptom: no path to
  // create an order from this page; the documents-page Linked-order
  // selector was therefore empty for any matter without a court
  // sync). The dialog shows up in the card header AND in the empty
  // state.
  it("BUG-032: renders Add-order affordance on Orders-on-file (header + empty state)", () => {
    workspaceData.current = {
      ...(workspaceData.current as { matter: unknown }),
      matter: {
        id: "m1",
        matter_code: "X",
        title: "T",
        status: "active",
      },
      hearings: [],
      attachments: [],
      invoices: [],
      time_entries: [],
      activity: [],
      tasks: [],
      notes: [],
      court_orders: [],
      cause_list_entries: [],
    } as unknown;

    render(withClient(<MatterHearingsPage />));
    // Header + empty-state both mount the dialog trigger; the
    // dialog uses a single testid so we expect at least 2 trigger
    // buttons on screen.
    const triggers = screen.getAllByTestId("add-court-order-open");
    expect(triggers.length).toBeGreaterThanOrEqual(2);
  });

  it("renders proceeding intelligence directions with due date and source link", async () => {
    fetchProceedingIntelligenceMock.mockResolvedValue({
      matter_id: "m1",
      generated_at: "2026-05-11T00:00:00Z",
      disclaimer:
        "Proceeding intelligence is source-backed decision support for legal teams. It is not legal advice; counsel must review extracted directions before external use or client-facing communication.",
      orders: [
        {
          court_order_id: "o1",
          sync_run_id: "sync-1",
          title: "Daily order sheet",
          order_date: "2026-05-06",
          source: "manual-test",
          source_reference: "fixture:order",
          order_attachment_id: "att-1",
          extraction_status: "supported",
          missing_data: [],
          signals: [
            {
              id: "sig-1",
              matter_id: "m1",
              court_order_id: "o1",
              sync_run_id: "sync-1",
              signal_type: "reply_affidavit_deadline",
              signal_text: "Reply or affidavit deadline due 2026-05-20",
              action_required: "Respondent shall file reply affidavit by 20.05.2026.",
              due_on: "2026-05-20",
              hearing_on: null,
              order_kind: null,
              confidence_label: "high",
              source_snippet: "Respondent shall file reply affidavit by 20.05.2026.",
              review_status: "review_required",
              generated_task_id: "task-1",
              generated_deadline_id: "deadline-1",
              extraction_method: "deterministic",
              parser_version: "caseops-proceeding-deterministic-v1",
              created_at: "2026-05-11T00:00:00Z",
              updated_at: "2026-05-11T00:00:00Z",
            },
          ],
        },
      ],
      pending_compliance_items: [
        {
          id: "sig-1",
          matter_id: "m1",
          court_order_id: "o1",
          sync_run_id: "sync-1",
          signal_type: "reply_affidavit_deadline",
          signal_text: "Reply or affidavit deadline due 2026-05-20",
          action_required: "Respondent shall file reply affidavit by 20.05.2026.",
          due_on: "2026-05-20",
          hearing_on: null,
          order_kind: null,
          confidence_label: "high",
          source_snippet: "Respondent shall file reply affidavit by 20.05.2026.",
          review_status: "review_required",
          generated_task_id: "task-1",
          generated_deadline_id: "deadline-1",
          extraction_method: "deterministic",
          parser_version: "caseops-proceeding-deterministic-v1",
          created_at: "2026-05-11T00:00:00Z",
          updated_at: "2026-05-11T00:00:00Z",
        },
      ],
    });

    render(withClient(<MatterHearingsPage />));

    expect(await screen.findByText("Proceeding intelligence")).toBeInTheDocument();
    expect(await screen.findByText("Reply / affidavit deadline")).toBeInTheDocument();
    expect(screen.getByText(/Respondent shall file reply affidavit/i)).toBeInTheDocument();
    expect(screen.getByText(/Due 20 May 2026/i)).toBeInTheDocument();
    expect(screen.getByText(/Human review/i)).toBeInTheDocument();
    expect(screen.getAllByText(/not legal advice/i).length).toBeGreaterThan(0);
    expect(screen.getByText("Linked task/deadline")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View source" })).toHaveAttribute(
      "href",
      "/app/matters/m1/documents/att-1/view",
    );
  });

  it("renders proceeding insufficient-source state without duplicate actions", async () => {
    fetchProceedingIntelligenceMock.mockResolvedValue({
      matter_id: "m1",
      generated_at: "2026-05-11T00:00:00Z",
      disclaimer:
        "Proceeding intelligence is source-backed decision support for legal teams. It is not legal advice.",
      orders: [
        {
          court_order_id: "o1",
          sync_run_id: null,
          title: "Summary-only order",
          order_date: "2026-05-06",
          source: "manual-test",
          source_reference: null,
          order_attachment_id: null,
          extraction_status: "insufficient_source_text",
          missing_data: ["raw_order_text"],
          signals: [],
        },
      ],
      pending_compliance_items: [],
    });
    const view = render(withClient(<MatterHearingsPage />));

    expect(await screen.findByText("Insufficient source text")).toBeInTheDocument();
    expect(screen.getByText(/Summaries are not used/i)).toBeInTheDocument();

    view.rerender(withClient(<MatterHearingsPage />));

    expect(screen.queryAllByRole("link", { name: "View source" })).toHaveLength(0);
  });

  it("starts a mock hearing session and renders source-backed questions", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "hearing_packs:generate");
    const session = mockHearingSession();
    startMockHearingMock.mockResolvedValue(session);

    render(withClient(<MatterHearingsPage />));

    expect(await screen.findByTestId("mock-hearing-section")).toBeInTheDocument();
    expect(await screen.findByText("No mock hearing sessions")).toBeInTheDocument();
    await userEvent.click(screen.getByTestId("mock-hearing-start"));

    expect(await screen.findByText("Which invoice supports the payment statement?")).toBeInTheDocument();
    expect(screen.getByText("I state that respondent paid Rs. 10,000 under Invoice A.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View source" })).toHaveAttribute(
      "href",
      "/app/matters/m1/documents/att1/view",
    );
  });

  it("submitting a mock hearing response renders observable feedback and scorecard", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "hearing_packs:generate");
    const answeredSession = mockHearingSession({
      current_question_id: null,
      scorecard: {
        total_questions: 1,
        answered_questions: 1,
        responses_recorded: 1,
        answered_question_count: 1,
        unsupported_assertion_count: 1,
        missing_document_reference_count: 0,
        contradiction_count: 0,
        review_required_count: 1,
        average_response_seconds: null,
      },
      questions: [
        {
          ...mockHearingSession().questions[0],
          status: "answered",
          responses: [
            {
              id: "mr1",
              session_id: "mh1",
              question_id: "mq1",
              matter_id: "m1",
              response_text: "Invoice A supports it, with a new Pune warehouse detail.",
              response_word_count: 9,
              elapsed_seconds: null,
              answered_question: true,
              consistency_with_affidavit: true,
              unsupported_assertion_added: true,
              missing_document_reference: false,
              contradiction_with_source: false,
              response_completeness: "medium",
              confidence_label: "medium",
              feedback_text: "Response adds facts not visible in the source quote.",
              source_quote: "I state that respondent paid Rs. 10,000 under Invoice A.",
              review_required: true,
              review_status: "review_required",
              created_at: "2026-05-11T10:02:00Z",
              updated_at: "2026-05-11T10:02:00Z",
            },
          ],
        },
      ],
    });
    fetchMockHearingsMock.mockResolvedValue({
      matter_id: "m1",
      generated_at: "2026-05-11T10:00:00Z",
      disclaimer:
        "Mock hearings are source-backed hearing-preparation decision support, not legal advice.",
      sessions: [mockHearingSession()],
      latest_session: mockHearingSession(),
    });
    submitMockHearingResponseMock.mockResolvedValue(answeredSession);

    render(withClient(<MatterHearingsPage />));

    expect(await screen.findByText("Which invoice supports the payment statement?")).toBeInTheDocument();
    await userEvent.type(
      screen.getByTestId("mock-hearing-response-input"),
      "Invoice A supports it, with a new Pune warehouse detail.",
    );
    await userEvent.click(screen.getByTestId("mock-hearing-submit-response"));

    expect(await screen.findByTestId("mock-hearing-feedback")).toHaveTextContent(
      "Response adds facts not visible in the source quote.",
    );
    expect(screen.getByTestId("mock-hearing-scorecard")).toHaveTextContent("New assertions");
    expect(screen.getByTestId("mock-hearing-scorecard")).toHaveTextContent("1");
  });

  it("keeps mock hearing copy within legal-safety boundaries", async () => {
    render(withClient(<MatterHearingsPage />));

    const section = await screen.findByTestId("mock-hearing-section");
    expect(section).toHaveTextContent("not legal advice");
    expect(section.textContent).not.toMatch(
      /guaranteed|will win|emotional|psychological|mental state|biometric|voice stress|voice/i,
    );
  });

  it("renders hearing coach consent gate and source-linked report", async () => {
    useCapabilityMock.mockImplementation((cap: string) => cap === "hearing_packs:generate");
    const answeredSession = mockHearingSession({
      current_question_id: null,
      questions: [
        {
          ...mockHearingSession().questions[0],
          status: "answered",
          responses: [
            {
              id: "mr1",
              session_id: "mh1",
              question_id: "mq1",
              matter_id: "m1",
              response_text: "Invoice A supports it, with a new Pune warehouse detail.",
              response_word_count: 9,
              elapsed_seconds: null,
              answered_question: true,
              consistency_with_affidavit: true,
              unsupported_assertion_added: true,
              missing_document_reference: false,
              contradiction_with_source: false,
              response_completeness: "medium",
              confidence_label: "medium",
              feedback_text: "Response adds facts not visible in the source quote.",
              source_quote: "I state that respondent paid Rs. 10,000 under Invoice A.",
              review_required: true,
              review_status: "review_required",
              created_at: "2026-05-11T10:02:00Z",
              updated_at: "2026-05-11T10:02:00Z",
            },
          ],
        },
      ],
    });
    fetchMockHearingsMock.mockResolvedValue({
      matter_id: "m1",
      generated_at: "2026-05-11T10:00:00Z",
      disclaimer:
        "Mock hearings are source-backed hearing-preparation decision support, not legal advice.",
      sessions: [answeredSession],
      latest_session: answeredSession,
    });
    fetchHearingCoachMock.mockResolvedValue({
      matter_id: "m1",
      generated_at: "2026-05-12T00:00:00Z",
      status: "consent_required",
      disclaimer:
        "Hearing coach is a transcript-first training aid for hearing preparation, not legal advice.",
      consent_required: true,
      latest_session_id: "mh1",
      response_count: 1,
      limitation_notes: [
        "Uses typed mock-hearing responses and source-backed affidavit question banks only.",
      ],
    });
    generateHearingCoachMock.mockResolvedValue(hearingCoachReport());

    render(withClient(<MatterHearingsPage />));

    const section = await screen.findByTestId("hearing-coach-section");
    expect(section).toHaveTextContent("Transcript-first training aid");
    const button = await screen.findByTestId("hearing-coach-generate");
    expect(button).toBeDisabled();
    await userEvent.click(await screen.findByTestId("hearing-coach-consent"));
    expect(button).not.toBeDisabled();
    await userEvent.click(button);

    expect(generateHearingCoachMock).toHaveBeenCalledWith({
      matterId: "m1",
      sessionId: "mh1",
      acknowledged: true,
    });
    const report = await screen.findByTestId("hearing-coach-report");
    expect(report).toHaveTextContent("Clarity");
    expect(report).toHaveTextContent("Source refs");
    expect(report).toHaveTextContent("Invoice A supports it");
    expect(report).toHaveTextContent("Remove new facts");
    expect(within(report).getByRole("link", { name: "View source" })).toHaveAttribute(
      "href",
      "/app/matters/m1/documents/att1/view",
    );
  });

  it("renders hearing coach empty and error states", async () => {
    const view = render(withClient(<MatterHearingsPage />));

    expect(await screen.findByText("No typed responses yet")).toBeInTheDocument();
    view.unmount();

    fetchHearingCoachMock.mockRejectedValue(new Error("status failed"));
    render(withClient(<MatterHearingsPage />));

    expect(
      await screen.findByText("Hearing coach status could not be loaded."),
    ).toBeInTheDocument();
  });

  it("keeps hearing coach copy within transcript-first legal-safety boundaries", async () => {
    render(withClient(<MatterHearingsPage />));

    const section = await screen.findByTestId("hearing-coach-section");
    expect(section).toHaveTextContent("not legal advice");
    expect(section.textContent).not.toMatch(
      /guaranteed|will win|will lose|win probability|loss probability|judge reputation|judge likes|judge dislikes|favorable judge|emotional|psychological|mental|biometric|stress|sentiment|personality|lie detection|voice|audio/i,
    );
  });
});
