import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchCalendarSyncStatusMock,
  listMatterRemindersMock,
  syncHearingToOutlookMock,
  workspaceData,
  useCapabilityMock,
} = vi.hoisted(() => ({
  fetchCalendarSyncStatusMock: vi.fn(),
  listMatterRemindersMock: vi.fn(),
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
  createMatterHearing: vi.fn(),
  // BUG-032 (Hari 2026-05-09): AddCourtOrderDialog (mounted on the
  // Orders-on-file card) imports these. Mock so the page renders
  // without hitting real fetch; the API-call shape is asserted in
  // the dedicated BUG-032 test below.
  createMatterCourtOrder: vi.fn().mockResolvedValue({ id: "order-new" }),
  uploadMatterAttachment: vi.fn().mockResolvedValue({ id: "att-new" }),
  fetchCalendarSyncStatus: fetchCalendarSyncStatusMock,
  listMatterReminders: listMatterRemindersMock,
  pullMatterCourtSync: vi.fn(),
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

describe("MatterHearingsPage", () => {
  beforeEach(() => {
    fetchCalendarSyncStatusMock.mockReset();
    listMatterRemindersMock.mockReset();
    syncHearingToOutlookMock.mockReset();
    listMatterRemindersMock.mockResolvedValue({ matter_id: "m1", reminders: [] });
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
      connections: [],
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
});
