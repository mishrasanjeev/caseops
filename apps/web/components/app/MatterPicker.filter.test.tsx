import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { listMattersMock } = vi.hoisted(() => ({ listMattersMock: vi.fn() }));

vi.mock("@/lib/api/endpoints", () => ({ listMatters: listMattersMock }));
vi.mock("@/lib/capabilities", () => ({ useCapability: () => true }));

import { MatterPicker } from "@/components/app/MatterPicker";

function withClient(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const matter = (index: number) => ({
  id: `m${index}`,
  matter_code: `M-${index}`,
  title: `Matter ${index}`,
  client_name: null,
  status: "active",
});

describe("MatterPicker as a filter (B4-ADJ-03)", () => {
  beforeEach(() => {
    listMattersMock.mockReset();
    listMattersMock.mockImplementation(async ({ cursor }: { cursor?: string }) =>
      cursor === "c2"
        ? { matters: [matter(60)], next_cursor: null }
        : { matters: [matter(1), matter(2)], next_cursor: "c2" });
  });

  it("offers a selectable empty choice and reaches the next server page", async () => {
    const onChange = vi.fn();
    render(withClient(
      <MatterPicker id="filter" label="Filter by matter" emptyOptionLabel="All matters" value="" onChange={onChange} />,
    ));
    const select = screen.getByLabelText("Filter by matter");
    await waitFor(() => expect(select).toBeEnabled());
    const all = within(select).getByRole("option", { name: "All matters" }) as HTMLOptionElement;
    expect(all.disabled).toBe(false);
    expect(select).toHaveValue("");
    expect(screen.getByText(/Showing the 2 most recently updated Matters/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Load more Matters" }));
    await waitFor(() => expect(within(select).getByRole("option", { name: /M-60/ })).toBeInTheDocument());
    fireEvent.change(select, { target: { value: "m60" } });
    expect(onChange).toHaveBeenLastCalledWith("m60", expect.objectContaining({ id: "m60" }));
  });

  it("keeps the disabled placeholder when no empty choice is offered", async () => {
    render(withClient(<MatterPicker id="pick" label="Matter" value="" onChange={() => undefined} />));
    const select = screen.getByLabelText("Matter");
    await waitFor(() => expect(select).toBeEnabled());
    const placeholder = within(select).getByRole("option", { name: "Select a Matter" }) as HTMLOptionElement;
    expect(placeholder.disabled).toBe(true);
  });
});
