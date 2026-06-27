import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  bulkAssignMatterTagMock,
  listMatterTagsMock,
  listMattersMock,
  updateMatterMock,
  useCapabilityMock,
  useRouterMock,
} = vi.hoisted(() => ({
  bulkAssignMatterTagMock: vi.fn(),
  listMatterTagsMock: vi.fn(),
  listMattersMock: vi.fn(),
  updateMatterMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  useRouterMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  bulkAssignMatterTag: bulkAssignMatterTagMock,
  listMatterTags: listMatterTagsMock,
  listMatters: listMattersMock,
  updateMatter: updateMatterMock,
}));

vi.mock("@/lib/capabilities", () => ({
  useCapability: useCapabilityMock,
}));

vi.mock("next/navigation", () => ({
  useRouter: useRouterMock,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

import MattersPage from "@/app/app/matters/page";

function withClient(children: ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("MattersPage", () => {
  beforeEach(() => {
    bulkAssignMatterTagMock.mockReset();
    listMatterTagsMock.mockReset();
    listMattersMock.mockReset();
    updateMatterMock.mockReset();
    useCapabilityMock.mockReset();
    listMatterTagsMock.mockResolvedValue({
      tags: [{ id: "tag-1", company_id: "c-1", name: "Urgent", slug: "urgent" }],
    });
    bulkAssignMatterTagMock.mockResolvedValue({ assigned_count: 1, skipped_count: 0 });
    updateMatterMock.mockResolvedValue({
      id: "m1",
      matter_code: "ACME-1",
      title: "Acme v Smith",
      status: "disposed",
      practice_area: "Commercial",
      forum_level: "high_court",
      next_hearing_on: null,
      created_at: "2026-04-01T00:00:00Z",
      updated_at: "2026-04-15T00:00:00Z",
    });
    useCapabilityMock.mockImplementation((capability: string) => capability === "matters:edit");
    useRouterMock.mockReturnValue({
      push: vi.fn(),
      replace: vi.fn(),
      refresh: vi.fn(),
    });
  });

  it("renders the Matter portfolio header and a row per matter", async () => {
    listMattersMock.mockResolvedValue({
      matters: [
        {
          id: "m1",
          matter_code: "ACME-1",
          title: "Acme v Smith",
          status: "active",
          practice_area: "Commercial",
          forum_level: "high_court",
          claim_amount_minor: 25000000,
          claim_currency: "INR",
          tags: [{ id: "tag-1", company_id: "c-1", name: "Urgent", slug: "urgent" }],
          has_stay: true,
          has_interim_order: true,
          next_hearing_on: null,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-15T00:00:00Z",
        },
      ],
      next_cursor: null,
    });
    render(withClient(<MattersPage />));
    expect(screen.getByText(/Matter portfolio/i)).toBeInTheDocument();
    await waitFor(() => expect(listMattersMock).toHaveBeenCalled());
    expect(await screen.findByText(/Acme v Smith/i)).toBeInTheDocument();
    expect(screen.getByText("Urgent")).toBeInTheDocument();
    expect(screen.getByText("Stay")).toBeInTheDocument();
    expect(screen.getByText("Interim")).toBeInTheDocument();
    expect(screen.getByText(/2,50,000/)).toBeInTheDocument();
  });

  it("labels the disposed status action as Dispose", async () => {
    listMattersMock.mockResolvedValue({
      matters: [
        {
          id: "m1",
          matter_code: "ACME-1",
          title: "Acme v Smith",
          status: "active",
          practice_area: "Commercial",
          forum_level: "high_court",
          next_hearing_on: null,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-15T00:00:00Z",
        },
      ],
      next_cursor: null,
    });

    render(withClient(<MattersPage />));

    const statusSelect = await screen.findByLabelText("Status for ACME-1");
    expect(within(statusSelect).getByRole("option", { name: "Dispose" })).toHaveValue(
      "disposed",
    );
  });

  it("surfaces the QueryErrorState when listMatters throws", async () => {
    listMattersMock.mockRejectedValue(new Error("boom"));
    render(withClient(<MattersPage />));
    expect(
      await screen.findByText(/Could not load matters/i),
    ).toBeInTheDocument();
  });

  it("falls back when legacy matter rows contain malformed claim currency", async () => {
    listMattersMock.mockResolvedValue({
      matters: [
        {
          id: "m1",
          matter_code: "BAD-CURRENCY-1",
          title: "Legacy malformed currency",
          status: "active",
          practice_area: "Commercial",
          forum_level: "high_court",
          claim_amount_minor: 1250000,
          claim_currency: "12$",
          tags: [],
          has_stay: false,
          next_hearing_on: null,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-15T00:00:00Z",
        },
      ],
      next_cursor: null,
    });

    render(withClient(<MattersPage />));

    expect(await screen.findByText(/Legacy malformed currency/i)).toBeInTheDocument();
    expect(screen.getByText(/12,500/)).toBeInTheDocument();
  });

  it("passes server-side filters to listMatters", async () => {
    listMattersMock.mockResolvedValue({
      matters: [
        {
          id: "m1",
          matter_code: "ACME-1",
          title: "Acme v Smith",
          status: "active",
          practice_area: "Commercial",
          forum_level: "high_court",
          next_hearing_on: null,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-15T00:00:00Z",
        },
      ],
      next_cursor: null,
    });
    render(withClient(<MattersPage />));
    await waitFor(() => expect(listMattersMock).toHaveBeenCalled());
    await screen.findByText(/Acme v Smith/i);

    fireEvent.change(screen.getByLabelText("Search"), {
      target: { value: "Acme" },
    });
    fireEvent.change(screen.getByLabelText("Min claim"), {
      target: { value: "100000" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Apply/i }));

    await waitFor(() =>
      expect(listMattersMock).toHaveBeenLastCalledWith(
        expect.objectContaining({
          q: "Acme",
          min_claim_amount_minor: 10000000,
        }),
      ),
    );
  });

  it("lets matter editors update status from the portfolio without opening the row", async () => {
    const push = vi.fn();
    useRouterMock.mockReturnValue({
      push,
      replace: vi.fn(),
      refresh: vi.fn(),
    });
    listMattersMock.mockResolvedValue({
      matters: [
        {
          id: "m1",
          matter_code: "ACME-1",
          title: "Acme v Smith",
          status: "active",
          practice_area: "Commercial",
          forum_level: "high_court",
          next_hearing_on: null,
          created_at: "2026-04-01T00:00:00Z",
          updated_at: "2026-04-15T00:00:00Z",
        },
      ],
      next_cursor: null,
    });

    render(withClient(<MattersPage />));

    const statusSelect = await screen.findByLabelText("Status for ACME-1");
    fireEvent.change(statusSelect, { target: { value: "disposed" } });

    await waitFor(() => expect(updateMatterMock).toHaveBeenCalledTimes(1));
    expect(updateMatterMock).toHaveBeenCalledWith({
      matterId: "m1",
      status: "disposed",
    });
    expect(push).not.toHaveBeenCalled();
  });
});
