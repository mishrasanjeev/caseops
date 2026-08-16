import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TodayPage from "@/app/app/today/page";
import * as endpoints from "@/lib/api/endpoints";

function renderWithQuery(ui: ReactElement) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

describe("TodayPage smoke", () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn() as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("renders the header while data is loading", () => {
    vi.spyOn(endpoints, "fetchTodayView").mockReturnValue(new Promise(() => {}));
    renderWithQuery(<TodayPage />);
    expect(screen.getByRole("heading", { name: /today/i })).toBeInTheDocument();
  });

  it("renders empty-state copy when nothing is due today", async () => {
    vi.spyOn(endpoints, "fetchTodayView").mockResolvedValue({
      hearings: [],
      deadlines: [],
      tasks: [],
      drafts_in_review: [],
      overdue_invoices: [],
    } as unknown as endpoints.TodayView);
    renderWithQuery(<TodayPage />);
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /today/i })).toBeInTheDocument();
    });
  });

  // Bounds feature: a populated stream flagged truncated must show the
  // "Showing the first N" affordance; an un-flagged (or metadata-absent)
  // stream must NOT. Copy must say "first N", never "N total".
  const oneHearingView = (
    truncated: boolean | undefined,
  ): endpoints.TodayView =>
    ({
      today: "2026-05-16",
      horizon_days: 7,
      hearings_next_7d: [
        {
          id: "h1",
          matter: { id: "m1", title: "Matter One", matter_code: "M-1" },
          hearing_on: "2026-05-18",
          forum_name: "Court 7",
          judge_name: null,
          purpose: "Arguments",
        },
      ],
      tasks_due_or_overdue: [],
      drafts_in_review: [],
      overdue_invoices: [],
      deadlines_next_7d: [],
      ...(truncated === undefined
        ? {}
        : {
            stream_limits: { hearings_next_7d: 100 } as Record<
              endpoints.TodayStreamKey,
              number
            >,
            stream_counts: { hearings_next_7d: 100 } as Record<
              endpoints.TodayStreamKey,
              number
            >,
            stream_truncated: { hearings_next_7d: truncated } as Record<
              endpoints.TodayStreamKey,
              boolean
            >,
          }),
    }) as unknown as endpoints.TodayView;

  it("shows the truncation affordance for a capped stream", async () => {
    vi.spyOn(endpoints, "fetchTodayView").mockResolvedValue(
      oneHearingView(true),
    );
    renderWithQuery(<TodayPage />);
    const note = await screen.findByTestId("today-stream-truncated");
    expect(note).toBeInTheDocument();
    expect(note.textContent).toMatch(/Showing the first 100/);
    expect(note.textContent).not.toMatch(/total/i);
  });

  it("does not show the affordance when the stream is not truncated", async () => {
    vi.spyOn(endpoints, "fetchTodayView").mockResolvedValue(
      oneHearingView(false),
    );
    renderWithQuery(<TodayPage />);
    await screen.findByText(/Matter One/);
    expect(
      await screen.findByText(/(18 May 2026|May 18, 2026)/i),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("today-stream-truncated")).toBeNull();
  });

  it("degrades gracefully when bounding metadata is absent (old API)", async () => {
    vi.spyOn(endpoints, "fetchTodayView").mockResolvedValue(
      oneHearingView(undefined),
    );
    renderWithQuery(<TodayPage />);
    await screen.findByText(/Matter One/);
    expect(screen.queryByTestId("today-stream-truncated")).toBeNull();
  });

  // IP coverage actions: two personal queues that previously lived only in the
  // IP workspace, so a transfer could sit unseen while it blocked a colleague.
  const ipView = (
    actions: endpoints.TodayIpCoverageAction[],
  ): endpoints.TodayView =>
    ({
      today: "2026-08-16",
      horizon_days: 7,
      hearings_next_7d: [],
      tasks_due_or_overdue: [],
      drafts_in_review: [],
      overdue_invoices: [],
      deadlines_next_7d: [],
      ip_coverage_actions: actions,
    }) as unknown as endpoints.TodayView;

  const ipAction = (
    over: Partial<endpoints.TodayIpCoverageAction> = {},
  ): endpoints.TodayIpCoverageAction => ({
    coverage_id: "cov-1",
    docket_id: "ip-1",
    docket_title: "ACME WORDMARK",
    deadline_title: "Opposition reply",
    due_on: "2026-08-21",
    days_until: 5,
    critical: true,
    kind: "acknowledge",
    responsible_label: "You",
    reason: null,
    ...over,
  });

  it("surfaces an IP deadline the user has not acknowledged", async () => {
    vi.spyOn(endpoints, "fetchTodayView").mockResolvedValue(ipView([ipAction()]));
    renderWithQuery(<TodayPage />);

    const card = await screen.findByTestId("today-ip-coverage-actions");
    expect(within(card).getByText("ACME WORDMARK")).toBeVisible();
    expect(within(card).getByText(/Opposition reply/)).toBeVisible();
    expect(within(card).getByText("Acknowledge")).toBeVisible();
    expect(within(card).getByText(/You hold this and have not acknowledged it/)).toBeVisible();
  });

  it("says a colleague is waiting when a transfer needs a decision", async () => {
    vi.spyOn(endpoints, "fetchTodayView").mockResolvedValue(
      ipView([
        ipAction({
          kind: "decide_transfer",
          responsible_label: "Priya Raghavan",
          reason: "Covering while I am in hearings.",
        }),
      ]),
    );
    renderWithQuery(<TodayPage />);

    const card = await screen.findByTestId("today-ip-coverage-actions");
    // The two kinds ask for different acts and must not read the same.
    expect(within(card).getByText("Decision needed")).toBeVisible();
    expect(within(card).getByText(/1 colleague is waiting on your decision/)).toBeVisible();
    expect(within(card).getByText(/Priya Raghavan holds this until you accept/)).toBeVisible();
  });

  it("does not claim nothing is due while IP coverage is waiting", async () => {
    // The empty-state gate has to count this stream, or Today would say
    // "nothing demanding attention" while a colleague waits on a decision.
    vi.spyOn(endpoints, "fetchTodayView").mockResolvedValue(ipView([ipAction()]));
    renderWithQuery(<TodayPage />);

    await screen.findByTestId("today-ip-coverage-actions");
    expect(screen.queryByText("Nothing demanding attention today")).toBeNull();
  });

  it("renders nothing for this stream when there is no IP work", async () => {
    vi.spyOn(endpoints, "fetchTodayView").mockResolvedValue(ipView([]));
    renderWithQuery(<TodayPage />);

    await waitFor(() => {
      expect(screen.getByText("Nothing demanding attention today")).toBeVisible();
    });
    expect(screen.queryByTestId("today-ip-coverage-actions")).toBeNull();
  });
});
