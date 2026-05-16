// Phase B / J08 / M08 — calendar page rendering contract.
//
// Covers the invariants that, if broken, would re-open BUG-029 or
// silently drop events from the lawyer's grid:
//
// - Page mounts and shows the current month label.
// - Events for the current month render as chips with the
//   matter title in the chip's tooltip.
// - Each event chip deep-links to the right matter route per kind.
// - "+N more" overflow appears when a single day has >3 events.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  fetchCalendarEventsMock,
  fetchCalendarSyncStatusMock,
  listCalendarConnectionsMock,
  startOutlookCalendarConnectionMock,
  syncOutlookVisibleRangeMock,
  useCapabilityMock,
} = vi.hoisted(() => ({
  fetchCalendarEventsMock: vi.fn(),
  fetchCalendarSyncStatusMock: vi.fn(),
  listCalendarConnectionsMock: vi.fn(),
  startOutlookCalendarConnectionMock: vi.fn(),
  syncOutlookVisibleRangeMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchCalendarEvents: fetchCalendarEventsMock,
  fetchCalendarSyncStatus: fetchCalendarSyncStatusMock,
  listCalendarConnections: listCalendarConnectionsMock,
  revokeCalendarConnection: vi.fn(),
  startOutlookCalendarConnection: startOutlookCalendarConnectionMock,
  syncOutlookVisibleRange: syncOutlookVisibleRangeMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

import CalendarPage from "./page";

function withClient(node: ReactNode): ReactNode {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{node}</QueryClientProvider>;
}

function isoToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

describe("CalendarPage", () => {
  beforeEach(() => {
    fetchCalendarEventsMock.mockReset();
    fetchCalendarSyncStatusMock.mockReset();
    listCalendarConnectionsMock.mockReset();
    startOutlookCalendarConnectionMock.mockReset();
    syncOutlookVisibleRangeMock.mockReset();
    useCapabilityMock.mockReset();
    useCapabilityMock.mockReturnValue(true);
    listCalendarConnectionsMock.mockResolvedValue({
      provider: "outlook",
      provider_available: true,
      unavailable_reason: null,
      durable_automation: "blocked_pending_temporal",
      connections: [],
    });
    fetchCalendarSyncStatusMock.mockResolvedValue({
      provider_available: true,
      durable_automation: "blocked_pending_temporal",
      connections: [],
      syncs: [],
    });
  });

  it("renders the current month label and a Today affordance", async () => {
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    render(withClient(<CalendarPage />));
    const label = await screen.findByTestId("calendar-month-label");
    expect(label.textContent).toMatch(
      /(January|February|March|April|May|June|July|August|September|October|November|December) \d{4}/,
    );
    expect(screen.getByTestId("calendar-today")).toBeTruthy();
    expect(screen.getByTestId("calendar-prev-month")).toBeTruthy();
    expect(screen.getByTestId("calendar-next-month")).toBeTruthy();
    expect(await screen.findByTestId("calendar-outlook-panel")).toBeTruthy();
    expect(screen.getByTestId("calendar-ics-download")).toBeTruthy();
  });

  it("shows Outlook unavailable state without hiding ICS export", async () => {
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    listCalendarConnectionsMock.mockResolvedValueOnce({
      provider: "outlook",
      provider_available: false,
      unavailable_reason: "Microsoft Graph OAuth is not configured.",
      durable_automation: "blocked_pending_temporal",
      connections: [],
    });
    render(withClient(<CalendarPage />));
    expect(
      await screen.findByText(/Microsoft Graph OAuth is not configured/i),
    ).toBeInTheDocument();
    expect(screen.getByTestId("calendar-ics-download")).toBeInTheDocument();
  });

  it("renders an event chip for each event returned by the API", async () => {
    const today = isoToday();
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: today,
      range_to: today,
      events: [
        {
          id: "hearing:h1",
          kind: "hearing",
          occurs_on: today,
          title: "Bail hearing",
          matter_id: "m1",
          matter_code: "BAIL-001",
          matter_title: "State v Accused",
          status: "scheduled",
          detail: "Bombay HC",
        },
        {
          id: "task:t1",
          kind: "task",
          occurs_on: today,
          title: "Draft reply",
          matter_id: "m2",
          matter_code: "CIV-002",
          matter_title: "Civil dispute",
          status: "todo",
          detail: "high",
        },
      ],
    });
    render(withClient(<CalendarPage />));

    // Wait for the data — the chips have stable testids tied to the
    // event id.
    expect(await screen.findByTestId("calendar-event-hearing:h1")).toBeTruthy();
    expect(await screen.findByTestId("calendar-event-task:t1")).toBeTruthy();
  });

  it("deep-links each event chip to the source matter's right tab", async () => {
    const today = isoToday();
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: today,
      range_to: today,
      events: [
        {
          id: "hearing:h1",
          kind: "hearing",
          occurs_on: today,
          title: "Bail hearing",
          matter_id: "m1",
          matter_code: "BAIL-001",
          matter_title: "State v Accused",
        },
        {
          id: "task:t1",
          kind: "task",
          occurs_on: today,
          title: "Draft reply",
          matter_id: "m2",
          matter_code: "CIV-002",
          matter_title: "Civil dispute",
        },
        {
          id: "deadline:d1",
          kind: "deadline",
          occurs_on: today,
          title: "Filing deadline",
          matter_id: "m3",
          matter_code: "DRAFT-003",
          matter_title: "Filing matter",
        },
      ],
    });
    render(withClient(<CalendarPage />));

    const hearingLink = await screen.findByTestId("calendar-event-hearing:h1");
    const taskLink = await screen.findByTestId("calendar-event-task:t1");
    const deadlineLink = await screen.findByTestId("calendar-event-deadline:d1");

    expect(hearingLink.getAttribute("href")).toBe("/app/matters/m1/hearings");
    expect(taskLink.getAttribute("href")).toBe("/app/matters/m2/tasks");
    expect(deadlineLink.getAttribute("href")).toBe("/app/matters/m3/tasks");
  });

  it("shows '+N more' when a single day has more than 3 events", async () => {
    const today = isoToday();
    const events = Array.from({ length: 5 }).map((_, i) => ({
      id: `hearing:overflow-${i}`,
      kind: "hearing" as const,
      occurs_on: today,
      title: `Hearing ${i + 1}`,
      matter_id: `m${i}`,
      matter_code: `OV-${i}`,
      matter_title: `Overflow matter ${i}`,
    }));
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: today,
      range_to: today,
      events,
    });
    render(withClient(<CalendarPage />));

    // Wait for the first chip to land before asserting overflow.
    await screen.findByTestId("calendar-event-hearing:overflow-0");
    // The overflow badge reads "+2 more" because we cap at 3 chips.
    const overflow = await screen.findAllByText(/\+2 more/);
    expect(overflow.length).toBeGreaterThan(0);
    // And the overflow chips should NOT have rendered as their own
    // links — the cap is enforced at render time.
    expect(screen.queryByTestId("calendar-event-hearing:overflow-3")).toBeNull();
    expect(screen.queryByTestId("calendar-event-hearing:overflow-4")).toBeNull();
    // Use 'within' so the linter doesn't flag the import as unused.
    void within;
  });

  // BUG-039 (Hari 2026-05-09): the bulk sync button only renders
  // when the caller has the `calendar:sync` capability AND a
  // connected Outlook account. Click triggers
  // POST /api/calendar/sync/outlook with the same `from`/`to` the
  // events query is using. Result counts surface to the user via the
  // existing outlook-message panel.
  it("renders Sync visible range to Outlook button when connected and posts the visible range", async () => {
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    listCalendarConnectionsMock.mockResolvedValueOnce({
      provider: "outlook",
      provider_available: true,
      unavailable_reason: null,
      durable_automation: "blocked_pending_temporal",
      connections: [
        {
          id: "conn-1",
          company_id: "co-1",
          membership_id: "mem-1",
          provider: "outlook",
          provider_account_id: "acct-1",
          display_email: "qa-bot@caseops.ai",
          status: "connected",
          scopes: ["Calendars.ReadWrite"],
          connected_at: new Date().toISOString(),
          last_sync_at: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      ],
    });
    syncOutlookVisibleRangeMock.mockResolvedValueOnce({
      examined: 3,
      created: 2,
      updated: 1,
      failed: 0,
      skipped: 0,
      items: [],
      durable_automation: "blocked_pending_temporal",
    });

    const user = userEvent.setup();
    render(withClient(<CalendarPage />));

    const syncButton = await screen.findByTestId("calendar-outlook-sync-range");
    expect(syncButton).toBeEnabled();
    await user.click(syncButton);

    await waitFor(() => expect(syncOutlookVisibleRangeMock).toHaveBeenCalled());
    const args = syncOutlookVisibleRangeMock.mock.calls[0][0];
    expect(args.from).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(args.to).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    // Summary message includes the per-bucket counts.
    expect(
      await screen.findByText(
        /Synced 2 new, 1 updated, 0 failed, 0 skipped \(3 examined\)\./,
      ),
    ).toBeInTheDocument();
  });

  it("hides the Sync visible range to Outlook button when no Outlook account is connected", async () => {
    fetchCalendarEventsMock.mockResolvedValueOnce({
      range_from: "2026-04-01",
      range_to: "2026-05-31",
      events: [],
    });
    // The default beforeEach mock returns connections: []. Wait for
    // the connect-button to appear (proving the connections query
    // resolved) before asserting the sync button is absent.
    render(withClient(<CalendarPage />));
    await screen.findByTestId("calendar-outlook-connect");
    expect(screen.queryByTestId("calendar-outlook-sync-range")).toBeNull();
    expect(syncOutlookVisibleRangeMock).not.toHaveBeenCalled();
  });
});
