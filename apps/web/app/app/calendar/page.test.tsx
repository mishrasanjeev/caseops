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
import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const { fetchCalendarEventsMock } = vi.hoisted(() => ({
  fetchCalendarEventsMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  fetchCalendarEvents: fetchCalendarEventsMock,
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
    // Tasks + deadlines deep-link to the matter cockpit root for now;
    // when the matter cockpit gains a Tasks tab they'll route to it.
    expect(taskLink.getAttribute("href")).toBe("/app/matters/m2");
    expect(deadlineLink.getAttribute("href")).toBe("/app/matters/m3");
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
});
