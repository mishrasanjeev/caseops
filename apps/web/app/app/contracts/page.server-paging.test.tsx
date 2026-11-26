// Adjacent path of Nov 24 workbook rows 4-5: the Contracts repository used the
// same client-side table over 50 loaded rows, so its search and Next had the
// Matters defect. The page now searches and pages on the server.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listContractsMock } = vi.hoisted(() => ({ listContractsMock: vi.fn() }));

vi.mock("@/lib/api/endpoints", () => ({ listContracts: listContractsMock }));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => false }));
vi.mock("@/components/app/NewContractDialog", () => ({ NewContractDialog: () => null }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import ContractsPage from "@/app/app/contracts/page";

const SERVER = Array.from({ length: 75 }, (_, i) => {
  const n = String(i + 1).padStart(3, "0");
  return {
    id: `k-${n}`,
    contract_code: `CON-${n}`,
    title: `Agreement ${n}`,
    counterparty_name: `Vendor ${n}`,
    contract_type: "Supply",
    effective_on: null,
    expires_on: null,
    total_value_minor: null,
    currency: "INR",
    status: "active",
  };
});

function fakeServer(params: { q?: string; cursor?: string | null; limit?: number; include_total?: boolean }) {
  const needle = params.q?.toLowerCase();
  const rows = needle
    ? SERVER.filter((c) => [c.contract_code, c.title, c.counterparty_name].some((v) => v.toLowerCase().includes(needle)))
    : SERVER;
  const start = params.cursor ? Number(params.cursor) : 0;
  const page = rows.slice(start, start + (params.limit ?? 50));
  const end = start + page.length;
  return Promise.resolve({
    company_id: "c-1",
    contracts: page,
    next_cursor: end < rows.length ? String(end) : null,
    total_count: params.include_total ? rows.length : null,
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ContractsPage />
    </QueryClientProvider>,
  );
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
    () => expect(listContractsMock).toHaveBeenLastCalledWith(expect.objectContaining({ q: value })),
    { timeout: SEARCH_DEBOUNCE_MS + 1000 },
  );
}

describe("Contracts list pages and searches on the server", () => {
  beforeEach(() => {
    listContractsMock.mockReset();
    listContractsMock.mockImplementation(fakeServer);
  });

  it("Next loads the second server page without Load more", async () => {
    renderPage();
    await screen.findByText("CON-001");
    expect(screen.queryByRole("button", { name: /load more/i })).toBeNull();
    expect(screen.getByTestId("data-table-range")).toHaveTextContent("1-50 of 75");
    fireEvent.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByText("CON-075");
    expect(screen.getByTestId("data-table-range")).toHaveTextContent("51-75 of 75");
    expect(screen.queryByText("CON-001")).toBeNull();
  });

  it("search finds a contract that is not loaded yet", async () => {
    renderPage();
    await screen.findByText("CON-001");
    await searchFor("Vendor 070");
    await screen.findByText("CON-070");
    expect(listContractsMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ q: "Vendor 070", cursor: null, include_total: true }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("data-table-range")).toHaveTextContent("1-1 of 1"),
    );
  });
});
