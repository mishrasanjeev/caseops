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
});
