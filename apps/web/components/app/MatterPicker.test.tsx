import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api/config";

// `page` serves the picker's list; `byId` serves GET /api/matters/?id= (the
// wall-scoped lookup). GET /api/matters/{id} is deliberately not mocked: it
// audits a denial for a walled viewer and must not be used to name a Matter.
const mocks = vi.hoisted(() => ({ page: vi.fn(), byId: vi.fn() }));

vi.mock("@/lib/api/endpoints", () => ({
  listMatters: (params?: { id?: string }) =>
    params?.id
      ? Promise.resolve(mocks.byId(params.id)).then((found) => ({ matters: found ? [found] : [], next_cursor: null }))
      : mocks.page(params),
}));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));

import { MatterName, MatterPicker } from "@/components/app/MatterPicker";

function matter(id: string, code: string, status = "active") {
  return { id, matter_code: code, title: `Title ${code}`, client_name: "Aster Holdings", status } as never;
}

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  mocks.page.mockReset();
  mocks.byId.mockReset();
});

describe("MatterPicker fetch-by-id (B4-ADJ-02)", () => {
  beforeEach(() => {
    // One page of 50 recent Matters, more behind the cursor: the pre-filled
    // Matter is older than every loaded row.
    mocks.page.mockResolvedValue({
      matters: Array.from({ length: 50 }, (_, index) => matter(`m-${index}`, `RECENT-${index}`)),
      next_cursor: "cursor-2",
    });
  });

  it("reads a pre-filled Matter beyond the loaded page by id and shows it as the selection", async () => {
    mocks.byId.mockResolvedValue(matter("m-old", "OLD-2019"));
    render(<MatterPicker value="m-old" onChange={vi.fn()} label="Matter" />, { wrapper: wrapper() });

    const select = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Matter" });
    await waitFor(() => expect(select).toHaveValue("m-old"));
    expect(mocks.byId).toHaveBeenCalledWith("m-old");
    expect(Array.from(select.options, (option) => option.value)).toContain("m-old");
    // The select shows "Loading the selected Matter…" under the same value first; wait for the caption.
    expect((await screen.findAllByText("OLD-2019 · Title OLD-2019 · Aster Holdings")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("does not read by id when the Matter is already on the loaded page", async () => {
    render(<MatterPicker value="m-3" onChange={vi.fn()} label="Matter" />, { wrapper: wrapper() });
    const select = await screen.findByRole<HTMLSelectElement>("combobox", { name: "Matter" });
    await waitFor(() => expect(select).toHaveValue("m-3"));
    expect(mocks.byId).not.toHaveBeenCalled();
  });

  it("reports a walled or deleted pre-filled Matter without its title and lets the user clear it", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    // Walled or deleted: the wall-scoped list simply does not return it.
    mocks.byId.mockResolvedValue(null);
    render(<MatterPicker value="m-walled" onChange={onChange} label="Matter" />, { wrapper: wrapper() });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The selected Matter is not available to you or no longer exists.");
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "Matter" });
    expect(select).toHaveAttribute("aria-invalid", "true");
    expect(Array.from(select.options, (option) => option.value)).not.toContain("m-walled");
    // A hidden Matter is not retried: retrying cannot reveal it.
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(onChange).toHaveBeenCalledWith("", null);
  });

  it("offers Retry when the by-id read fails for another reason", async () => {
    const user = userEvent.setup();
    mocks.byId.mockRejectedValueOnce(new ApiError(503, "Service unavailable.", null));
    mocks.byId.mockResolvedValueOnce(matter("m-old", "OLD-2019"));
    render(<MatterPicker value="m-old" onChange={vi.fn()} label="Matter" />, { wrapper: wrapper() });

    expect(await screen.findByRole("alert")).toHaveTextContent("could not be loaded: Service unavailable.");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    const select = screen.getByRole<HTMLSelectElement>("combobox", { name: "Matter" });
    await waitFor(() => expect(select).toHaveValue("m-old"));
    expect((await screen.findAllByText("OLD-2019 · Title OLD-2019 · Aster Holdings")).length).toBeGreaterThan(0);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
});

describe("MatterName", () => {
  it("shows the caption, never the id", async () => {
    mocks.byId.mockResolvedValue(matter("m-9", "CODE-9"));
    render(<MatterName matterId="m-9" />, { wrapper: wrapper() });
    expect(await screen.findByText("CODE-9 · Title CODE-9 · Aster Holdings")).toBeVisible();
    expect(screen.queryByText("m-9")).toBeNull();
  });

  it("names a Matter the viewer cannot open without leaking it", async () => {
    // Walled or deleted: the wall-scoped list simply does not return it.
    mocks.byId.mockResolvedValue(null);
    render(<MatterName matterId="m-walled" />, { wrapper: wrapper() });
    expect(await screen.findByText("A Matter you cannot open")).toBeVisible();
    expect(screen.queryByText("m-walled")).toBeNull();
  });

  it("renders the fallback for no Matter", () => {
    render(<MatterName matterId={null} fallback="Unlinked" />, { wrapper: wrapper() });
    expect(screen.getByText("Unlinked")).toBeVisible();
    expect(mocks.byId).not.toHaveBeenCalled();
  });
});
