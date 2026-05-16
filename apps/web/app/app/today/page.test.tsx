import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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
});
