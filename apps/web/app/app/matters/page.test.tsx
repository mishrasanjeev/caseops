import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  bulkAssignMatterTagMock,
  listMatterTagsMock,
  listMattersMock,
  transitionMatterStatusMock,
  updateMatterMock,
  useCapabilityMock,
  useRouterMock,
} = vi.hoisted(() => ({
  bulkAssignMatterTagMock: vi.fn(),
  listMatterTagsMock: vi.fn(),
  listMattersMock: vi.fn(),
  transitionMatterStatusMock: vi.fn(),
  updateMatterMock: vi.fn(),
  useCapabilityMock: vi.fn(),
  useRouterMock: vi.fn(),
}));

vi.mock("@/lib/api/endpoints", () => ({
  bulkAssignMatterTag: bulkAssignMatterTagMock,
  listMatterTags: listMatterTagsMock,
  listMatters: listMattersMock,
  transitionMatterStatus: transitionMatterStatusMock,
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
    transitionMatterStatusMock.mockReset();
    useCapabilityMock.mockReset();
    listMatterTagsMock.mockResolvedValue({
      tags: [
        { id: "tag-1", company_id: "c-1", name: "Urgent", slug: "urgent" },
      ],
    });
    bulkAssignMatterTagMock.mockResolvedValue({
      assigned_count: 1,
      skipped_count: 0,
    });
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
    useCapabilityMock.mockImplementation(
      (capability: string) => capability === "matters:edit",
    );
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
          tags: [
            { id: "tag-1", company_id: "c-1", name: "Urgent", slug: "urgent" },
          ],
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

  it("shows bulk upload only to users with the dedicated matter-import capability", async () => {
    const push = vi.fn();
    useRouterMock.mockReturnValue({ push, replace: vi.fn(), refresh: vi.fn() });
    useCapabilityMock.mockImplementation(
      (capability: string) => capability === "matters:bulk_import",
    );
    listMattersMock.mockResolvedValue({ matters: [], next_cursor: null });

    render(withClient(<MattersPage />));

    const trigger = await screen.findByTestId("matter-import-trigger");
    fireEvent.click(trigger);
    expect(push).toHaveBeenCalledWith("/app/matters/imports");
  });

  it("separates disposal from ordinary status editing", async () => {
    useCapabilityMock.mockImplementation(
      (capability: string) =>
        capability === "matters:edit" || capability === "matters:archive",
    );
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
    expect(
      within(statusSelect).queryByRole("option", { name: "Dispose" }),
    ).toBeNull();
    expect(screen.getByTestId("matter-dispose-trigger")).toBeInTheDocument();
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

    expect(
      await screen.findByText(/Legacy malformed currency/i),
    ).toBeInTheDocument();
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

  it("keeps the complete filter surface shrinkable and wrapped across breakpoints", async () => {
    listMattersMock.mockResolvedValue({ matters: [], next_cursor: null });
    render(withClient(<MattersPage />));

    const grid = await screen.findByTestId("matter-filter-grid");
    expect(grid).toHaveClass("min-w-0", "sm:grid-cols-2", "lg:grid-cols-3");
    expect(grid).toHaveClass("2xl:grid-cols-6");
    expect(screen.getByLabelText("Search")).toBeInTheDocument();
    expect(screen.getByLabelText("Matter status filter")).toBeInTheDocument();
    expect(screen.getByLabelText("Forum filter")).toBeInTheDocument();
    expect(screen.getByLabelText("Tag filter")).toBeInTheDocument();
    expect(screen.getByLabelText("Min claim")).toBeInTheDocument();
    expect(screen.getByLabelText("Max claim")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Apply/i })).toHaveClass(
      "w-full",
      "sm:w-auto",
    );

    fireEvent.change(screen.getByLabelText("Search"), {
      target: { value: "visible reset" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Apply/i }));
    expect(await screen.findByRole("button", { name: /^Reset$/i })).toHaveClass(
      "w-full",
      "sm:w-auto",
    );
  });

  it("lets matter editors activate an On-hold matter from the portfolio", async () => {
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
          status: "on_hold",
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
    fireEvent.change(statusSelect, { target: { value: "active" } });

    await waitFor(() => expect(updateMatterMock).toHaveBeenCalledTimes(1));
    expect(updateMatterMock).toHaveBeenCalledWith({
      matterId: "m1",
      status: "active",
      expected_updated_at: "2026-04-15T00:00:00Z",
    });
    expect(push).not.toHaveBeenCalled();
  });
});
