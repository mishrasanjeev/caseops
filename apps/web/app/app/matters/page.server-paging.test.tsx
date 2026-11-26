// Nov 24 workbook rows 4-5 (Test Legal LLP, /app/matters).
//
// Row 4: Next stopped at the last page loaded with "Load more".
// Row 5: Search said "Nothing to show yet" for a Matter on an unloaded page.
//
// Both came from a client-side table paging and filtering only the rows the
// browser had already loaded. These tests drive the page against a fake
// server holding 130 Matters (three server pages) and prove that Next fetches
// the following page itself, that search is answered by the server for every
// Matter, and that each Matter appears exactly once while paging.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listMattersMock, listMatterTagsMock, useCapabilityMock } = vi.hoisted(() => ({
  listMattersMock: vi.fn(),
  listMatterTagsMock: vi.fn(),
  useCapabilityMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  bulkAssignMatterTag: vi.fn(),
  listMatterTags: listMatterTagsMock,
  listMatters: listMattersMock,
  updateMatter: vi.fn(),
}));
vi.mock("@/lib/capabilities", () => ({ useCapability: useCapabilityMock }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import MattersPage from "@/app/app/matters/page";

const TOTAL = 130;
const SERVER_PAGE = 50;

function matter(index: number) {
  const n = String(index).padStart(3, "0");
  return {
    id: `m-${n}`,
    matter_code: `MAT-${n}`,
    title: `Recovery suit ${n}`,
    client_name: `Client ${n}`,
    opposing_party: "Respondent",
    status: "active",
    practice_area: "Commercial",
    forum_level: "high_court",
    next_hearing_on: null,
    created_at: "2026-11-01T00:00:00Z",
    updated_at: "2026-11-01T00:00:00Z",
  };
}

const SERVER = Array.from({ length: TOTAL }, (_, index) => matter(index + 1));

function fakeServer(params: { q?: string; cursor?: string | null; limit?: number; include_total?: boolean }) {
  const needle = params.q?.toLowerCase();
  const rows = needle
    ? SERVER.filter((m) =>
        [m.matter_code, m.title, m.client_name].some((value) =>
          value.toLowerCase().includes(needle),
        ),
      )
    : SERVER;
  const start = params.cursor ? Number(params.cursor.replace("after-", "")) : 0;
  const size = params.limit ?? SERVER_PAGE;
  const page = rows.slice(start, start + size);
  const end = start + page.length;
  return Promise.resolve({
    matters: page,
    next_cursor: end < rows.length ? `after-${end}` : null,
    total_count: params.include_total ? rows.length : null,
  });
}

function renderPage(children: ReactNode = <MattersPage />) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{children}</QueryClientProvider>);
}

function visibleCodes(): string[] {
  const table = screen.getByRole("table");
  return within(table)
    .queryAllByText(/^MAT-\d{3}$/)
    .map((cell) => cell.textContent ?? "");
}

// The page waits SEARCH_DEBOUNCE_MS (300ms) before it asks the server. Wait
// for that request on its own budget, so the default wait that follows covers
// only the server answer and render (CI under coverage measured 1.3s for both).
const SEARCH_DEBOUNCE_MS = 300;
async function searchFor(value: string) {
  fireEvent.change(screen.getByRole("searchbox", { name: "Search all rows" }), {
    target: { value },
  });
  await waitFor(
    () => expect(listMattersMock).toHaveBeenLastCalledWith(expect.objectContaining({ q: value })),
    { timeout: SEARCH_DEBOUNCE_MS + 1000 },
  );
}

describe("Matters list pages and searches on the server", () => {
  beforeEach(() => {
    listMattersMock.mockReset();
    listMattersMock.mockImplementation(fakeServer);
    listMatterTagsMock.mockResolvedValue({ tags: [] });
    useCapabilityMock.mockReturnValue(false);
  });

  it("Next fetches the following server page without Load more (row 4)", async () => {
    renderPage();
    await screen.findByText("MAT-001");
    expect(screen.queryByRole("button", { name: /load more/i })).toBeNull();
    expect(screen.getByTestId("data-table-range")).toHaveTextContent("1-50 of 130");
    expect(screen.getByTestId("data-table-page")).toHaveTextContent("Page 1 of 3");

    const seen = new Set(visibleCodes());
    expect(seen.size).toBe(50);

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByText("MAT-051");
    expect(listMattersMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ cursor: "after-50", limit: 50 }),
    );
    expect(screen.getByTestId("data-table-range")).toHaveTextContent("51-100 of 130");
    expect(screen.getByTestId("data-table-page")).toHaveTextContent("Page 2 of 3");
    for (const code of visibleCodes()) {
      expect(seen.has(code)).toBe(false);
      seen.add(code);
    }

    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByText("MAT-130");
    expect(screen.getByTestId("data-table-range")).toHaveTextContent("101-130 of 130");
    for (const code of visibleCodes()) {
      expect(seen.has(code)).toBe(false);
      seen.add(code);
    }
    // Every Matter exactly once across the two page boundaries.
    expect(seen.size).toBe(TOTAL);
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();

    // Previous reuses the loaded page instead of fetching again.
    const calls = listMattersMock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Previous page" }));
    await screen.findByText("MAT-051");
    expect(screen.getByTestId("data-table-page")).toHaveTextContent("Page 2 of 3");
    expect(listMattersMock.mock.calls.length).toBe(calls);
  });

  it.each([
    ["Search Matters (title)", "Recovery suit 120", "MAT-120"],
    ["Search by Codes", "mat-127", "MAT-127"],
    ["Search by Client", "Client 101", "MAT-101"],
  ])("%s finds a Matter on an unloaded page (row 5)", async (_label, needle, code) => {
    renderPage();
    await screen.findByText("MAT-001");
    expect(screen.queryByText(code)).toBeNull();

    await searchFor(needle);

    await screen.findByText(code);
    expect(listMattersMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: needle, cursor: null, include_total: true }),
    );
    expect(visibleCodes()).toEqual([code]);
    expect(screen.getByTestId("data-table-range")).toHaveTextContent("1-1 of 1");
    expect(screen.queryByText(/nothing to show yet/i)).toBeNull();
  });

  it("keeps the search box and says so when nothing matches", async () => {
    renderPage();
    await screen.findByText("MAT-001");
    await searchFor("no such matter");
    await screen.findByText("No matters match this search or these filters.");
    expect(screen.getByRole("searchbox", { name: "Search all rows" })).toHaveValue(
      "no such matter",
    );
    fireEvent.click(screen.getByRole("button", { name: /reset filters/i }));
    await screen.findByText("MAT-001");
    expect(screen.getByTestId("data-table-range")).toHaveTextContent("1-50 of 130");
  });

  it("a new search after paging starts again at page 1", async () => {
    renderPage();
    await screen.findByText("MAT-001");
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByText("MAT-051");
    await searchFor("Client 00");
    // The previous page stays visible while the search loads; wait for the result.
    await waitFor(() =>
      expect(screen.getByTestId("data-table-range")).toHaveTextContent("1-9 of 9"),
    );
    expect(screen.getByTestId("data-table-page")).toHaveTextContent("Page 1 of 1");
    expect(visibleCodes()).toEqual([
      "MAT-001", "MAT-002", "MAT-003", "MAT-004", "MAT-005",
      "MAT-006", "MAT-007", "MAT-008", "MAT-009",
    ]);
  });

  it("sorts in the browser only when one page holds every match", async () => {
    renderPage();
    await screen.findByText("MAT-001");
    // 130 matters over three pages: ordering one page would misstate the list.
    expect(screen.queryByRole("button", { name: "Code" })).toBeNull();
    expect(screen.getByRole("columnheader", { name: "Code" })).toBeInTheDocument();

    await searchFor("Client 00");
    await waitFor(() =>
      expect(screen.getByTestId("data-table-range")).toHaveTextContent("1-9 of 9"),
    );
    const code = screen.getByRole("button", { name: "Code" });
    fireEvent.click(code);
    fireEvent.click(code);
    expect(visibleCodes()[0]).toBe("MAT-009");
  });

  it("keeps a way out when a search fails", async () => {
    listMattersMock.mockImplementation((params: { q?: string }) =>
      params.q ? Promise.reject(new Error("search failed")) : fakeServer(params),
    );
    renderPage();
    await screen.findByText("MAT-001");
    await searchFor("boom");
    const reset = await screen.findByRole("button", { name: /reset filters/i });
    expect(screen.getByLabelText("Search")).toHaveValue("boom");
    fireEvent.click(reset);
    await screen.findByText("MAT-001");
  });

  it("caps the search at the server's limit", async () => {
    renderPage();
    await screen.findByText("MAT-001");
    expect(screen.getByRole("searchbox", { name: "Search all rows" })).toHaveAttribute("maxLength", "255");
  });
});
